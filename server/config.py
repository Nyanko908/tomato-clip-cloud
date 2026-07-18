# -*- coding: utf-8 -*-
"""server/config.py — 環境変数からクラウド設定を組む。

デスクトップ版は `~/.tomato_clip_config.json`（`web_app._DEFAULTS`）＋ローカルGUIで設定するが、
クラウド（BYO-deploy）では設定を**環境変数で注入**する。本モジュールは：

- `HOME` を書き換え可能なディレクトリへ向ける（Linuxのみ。license/credits/db/出力が全てそこに集まる）。
  ※ これは chat_engine/license/db を import する前に効かせる必要があるため、本モジュールの
     **import 時点**で実行する。エントリ(server/app.py)は最初に `import server.config` すること。
- env → config dict（`web_app._DEFAULTS` を土台にマージ）。
- `CREDENTIALS_JSON` / `YT_TOKEN_B64` / `YTDLP_COOKIES_B64` をファイル復元し、
  `YTDLP_COOKIEFILE` / `YTDLP_PROXY` を os.environ に渡す（pipeline.download_video が参照）。
- ライセンス getter（`TOMATO_UNGATED=1` で Pro相当スタブ＝クレジット消費なし。machine_id紐付け回避）。

必要な環境変数（詳細は server/README.md）:
  GEMINI_KEY, YOUTUBE_KEY, GEMINI_MODEL, OUTPUT_LANGUAGE, UI_LANG,
  DISCORD_BOT_TOKEN, CREDENTIALS_JSON, YT_TOKEN_B64,
  YTDLP_COOKIES_B64, YTDLP_PROXY, VOICEVOX_URL, TOMATO_HOME, TOMATO_UNGATED
"""
import os
import sys
import json
import base64
from pathlib import Path

# ── 1) HOME をクラウド用の書き込み可能ディレクトリへ（Linux/PaaS向け。import最速で実行） ──
# Path.home() は POSIX では $HOME を見る。ここを差し替えると license.json / credits.json /
# data.db / TomatoClip_Output が全て同じ書込み可能ツリーに集まる（chat_engine等のimport前提）。
if os.name == "posix":
    _home = os.environ.get("TOMATO_HOME", "/tmp/tomato_home")
    try:
        Path(_home).mkdir(parents=True, exist_ok=True)
        os.environ["HOME"] = _home
    except Exception:
        pass

# クラウド動作の目印。web_app.save_config はこれを見てファイル書き込みを止める
# （WindowsローカルでのクラウドテストはHOME差し替えが効かず、env由来のほぼ空config
#   がデスクトップの ~/.tomato_clip_config.json を上書きしてAPIキーを消すため）。
os.environ["TOMATO_CLOUD"] = "1"

# web_app の既定値を土台に使う（重複定義を避け、キーの追加に追従）。
# web_app は import 時点で pywebview を読まない（webview は main() 内で遅延import）ので安全。
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
try:
    from web_app import _DEFAULTS as _DESKTOP_DEFAULTS
except Exception:  # フォールバック（web_app が読めない環境向けの最小既定）
    _DESKTOP_DEFAULTS = {
        "gemini_key": "", "youtube_key": "", "credentials_path": "",
        "gemini_model": "gemini-flash-lite-latest",   # pipeline.DEFAULT_MODEL と同値
        "output_resolution": "1080p", "encode_preset": "fast", "freshness_hours": 72,
        "search_keywords": "", "my_channel_id": "", "auto_memory": True,
        "agreed_terms": False, "ui_lang": "ja", "seen_tutorial": False,
        "output_language": "ja", "monthly_goal": 10, "dev_mode": False,
    }

# クラウド用の設定・鍵ファイルを置く場所（HOME 差し替え後に評価）
_CLOUD_DIR = Path.home() / ".tomato_cloud"


def _b64_to_file(env_name: str, dest: Path) -> bool:
    """base64 環境変数をデコードして dest に書き出す。無ければ False。"""
    raw = os.environ.get(env_name, "")
    if not raw:
        return False
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(base64.b64decode(raw))
        return True
    except Exception as e:
        print(f"[config] {env_name} のデコードに失敗: {e}", file=sys.stderr)
        return False


def _env(*names, default=""):
    for n in names:
        v = os.environ.get(n)
        if v not in (None, ""):
            return v
    return default


def _restore_bundle(cfg: dict):
    """TOMATO_BUNDLE(+KEY) があれば復号して cfg を埋める（設定移送バンドル）。

    デスクトップの「☁ クラウド」タブが作った1つの暗号文字列から、APIキー/チャンネル/
    client_secrets.json/yt_token.pickle/Discordトークン等をまとめて復元する。
    個別 env（GEMINI_KEY 等）が来ていればそちらを優先させたいので、ここでは cfg に
    「バンドル由来の既定」を入れるだけ（後段の str_map 上書きが個別 env を優先させる）。
    """
    bundle = os.environ.get("TOMATO_BUNDLE", "")
    key = os.environ.get("TOMATO_BUNDLE_KEY", "")
    if not (bundle and key):
        return
    try:
        import cloud_bundle
        payload = cloud_bundle.open_bundle(bundle, key)
    except Exception as e:
        print(f"[config] TOMATO_BUNDLE の復号に失敗: {e}", file=sys.stderr)
        return
    # 通常キー
    for k, v in payload.items():
        if k in ("credentials_json", "yt_token_b64"):
            continue
        if v not in (None, "", []):
            cfg[k] = v
    # client_secrets.json / yt_token.pickle をファイル復元
    cred_json = payload.get("credentials_json")
    if cred_json:
        try:
            _CLOUD_DIR.mkdir(parents=True, exist_ok=True)
            cs = _CLOUD_DIR / "client_secrets.json"
            cs.write_text(cred_json, encoding="utf-8")
            cfg["credentials_path"] = str(cs)
            tok_b64 = payload.get("yt_token_b64")
            if tok_b64:
                (_CLOUD_DIR / "yt_token.pickle").write_bytes(base64.b64decode(tok_b64))
        except Exception as e:
            print(f"[config] バンドルの認証情報復元に失敗: {e}", file=sys.stderr)
    # voicevox_url は os.environ 経由で voicevox.py に効かせる
    if payload.get("voicevox_url"):
        os.environ.setdefault("VOICEVOX_URL", payload["voicevox_url"])
    print("[config] TOMATO_BUNDLE を復元しました（設定移送）", file=sys.stderr)


def _restore_from_account(cfg: dict):
    """TOMATO_ACCOUNT_TOKEN があれば、アカウントの Firestore から設定を復元する。

    ユーザーはサーバーの env にこのトークン1つを貼るだけ。デスクトップの
    「☁ クラウド」タブで設定をアカウントに保存しておけば、ここで引き継がれる。
    """
    token = os.environ.get("TOMATO_ACCOUNT_TOKEN", "")
    if not token:
        return
    try:
        import account
        acc = account.pull_account_with_token(token)
    except Exception as e:
        print(f"[config] アカウントからの設定取得に失敗: {e}", file=sys.stderr)
        return
    payload = acc.get("settings") or {}
    # プラン判定：worker(operator権威)が "pro" ならそれを優先。
    # それ以外は Firestore の plan にフォールバック（worker 未デプロイ/未紐付け時も動く）。
    uid = acc.get("uid", "")
    plan = "free"
    try:
        import account
        wp = account.worker_plan(uid) if uid else ""
        plan = "pro" if wp == "pro" else (acc.get("plan", "") or "free")
    except Exception:
        plan = acc.get("plan", "") or "free"
    os.environ["TOMATO_ACCOUNT_PLAN"] = plan
    os.environ["TOMATO_ACCOUNT_CHANNEL"] = acc.get("channel_title", "") or ""
    if not payload:
        print("[config] アカウントに保存された設定が見つかりません", file=sys.stderr)
        return
    for k, v in payload.items():
        if k in ("credentials_json", "yt_token_b64"):
            continue
        if v not in (None, "", []):
            cfg[k] = v
    cred_json = payload.get("credentials_json")
    if cred_json:
        try:
            _CLOUD_DIR.mkdir(parents=True, exist_ok=True)
            cs = _CLOUD_DIR / "client_secrets.json"
            cs.write_text(cred_json, encoding="utf-8")
            cfg["credentials_path"] = str(cs)
            tok_b64 = payload.get("yt_token_b64")
            if tok_b64:
                (_CLOUD_DIR / "yt_token.pickle").write_bytes(base64.b64decode(tok_b64))
        except Exception as e:
            print(f"[config] アカウントの認証情報復元に失敗: {e}", file=sys.stderr)
    print("[config] アカウントから設定を復元しました", file=sys.stderr)


def load_config() -> dict:
    """環境変数からクラウド用 config dict を組んで返す。"""
    cfg = dict(_DESKTOP_DEFAULTS)

    # ── TomatoAI アカウント経由の設定取得（トークン1つで全設定を引き継ぐ） ──
    _restore_from_account(cfg)

    # ── 設定移送バンドル（個別 env より先。個別 env があれば後段で上書き＝優先） ──
    _restore_bundle(cfg)

    # ── 文字列系 env → config キー ──
    str_map = {
        "gemini_key":       ("GEMINI_KEY", "GEMINI_API_KEY"),
        "youtube_key":      ("YOUTUBE_KEY", "YOUTUBE_API_KEY"),
        "gemini_model":     ("GEMINI_MODEL",),
        "output_language":  ("OUTPUT_LANGUAGE",),
        "ui_lang":          ("UI_LANG",),
        "output_resolution": ("OUTPUT_RESOLUTION",),
        "encode_preset":    ("ENCODE_PRESET",),
        "search_keywords":  ("SEARCH_KEYWORDS",),
        "my_channel_id":    ("MY_CHANNEL_ID",),
        "discord_bot_token": ("DISCORD_BOT_TOKEN",),
    }
    for key, envs in str_map.items():
        v = _env(*envs)
        if v:
            cfg[key] = v.strip()

    # ── 数値系 ──
    fh = _env("FRESHNESS_HOURS")
    if fh:
        try:
            cfg["freshness_hours"] = int(fh)
        except ValueError:
            pass

    # ── 認証情報の復元 ──
    # client_secrets.json（インライン JSON か base64 のどちらでも受ける）
    cred_json = os.environ.get("CREDENTIALS_JSON", "")
    if cred_json:
        try:
            # base64 で来ることも許容
            if not cred_json.lstrip().startswith("{"):
                cred_json = base64.b64decode(cred_json).decode("utf-8")
            _CLOUD_DIR.mkdir(parents=True, exist_ok=True)
            cs_path = _CLOUD_DIR / "client_secrets.json"
            cs_path.write_text(cred_json, encoding="utf-8")
            cfg["credentials_path"] = str(cs_path)
        except Exception as e:
            print(f"[config] CREDENTIALS_JSON の復元に失敗: {e}", file=sys.stderr)

    # yt_token.pickle（デスクトップで発行済み → 無人投稿用）。client_secrets と同じ親に置く。
    if cfg.get("credentials_path"):
        _b64_to_file("YT_TOKEN_B64", Path(cfg["credentials_path"]).parent / "yt_token.pickle")

    # ── yt-dlp cookies / proxy（データセンターIP対策）を os.environ 経由で pipeline へ ──
    if _b64_to_file("YTDLP_COOKIES_B64", _CLOUD_DIR / "cookies.txt"):
        os.environ["YTDLP_COOKIEFILE"] = str(_CLOUD_DIR / "cookies.txt")
    if os.environ.get("YTDLP_PROXY"):
        # そのまま pipeline 側が os.environ["YTDLP_PROXY"] を読む
        pass

    # ── VOICEVOX_URL（任意）。voicevox.py は定数持ちだが env があれば best-effort で差し替え ──
    vv = os.environ.get("VOICEVOX_URL")
    if vv:
        try:
            import voicevox
            voicevox.VOICEVOX_URL = vv.rstrip("/")
        except Exception:
            pass

    # ── クラウドではオンボーディング不要（規約はデプロイ者が同意済みとみなす） ──
    cfg["agreed_terms"] = True
    cfg["seen_tutorial"] = True

    return cfg


class CloudProLicense:
    """BYO-deploy 用の軽量ライセンススタブ。

    自前サーバー＝Proユーザー本人の環境なので Pro相当として扱い、クレジット消費を無効化する
    （chat_engine._run_generation は is_demo=False ならクレジットに触れない）。
    machine_id 紐付け（サーバーのMACに固定される問題）を回避するための割り切り。
    """
    is_demo = False
    is_pro = True
    tier = "pro"
    uid = os.environ.get("TOMATO_UID", "cloud")

    def activate(self, key):
        return (False, "クラウド版ではライセンス認証は不要です（サーバー所有者＝Pro）")

    def deactivate(self):
        return True


def license_getter():
    """ChatEngine に渡す get_license コールバックを返す。

    TOMATO_UNGATED=1（既定）: Proスタブ（クレジット無制限）。
    TOMATO_UNGATED=0        : 実ライセンス（license.get_license()。デモならクレジット制限あり）。
    """
    ungated = os.environ.get("TOMATO_UNGATED", "1") != "0"
    if ungated:
        _stub = CloudProLicense()
        return lambda: _stub
    try:
        from license import get_license
        lic = get_license()
        return lambda: lic
    except Exception:
        return lambda: None


def is_pro_allowed() -> bool:
    """クラウド起動を許可してよいか。

    アカウントトークンで動く場合は **Pro プランのみ許可**（買い切り死守）。
    手動 env / 自己ホスト（トークン未使用）は従来通り許可。
    ※ load_config() 実行後に呼ぶこと（TOMATO_ACCOUNT_PLAN が設定される）。
    """
    if not os.environ.get("TOMATO_ACCOUNT_TOKEN"):
        return True
    return os.environ.get("TOMATO_ACCOUNT_PLAN", "") == "pro"


def upsell_html() -> str:
    """非Pro時に表示する勧誘ページ。"""
    return """<!doctype html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Tomato Clip Cloud</title>
<style>body{font-family:system-ui,"Segoe UI","Hiragino Kaku Gothic ProN",sans-serif;background:#fff;color:#1d1d20;
display:flex;min-height:100vh;margin:0;align-items:center;justify-content:center;text-align:center;padding:24px}
.box{max-width:440px}h1{font-size:24px;margin:14px 0 8px}p{color:#6b6b76;line-height:1.8}
.badge{display:inline-block;padding:4px 12px;border-radius:999px;background:#fdeeeb;color:#e5503c;font-weight:700;font-size:13px;margin-bottom:12px}
.cta{display:inline-block;margin-top:18px;padding:12px 26px;border-radius:12px;background:#e5503c;color:#fff;text-decoration:none;font-weight:700}
.cta:hover{background:#cf432f}</style></head><body><div class="box">
<div class="badge">Pro 限定機能</div>
<h1>クラウドは Pro プラン限定です</h1>
<p>Tomato Clip Cloud（24時間稼働・Discordボット）は、買い切りの Pro をご購入いただいた方の特典です。
アプリでライセンスを認証し、設定を保存し直すと、このサーバーが使えるようになります。</p>
<a class="cta" href="https://tomatoshorts.booth.pm/" target="_blank" rel="noopener">Pro を入手する →</a>
</div></body></html>"""


def setup_media_env():
    """生成（moviepy編集）用の ffmpeg パス設定 & PIL 互換パッチ（web_app._setup_media_env 相当）。"""
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


def output_root() -> Path:
    """生成物の出力ルート（pipeline が書き込む先。/media 配信に使う）。

    chat_engine._run_generation が work_dir=Path.home()/"TomatoClip_Output" を注入し、
    pipeline はその下の "tomato_clip" に output_*.mp4 を書く。
    """
    return Path.home() / "TomatoClip_Output" / "tomato_clip"
