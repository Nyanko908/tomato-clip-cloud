# Tomato Clip — クラウド版（BYO-deploy）

自分のサーバー（Render / Railway / Fly.io / Replit / 任意のDocker環境）にデプロイして、
**ブラウザから操作できるWeb UI** と **Discord ボット（@TomatoAI）** を24時間動かすための構成です。
デスクトップ版と同じ頭脳（`chat_engine`）＋生成（`pipeline`）を共有します。

> 買い切りモデルのまま、運営はサーバーを持ちません。**API費・計算費はあなたのサーバー持ち**です。

---

## ⭐ かんたんセットアップ（推奨・env 2個だけ）

APIキーを10個並べる必要はありません。**デスクトップ版の設定をまるごと1つの暗号文字列**にまとめ、
`TOMATO_BUNDLE` と `TOMATO_BUNDLE_KEY` の**2つの環境変数を貼るだけ**でデプロイできます。

### 方法A：ターミナルのセットアップスクリプト（Claude Code 風）
```bash
python cloud_setup.py
```
デスクトップ版の設定（`~/.tomato_clip_config.json`）を**自動で同期**して読み込み、質問に答えるだけで
`TOMATO_BUNDLE` / `TOMATO_BUNDLE_KEY` を発行します。控えは `~/.tomato_clip_cloud_bundle.txt` にも保存。

### 方法B：アプリの「☁ クラウド」タブ
新UIの左メニュー「クラウド」→ 合言葉を決めて「パッケージ化」→ 表示された2つをコピー。

### 貼り付けてデプロイ
1. デプロイ先（Render/Railway/Fly/Replit）にこのリポジトリを接続。
2. Secrets に `TOMATO_BUNDLE` と `TOMATO_BUNDLE_KEY` を登録。
3. デプロイ（`Dockerfile` が自動で使われます）。
4. `https://<あなたのURL>/healthz` が `{"ok":true}` を返せば成功。
5. アプリの「☁ クラウド」タブに URL を入れて「接続を確認」。

> バンドルには APIキー・チャンネルID・YouTube投稿トークン・Discordトークンが含まれます。
> `TOMATO_BUNDLE_KEY` はパスワードと同じ扱いにしてください。
> デプロイ後の自己診断は `python -m server.preflight` で確認できます。

個別の環境変数で細かく設定したい上級者は、下の「環境変数」表を参照（個別 env はバンドルより優先されます）。

---

## 構成

| ファイル | 役割 |
|---|---|
| `server/config.py` | 環境変数から設定・鍵を組む。`HOME` を書込み可能ツリーへ。 |
| `server/web.py` | FastAPI。既存 `webui/` を `bridge.js`（fetchシム）付きで配信。`web_app.Api` を継承。 |
| `server/discord_client.py` | Discord ボット。`/tomato` スラッシュ＋@メンション/DM。 |
| `server/app.py` | 統合エントリ。Web と Bot を1プロセスで同居起動。 |
| `Dockerfile` / `Procfile` / `render.yaml` / `fly.toml` / `.replit`+`replit.nix` | 各PaaSのデプロイ設定。 |

起動: `python -m server.app` （`DISCORD_BOT_TOKEN` があれば Bot も起動、無ければ Web のみ）

---

## 環境変数

| 変数 | 必須 | 説明 |
|---|---|---|
| `TOMATO_BUNDLE` | 推奨 | `cloud_setup.py`/クラウドタブが発行する暗号バンドル。これ1つで下記の大半が復元される。 |
| `TOMATO_BUNDLE_KEY` | 推奨 | バンドルの合言葉（復号キー）。**パスワード扱い**。 |
| `GEMINI_KEY` | ✅（バンドル未使用時） | Gemini APIキー（あなた自身のキー）。 |
| `YOUTUBE_KEY` | 任意 | YouTube Data API キー（トレンド分析・検索に使用）。 |
| `GEMINI_MODEL` | 任意 | 既定 `gemini-2.5-flash-lite`。 |
| `OUTPUT_LANGUAGE` / `UI_LANG` | 任意 | 生成言語 / UI言語（既定 `ja`）。 |
| `DISCORD_BOT_TOKEN` | Bot使うなら | Discord Bot トークン。未設定なら Web のみ。 |
| `CREDENTIALS_JSON` | 投稿するなら | `client_secrets.json` の中身（インラインJSON か base64）。 |
| `YT_TOKEN_B64` | 投稿するなら | デスクトップで発行済みの `yt_token.pickle` を base64（後述）。 |
| `YTDLP_COOKIES_B64` | 任意 | yt-dlp 用 `cookies.txt` を base64（データセンターIPの429対策）。 |
| `YTDLP_PROXY` | 任意 | プロキシURL（`http://user:pass@host:port`）。429対策。 |
| `VOICEVOX_URL` | 任意 | VOICEVOX ENGINE のURL。未設定なら gTTS に自動フォールバック。 |
| `TOMATO_HOME` | 任意 | 書込み用HOME（既定 `/tmp/tomato_home`）。 |
| `TOMATO_UNGATED` | 任意 | `1`（既定）で Pro相当（クレジット無制限）。`0` で実ライセンス判定。 |
| `PORT` | 任意 | PaaSが指定。既定 `8000`。 |

---

## YouTube 無人投稿のセットアップ（`YT_TOKEN_B64`）

クラウドはヘッドレスでブラウザOAuthができないため、**デスクトップ版で一度だけ認証**して
生成される `yt_token.pickle` をサーバーへ移送します。

1. デスクトップ版（`web_app.py` / 本体アプリ）で YouTube 連携を済ませ、1本アップロードして
   `client_secrets.json` と同じフォルダに `yt_token.pickle` が出来ることを確認。
2. base64 化：
   ```bash
   # macOS/Linux
   base64 -i yt_token.pickle | tr -d '\n'
   # Windows PowerShell
   [Convert]::ToBase64String([IO.File]::ReadAllBytes("yt_token.pickle"))
   ```
3. 出力を `YT_TOKEN_B64` に、`client_secrets.json` の中身を `CREDENTIALS_JSON` に設定。

→ これで `pipeline.upload_to_youtube` がブラウザ無しで投稿できます（`_can_upload_unattended` が満たされる）。

---

## Discord ボット

1. [Discord Developer Portal](https://discord.com/developers/applications) で Bot を作成し、トークンを `DISCORD_BOT_TOKEN` に。
2. **Privileged Gateway Intents → MESSAGE CONTENT INTENT を ON**（@メンション本文を読むため）。
3. OAuth2 URL Generator で `bot` + `applications.commands` スコープ、権限は「メッセージ送信」等を付与して招待。
4. 使い方：
   - `/tomato <prompt>` スラッシュコマンド（推奨。長時間ジョブは defer→followup）。
   - チャンネルで `@TomatoAI つくって…` メンション、または DM。
5. 完成動画は **YouTube に投稿してリンクを返します**（Discordへの添付はしません）。

配線だけ確認：`python -m server.discord_client --selftest`（トークン不要）。

---

## デプロイ例（Render, Docker）

```bash
# ローカルDocker
docker build -t tomato-cloud .
docker run -p 8000:8000 \
  -e GEMINI_KEY=xxx \
  -e DISCORD_BOT_TOKEN=xxx \
  -e CREDENTIALS_JSON="$(cat client_secrets.json)" \
  -e YT_TOKEN_B64="$(base64 -i yt_token.pickle | tr -d '\n')" \
  tomato-cloud
# → http://localhost:8000 をブラウザで開く
```

Render は `render.yaml` の Blueprint、Fly.io は `fly.toml`＋`fly secrets set`、Replit は Secrets を使用。

---

## 既知の制約（MVP）

- **yt-dlp × データセンターIP**：クラウドIPからのYouTube DLは 429/bot判定が出やすい。
  `YTDLP_COOKIES_B64` / `YTDLP_PROXY` を用意。実効性はデプロイ後に要確認（最重要リスク）。
- **VOICEVOX 非搭載**：既定は gTTS（多言語・軽量）にフォールバック。日本語の声質にこだわる場合は
  VOICEVOX ENGINE を別サービスで立て `VOICEVOX_URL` を指定。
- **設定移送は手動env**：ワンタイムコードによる自動移送（本体「☁ Cloud」タブ連携）は後続フェーズ。
- **単一ユーザー想定**：BYO-deploy＝あなた専用サーバー。マルチテナントSaaSではありません。
