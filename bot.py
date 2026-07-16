"""
bot.py - Tomato Clip ライセンス発行ボット

環境変数:
  DISCORD_TOKEN   : ボットトークン
  GUILD_ID        : サーバーID（数字）
  PRIVATE_KEY_B64 : private_key.pem をBase64エンコードした文字列
  ADMIN_ROLE_ID   : 管理者ロールID（任意）
"""

import discord
from discord import app_commands
import os, json, time, base64, secrets
from pathlib import Path

# ── 設定 ──────────────────────────────────────────────
DISCORD_TOKEN   = os.environ["DISCORD_TOKEN"]
GUILD_ID        = int(os.environ["GUILD_ID"])
PRIVATE_KEY_B64 = os.environ["PRIVATE_KEY_B64"]   # PEMをbase64にしたもの
ADMIN_ROLE_ID   = int(os.environ.get("ADMIN_ROLE_ID", "0"))

ISSUED_FILE = Path("issued_keys.json")   # 発行済み記録（Railway の volume か永続ディスクに置く）
KEY_DAYS    = 365


# ── キー生成 ───────────────────────────────────────────
def _generate_key(discord_id: str) -> str:
    from cryptography.hazmat.primitives.serialization import load_pem_private_key
    pem = base64.b64decode(PRIVATE_KEY_B64)
    priv = load_pem_private_key(pem, password=None)
    payload = {
        "uid":  discord_id,
        "tier": "pro",
        "exp":  int(time.time()) + KEY_DAYS * 86400,
        "kid":  secrets.token_hex(4),
    }
    payload_b64 = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode()
    ).decode().rstrip("=")
    sig_b64 = base64.urlsafe_b64encode(
        priv.sign(payload_b64.encode())
    ).decode().rstrip("=")
    return f"{payload_b64}.{sig_b64}"


# ── 発行記録（ローカルJSON） ────────────────────────────
def _load_issued() -> dict:
    if ISSUED_FILE.exists():
        try:
            return json.loads(ISSUED_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}

def _save_issued(data: dict):
    ISSUED_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ── Bot ───────────────────────────────────────────────
intents = discord.Intents.default()
client  = discord.Client(intents=intents)
tree    = app_commands.CommandTree(client)
GUILD   = discord.Object(id=GUILD_ID)


@client.event
async def on_ready():
    await tree.sync(guild=GUILD)
    print(f"✅ Bot 起動: {client.user}  Guild={GUILD_ID}")


# ── /activate ─────────────────────────────────────────
@tree.command(
    name="activate",
    description="Tomato Clip のライセンスキーをDMで受け取ります",
    guild=GUILD,
)
async def cmd_activate(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    uid = str(interaction.user.id)

    issued = _load_issued()

    # 重複チェック
    if uid in issued:
        exp = issued[uid].get("issued_at", "")
        await interaction.followup.send(
            f"⚠️ すでにキーが発行されています（{exp}）\n"
            "DMを確認してください。紛失した場合は管理者にご連絡ください。",
            ephemeral=True,
        )
        return

    # キー生成
    try:
        key = _generate_key(uid)
    except Exception as e:
        await interaction.followup.send(f"❌ キー生成に失敗しました: {e}", ephemeral=True)
        return

    # DM送信
    try:
        dm = await interaction.user.create_dm()
        await dm.send(
            "🎬 **Tomato Clip ライセンスキー**\n\n"
            f"```\n{key}\n```\n\n"
            "**使い方**\n"
            "1. アプリを起動\n"
            "2. 設定 → 「APIキー & 設定」タブを開く\n"
            "3. キーを貼り付けて「認証」を押す\n\n"
            "有効期間: 365日\n"
            "ご不明な点はサーバーでお気軽にどうぞ！"
        )
    except discord.Forbidden:
        await interaction.followup.send(
            "❌ DMを送れませんでした。\n"
            "Discord の設定でサーバーメンバーからのDMを許可してから再試行してください。",
            ephemeral=True,
        )
        return

    # 記録保存
    issued[uid] = {
        "username":  str(interaction.user),
        "key":       key,
        "issued_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    _save_issued(issued)

    await interaction.followup.send("✅ DMにキーを送りました！", ephemeral=True)


# ── /revoke（管理者専用） ──────────────────────────────
@tree.command(
    name="revoke",
    description="ユーザーのライセンスを無効化します（管理者専用）",
    guild=GUILD,
)
@app_commands.default_permissions(administrator=True)
async def cmd_revoke(interaction: discord.Interaction, user: discord.Member):
    await interaction.response.defer(ephemeral=True)
    uid = str(user.id)
    issued = _load_issued()

    if uid not in issued:
        await interaction.followup.send(f"⚠️ {user} のキー記録がありません", ephemeral=True)
        return

    key = issued[uid].get("key", "")
    if not key:
        await interaction.followup.send("❌ キーが記録されていません", ephemeral=True)
        return

    # Cloudflare Worker で revoke
    try:
        import urllib.request
        worker_url  = os.environ.get("WORKER_URL", "")
        admin_token = os.environ.get("WORKER_ADMIN_TOKEN", "")
        body = json.dumps({"key": key, "admin_token": admin_token}).encode()
        req  = urllib.request.Request(
            f"{worker_url}/revoke", data=body,
            headers={"Content-Type": "application/json", "User-Agent": "TomatoClipBot/1.0"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            result = json.loads(resp.read())
    except Exception as e:
        await interaction.followup.send(f"❌ Worker revoke 失敗: {e}", ephemeral=True)
        return

    if result.get("status") == "ok":
        issued[uid]["revoked"] = True
        issued[uid]["revoked_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        _save_issued(issued)
        await interaction.followup.send(f"✅ {user} のライセンスを無効化しました", ephemeral=True)
    else:
        await interaction.followup.send(f"❌ {result}", ephemeral=True)


# ── /list（管理者専用） ────────────────────────────────
@tree.command(
    name="list",
    description="発行済みキー一覧（管理者専用）",
    guild=GUILD,
)
@app_commands.default_permissions(administrator=True)
async def cmd_list(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    issued = _load_issued()
    if not issued:
        await interaction.followup.send("まだキーは発行されていません", ephemeral=True)
        return
    lines = ["**発行済みキー一覧**\n"]
    for uid, info in list(issued.items())[-20:]:
        revoked = "🚫" if info.get("revoked") else "✅"
        lines.append(f"{revoked} `{info.get('username','?')}` — {info.get('issued_at','')}")
    await interaction.followup.send("\n".join(lines), ephemeral=True)


client.run(DISCORD_TOKEN)
