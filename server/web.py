# -*- coding: utf-8 -*-
"""server/web.py — クラウドWeb版（FastAPI）。

デスクトップの web_app.Api を継承し、pywebview 依存部分だけクラウド向けに差し替える：
- 設定/ライセンスを server.config から注入（env 由来）。
- on_video: サーバー上の生成物パスを /media/... の配信URLへ書き換え（ブラウザで再生可能に）。
- open_file / post_video: os.startfile を使わず、リンク提示 / YouTube無人投稿に置換。

フロントは既存 webui/ を無改変で再利用し、<head> に bridge.js（fetchシム）を注入する。
"""
import json
import base64
import hashlib
import hmac
import os
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse, Response, RedirectResponse

from server import config as cloudcfg

# server.config が HOME を差し替えた後に web_app を読む（Path.home() 由来の定数を正しく解決）。
import web_app

_ROOT = Path(__file__).resolve().parent.parent
_WEBUI = _ROOT / "webui"
_BRIDGE = Path(__file__).resolve().parent / "static" / "bridge.js"
_SESSION_COOKIE = "tomato_web_session"
_SESSION_MAX_AGE = 12 * 60 * 60

def _session_value(secret: str) -> str:
    issued = str(int(time.time()))
    sig = hmac.new(secret.encode("utf-8"), issued.encode("ascii"), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode((issued + "." + sig).encode("ascii")).decode("ascii")

def _valid_session(value: str, secret: str) -> bool:
    try:
        issued, sig = base64.urlsafe_b64decode(value.encode("ascii")).decode("ascii").split(".", 1)
        if time.time() - int(issued) > _SESSION_MAX_AGE: return False
        expected = hmac.new(secret.encode("utf-8"), issued.encode("ascii"), hashlib.sha256).hexdigest()
        return hmac.compare_digest(sig, expected)
    except Exception:
        return False


class CloudApi(web_app.Api):
    """web_app.Api のクラウド版。config/license をenvから、生成物URLを配信URLに。"""

    def __init__(self):
        self._queue = []
        self._lock = threading.Lock()
        self.config = cloudcfg.load_config()
        self.current_cid = None   # 会話履歴（継承した send_message が参照）
        self._get_license = cloudcfg.license_getter()
        self._license = self._get_license()
        self.engine = self._new_engine()

    # ライセンス再取得はクラウド用 getter を使う（親は license.get_license を直import するため上書き）
    def _reload_license(self):
        self._license = self._get_license()
        return self._license

    # エンジンのコールバック（on_video だけ配信URL書き換え版に差し替え）
    def _new_engine(self):
        from chat_engine import ChatEngine
        cb = {
            "on_text":           lambda t: self._js("addAiText", t),
            "on_progress_start": lambda pid, title: self._js("startProgress", pid, title),
            "on_progress":       lambda pid, step: self._js("updateProgress", pid, step),
            "on_progress_done":  lambda pid, title: self._js("finishProgress", pid, title),
            "on_video":          lambda d: self._on_video(d),
            "on_error":          lambda t: self._js("addError", t),
            "on_done":           lambda: self._js("done"),
        }
        return ChatEngine(self.config, self._get_license, cb)

    # ---- 生成物パス ⇔ /media 配信URL ----
    def _media_url(self, path: str) -> str:
        try:
            rel = Path(path).resolve().relative_to(cloudcfg.output_root().resolve())
            return "/media/" + str(rel).replace("\\", "/")
        except Exception:
            return ""

    def _reverse_media(self, url: str) -> str:
        """/media/<rel> → サーバー上の実ファイルパス（post_video/open_file 用）。"""
        if url and url.startswith("/media/"):
            return str(cloudcfg.output_root() / url[len("/media/"):])
        return url

    def list_videos(self, limit=60):
        """エディタの素材レール：サーバー上のパスはブラウザで開けないので /media URL に直す。"""
        out = []
        for v in super().list_videos(limit):
            url = self._media_url(v.get("path", ""))
            if not url:
                continue          # 配信できない場所のファイルは出さない
            v = dict(v)
            v["path"] = url
            out.append(v)
        return out

    def _on_video(self, d):
        try:
            d = d if isinstance(d, dict) else json.loads(d)
        except Exception:
            d = {}
        url = self._media_url(d.get("path", ""))
        out = dict(d)
        if url:
            out["path"] = url
        self._js("addVideoCard", out)

    def _on_ai_video(self, d):
        """export_cuts(台本編集の書き出し)経由のカードも配信URLに直してから流す。"""
        d = dict(d or {})
        url = self._media_url(d.get("path", ""))
        if url:
            d["path"] = url
        super()._on_ai_video(d)

    # ---- クラウド向けオーバーライド ----
    def open_file(self, path):
        # クラウドではサーバーFSを開けない。配信URLを案内するだけ。
        self._js("addAiText", "🔗 " + (self._media_url(self._reverse_media(path)) or str(path)))
        return True

    def post_video(self, path):
        """完成動画を YouTube へ無人投稿してリンクを返す（creds/yt_token が揃っていれば）。"""
        real = self._reverse_media(path)
        cred = self.config.get("credentials_path", "")
        if not (cred and Path(cred).exists() and real and Path(real).exists()):
            self._js("addAiText", "YouTube連携が未設定のため投稿できません（設定でクレデンシャルを注入してください）。")
            return True

        def _up():
            try:
                from pipeline import upload_to_youtube
                analysis = {
                    "title": "Tomato Clip",
                    "description": "",
                    "output_language": self.config.get("output_language", "ja"),
                }
                url = upload_to_youtube(real, analysis, cred, lambda m: None)
                self._js("addAiText", (f"🎬 YouTube に投稿しました: {url}" if url
                                       else "YouTube投稿に失敗しました（サーバーに保存済み）。"))
            except Exception as e:
                self._js("addAiText", f"⚠️ 投稿エラー: {e}")

        threading.Thread(target=_up, daemon=True).start()
        self._js("addAiText", "📤 YouTube に投稿中…")
        return True


# ── 公開メソッドのホワイトリスト（/api 経由で呼べるもの） ──
_ALLOWED = {
    "poll", "send_message", "new_conversation", "get_init", "get_strings", "set_ui_lang",
    "get_account_state", "get_settings", "agree_terms", "mark_tutorial_seen", "get_legal_text",
    "save_api_keys", "test_api_key", "activate_license", "deactivate_license", "apply_promo",
    "open_file", "post_video",
    "list_conversations", "load_conversation", "delete_conversation", "search_conversations",
    "get_stats", "get_youtube_dashboard",
    "list_schedule", "add_schedule", "reschedule", "cancel_schedule",
    "update_schedule_prompt", "list_videos", "get_transcript", "export_cuts",
    "set_source_preference", "get_edit_log",
    "cloud_get_state", "cloud_make_bundle", "cloud_save_url", "cloud_test", "cloud_launch_setup",
    "account_state", "account_login", "account_logout", "cloud_push_settings", "account_token",
    "cloud_server_state",
}


def create_app() -> FastAPI:
    app = FastAPI(title="Tomato Clip Cloud")
    api = CloudApi()   # ← ここで load_config が走り TOMATO_ACCOUNT_PLAN が設定される
    app.state.api = api
    pro_ok = cloudcfg.is_pro_allowed()
    web_password = os.environ.get("TOMATO_WEB_PASSWORD", "").strip()
    if pro_ok and not web_password:
        raise RuntimeError("TOMATO_WEB_PASSWORD must be set for a Pro cloud deployment")
    def authenticated(request: Request) -> bool:
        return bool(web_password) and _valid_session(request.cookies.get(_SESSION_COOKIE, ""), web_password)
    def login_page(error=False):
        msg = "<p style='color:#b42318'>パスワードが正しくありません。</p>" if error else ""
        return HTMLResponse("<!doctype html><meta charset='utf-8'><title>Tomato Clip</title><style>body{margin:0;min-height:100vh;display:grid;place-items:center;background:#fff8f5;color:#231815;font:16px system-ui,sans-serif}.box{width:min(360px,calc(100vw - 40px));padding:28px;border:1px solid #f2cabe;border-radius:18px;background:#fff;box-shadow:0 14px 45px #d35a3522}input,button{box-sizing:border-box;width:100%;padding:11px 13px;border-radius:9px;font:inherit}input{border:1px solid #d8c7c1;margin:10px 0}button{border:0;background:#e64a2e;color:#fff;font-weight:700;cursor:pointer}</style><main class='box'><h1>Tomato Clip</h1><p>この編集デスクは保護されています。</p>"+msg+"<form method='post' action='/login'><input name='password' type='password' autocomplete='current-password' autofocus required placeholder='パスワード'><button type='submit'>開く</button></form></main>")
    if not pro_ok:
        import sys as _sys
        print("[web] 非Proアカウントのためクラウドをブロックします（勧誘ページを表示）", file=_sys.stderr)

    # StaticFilesでは認証できないため、動画は下のルートで確認して配信する。
    out_root = cloudcfg.output_root()
    out_root.mkdir(parents=True, exist_ok=True)
    @app.get("/login", response_class=HTMLResponse)
    def login(request: Request):
        return RedirectResponse("/", status_code=303) if pro_ok and authenticated(request) else login_page()
    @app.post("/login")
    async def login_submit(request: Request):
        supplied = (parse_qs((await request.body()).decode("utf-8", "ignore")).get("password") or [""])[0]
        if not pro_ok or not hmac.compare_digest(supplied, web_password): return login_page(True)
        response = RedirectResponse("/", status_code=303)
        secure = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
        response.set_cookie(_SESSION_COOKIE, _session_value(web_password), max_age=_SESSION_MAX_AGE, httponly=True, samesite="strict", secure=secure, path="/")
        return response
    @app.post("/logout")
    def logout():
        response = JSONResponse({"ok": True}); response.delete_cookie(_SESSION_COOKIE, path="/"); return response

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):
        if not pro_ok:
            return HTMLResponse(cloudcfg.upsell_html())
        if not authenticated(request):
            return RedirectResponse("/login", status_code=303)
        html = (_WEBUI / "index.html").read_text(encoding="utf-8")
        # <head> に bridge.js を注入（app.js より前に window.pywebview を用意）
        html = html.replace("</head>", '  <script src="/bridge.js"></script>\n</head>', 1)
        return HTMLResponse(html)

    @app.get("/bridge.js")
    def bridge():
        return FileResponse(str(_BRIDGE), media_type="application/javascript")

    @app.get("/app.js")
    def appjs():
        return FileResponse(str(_WEBUI / "app.js"), media_type="application/javascript")

    @app.get("/logo.png")
    def logo():
        return FileResponse(str(_WEBUI / "logo.png"), media_type="image/png")

    @app.get("/healthz")
    def health():
        return {"ok": True}
    @app.get("/media/{path:path}")
    def media(path: str, request: Request):
        if not pro_ok or not authenticated(request): return Response(status_code=401)
        try:
            candidate = (out_root / path).resolve(); candidate.relative_to(out_root.resolve())
        except (ValueError, OSError): return Response(status_code=404)
        return FileResponse(str(candidate)) if candidate.is_file() else Response(status_code=404)

    @app.post("/api/{name}")
    def api_call(name: str, request: Request, body: dict = None):
        if not pro_ok:
            return JSONResponse({"error": "pro_required",
                                 "message": "クラウドは Pro プラン限定です"}, status_code=403)
        if not authenticated(request):
            return JSONResponse({"error": "authentication_required"}, status_code=401)
        if name not in _ALLOWED:
            return JSONResponse({"error": "unknown method"}, status_code=404)
        args = (body or {}).get("args", []) if isinstance(body, dict) else []
        fn = getattr(api, name, None)
        if not callable(fn):
            return JSONResponse({"error": "not callable"}, status_code=404)
        try:
            result = fn(*args)
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)
        return JSONResponse(result)

    return app
