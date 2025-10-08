import streamlit as st

st.title("Secrets 最終検証")

key_to_check = "gcp_service_account"

st.header(f"キー '{key_to_check}' の存在チェック")

if key_to_check in st.secrets:
    st.success(f"✅ 成功: キー '{key_to_check}' は見つかりました！")
    st.info("キーに設定されている値:")
    st.text(st.secrets[key_to_check])
else:
    st.error(f"❌ 失敗: キー '{key_to_check}' が見つかりません。")
    st.warning("現在アプリが認識しているSecretsのキー一覧:")
    
    # st.secrets.keys()が空でないことを確認してから表示
    keys_list = list(st.secrets.keys())
    if keys_list:
        st.write(keys_list)
    else:
        st.write("（キーが一つも読み込めていません）")
