# Tomato Clip クラウド版（Web UI ＋ Discord ボット）
# BYO-deploy: ユーザーが自前サーバー（Render/Railway/Fly/Docker）で 24h 稼働させる。
FROM python:3.12-slim

# ffmpeg（moviepy/yt-dlp のマージに必須）＋ 最小ビルド依存
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 依存を先に入れてレイヤキャッシュを効かせる
COPY server/requirements.txt /app/server/requirements.txt
RUN pip install --no-cache-dir -r /app/server/requirements.txt

# アプリ本体（server/ ＋ 共有する頭脳・生成・UI）
COPY . /app

# HOME を書き込み可能なツリーへ（license/credits/db/出力が集まる。server/config も同値を設定）
ENV TOMATO_HOME=/tmp/tomato_home \
    PORT=8000 \
    PYTHONUNBUFFERED=1 \
    TOMATO_UNGATED=1

EXPOSE 8000

CMD ["python", "-m", "server.app"]
