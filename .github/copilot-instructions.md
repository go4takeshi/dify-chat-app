## dify-chat-app — Streamlit Community Cloud 用短縮ガイド（日本語）

このリポジトリは Streamlit アプリ（`app25.py`）で、Dify のペルソナを使った対話を行います。Google Sheets へのログ保存ユーティリティは `AI Persona MinonBC.py` にあります。

重要なファイル
- `app25.py` — メインの Streamlit アプリ（ログイン→チャット、CSVアップロード/添付、チャットCSVダウンロードを含む）
- `AI Persona MinonBC.py` — Google Sheets 連携と persona キー/アバターの管理ユーティリティ
- `requirements.txt` — Cloud が参照する依存リスト
- `persona_*.jpg|png` — ペルソナのアバター画像

デプロイ（Streamlit Community Cloud）手順（最短）
1. GitHub にこのリポジトリを push します（ブランチは任意）。
2. Streamlit Community Cloud で "New app" → GitHub リポジトリを選択 → ブランチと `app25.py` を指定して作成。
3. Secrets を設定（下記参照）。アプリが自動的に `requirements.txt` を使って依存をインストールします。

必須 Secrets（Streamlit Cloud の App → Settings → Secrets）
- `PERSONA_1_KEY` ... `PERSONA_8_KEY`: 各ペルソナの Dify API キー
- `gcp_service_account`: Google サービスアカウントの JSON（クォート付きの文字列 or TOML テーブル）。Google Sheets を使う場合に必要。
- `gsheet_id`: ログを書き込む Google スプレッドシートのキー

ローカルでの動作確認（任意）
- `.streamlit/secrets.toml` を作って Secrets を模擬できます（ローカル用。コミット禁止）。例：
  ```toml
  PERSONA_1_KEY = "app-xxxx"
  gcp_service_account = '''{ "type": "service_account", "private_key": "-----BEGIN PRIVATE KEY-----\n..." }'''
  gsheet_id = "1AbC..."
  ```

CSV 関連の挙動（実装済み）
- チャット画面で CSV をアップロードすると先頭 10 行をプレビューします。
- 「次のメッセージにこのCSVの内容を含める」を ON にすると、送信時に payload の `inputs.csv` に先頭100行をテキスト化して含めます（API の受け取り方は Dify の仕様に依存）。
- チャット履歴は画面上のボタンで `chat_logs.csv` としてダウンロードできます。

設計上の注意点 / 既知のポイント
- `AI Persona MinonBC.py` にある `save_log(...)` を使えば Google Sheets に逐次ログ保存できますが、現在の `app25.py` 実装はローカルダウンロードを行うのみで自動保存はしていません。必要なら `save_log` を呼ぶ hook を追加可能です。
- 大きな CSV をそのまま送るとリクエストが重くなるため、先頭 100 行で制限しています。
- Persona の鍵や Secrets のキー名は `app25.py` と `AI Persona MinonBC.py` で一貫性を保ってください（現在は `PERSONA_1_KEY` ... を参照）。

トラブルシューティング（Cloud 特有）
- 依存のインストールで失敗した場合：Streamlit Cloud のビルドログを確認。特定のバージョンを `requirements.txt` に固定すると安定します。
- Secrets がないと Dify API は 401/403 を返します。Cloud の Secrets を正確に登録してください。
- Google Sheets の権限エラー（403）の場合、対象スプレッドシートをサービスアカウントの `client_email` に『編集者』で共有してください。

追加提案（任意）
- Google Sheets へチャットを自動保存したい場合：`app25.py` のメッセージ append 箇所に `from AI Persona MinonBC import save_log` を追加して呼び出します（Secrets 必須）。
- Dify の受け取り仕様に合わせ、CSV を multipart/form-data のファイルアップロードに変更することも可能（要 API 仕様確認）。

最後に
- まずは Streamlit Community Cloud に push → デプロイ → Secrets を設定して動かしてみてください。ログやエラーを貼って頂ければ継続サポートします。
