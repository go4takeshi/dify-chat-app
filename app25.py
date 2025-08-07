import streamlit as st
import requests
import uuid
import json # jsonライブラリをインポート
import os   # ファイルの存在を確認するためにosライブラリをインポート

# ----------------------------
# Dify API設定
# ----------------------------
# ▼▼▼ 修正点 ▼▼▼
# Streamlit Community Cloudにデプロイするため、
# APIキーは「Secrets」機能で安全に管理します。
# このコードをそのままお使いください。
PERSONA_API_KEYS = {
    "①ミノンBC理想ファン_乳児ママ_本田ゆい（30）": "",
    "②ミノンBC理想ファン_乳児パパ_安西涼太（31）": "",
    "③ミノンBC理想ファン_保育園/幼稚園ママ_戸田綾香（35）": "",
    "④ミノンBC理想ファン_更年期女性_高橋恵子（48）": "",
    "⑤ミノンBC未満ファン_乳児ママ_中村優奈（31）": "",
    "⑥ミノンBC未満ファン_乳児パパ_岡田健志（32）": "",
    "⑦ミノンBC未満ファン_保育園・幼稚園ママ_石田真帆（34）": "",
    "⑧ミノンBC未満ファン_更年期女性_杉山紀子（51）": ""
}

# ペルソナごとにアバター画像を管理するための辞書
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


DIFY_API_URL = "https://api.dify.ai/v1/chat-messages"

# ----------------------------
# ページ設定
# ----------------------------
st.set_page_config(page_title="Dify連携チャット", layout="centered")

# --- session_stateの初期化 ---
if "page" not in st.session_state:
    st.session_state.page = "login"
    st.session_state.cid = "" 
    st.session_state.messages = []
    st.session_state.bot_type = "" # 選択されたボットの種類を保存
    st.session_state.user_avatar_data = None # ユーザーアバターのデータを保存

# ----------------------------
# STEP 1：ユーザー情報入力画面
# ----------------------------
if st.session_state.page == "login":
    st.title("AIペルソナとの対話を始める")

    with st.form("user_info_form"):
        name = st.text_input("あなたのお名前（例：山田太郎）")
        bot_type = st.selectbox("対話するAIペルソナを選んでください", list(PERSONA_API_KEYS.keys()))
        uploaded_file = st.file_uploader("あなたのアバター画像を選択（任意）", type=["png", "jpg", "jpeg"])
        submitted = st.form_submit_button("対話開始")

        if submitted and name:
            if uploaded_file is not None:
                st.session_state.user_avatar_data = uploaded_file.getvalue()
            else:
                st.session_state.user_avatar_data = None

            st.session_state.page = "chat"
            st.session_state.cid = "" 
            st.session_state.messages = []
            st.session_state.bot_type = bot_type 
            st.query_params["page"] = "chat"
            st.rerun()

# ----------------------------
# STEP 2：チャット画面
# ----------------------------
elif st.session_state.page == "chat":
    st.markdown(f"#### 💬 {st.session_state.bot_type}")
    
    assistant_avatar_file = PERSONA_AVATARS.get(st.session_state.bot_type, "default_assistant.png")
    
    user_avatar = st.session_state.get("user_avatar_data") if st.session_state.get("user_avatar_data") is not None else "👤"
    assistant_avatar = assistant_avatar_file if os.path.exists(assistant_avatar_file) else "🤖"

    if assistant_avatar == " ":
        st.info(f"アシスタントのアバター画像（{assistant_avatar_file}）が見つかりません。app.py と同じフォルダに配置すると、カスタムアイコンが表示されます。")

    for msg in st.session_state.messages:
        current_avatar = assistant_avatar if msg["role"] == "assistant" else user_avatar
        with st.chat_message(msg["role"], avatar=current_avatar):
            st.markdown(msg["content"])

    if user_input := st.chat_input("メッセージを入力してください"):
        with st.chat_message("user", avatar=user_avatar):
            st.markdown(user_input)
        st.session_state.messages.append({"role": "user", "content": user_input})

        current_api_key = PERSONA_API_KEYS.get(st.session_state.bot_type)

        if not current_api_key:
            st.error("選択されたペルソナのAPIキーが設定されていません。Streamlit CloudのSecretsを確認してください。")
        else:
            headers = {
                "Authorization": f"Bearer {current_api_key}",
                "Content-Type": "application/json"
            }
            
            payload = {
                "inputs": {},
                "query": user_input,
                "user": "streamlit-user",
                "conversation_id": st.session_state.cid,
                "response_mode": "blocking", 
            }

            with st.chat_message("assistant", avatar=assistant_avatar):
                try:
                    with st.spinner("AIが応答を生成中です..."):
                        res = requests.post(
                            DIFY_API_URL, 
                            headers=headers, 
                            data=json.dumps(payload),
                            timeout=30
                        )
                        res.raise_for_status()
                        
                        res_json = res.json()
                        answer = res_json.get("answer", "⚠️ 応答がありませんでした。")
                        
                        new_conv_id = res_json.get("conversation_id")
                        if new_conv_id:
                            st.session_state.cid = new_conv_id
                        
                        st.markdown(answer)

                except requests.exceptions.HTTPError as e:
                    error_response = e.response
                    error_details = f"Status Code: {error_response.status_code}\n"
                    error_details += f"Response Body: {error_response.text}"
                    answer = f"⚠️ APIリクエストでHTTPエラーが発生しました：\n\n---\n**詳細情報:**\n\n```\n{error_details}\n```"
                    st.markdown(answer)
                except Exception as e:
                    answer = f"⚠️ 不明なエラーが発生しました：\n\n{e}"
                    st.markdown(answer)

            st.session_state.messages.append({"role": "assistant", "content": answer})

# ----------------------------
# ページパラメータが不正な場合の表示
# ----------------------------
else:
    st.error("不正なページ指定です。URLを確認してください。")
    if st.button("最初のページに戻る"):
        st.session_state.page = "login"
        st.session_state.cid = ""
        st.query_params.clear()

        st.rerun()
