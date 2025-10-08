# -*- coding: utf-8 -*-
import json
import os
import time
from datetime import datetime, timezone
from typing import Dict, Optional
from urllib.parse import urlencode

import pandas as pd
import requests
import streamlit as st

# =========================
# Constants & Secrets
# =========================
DIFY_CHAT_URL = "https://api.dify.ai/v1/chat-messages"

# 必須 Secrets チェック
if "persona_api_keys" not in st.secrets:
    st.error("Secrets に persona_api_keys がありません。 .streamlit/secrets.toml を設定してください。")
    st.stop()
if "gcp_service_account" not in st.secrets:
    st.error("Secrets に gcp_service_account がありません（サービスアカウントJSON）。")
    st.stop()
if "gsheet_id" not in st.secrets:
    st.error("Secrets に gsheet_id がありません（スプレッドシートID）。")
    st.stop()

# Secretsからpersona_api_keysテーブル（表示名とキー変数/キー本体のマッピング）を読み込む
persona_key_map = dict(st.secrets["persona_api_keys"])  # 例：{"①ミノン...": "PERSONA_1_KEY"}

# マッピングの値を Secrets に定義された実際のAPIキーに解決（直接 app-... が入っていればそれを採用）
PERSONA_API_KEYS: Dict[str, str] = {
    k: st.secrets.get(str(v), str(v)) for k, v in persona_key_map.items()
}

GSHEET_ID: str = st.secrets["gsheet_id"]
MAX_INPUT_CHARS: int = int(st.secrets.get("max_input_chars", 0))

# UI アバター（公開ファイル名）
PERSONA_AVATARS: Dict[str, str] = {
    "①ミノンBC理想ファン_乳児ママ_本田ゆい（30）": "persona_1.jpg",
    "②ミノンBC理想ファン_乳児パパ_安西涼太（31）": "persona_2.jpg",
    "③ミノンBC理想ファン_保育園/幼稚園ママ_戸田綾香（35）": "persona_3.jpg",
    "④ミノンBC理想ファン_更年期女性_高橋恵子（48）": "persona_4.jpg",
    "⑤ミノンBC未満ファン_乳児ママ_中村優奈（31）": "persona_5.jpg",
    "⑥ミノンBC未満ファン_乳児パパ_岡田健志（32）": "persona_6.jpg",
    "⑦ミノンBC未満ファン_保育園・幼稚園ママ_石田真帆（34）": "persona_7.png",
    "⑧ミノンBC未満ファン_更年期女性_杉山紀子（51）": "persona_8.jpg",
}

# =========================
# Bot name resolver (表記ゆれ対策)
# =========================
CANONICAL_BOT_NAMES = set(PERSONA_API_KEYS.keys())

# 過去ログに残っている可能性のある別表記 → 正規名 への写像
ALIASES: Dict[str, str] = {
    # 例：中点や全角スラッシュで保存された過去ログを現行の「/」に寄せる
    "③ミノンBC理想ファン_保育園・幼稚園ママ_戸田綾香（35）":
        "③ミノンBC理想ファン_保育園/幼稚園ママ_戸田綾香（35）",
    # 必要に応じて追加していく
}

def _normalize_bot_name(s: str) -> str:
    if not isinstance(s, str):
        return s
    t = s.strip()
    # よくある記号のゆれ
    t = t.replace("・", "/").replace("／", "/").replace("︰", ":")
    return t


def resolve_bot_type(name: Optional[str]) -> Optional[str]:
    """ログやクエリから来た bot 表記を正規名に解決する。なければ None。"""
    if not name:
        return None
    if name in CANONICAL_BOT_NAMES:
        return name
    n = _normalize_bot_name(name)
    if n in CANONICAL_BOT_NAMES:
        return n
    if name in ALIASES:
        return ALIASES[name]
    if n in ALIASES:
        return ALIASES[n]
    return None


# =========================
# Google Sheets Utilities
# =========================

def _get_sa_dict() -> dict:
    # Secrets の gcp_service_account を dict で返す（JSON文字列/TOMLテーブル両対応）
    raw = st.secrets["gcp_service_account"]
    if isinstance(raw, str):
        s = raw.strip()
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            # private_key の実改行を \n に自動補正して再トライ（貼付ミス救済）
            try:
                fixed = s.replace("\r\n", "\n").replace("\n", "\\n")
                return json.loads(fixed)
            except json.JSONDecodeError as e:
                raise ValueError(
                    "Secrets 'gcp_service_account' が正しいJSONではありません。"
                    "ダブルクォート、末尾カンマなし、コメントなしで、"
                    "Google配布のJSONそのまま（または TOMLテーブル）で保存してください。"
                ) from e
    return dict(raw)  # TOMLテーブルの場合も辞書型に統一


def _gs_client():
    import gspread
    from google.oauth2.service_account import Credentials

    sa_info = _get_sa_dict()
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_info(sa_info, scopes=scopes)
    return gspread.authorize(creds)


def _open_sheet():
    import gspread
    from gspread.exceptions import SpreadsheetNotFound, WorksheetNotFound

    gc = _gs_client()

    try:
        sh = gc.open_by_key(GSHEET_ID)
    except SpreadsheetNotFound:
        st.error("スプレッドシートが見つかりません。Secrets の gsheet_id を確認してください。")
        st.stop()
    except Exception:
        st.error("アクセス権がありません。対象シートを Service Account に『編集者』で共有してください。")
        st.stop()

    try:
        ws = sh.worksheet("chat_logs")
    except WorksheetNotFound:
        ws = sh.add_worksheet(title="chat_logs", rows=1000, cols=10)
        ws.append_row(["timestamp", "conversation_id", "bot_type", "role", "name", "content"])
    return ws


def save_log(conversation_id: str, bot_type: str, role: str, name: str, content: str) -> None:
    # 1行追記（APIの一時的エラーに対して指数バックオフ付きで再試行）
    from gspread.exceptions import APIError

    ws = _open_sheet()
    row = [datetime.now(timezone.utc).isoformat(), conversation_id, bot_type, role, name, content]
    for i in range(5):
        try:
            ws.append_row(row, value_input_option="USER_ENTERED")
            return
        except APIError as e:
            code = e.response.status_code
            if code in (429, 500, 503):
                time.sleep(1.5 ** i)
                continue
            raise
    raise RuntimeError("Google Sheets への保存に連続失敗しました。")


@st.cache_data(ttl=3)
def load_history(conversation_id: str, bot_type: Optional[str] = None) -> pd.DataFrame:
    # 会話IDの履歴を読み込み。bot_type 指定時は複合キーで絞込。
    ws = _open_sheet()
    data = ws.get_all_records()
    df = pd.DataFrame(data)
    if df.empty:
        return df
    # カラムが期待通りに存在するか確認
    if "conversation_id" not in df.columns:
        return pd.DataFrame()  # 空のDFを返す

    df = df[df["conversation_id"] == conversation_id].copy()
    if bot_type is not None and "bot_type" in df.columns:
        df = df[df["bot_type"] == bot_type].copy()
    if not df.empty and "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
        df = df.sort_values("timestamp")
    return df


# =========================
# Streamlit App
# =========================
st.set_page_config(page_title="Dify連携チャット（チャットフロー/グループ）", layout="centered")

# --- State init ---
if "page" not in st.session_state:
    st.session_state.page = "login"
    st.session_state.cid = ""
    st.session_state.messages = []  # CID 未確定時だけ使う一時バッファ
    st.session_state.bot_type = ""
    st.session_state.user_avatar_data = None
    st.session_state.name = ""

# --- Restore from query (share link) ---
qp = st.query_params
if qp.get("cid") and not st.session_state.cid:
    st.session_state.cid = qp.get("cid")
if qp.get("bot") and not st.session_state.bot_type:
    st.session_state.bot_type = qp.get("bot")
if qp.get("name") and not st.session_state.name:
    st.session_state.name = qp.get("name")
if qp.get("page") and st.session_state.page != qp.get("page"):
    st.session_state.page = qp.get("page")

# ========== STEP 1: LOGIN ==========
if st.session_state.page == "login":
    st.title("ミノンＢＣファンＡＩとチャット")

    with st.form("user_info_form"):
        name = st.text_input("あなたの表示名", value=st.session_state.name or "")
        lock_bot = bool(st.session_state.cid)  # 共有CIDがあるならボット選択はロック
        persona_choices = list(PERSONA_API_KEYS.keys())
        if not persona_choices:
            st.error("persona_api_keys が空です。Secrets を確認してください。")
            st.stop()

        # bot_type が persona_choices に存在する場合のみ index を設定
        try:
            current_index = persona_choices.index(st.session_state.bot_type)
        except ValueError:
            current_index = 0

        bot_type = st.selectbox(
            "対話するミノンＢＣファンＡＩ",
            persona_choices,
            index=current_index,
            disabled=lock_bot,
        )
        existing_cid = st.text_input("既存の会話ID（共有リンクで参加する場合に貼付）", value=st.session_state.cid or "")
        uploaded_file = st.file_uploader("あなたのアバター画像（任意）", type=["png", "jpg", "jpeg"])
        submitted = st.form_submit_button("チャット開始")

    if submitted and name:
        st.session_state.name = (name or "").strip() or "anonymous"
        st.session_state.bot_type = bot_type
        st.session_state.cid = (existing_cid or "").strip()
        st.session_state.user_avatar_data = uploaded_file.getvalue() if uploaded_file else None
        st.session_state.messages = []
        st.query_params.clear()
        st.query_params["page"] = "chat"
        st.query_params["cid"] = st.session_state.cid or ""
        st.query_params["bot"] = st.session_state.bot_type
        st.query_params["name"] = st.session_state.name
        st.rerun()

# ========== STEP 2: CHAT ==========
elif st.session_state.page == "chat":
    # 共有CIDが指定されている場合、そのCIDの主ペルソナに自動切替（履歴表示前）
    if st.session_state.cid:
        try:
            df_any = load_history(st.session_state.cid, bot_type=None)
            if not df_any.empty and "bot_type" in df_any.columns:
                series = df_any["bot_type"].dropna()
                if not series.empty:
                    cid_bot_raw = series.mode().iloc[0]
                    cid_bot = resolve_bot_type(cid_bot_raw)

                    if not cid_bot:
                        st.warning(
                            f"この会話IDは未知のペルソナ表記『{cid_bot_raw}』で作成されています。"
                            "セレクトボックスから該当のペルソナを選び直してください。"
                        )
                    else:
                        if st.session_state.bot_type != cid_bot:
                            st.session_state.bot_type = cid_bot
                            st.query_params["bot"] = cid_bot
                            if cid_bot_raw != cid_bot:
                                st.info(f"表記ゆれ『{cid_bot_raw}』→『{cid_bot}』に自動補正しました。")

        except Exception as e:
            st.info(f"会話IDのペルソナ自動判定に失敗しました: {e}")

    resolved_current_bt = resolve_bot_type(st.session_state.bot_type) or st.session_state.bot_type

    st.markdown(f"#### 💬 {resolved_current_bt}")

    # 共有リンク
    cid_show = st.session_state.cid or "(未発行：最初の発話で採番されます)"
    st.info(f"会話ID: `{cid_show}`")
    if st.session_state.cid:
        params = {
            "page": "chat",
            "cid": st.session_state.cid,
            "bot": resolved_current_bt,
            "name": st.session_state.name,
        }
        share_link = f"/?{urlencode(params)}"
        st.link_button("この会話の共有リンクをコピー", share_link)

    # アバター
    assistant_avatar_file = PERSONA_AVATARS.get(resolved_current_bt, "default_assistant.png")
    user_avatar = st.session_state.get("user_avatar_data") if st.session_state.get("user_avatar_data") else "👤"
    assistant_avatar = assistant_avatar_file if os.path.exists(assistant_avatar_file) else "🤖"

    # 履歴表示（CID 確定時は Sheets のみを信頼）
    if st.session_state.cid:
        try:
            df = load_history(st.session_state.cid)
            for _, r in df.iterrows():
                # ログ側 bot_type も解決してからアバターを選ぶ
                row_bt_resolved = resolve_bot_type(r.get("bot_type")) or r.get("bot_type")
                row_av_file = PERSONA_AVATARS.get(row_bt_resolved, "default_assistant.png")
                row_assistant_avatar = row_av_file if os.path.exists(row_av_file) else "🤖"

                avatar = row_assistant_avatar if r["role"] == "assistant" else user_avatar
                with st.chat_message(r["role"], avatar=avatar):
                    st.markdown(r["content"])
        except Exception as e:
            st.warning(f"履歴読み込みでエラーが発生しました: {e}")

    # CID 未確定時のみローカルバッファを表示（重複防止）
    if not st.session_state.cid:
        for msg in st.session_state.messages:
            avatar = assistant_avatar if msg["role"] == "assistant" else user_avatar
            with st.chat_message(msg["role"], avatar=avatar):
                st.markdown(msg["content"])

    # 入力
    if user_input := st.chat_input("メッセージを入力してください"):
        # 入力長ガード（任意）
        if MAX_INPUT_CHARS and len(user_input) > MAX_INPUT_CHARS:
            st.error(f"入力が長すぎます（最大 {MAX_INPUT_CHARS} 文字）。短くしてください。")
        else:
            is_new_thread = not bool(st.session_state.cid)

            # ユーザー発話の即時描画
            if is_new_thread:
                st.session_state.messages.append({"role": "user", "content": user_input})
            else:
                try:
                    save_log(st.session_state.cid, resolved_current_bt, "user", st.session_state.name or "anonymous", user_input)
                except Exception as e:
                    st.warning(f"スプレッドシート保存に失敗（user）：{e}")
            with st.chat_message("user", avatar=user_avatar):
                st.markdown(user_input)

            # Dify へ送信
            resolved_bt = resolve_bot_type(st.session_state.bot_type) or st.session_state.bot_type
            api_key = (PERSONA_API_KEYS.get(resolved_bt) or "").strip()
            if not api_key or not api_key.startswith("app-"):
                st.error(
                    f"選択されたペルソナ『{resolved_bt}』のAPIキーが正しく設定されていません。Secretsを確認してください。"
                )
            else:
                headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
                payload = {
                    "inputs": {},
                    "query": user_input,
                    "user": st.session_state.name or "streamlit-user",
                    "conversation_id": st.session_state.cid,
                    "response_mode": "blocking",
                }
                with st.chat_message("assistant", avatar=assistant_avatar):
                    try:
                        with st.spinner("AIが応答を生成中です…"):
                            res = requests.post(DIFY_CHAT_URL, headers=headers, data=json.dumps(payload), timeout=60)
                            res.raise_for_status()
                            rj = res.json()
                            answer = rj.get("answer", "⚠️ 応答がありませんでした。")
                            new_cid = rj.get("conversation_id")

                            if st.session_state.cid and new_cid and new_cid != st.session_state.cid:
                                st.error("この会話IDは現在のペルソナでは引き継げません。共有元と同じペルソナを選んでください。")
                            else:
                                if is_new_thread and new_cid:
                                    st.session_state.cid = new_cid
                                    st.query_params["cid"] = new_cid
                                    # 初回ユーザー発話の遅延保存（正規名で固定して保存）
                                    save_log(st.session_state.cid, resolved_bt, "user", st.session_state.name or "anonymous", user_input)

                                # アシスタント発話の保存（正規名で固定）
                                save_log(st.session_state.cid, resolved_bt, "assistant", resolved_bt, answer)
                                st.markdown(answer)

                    except requests.exceptions.RequestException as e:
                        answer = f"⚠️ APIリクエストエラー: {e}"
                        st.error(answer)
                    except Exception as e:
                        answer = f"⚠️ 不明なエラー: {e}"
                        st.error(answer)

                # 新規スレッド完了時の処理
                if is_new_thread and st.session_state.cid:
                    st.session_state.messages.clear()
                    st.rerun()

    # 操作ボタン
    if st.button("ログアウト"):
        st.session_state.page = "login"
        st.session_state.cid = ""
        st.session_state.bot_type = ""
        st.session_state.name = ""
        st.session_state.messages = []
        st.query_params.clear()
        st.rerun()

with st.expander("🔧 Google Sheets 診断", expanded=False):
    ok = True
    try:
        ws = _open_sheet()
        st.write("ワークシート一覧:", [w.title for w in ws.spreadsheet.worksheets()])
        header = ws.row_values(1)
        st.write("先頭行(ヘッダー):", header)
        values = ws.get_all_values()
        st.write(f"総行数: {len(values)}")
        st.write("末尾3行:", values[-3:] if len(values) >= 3 else values)
    except Exception as e:
        ok = False
        st.error(f"診断: 読み取りに失敗 → {e}")

    if ok and st.button("このシートにテスト行を追加"):
        try:
            test_row = [datetime.now(timezone.utc).isoformat(), "DIAG_TEST", "diag_bot", "user", "tester", "ping"]
            ws.append_row(test_row, value_input_option="USER_ENTERED")
            st.success("テスト行を追加しました。『末尾3行』に DIAG_TEST が見えるか確認してください。")
        except Exception as e:
            st.error(f"診断: 書き込みに失敗 → {e}")

