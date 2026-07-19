# AGENTS.md — Tomato Clip 開発エージェント向けガイド

Python製・買い切り型のショート動画自動生成アプリ。デスクトップ（pywebview/WebView2）と
クラウド（FastAPI・Render・BYO-deploy）の2形態が**同じコードベース**で動く。

## リポジトリと作業フロー（重要）
- GitHub リポジトリ `Nyanko908/tomato-clip-cloud` が**正**。Render が master への push を自動デプロイする。
- ローカル作業コピー `C:\Users\koumo\CLIP FLOW ProMax fixed\CLIP_FLOW_ProMax` は **git 管理外**。
  複数エージェントが併走するため、**push 前に必ず pull して差分を確認**すること。
- デスクトップ専用ファイル（`main.py` / `app.py`(旧Tkinter・現役ではない) / `build_exe.py` /
  `dist/`）はクラウドリポに含めない。

## 主要モジュール
| ファイル | 役割 |
|---|---|
| `web_app.py` | デスクトップ入口・`Api`クラス（JS↔Python）・ローカルメディア配信サーバー |
| `chat_engine.py` | チャットの頭脳（Gemini function calling・クレジット管理） |
| `pipeline.py` | 検索→DL→解析→編集→投稿のパイプライン全体 |
| `editor.py` | レンダリング（レイアウト/字幕/エフェクト/`TimeMap`） |
| `code_edit.py` | Python編集モード（AIが編集コードを生成・ASTサンドボックス・自己修復） |
| `tc_db.py` | 素材ストア（Web検索取得＋ライセンス記録・AI画像生成） |
| `server/` | クラウド版（`CloudApi` が `web_app.Api` を継承） |
| `webui/` | フロント（`index.html`+`app.js`。デスクトップ/クラウド共用・無改変配信） |

## 地雷リスト（実際に踏んだもの）
1. **ファイルエンコーディング**: `pipeline.py` は BOM 付き UTF-8。読むときは `utf-8-sig`。
   コンソールは cp932 なので `python -X utf8` 推奨。em-dash 等でクラッシュした前例あり。
2. **config の上書き事故**: クラウド系コード（`server/*`）から `web_app.save_config` に到達すると
   env 由来のほぼ空 config が `~/.tomato_clip_config.json` を潰す。ガードとして
   `TOMATO_CLOUD=1` のとき save_config は no-op。**このガードを外さないこと**（APIキー消失の実害あり）。
3. **file:/// の動画は WebView2 で再生不可**（pywebview はページを内蔵HTTPサーバー配信するため
   「URL safety check」で拒否される）。DOM に渡す動画は必ず配信URL
   （デスクトップ=`Api._local_media_url`、クラウド=`CloudApi._media_url`）を通す。
4. **時間写像（TimeMap）**: 編集で尺が変わるのに元動画基準の秒数を使うと字幕がズレる。
   カット等の秒数は `editor.TimeMap` / `code_edit` のオペログを必ず経由する。
   `editor.run_edit` の適用順（cuts→fastforward→rewind→freeze）を変えるなら
   `web_app.Api._build_timemap` も同時に合わせること。
5. **CSSのパーセント連鎖**: 高さ auto の親に対する `max-height:100%` は WebView2 で壊れる
   （Chrome では偶然動く）。確定サイズ（絶対配置）を使う。
6. **Gemini モデル名は `-latest` エイリアスを使う**（`pipeline.DEFAULT_MODEL`）。
   固定バージョン名は廃止で全滅した前例あり。廃止モデルは `web_app._RETIRED_MODELS` で移行。
7. **Gemini 画像生成は無料枠キーで quota limit:0**（全モデル）。`tc_db.generate_asset` は
   検知して無効化する。テストで生成系を実キーで叩くときはクォータ消費に注意。
8. **サンドボックス**: `code_edit.validate_code` は Python編集コードの安全弁
   （import 許可リスト・open/eval/os 禁止・ダンダー禁止）。**緩めるときはユーザー承認必須**。
9. **素材のライセンス**: `tc_db` は商用可（CC0/PD/CC BY/BY-SA）のみ保存し、meta.json に
   出所・作者・ライセンスを必ず記録。クレジット必要素材は動画の引用元表示に自動追記される。
   この方針を壊す変更は不可（買い切り商品の最大リスク領域）。
10. **セキュリティ既知の弱点（修正歓迎）**: `server/web.py` の `/api/{name}` は
    `_ALLOWED` ホワイトリスト方式・認証なし（Pro ゲートのみ）。ローカルメディアサーバーは
    127.0.0.1 限定・Range 対応・出力フォルダのみ配信。license/worker 関連は
    `license.py`・Cloudflare Worker 側も参照。

## 検証のやり方
- ブラウザE2E: `PORT=8765 python -m server.app` → Playwright + 既存 Chrome
  （`executable_path=C:\Program Files\Google\Chrome\Application\chrome.exe`）。
- 実アプリ(WebView2)の検証: `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--remote-debugging-port=9222`
  で起動し Playwright `connect_over_cdp`。
- レンダリング検証: `pipeline.edit_video` を合成 analysis で直接呼び、ffmpeg でフレーム抽出して確認。
- 生成系のフルE2Eは Gemini/YouTube クォータを消費する。乱発しない。

## 作法
- 日本語UI文字列は `i18n.py` の `_NEW_UI*` 辞書（12言語）に追加。
- コメントは日本語。「何をしたか」ではなく「なぜ・制約」を書く。
- 動画が完成しない事態は絶対に作らない（新機能は必ずフォールバック付き）。
