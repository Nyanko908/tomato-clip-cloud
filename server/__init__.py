# -*- coding: utf-8 -*-
"""server パッケージ — Tomato Clip のクラウド版（BYO-deploy）バックエンド。

ヘッドレスLinuxで FastAPI Web UI と Discord ボットを、デスクトップ版と同じ
頭脳(chat_engine.ChatEngine)＋生成(pipeline)で動かす。設定は環境変数で注入する。
既存のデスクトップ資産(web_app.py / main.py / app.py / webui) は非破壊。
"""
