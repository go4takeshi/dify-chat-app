# app.py
import streamlit as st
import requests, json, os, time, uuid
from datetime import datetime, timezone
import pandas as pd
from urllib.parse import urlencode

# ====== ここはそのまま（あなたの設定を流用） ======
PERSONA_API_KEYS = {
    "①ミノンBC理想ファン_乳児ママ_本田ゆい（30）": "app-qNLWOMF6gJYLLzvWy6aUe3Fs",
    "②ミノンBC理想ファン_乳児パパ_安西涼太（31）": "app-2929ZbRVXV8iusFNSy4cupT5",
    "③ミノンBC理想ファン_保育園/幼稚園ママ_戸田綾香（35）": "app-7fzWdvERX8PWhhxiblrO5UY1",
    "④ミノンBC理想ファン_更年期女性_高橋恵子（48）": "app-tAw9tNFRWTiXqsmeduNEzzXX",
    "⑤ミノンBC未満ファン_乳児ママ_中村優奈（31）": "app-iGSXywEwUI5faBVTG3xRvOzU",
    "⑥ミノンBC未満ファン_乳児パパ_岡田健志（32）": "app-0fb7NSs8rWRAU3eLcY0Z7sHH",
    "⑦ミノンBC未満ファン_保育園・幼稚園ママ_石田真帆（34）": "app-3mq6c6el9Cu8H8JyULFCFInu",
    "⑧ミノンBC未満ファン_更年期女性_杉山紀子（51）": "app-3mq6c6el9Cu8H8JyULFCFInu"
}
PERSONA_AVATARS = {
    "①ミノンBC理想ファン_乳児ママ_本田ゆい（30）": "persona_1.jpg",
    "②ミノンBC理想ファン_乳児パパ_安西涼太（31）": "persona_2.jpg",
    "③ミノンBC理想ファン_保育園/幼稚園ママ_戸田綾香（35）": "persona_3.jpg",
    "④ミノンBC理想ファン_更年期女性_高橋恵子（48）": "persona_4.jpg",
    "⑤ミノンBC未満ファン_乳児ママ_中村優奈（31）": "persona_5.jpg",
    "⑥ミノンBC未満ファン_乳児パパ_岡田健志（32）": "persona_6.jpg",
    "⑦ミノンBC未満ファン_保育園・幼稚園ママ_石田真帆（34）": "persona_7.png",
    "⑧ミノンBC未満ファン_更年期女性_杉山紀子（51）": "persona_8.jpg"
}
DIFY_CHAT_URL = "https://api.dify.ai/v1/chat-messages"   # チャットフロー
# DIFY_WF_URL  = "https://api.dify.ai/v1/workflows/run"  # （参考）非会話ワークフロー

# ====== Google Sheets 接続 ======
import gspread
from google.oauth2.service_account import Credentials

def _gs_client():
    sa_info = st.secrets["gcp_service_account"]  # サービスアカウントJSONそのもの
    if isinstance(sa_info, str):
        import json as _json
        sa_info = _json.loads(sa_info)
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_info(sa_info, scopes=scopes)
    return gspread.authorize(creds)

def _open_sheet():
    gc = _gs_client()
    sh = gc.open_by_key(st.secrets["gsheet_id"])
    try:
        ws = sh.worksheet("chat_logs")
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title="chat_logs", rows=1000, cols=10)
        ws.append_row(["timestamp","conversation_id","bot_type","role","name","content"])
    return ws

def save_log(conversation_id:str, bot_type:str, role:str, name:str, content:str):
    ws = _open_sheet()
    ts = datetime.now(timezone.utc).isoformat()
    ws.append_row([ts, conversation_id, bot_type, role, name, content], value_input_option="RAW")

@st.cache_data(ttl=3)  # 軽いライブ更新用
def load_history(conversation_id:str) -> pd.DataFrame:
    ws = _open_sheet()
    data = ws.get_all_records()
    df = pd.DataFrame(data)
    if df.empty: 
        return df
    df = df[df["conversation_id"]==conversation_id].copy()
    if not df.empty and "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
        df = df.sort_values("timestamp")
    return df

# ====== Streamlit UI ======
st.set_page_config(page_title="Dify連携チャット（チャットフロー/グループ）", layout="centered")

# 初期化
if "page" not in st.session_state:
    st.session_state.page = "login"
    st.session_state.cid = "" 
    st.session_state.messages = []   # 画面即時反映用（ソースはSheetsと二重化）
    st.session_state.bot_type = ""
    st.session_state.user_avatar_data = None
    st.session_state.name = ""

# クエリから復元（共有リンク用）
qp = st.query_params
if "cid" in qp and not st.session_state.cid:
    st.session_state.cid = qp.get("cid")
if "bot" in qp and not st.session_state.bot_type:
    st.session_state.bot_type = qp.get("bot")
if "name" in qp and not st.session_state.name:
    st.session_state.name = qp.get("name")
if "page" in qp and st.session_state.page != qp.get("page"):
    st.session_state.page = qp.get("page")

# ========== STEP 1: ログイン ==========
if st.session_state.page == "login":
    st.title("AIペルソナとグループでチャット（Dify チャットフロー）")

    with st.form("user_info_form"):
        name = st.text_input("あなたの表示名", value=st.session_state.name or "")
        bot_type = st.selectbox("対話するAIペルソナ", list(PERSONA_API_KEYS.keys()),
                                index=(list(PERSONA_API_KEYS.keys()).index(st.session_state.bot_type)
                                       if st.session_state.bot_type in PERSONA_API_KEYS else 0))
        existing_cid = st.text_input("既存の会話ID（共有リンクで参加する場合に貼付）", value=st.session_state.cid or "")
        uploaded_file = st.file_uploader("あなたのアバター画像（任意）", type=["png","jpg","jpeg"])
        colA, colB = st.columns(2)
        submitted = colA.form_submit_button("チャット開始")
        new_conv   = colB.form_submit_button("新しい会話を始める（会話IDをリセット）")

        if submitted and name:
            if uploaded_file is not None:
                st.session_state.user_avatar_data = uploaded_file.getvalue()
            st.session_state.page = "chat"
            st.session_state.cid = existing_cid.strip()
            st.session_state.bot_type = bot_type
            st.session_state.name = name.strip()
            st.session_state.messages = []
            st.query_params.update({"page":"chat","cid":st.session_state.cid or "","bot":bot_type,"name":st.session_state.name})
            st.rerun()

        if new_conv:
            st.session_state.page = "chat"
            st.session_state.cid = ""  # 空で開始→Difyが新規IDを発行
            st.session_state.bot_type = bot_type
            st.session_state.name = (name or "").strip() or "anonymous"
            st.session_state.messages = []
            st.query_params.update({"page":"chat","cid":"","bot":bot_type,"name":st.session_state.name})
            st.rerun()

# ========== STEP 2: チャット ==========
elif st.session_state.page == "chat":
    st.markdown(f"#### 💬 {st.session_state.bot_type}")
    st.caption("同じ会話IDを共有すれば、全員で同じコンテキストを利用できます。")

    # アバター
    assistant_avatar_file = PERSONA_AVATARS.get(st.session_state.bot_type, "default_assistant.png")
    user_avatar = st.session_state.get("user_avatar_data") if st.session_state.get("user_avatar_data") else "👤"
    assistant_avatar = assistant_avatar_file if os.path.exists(assistant_avatar_file) else "🤖"

    # 読み取りは常に新API
    qp = st.query_params
    
    # 共有リンク（相対URLでOK。クリックすれば同アプリ内で遷移します）
    params = {
        "page": "chat",
        "cid": st.session_state.cid or "",
        "bot": st.session_state.bot_type,
        "name": st.session_state.name,
    }
    share_link = f"?{urlencode(params)}"
    
    st.code(share_link, language="text")
    st.link_button("共有リンクを開く", share_link)
    
# 共有リンク表示
cid_show = st.session_state.cid or "(未発行：最初の発話で採番されます)"
st.info(f"会話ID: `{cid_show}`")

if st.session_state.cid:
    params = {
        "page": "chat",
        "cid": st.session_state.cid,
        "bot": st.session_state.bot_type,
        "name": st.session_state.name,
    }
    share_link = f"?{urlencode(params)}"  # 相対リンク
    st.code(share_link, language="text")
    st.link_button("共有リンクを開く", share_link)

    # 履歴（Google Sheets）を読み込み & 画面に描画
    if st.session_state.cid:
        df = load_history(st.session_state.cid)
        for _, r in df.iterrows():
            avatar = assistant_avatar if r["role"]=="assistant" else user_avatar
            with st.chat_message(r["role"], avatar=avatar):
                st.markdown(r["content"])

    # ローカルの未保存メッセージも反映
    for msg in st.session_state.messages:
        avatar = assistant_avatar if msg["role"]=="assistant" else user_avatar
        with st.chat_message(msg["role"], avatar=avatar):
            st.markdown(msg["content"])

    # 入力
    if user_input := st.chat_input("メッセージを入力してください"):
        # 画面即時に反映
        st.session_state.messages.append({"role":"user","content":user_input})
        with st.chat_message("user", avatar=user_avatar):
            st.markdown(user_input)
        # 永続化（user）
        try:
            save_log(st.session_state.cid or "(allocating...)", st.session_state.bot_type, "user", st.session_state.name or "anonymous", user_input)
        except Exception as e:
            st.warning(f"スプレッドシート保存に失敗：{e}")

        # Difyに投げる
        api_key = PERSONA_API_KEYS.get(st.session_state.bot_type)
        if not api_key:
            st.error("選択されたペルソナのAPIキーが未設定です。")
        else:
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type":"application/json"}
            payload = {
                "inputs": {},                  # 既存のconversation_idがある場合、inputsは無視される（仕様）
                "query": user_input,
                "user": st.session_state.name or "streamlit-user",
                "conversation_id": st.session_state.cid,
                "response_mode": "blocking"
            }
            with st.chat_message("assistant", avatar=assistant_avatar):
                try:
                    with st.spinner("AIが応答を生成中です…"):
                        res = requests.post(DIFY_CHAT_URL, headers=headers, data=json.dumps(payload), timeout=60)
                        res.raise_for_status()
                        res_json = res.json()
                        answer = res_json.get("answer", "⚠️ 応答がありませんでした。")

                        # 会話IDの確定・更新
                        new_cid = res_json.get("conversation_id")
                        if new_cid:
                            st.session_state.cid = new_cid
                            st.query_params.update({"cid": new_cid})

                        st.markdown(answer)
                except requests.exceptions.HTTPError as e:
                    body = e.response.text
                    answer = f"⚠️ HTTPエラー: {e}\n\n```\n{body}\n```"
                    st.markdown(answer)
                except Exception as e:
                    answer = f"⚠️ 不明なエラー: {e}"
                    st.markdown(answer)

        # メモリ & 永続化（assistant）
        st.session_state.messages.append({"role":"assistant","content":answer})
        try:
            save_log(st.session_state.cid, st.session_state.bot_type, "assistant", st.session_state.bot_type, answer)
        except Exception as e:
            st.warning(f"スプレッドシート保存に失敗（assistant）：{e}")

    # 操作ボタン
    col1, col2, col3 = st.columns(3)
    if col1.button("履歴を再読込"):
        st.cache_data.clear()
        st.rerun()
    if col2.button("この会話を終了（新規IDで再開）"):
        st.session_state.cid = ""
        st.session_state.messages = []
        st.query_params.update({"cid": ""})
        st.success("会話IDをリセットしました。次の送信で新規IDが採番されます。")
    if col3.button("ログアウト"):
        st.session_state.page = "login"
        st.session_state.messages = []
        st.query_params.clear()
        st.rerun()

# ========== フォールバック ==========
else:
    st.error("不正なページ指定です。")
    if st.button("最初のページに戻る"):
        st.session_state.page = "login"
        st.session_state.cid = ""
        st.query_params.clear()

        st.rerun()


