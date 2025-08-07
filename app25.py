import streamlit as st

# ==============================================================================
# ▼▼▼【重要】Secrets機能の動作確認用テストコードです ▼▼▼
# ==============================================================================
# このコードは、Streamlit CloudのSecrets機能が正しく動作しているかを確認するためだけの
# 一時的なテストプログラムです。
# このテストが完了したら、元のチャットアプリのコードに戻します。
# ==============================================================================

st.title("Streamlit Secrets 機能テスト")

st.info("このページは、StreamlitのSecrets機能が正しく動作しているかを確認するためのテストです。")

# 'st.secrets' を使って値の取得を試みる
# Streamlit CloudのSecrets設定に 'TEST_KEY = "..."' が正しく設定されていれば、
# 'test_value' にはその値が入ります。
try:
    test_value = st.secrets["TEST_KEY"]
except KeyError:
    test_value = None # キーが存在しない場合はNoneを設定

if test_value:
    st.success("✅ Secretsからキーを正常に読み込めました！")
    st.balloons()
    st.write("設定されていた値は以下の通りです：")
    st.code(test_value, language="text")
    st.write("---")
    st.write("この結果は、Secrets機能自体は正しく動作していることを示しています。")
    st.write("元のエラーの原因は、キーの名前の不一致など、別の要因である可能性が高いです。")

else:
    st.error("❌ Secretsからキーを読み込めませんでした。")
    st.write("---")
    st.write("この結果は、Streamlit CloudのSecrets機能が何らかの理由で正しく動作していないことを示しています。")
    st.write("Secretsの入力内容（キーの名前、ダブルクォーテーションなど）を再度ご確認ください。")
