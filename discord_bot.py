# -*- coding: utf-8 -*-
"""
discord_bot.py — Tomato Clip の Discord ボット（プラグイン / Cloud版クライアント）

@TomatoAI へのメンション（またはDM）で、chat_engine.ChatEngine が返答し、動画生成も実行する。
完成動画は YouTube に自動アップロードして「リンク」を投稿する（Discordの添付容量制限を避けるため）。

Web版(web_app.py)と同じ頭脳(chat_engine)＋生成(pipeline)を共有する別クライアント。
現行の本体アプリ(main.py) とは独立。

必要: discord.py（導入済み）
起動:
  python discord_bot.py            # 本番（要 Botトークン）
  python discord_bot.py --selftest # Discordに接続せず、ChatEngine配線だけ検証（トークン不要）
設定: ~/.tomato_clip_config.json（gemini_key など）
トークン: 環境変数 DISCORD_BOT_TOKEN もしくは config["discord_bot_token"]
"""
import os, sys, json, asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
CONFIG_PATH = Path.home() / ".tomato_clip_config.json"


def load_config() -> dict:
    try:
        if CONFIG_PATH.exists():
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _setup_media_env():
    """生成（moviepy編集）のための ffmpeg パス設定 & PIL 互換パッチ（web_app と同じ）。"""
    try:
        import imageio_ffmpeg
        os.environ["IMAGEIO_FFMPEG_EXE"] = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass
    try:
        from PIL import Image
        if not hasattr(Image, "ANTIALIAS"):
            Image.ANTIALIAS = Image.LANCZOS
    except Exception:
        pass


class TomatoDiscord:
    """1 Discordチャンネル = 1 会話。ChatEngine を流用し、コールバックを Discord に橋渡しする。

    ChatEngine のコールバックは engine 側スレッドから呼ばれるため、
    asyncio.run_coroutine_threadsafe で bot のイベントループへ渡す（web版のqueue/poll相当）。
    """

    def __init__(self, config: dict):
        self.config = config
        self._license = None
        try:
            from license import get_license
            self._license = get_license()
        except Exception:
            self._license = None
        self._engines = {}  # channel_id -> ChatEngine（チャンネルごとに会話を保持）

    def _engine_for(self, cid):
        from chat_engine import ChatEngine
        if cid not in self._engines:
            self._engines[cid] = ChatEngine(self.config, lambda: self._license, {})
        return self._engines[cid]

    async def handle(self, message, text: str, client):
        """メッセージ1件を処理：テキスト応答＋（生成時は）YouTubeリンク投稿。"""
        loop = asyncio.get_running_loop()
        channel = message.channel
        status = await channel.send("🍅 考え中…")

        def post(coro):
            asyncio.run_coroutine_threadsafe(coro, loop)

        async def _edit(msg, content):
            try:
                await msg.edit(content=content[:1900])
            except Exception:
                pass

        async def _send(content):
            try:
                return await channel.send(content[:1900])
            except Exception:
                return None

        # ChatEngine → Discord のコールバック（engineスレッドから呼ばれる）
        cb = {
            "on_text":           lambda t: post(_send(t)),
            "on_progress_start": lambda pid, title: post(_edit(status, f"⏳ {title}…")),
            "on_progress":       lambda pid, step: post(_edit(status, f"⏳ {step}")),
            "on_progress_done":  lambda pid, title: post(_edit(status, f"✅ {title}")),
            "on_video":          lambda d: post(self._on_video(channel, d)),
            "on_error":          lambda t: post(_send(f"⚠️ {t}")),
            "on_done":           lambda: None,
        }
        engine = self._engine_for(channel.id)
        engine.cb = cb
        # engine.send はブロッキング（内部で生成スレッドを回す）→ executorで実行
        await loop.run_in_executor(None, engine.send, text)

    async def _on_video(self, channel, d):
        """完成動画 → YouTube アップロード → リンク投稿（★添付しない）。"""
        try:
            d = d if isinstance(d, dict) else json.loads(d)
        except Exception:
            d = {}
        path = d.get("path", "")
        title = d.get("title", "完成した動画")
        cred = self.config.get("credentials_path", "")
        loop = asyncio.get_running_loop()

        if cred and Path(cred).exists() and path and Path(path).exists():
            note = await channel.send(f"📤 「{title}」を YouTube に投稿中…")

            def _up():
                from pipeline import upload_to_youtube
                analysis = {
                    "title": title,
                    "description": d.get("subtitle", ""),
                    "output_language": self.config.get("output_language", "ja"),
                }
                return upload_to_youtube(path, analysis, cred, lambda m: None)

            try:
                url = await loop.run_in_executor(None, _up)
            except Exception as e:
                url = None
                print("[discord] upload error:", e)
            if url:
                await note.edit(content=f"🎬 **{title}**\n{url}")
            else:
                await note.edit(content=f"✅ 「{title}」完成（YouTube投稿に失敗／サーバーに保存済み）")
        else:
            await channel.send(
                f"✅ 「{title}」が完成しました（YouTube連携が未設定のためリンクを出せません）")


def build_client(config: dict):
    import discord
    intents = discord.Intents.default()
    intents.message_content = True  # @メンション本文を読むため（Dev Portalでも「MESSAGE CONTENT INTENT」を有効化）
    client = discord.Client(intents=intents)
    bot = TomatoDiscord(config)

    @client.event
    async def on_ready():
        print(f"[discord] logged in as {client.user} (id={client.user.id})")

    @client.event
    async def on_message(message):
        if message.author.bot:
            return
        mentioned = client.user in message.mentions
        is_dm = (message.guild is None)
        if not (mentioned or is_dm):
            return
        text = message.content or ""
        for m in message.mentions:
            text = text.replace(f"<@{m.id}>", "").replace(f"<@!{m.id}>", "")
        text = text.strip()
        if not text:
            await message.channel.send("🍅 何をつくりましょう？（例:「アイアンマウスで1本つくって」）")
            return
        await bot.handle(message, text, client)

    return client


def _selftest(config: dict):
    """Discordに接続せず、ChatEngine→コールバック配線を検証（トークン不要）。"""
    import discord
    print("[selftest] discord.py:", discord.__version__)
    from chat_engine import ChatEngine
    got = {"text": 0, "done": False}

    def _t(t):
        got["text"] += 1
        print("  on_text:", (t[:70] + "…") if len(t) > 70 else t)

    cb = {
        "on_text":           _t,
        "on_progress_start": lambda *a: print("  progress_start:", a[1:]),
        "on_progress":       lambda *a: None,
        "on_progress_done":  lambda *a: print("  progress_done:", a[1:]),
        "on_video":          lambda d: print("  on_video:", d),
        "on_error":          lambda t: print("  on_error:", t),
        "on_done":           lambda: got.__setitem__("done", True),
    }
    eng = ChatEngine(config, lambda: None, cb)
    msg = "こんにちは！あなたは何ができますか？簡潔に教えて"
    print(f"[selftest] send: {msg}")
    eng.send(msg)
    ok = got["text"] > 0 and got["done"]
    print(f"[selftest] {'OK' if ok else 'NG'} (on_text={got['text']}, done={got['done']})")


def main():
    try:
        from brand_migrate import migrate_legacy_paths
        migrate_legacy_paths(print)
    except Exception:
        pass
    _setup_media_env()
    config = load_config()
    if "--selftest" in sys.argv:
        _selftest(config)
        return
    token = os.environ.get("DISCORD_BOT_TOKEN") or config.get("discord_bot_token", "")
    if not token:
        print("DISCORD_BOT_TOKEN が未設定です（環境変数 or ~/.tomato_clip_config.json の discord_bot_token）。")
        return
    client = build_client(config)
    client.run(token)


if __name__ == "__main__":
    main()
