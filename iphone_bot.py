"""
iphone_bot.py
iPhone の Discord だけで全自動運用できる Bot
Railway にデプロイして 24 時間稼働

コマンド一覧:
  !make [URL or ジャンル]  → 動画1本作って YouTube UP + Discord 通知
  !auto                   → スケジュール自動実行 ON/OFF
  !template list          → テンプレ一覧
  !template new [説明]    → AI がテンプレ自動生成
  !template edit [ID]     → AI がテンプレ改善提案
  !status                 → 現在の進捗
  !queue                  → 処理待ちキュー
  !analytics              → 今週の成績
  !report                 → 週次レポート生成 & note 投稿
  !whitelist add [URL]    → ホワイトリスト追加
  !help                   → コマンド一覧
"""

import os, json, asyncio, threading, time, re
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Optional

import discord
from discord.ext import commands, tasks

# ── 環境変数から設定を読む（Railway の環境変数に設定する）
DISCORD_TOKEN    = os.environ.get("DISCORD_TOKEN", "")
GEMINI_KEY       = os.environ.get("GEMINI_KEY", "")
YOUTUBE_KEY      = os.environ.get("YOUTUBE_KEY", "")
PEXELS_KEY       = os.environ.get("PEXELS_KEY", "")
NOTE_EMAIL       = os.environ.get("NOTE_EMAIL", "")
NOTE_PASSWORD    = os.environ.get("NOTE_PASSWORD", "")
ADMIN_USER_IDS   = os.environ.get("ADMIN_USER_IDS", "").split(",")  # DiscordユーザーID
CHANNEL_ID       = int(os.environ.get("DISCORD_CHANNEL_ID", "0"))   # 通知先チャンネル
WORK_DIR         = Path(os.environ.get("WORK_DIR", "/tmp/tomato_clip"))
JST              = timezone(timedelta(hours=9))
SLEEP            = 20

# ── sys.path に tomato_clip を追加
import sys
sys.path.insert(0, str(Path(__file__).parent))

import db
from template_engine import (
    PLAN_TEMPLATES, ai_select_template, get_plan_template,
    sync_plan_templates_to_db
)

# ════════════════════════════════════════════════════════
#  Bot 初期化
# ════════════════════════════════════════════════════════
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

# グローバル状態
_processing   = False
_current_task = ""
_queue        = []   # [(user, task_desc, config_override)]
_stop_event   = threading.Event()


def is_admin(ctx):
    return str(ctx.author.id) in ADMIN_USER_IDS or not ADMIN_USER_IDS[0]

def _log_to_discord(msg: str):
    """pipeline のログを Discord に非同期送信"""
    if CHANNEL_ID and bot.is_ready():
        ch = bot.get_channel(CHANNEL_ID)
        if ch:
            # アイコン付きで見やすく
            asyncio.run_coroutine_threadsafe(
                ch.send(f"`{msg}`"), bot.loop
            )

def _build_config(override: dict = None) -> dict:
    cfg = {
        "gemini_key":        GEMINI_KEY,
        "youtube_key":       YOUTUBE_KEY,
        "pexels_key":        PEXELS_KEY,
        "priority_channels": [dict(w) for w in db.get_whitelist()],
        "regions":           ["US", "GB"],
        "categories":        ["24", "23", "17"],
        "skull_path":        str(Path(__file__).parent / "skull.png"),
        "phonk_path":        str(Path(__file__).parent / "phonk.mp3"),
        "work_dir":          str(WORK_DIR),
        "schedule_hour":     18,   # 18時に予約投稿
        "max_videos":        1,
        "active_template":   "auto",
    }
    if override:
        cfg.update(override)
    return cfg


# ════════════════════════════════════════════════════════
#  起動
# ════════════════════════════════════════════════════════
@bot.event
async def on_ready():
    db.init_db()
    sync_plan_templates_to_db()
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    print(f"✅ Bot 起動: {bot.user}")
    if CHANNEL_ID:
        ch = bot.get_channel(CHANNEL_ID)
        if ch:
            await ch.send(
                "🏭 **TOMATO SHORTS Bot** 起動しました！\n"
                "`!help` でコマンド一覧を確認できます。"
            )
    weekly_report_task.start()
    auto_pipeline_task.start()


# ════════════════════════════════════════════════════════
#  !help
# ════════════════════════════════════════════════════════
@bot.command(name="help")
async def help_cmd(ctx):
    embed = discord.Embed(
        title="🏭 TOMATO SHORTS Bot コマンド",
        color=0x6c63ff
    )
    embed.add_field(name="🎬 動画作成", value=(
        "`!make` — 自動でバズり動画を1本作成\n"
        "`!make [YouTube URL]` — 指定動画を日本語化\n"
        "`!make [ジャンル]` — ジャンル指定（例: !make スポーツ）"
    ), inline=False)
    embed.add_field(name="🎨 テンプレート", value=(
        "`!template list` — 一覧表示\n"
        "`!template new [説明]` — AIが自動生成\n"
        "`!template edit [ID]` — AIが改善提案\n"
        "`!template use [ID]` — 次回作成に使用"
    ), inline=False)
    embed.add_field(name="📅 自動化", value=(
        "`!auto on/off` — スケジュール自動実行\n"
        "`!schedule` — 次回実行時刻\n"
        "`!queue` — 処理待ちキュー"
    ), inline=False)
    embed.add_field(name="📊 分析", value=(
        "`!analytics` — 今週の成績\n"
        "`!report` — 週次レポート生成 & note投稿\n"
        "`!whitelist add [チャンネルID] [名前]` — 優先登録"
    ), inline=False)
    embed.add_field(name="🔧 その他", value=(
        "`!status` — 現在の進捗\n"
        "`!stop` — 処理を停止"
    ), inline=False)
    embed.set_footer(text="iPhoneから全部できます 🍎")
    await ctx.send(embed=embed)


# ════════════════════════════════════════════════════════
#  !make — メインコマンド
# ════════════════════════════════════════════════════════
@bot.command(name="make")
async def make_cmd(ctx, *, arg: str = ""):
    global _processing, _current_task

    if _processing:
        await ctx.send(f"⏳ 現在処理中です: `{_current_task}`\n`!queue` で確認できます。")
        return

    # YouTube URL かジャンル指定か判定
    yt_url = None
    genre  = None
    override = {}

    url_match = re.search(r"(https?://[^\s]+youtube[^\s]+|https?://youtu\.be/[^\s]+)", arg)
    if url_match:
        yt_url = url_match.group(1)
        await ctx.send(f"🎬 指定動画を処理します: {yt_url}")
        override["target_url"] = yt_url
    elif arg.strip():
        genre = arg.strip()
        await ctx.send(f"🔍 ジャンル「{genre}」でバズり動画を探します...")
        override["genre_filter"] = genre
    else:
        await ctx.send("🔍 自動でバズり動画を探して作ります...")

    config = _build_config(override)

    def _run():
        global _processing, _current_task
        _processing   = True
        _current_task = f"動画作成中 {'(' + genre + ')' if genre else ''}"
        result        = {"url": None, "title": None, "error": None}

        def _on_ready(path, analysis):
            result["title"] = analysis.get("title", "")
            result["path"]  = path

        try:
            from pipeline import run_pipeline
            run_pipeline(
                config         = config,
                log            = _log_to_discord,
                on_video_ready = _on_ready,
                stop_event     = _stop_event
            )
        except Exception as e:
            result["error"] = str(e)
        finally:
            _processing   = False
            _current_task = ""

        # 完了通知
        async def _notify():
            if result.get("error"):
                await ctx.send(f"❌ エラーが発生しました: {result['error']}")
            else:
                yt_url_done = result.get("url", "")
                title       = result.get("title", "完成")
                embed = discord.Embed(
                    title  = f"✅ 完成！「{title}」",
                    color  = 0x4cffb0,
                    description = yt_url_done or "YouTube URL は処理ログを確認してください"
                )
                embed.set_footer(text=f"{datetime.now(JST).strftime('%H:%M JST')}")
                await ctx.send(embed=embed)

        asyncio.run_coroutine_threadsafe(_notify(), bot.loop)

    threading.Thread(target=_run, daemon=True).start()


# ════════════════════════════════════════════════════════
#  !template
# ════════════════════════════════════════════════════════
@bot.command(name="template")
async def template_cmd(ctx, sub: str = "list", *, arg: str = ""):

    # ── list
    if sub == "list":
        templates = db.get_templates()
        embed = discord.Embed(title="🎨 テンプレート一覧", color=0x6c63ff)
        for t in templates:
            cfg = json.loads(t["config_json"]) if isinstance(t["config_json"], str) else t["config_json"]
            features = []
            if cfg.get("skull_enabled"):      features.append("💀ドクロ")
            if cfg.get("phonk_enabled"):      features.append("🎵Phonk")
            if cfg.get("ranking_overlay"):    features.append("🏆ランキング")
            if cfg.get("free_footage"):       features.append("🎥フリー素材")
            if cfg.get("narration_enabled"):  features.append("🗣️ナレーション")
            embed.add_field(
                name  = f"`{t['id']}` {t['name']}",
                value = " / ".join(features) or "シンプル",
                inline = False
            )
        embed.set_footer(text="!template use [ID] で使用 / !template new [説明] で作成")
        await ctx.send(embed=embed)

    # ── new — AI が自動生成
    elif sub == "new":
        if not arg:
            await ctx.send("❌ 使い方: `!template new [どんな動画向けか説明]`\n例: `!template new 料理動画向け・落ち着いた・フリー素材多め`")
            return
        await ctx.send(f"🤖 AI がテンプレートを生成中... (`{arg}`)")

        def _gen():
            tmpl_id, name, config = _ai_generate_template(arg)
            if tmpl_id:
                import base64
                from io import BytesIO
                from PIL import Image, ImageDraw
                img  = Image.new("RGB", (270,480), "#0a0a12")
                draw = ImageDraw.Draw(img)
                tc   = config.get("title_color","#fff")
                try: r,g,b = int(tc[1:3],16),int(tc[3:5],16),int(tc[5:7],16)
                except: r,g,b = 200,200,200
                draw.rectangle([20,180,250,300], fill=(r//3,g//3,b//3))
                buf = BytesIO(); img.save(buf,format="PNG")
                preview = base64.b64encode(buf.getvalue()).decode()
                db.save_template(tmpl_id, name, config, preview)

                async def _notify():
                    features = _config_to_features(config)
                    embed = discord.Embed(
                        title       = f"✅ テンプレート作成: {name}",
                        description = f"ID: `{tmpl_id}`\n演出: {features}",
                        color       = 0x6c63ff
                    )
                    embed.set_footer(text=f"!template use {tmpl_id} で使用")
                    await ctx.send(embed=embed)
                asyncio.run_coroutine_threadsafe(_notify(), bot.loop)
            else:
                asyncio.run_coroutine_threadsafe(
                    ctx.send("❌ テンプレート生成失敗"), bot.loop)

        threading.Thread(target=_gen, daemon=True).start()

    # ── edit — AI が改善提案
    elif sub == "edit":
        tid = arg.strip()
        if not tid:
            await ctx.send("❌ 使い方: `!template edit [ID]`")
            return
        await ctx.send(f"🤖 AI がテンプレート `{tid}` を分析・改善中...")

        def _edit():
            new_id, name, config = _ai_improve_template(tid)
            if new_id:
                import base64; from io import BytesIO; from PIL import Image, ImageDraw
                img=Image.new("RGB",(270,480),"#0a0a12"); buf=BytesIO(); img.save(buf,format="PNG")
                db.save_template(new_id, name, config, base64.b64encode(buf.getvalue()).decode())
                async def _n():
                    await ctx.send(f"✅ 改善版テンプレート作成: `{new_id}` — {name}\n`!template use {new_id}` で使用")
                asyncio.run_coroutine_threadsafe(_n(), bot.loop)

        threading.Thread(target=_edit, daemon=True).start()

    # ── use
    elif sub == "use":
        tid = arg.strip()
        if tid not in [t["id"] for t in db.get_templates()]:
            await ctx.send(f"❌ ID `{tid}` が見つかりません。`!template list` で確認してください")
            return
        # 設定ファイルに保存
        cfg_path = Path.home() / ".tomato_clip" / "config.json"
        cfg = {}
        if cfg_path.exists():
            cfg = json.loads(cfg_path.read_text())
        cfg["active_template"] = tid
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        cfg_path.write_text(json.dumps(cfg, ensure_ascii=False))
        await ctx.send(f"✅ 次回から `{tid}` テンプレートを使用します")

    else:
        await ctx.send("❌ `!template list / new / edit / use` のいずれかを使用してください")


# ════════════════════════════════════════════════════════
#  !auto — スケジュール ON/OFF
# ════════════════════════════════════════════════════════
@bot.command(name="auto")
@commands.check(is_admin)
async def auto_cmd(ctx, switch: str = ""):
    sched = db.get_schedule()
    if switch.lower() == "on":
        db.update_schedule(enabled=1)
        await ctx.send("📅 自動実行 **ON** にしました（4時間おき）\n次回実行まで待機中...")
    elif switch.lower() == "off":
        db.update_schedule(enabled=0)
        await ctx.send("📅 自動実行 **OFF** にしました")
    else:
        status = "🟢 ON" if sched.get("enabled") else "🔴 OFF"
        await ctx.send(f"📅 自動実行: {status}\n`!auto on` / `!auto off` で切り替え")


# ════════════════════════════════════════════════════════
#  !status
# ════════════════════════════════════════════════════════
@bot.command(name="status")
async def status_cmd(ctx):
    sched   = db.get_schedule()
    videos  = db.get_videos(limit=3)
    wl      = db.get_whitelist()

    embed = discord.Embed(title="🏭 TOMATO SHORTS ステータス", color=0x4cffb0)
    embed.add_field(
        name  = "現在の処理",
        value = f"`{_current_task}`" if _processing else "✅ 待機中",
        inline = False
    )
    embed.add_field(
        name  = "自動実行",
        value = f"{'🟢 ON' if sched.get('enabled') else '🔴 OFF'} / {sched.get('interval_hrs',4)}時間おき",
        inline = True
    )
    embed.add_field(
        name  = "ホワイトリスト",
        value = f"{len(wl)} チャンネル",
        inline = True
    )
    if videos:
        recent = "\n".join(f"• {v['title'][:25]}" for v in videos[:3])
        embed.add_field(name="直近の動画", value=recent, inline=False)
    await ctx.send(embed=embed)


# ════════════════════════════════════════════════════════
#  !analytics
# ════════════════════════════════════════════════════════
@bot.command(name="analytics")
async def analytics_cmd(ctx):
    from analytics import get_channel_ranking
    summary  = db.get_all_analytics_summary()
    ranking  = get_channel_ranking()[:3]
    total_v  = sum(v.get("peak_views") or 0 for v in summary)

    embed = discord.Embed(title="📊 アナリティクス", color=0xffcc44)
    embed.add_field(name="累計総再生数", value=f"{total_v:,} 回", inline=True)
    embed.add_field(name="総投稿数",     value=f"{len(summary)} 本",  inline=True)

    if summary:
        top = sorted(summary, key=lambda x: x.get("peak_views") or 0, reverse=True)[:3]
        top_str = "\n".join(
            f"{i+1}. {v['title'][:20]} — {(v.get('peak_views') or 0):,}再生"
            for i, v in enumerate(top)
        )
        embed.add_field(name="🏆 再生数TOP3", value=top_str, inline=False)

    if ranking:
        rank_str = "\n".join(f"{r['channel'][:15]} — 平均{r['avg_views']:,}再生" for r in ranking)
        embed.add_field(name="チャンネル別", value=rank_str, inline=False)

    await ctx.send(embed=embed)


# ════════════════════════════════════════════════════════
#  !report — 週次レポート & note 投稿
# ════════════════════════════════════════════════════════
@bot.command(name="report")
@commands.check(is_admin)
async def report_cmd(ctx):
    await ctx.send("📝 週次レポート生成中... (1〜2分かかります)")

    def _run():
        from note_poster import auto_post_weekly_report
        url = auto_post_weekly_report(
            gemini_key    = GEMINI_KEY,
            note_email    = NOTE_EMAIL,
            note_password = NOTE_PASSWORD,
            log           = _log_to_discord,
            publish       = bool(NOTE_EMAIL and NOTE_PASSWORD)
        )
        async def _notify():
            if url:
                await ctx.send(f"✅ note に投稿しました！\n{url}")
            else:
                await ctx.send("⚠️ note 投稿スキップ（設定未完）\nレポートファイルは生成済みです")
        asyncio.run_coroutine_threadsafe(_notify(), bot.loop)

    threading.Thread(target=_run, daemon=True).start()


# ════════════════════════════════════════════════════════
#  !whitelist
# ════════════════════════════════════════════════════════
@bot.command(name="whitelist")
@commands.check(is_admin)
async def whitelist_cmd(ctx, sub: str = "list", channel_id: str = "", *, name: str = ""):
    if sub == "add":
        if not channel_id:
            await ctx.send("❌ 使い方: `!whitelist add [チャンネルID] [名前]`")
            return
        db.add_whitelist(channel_id, name or channel_id, score_bonus=20)
        await ctx.send(f"⭐ ホワイトリスト追加: **{name or channel_id}** (`{channel_id}`)")

    elif sub == "list":
        wl = db.get_whitelist()
        if not wl:
            await ctx.send("⭐ ホワイトリストは空です")
            return
        lines = "\n".join(f"• `{w['channel_id']}` {w['channel_name']} (+{w['score_bonus']}点)" for w in wl[:10])
        await ctx.send(f"⭐ **ホワイトリスト**\n{lines}")

    elif sub == "remove":
        db.remove_whitelist(channel_id)
        await ctx.send(f"✅ `{channel_id}` を削除しました")


# ════════════════════════════════════════════════════════
#  !stop
# ════════════════════════════════════════════════════════
@bot.command(name="stop")
@commands.check(is_admin)
async def stop_cmd(ctx):
    _stop_event.set()
    await ctx.send("⏹ 停止リクエストを送信しました")
    await asyncio.sleep(2)
    _stop_event.clear()


# ════════════════════════════════════════════════════════
#  定期タスク: 自動パイプライン（4時間おき）
# ════════════════════════════════════════════════════════
@tasks.loop(hours=4)
async def auto_pipeline_task():
    global _processing
    sched = db.get_schedule()
    if not sched.get("enabled") or _processing:
        return

    ch = bot.get_channel(CHANNEL_ID)
    if ch:
        await ch.send("📅 自動実行開始します...")

    def _run():
        global _processing, _current_task
        _processing   = True
        _current_task = "自動スケジュール実行"
        try:
            from pipeline import run_pipeline
            run_pipeline(
                config     = _build_config(),
                log        = _log_to_discord,
                stop_event = _stop_event
            )
            db.update_schedule(
                last_run  = datetime.now(JST).isoformat(),
                run_count = sched.get("run_count", 0) + 1
            )
        except Exception as e:
            _log_to_discord(f"❌ 自動実行エラー: {e}")
        finally:
            _processing   = False
            _current_task = ""

    threading.Thread(target=_run, daemon=True).start()


# ════════════════════════════════════════════════════════
#  定期タスク: 週次レポート（毎週月曜）
# ════════════════════════════════════════════════════════
@tasks.loop(hours=24)
async def weekly_report_task():
    now = datetime.now(JST)
    if now.weekday() != 0:   # 月曜のみ
        return

    from weekly_report import should_run_weekly
    if not should_run_weekly():
        return

    ch = bot.get_channel(CHANNEL_ID)
    if ch:
        await ch.send("📝 週次レポートを自動生成・note投稿します...")

    def _run():
        from note_poster import auto_post_weekly_report
        auto_post_weekly_report(GEMINI_KEY, NOTE_EMAIL, NOTE_PASSWORD, _log_to_discord)

    threading.Thread(target=_run, daemon=True).start()


# ════════════════════════════════════════════════════════
#  AI テンプレート自動生成（内部）
# ════════════════════════════════════════════════════════
def _ai_generate_template(description: str):
    """Gemini に説明を渡してテンプレート設定を自動生成"""
    try:
        import google.generativeai as genai, uuid
        genai.configure(api_key=GEMINI_KEY)
        model = genai.GenerativeModel("gemini-2.0-flash")

        time.sleep(SLEEP)
        prompt = f"""
以下の説明に合う YouTube Shorts 編集テンプレートの設定を JSON で生成してください。
コードブロックや説明不要、JSONのみ返答。

説明: {description}

返答形式:
{{
  "name": "テンプレート名（絵文字+16文字以内）",
  "config": {{
    "title_color": "#HEX",
    "subtitle_color": "#HEX",
    "caption_color": "#HEX",
    "caption_bg": "#HEX",
    "caption_bg_alpha": 0-255,
    "font_size": 40-90,
    "title_font_size": 50-120,
    "skull_enabled": true/false,
    "skull_size_ratio": 0.2-0.8,
    "skull_duration": 1.0-5.0,
    "phonk_enabled": true/false,
    "phonk_volume": 0.0-1.0,
    "phonk_chorus_vol": 0.0-1.0,
    "narration_enabled": true/false,
    "mono_on_skull": true/false,
    "free_footage": true/false,
    "free_footage_mode": "background"/"transition"/"ai_decide",
    "ranking_overlay": true/false
  }}
}}
"""
        resp   = model.generate_content(prompt)
        raw    = resp.text.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        data   = json.loads(raw)
        tid    = str(uuid.uuid4())[:8]
        return tid, data["name"], data["config"]
    except Exception as e:
        print(f"テンプレ生成失敗: {e}")
        return None, None, None


def _ai_improve_template(tid: str):
    """既存テンプレートを AI が分析・改善"""
    try:
        import google.generativeai as genai, uuid
        genai.configure(api_key=GEMINI_KEY)
        model = genai.GenerativeModel("gemini-2.0-flash")

        current = get_plan_template(tid)
        summary = db.get_all_analytics_summary()

        # このテンプレートを使った動画の成績
        used = [v for v in summary if v.get("template_id") == tid]
        avg_views = sum(v.get("peak_views") or 0 for v in used) // max(len(used), 1)

        time.sleep(SLEEP)
        prompt = f"""
YouTube Shorts 編集テンプレートを改善してください。
このテンプレートを使った動画の平均再生数は {avg_views:,} 回でした。

現在の設定:
{json.dumps(current, ensure_ascii=False)}

改善後のテンプレートを JSON で返してください（同じ形式）。
name は改善版を示す名前にすること。
コードブロック不要、JSONのみ。
"""
        resp   = model.generate_content(prompt)
        raw    = resp.text.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        data   = json.loads(raw)
        new_id = str(uuid.uuid4())[:8]
        name   = data.get("name", f"改善版_{tid}")
        cfg    = data.get("config", current)
        return new_id, name, cfg
    except Exception as e:
        print(f"テンプレ改善失敗: {e}")
        return None, None, None


def _config_to_features(config: dict) -> str:
    features = []
    if config.get("skull_enabled"):    features.append("💀ドクロ")
    if config.get("phonk_enabled"):    features.append("🎵Phonk")
    if config.get("ranking_overlay"):  features.append("🏆ランキング")
    if config.get("free_footage"):     features.append("🎥フリー素材")
    if config.get("narration_enabled"):features.append("🗣️ナレーション")
    if config.get("mono_on_skull"):    features.append("⬛モノクロ")
    return " / ".join(features) or "シンプル"


# ════════════════════════════════════════════════════════
#  エラーハンドリング
# ════════════════════════════════════════════════════════
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CheckFailure):
        await ctx.send("❌ このコマンドは管理者専用です")
    elif isinstance(error, commands.CommandNotFound):
        await ctx.send(f"❓ コマンドが見つかりません。`!help` で確認してください")
    else:
        await ctx.send(f"❌ エラー: {error}")


# ════════════════════════════════════════════════════════
#  起動
# ════════════════════════════════════════════════════════
if __name__ == "__main__":
    if not DISCORD_TOKEN:
        print("❌ DISCORD_TOKEN 環境変数が設定されていません")
        sys.exit(1)
    bot.run(DISCORD_TOKEN)
