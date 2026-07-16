# -*- coding: utf-8 -*-
"""server/discord_client.py — Tomato Clip Discord ボット（クラウド版）。

既存 discord_bot.py（PoC）を土台に、クラウド向けに強化：
- 設定は server.config.load_config()（環境変数注入）に統一。
- `/tomato <prompt>` スラッシュコマンド（defer→followup で長時間ジョブ対応）を追加。
- @メンション / DM 経路も従来通り維持。
- 完成動画は YouTube へ無人投稿し「リンク」を返す（★添付しない）。

Web版(server/web.py)と同じ頭脳(chat_engine.ChatEngine)＋生成(pipeline)を共有する別クライアント。

起動:
  python -m server.discord_client            # 本番（要 DISCORD_BOT_TOKEN）
  python -m server.discord_client --selftest # Discord非接続で ChatEngine 配線検証
"""
import os
import sys
import json
import asyncio
from pathlib import Path

from server import config as cloudcfg


class TomatoDiscord:
    """1 Discordチャンネル = 1 会話。ChatEngine を流用し、コールバックを Discord へ橋渡し。

    ChatEngine のコールバックは engine 側スレッドから呼ばれるため、
    asyncio.run_coroutine_threadsafe で bot のイベントループへ渡す。
    """

    def __init__(self, config: dict):
        self.config = config
        self._get_license = cloudcfg.license_getter()
        self._engines = {}  # channel_id -> ChatEngine（チャンネルごとに会話を保持）

    def _engine_for(self, cid):
        from chat_engine import ChatEngine
        if cid not in self._engines:
            self._engines[cid] = ChatEngine(self.config, self._get_license, {})
        return self._engines[cid]

    async def handle(self, channel, text: str):
        """メッセージ1件を処理：テキスト応答＋（生成時は）YouTubeリンク投稿。

        channel は discord のテキストチャンネル（on_message でも slash の defer 後でも使える）。
        """
        loop = asyncio.get_running_loop()
        status = await channel.send("🍅 考え中…")

        def post(coro):
            asyncio.run_coroutine_threadsafe(coro, loop)

        async def _edit(msg, content):
            try:
                await msg.edit(content=content[:1900])
            except Exception as e:
                print("[discord] edit error:", e, file=sys.stderr)

        async def _send(content):
            try:
                return await channel.send(content[:1900])
            except Exception as e:
                print("[discord] send error:", e, file=sys.stderr)
                return None

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
                print("[discord] upload error:", e, file=sys.stderr)
            if url:
                await note.edit(content=f"🎬 **{title}**\n{url}")
            else:
                await note.edit(content=f"✅ 「{title}」完成（YouTube投稿に失敗／サーバーに保存済み）")
        else:
            await channel.send(
                f"✅ 「{title}」が完成しました（YouTube連携が未設定のためリンクを出せません）")


def build_client(config: dict):
    import discord
    from discord import app_commands

    intents = discord.Intents.default()
    intents.message_content = True  # @メンション本文を読むため（Dev Portalでも有効化必須）
    client = discord.Client(intents=intents)
    tree = app_commands.CommandTree(client)
    bot = TomatoDiscord(config)

    @client.event
    async def on_ready():
        try:
            await tree.sync()  # スラッシュコマンドを登録
        except Exception as e:
            print("[discord] slash sync error:", e, file=sys.stderr)
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
        await bot.handle(message.channel, text)

    @tree.command(name="tomato", description="Tomato Clip に話しかけて動画を生成 / 相談する")
    @app_commands.describe(prompt="やりたいこと（例: アイアンマウスの切り抜きを1本つくって）")
    async def tomato(interaction: "discord.Interaction", prompt: str):
        # 生成は数分かかりうる → まず defer（3秒以内ackが必須）
        await interaction.response.defer(thinking=True)
        await interaction.followup.send(f"🍅 「{prompt}」を承りました。")
        await bot.handle(interaction.channel, prompt)

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
    eng = ChatEngine(config, cloudcfg.license_getter(), cb)
    msg = "こんにちは！あなたは何ができますか？簡潔に教えて"
    print(f"[selftest] send: {msg}")
    eng.send(msg)
    ok = got["text"] > 0 and got["done"]
    print(f"[selftest] {'OK' if ok else 'NG'} (on_text={got['text']}, done={got['done']})")
    return ok


def run(config: dict = None):
    """Botを起動（ブロッキング）。トークンが無ければ False を返す。"""
    cloudcfg.setup_media_env()
    config = config or cloudcfg.load_config()
    token = os.environ.get("DISCORD_BOT_TOKEN") or config.get("discord_bot_token", "")
    if not token:
        print("[discord] DISCORD_BOT_TOKEN が未設定です（Botは起動しません）。")
        return False
    client = build_client(config)
    client.run(token)
    return True


def main():
    cloudcfg.setup_media_env()
    config = cloudcfg.load_config()
    if "--selftest" in sys.argv:
        ok = _selftest(config)
        sys.exit(0 if ok else 1)
    run(config)


if __name__ == "__main__":
    main()
