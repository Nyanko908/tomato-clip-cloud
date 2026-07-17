# -*- coding: utf-8 -*-
"""server/app.py — クラウド版の統合エントリ。

1プロセスで FastAPI(uvicorn) の Web UI と Discord ボットを asyncio で同居起動する。
PaaS の 1 コンテナ / 1 dyno で両方動く。DISCORD_BOT_TOKEN があれば Bot も起動、無ければ Web のみ。

起動:
  python -m server.app
環境変数（詳細は server/README.md）:
  PORT（PaaSが指定。既定8000）, GEMINI_KEY, DISCORD_BOT_TOKEN, CREDENTIALS_JSON, YT_TOKEN_B64 ...

※ server.config を最初に import することで HOME 差し替え（Linux）が chat_engine 等より先に効く。
"""
import os
import sys
import asyncio

from server import config as cloudcfg  # 先頭で import（HOME差し替えを最速に効かせる）


def _public_url(port) -> str:
    """このサーバーの公開URLを推定する。各PaaSが自動で入れる env を優先。"""
    for key in ("PUBLIC_URL", "TOMATO_PUBLIC_URL", "RENDER_EXTERNAL_URL"):
        v = os.environ.get(key)
        if v:
            return v.rstrip("/")
    # Fly.io は app 名から
    fly = os.environ.get("FLY_APP_NAME")
    if fly:
        return f"https://{fly}.fly.dev"
    # 不明ならローカル（開発時）
    return f"http://localhost:{port}"


async def _heartbeat(port):
    """5分ごとに自分のURL・生存時刻をアカウントに登録し続ける。"""
    token = os.environ.get("TOMATO_ACCOUNT_TOKEN", "")
    if not token:
        return
    url = _public_url(port)
    print(f"[app] このサーバーを登録します: {url}")
    while True:
        try:
            import account
            await asyncio.get_running_loop().run_in_executor(
                None, account.register_server_with_token, token, url, "online")
        except Exception as e:
            print(f"[app] heartbeat 失敗: {e}", file=sys.stderr)
        await asyncio.sleep(180)  # 3分ごと


async def _keep_alive(port):
    """
    24時間稼働：無料枠(Render等)は一定時間アクセスが無いとスリープするので、
    自分の /healthz を定期的に叩いて起きたままにする。
    - 間隔は TOMATO_KEEPALIVE_MIN 分（既定10分／Render のスリープは15分無アクセス）
    - 0 を指定すると無効。ローカル開発では自動で無効。
    """
    try:
        every = int(os.environ.get("TOMATO_KEEPALIVE_MIN", "10"))
    except ValueError:
        every = 10
    if every <= 0:
        return
    url = _public_url(port)
    if "localhost" in url or "127.0.0.1" in url:
        return  # ローカルではスリープしないので不要
    target = url.rstrip("/") + "/healthz"

    def _ping():
        import urllib.request
        req = urllib.request.Request(target, headers={"User-Agent": "tomato-clip-keepalive"})
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status

    print(f"[app] 24時間稼働：{every}分ごとに自分を起こします → {target}")
    while True:
        await asyncio.sleep(every * 60)
        try:
            st = await asyncio.get_running_loop().run_in_executor(None, _ping)
            if st != 200:
                print(f"[app] keep-alive: 応答 {st}", file=sys.stderr)
        except Exception as e:
            print(f"[app] keep-alive 失敗: {e}", file=sys.stderr)


async def _amain():
    import uvicorn
    from server.web import create_app

    cloudcfg.setup_media_env()
    config = cloudcfg.load_config()

    port = int(os.environ.get("PORT", "8000"))
    host = os.environ.get("HOST", "0.0.0.0")

    app = create_app()
    uvconf = uvicorn.Config(app, host=host, port=port, log_level="info", access_log=False)
    server = uvicorn.Server(uvconf)

    tasks = [asyncio.create_task(server.serve(), name="web")]
    print(f"[app] Web UI → http://{host}:{port}")

    # 自分のURLをアカウントに登録（heartbeat）→ サイト/アプリが発見できる
    if cloudcfg.is_pro_allowed():
        tasks.append(asyncio.create_task(_heartbeat(port), name="heartbeat"))
        # 24時間稼働：無料枠のスリープを防ぐ自己ping
        tasks.append(asyncio.create_task(_keep_alive(port), name="keepalive"))

    token = os.environ.get("DISCORD_BOT_TOKEN") or config.get("discord_bot_token", "")
    if token and not cloudcfg.is_pro_allowed():
        print("[app] 非Proのため Discord ボットは起動しません（Pro限定）")
    elif token:
        from server.discord_client import build_client
        client = build_client(config)
        tasks.append(asyncio.create_task(client.start(token), name="discord"))
        print("[app] Discord ボットも起動します")
    else:
        print("[app] DISCORD_BOT_TOKEN 未設定 → Web のみ起動")

    # どれか1つでも落ちたら全体を終わらせる（PaaSが再起動する）
    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
    for t in done:
        exc = t.exception()
        if exc:
            print(f"[app] タスク {t.get_name()} が異常終了: {exc}", file=sys.stderr)
    for t in pending:
        t.cancel()


def main():
    try:
        asyncio.run(_amain())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
