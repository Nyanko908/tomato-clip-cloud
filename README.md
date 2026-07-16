# Tomato Clip Cloud

**Tomato Clip** のクラウド版（BYO-deploy）。自分のサーバーにデプロイして、
PC を閉じても動画生成と Discord ボットを 24 時間動かすためのバックエンドです。

このリポジトリは「Deploy to Render」ボタンから使うことを想定しています。

## ワンクリック・デプロイ

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/Nyanko908/tomato-clip-cloud)

1. 上のボタンを押す（Render は無料枠・クレジットカード不要）
2. Secrets に **`TOMATO_ACCOUNT_TOKEN`** を貼る
   （Tomato Clip アプリの「☁ クラウド」→ セットアップで発行される鍵）
3. Deploy → 発行された URL の `/healthz` が `{"ok":true}` を返せば成功

設定（API キー・チャンネル・YouTube 連携など）は、あなたの **TomatoAI アカウント**から
自動で引き継がれます。個別の環境変数を並べる必要はありません。

## 仕組み
- `server/app.py` … Web UI（FastAPI）＋ Discord ボットを 1 プロセスで起動
- 起動時にアカウントから設定を復元し、自分の URL をアカウントに登録（アプリ/サイトが発見できる）
- **Pro プラン限定**（買い切り購入者のみ）。非 Pro は起動をブロックします

詳しくは `server/README.md` を参照してください。

---
🤖 Powered by [Tomato Clip](https://tomatoclip.web.app)
