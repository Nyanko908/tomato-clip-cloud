# -*- coding: utf-8 -*-
"""account.py — TomatoAI アカウント（Firebase Auth / Google ログイン）。

デスクトップ（WebView2）内では Google OAuth が動かないため、
**システムブラウザで localhost のログインページを開く**方式を使う：

  1. ランダムポートでローカルHTTPサーバを立て、Firebase JS SDK 入りのログインページを配信。
  2. システムブラウザでそのページ（http://127.0.0.1:PORT/）を開く。
  3. ユーザーが「Googleでログイン」→ Firebase が認証 → idToken/refreshToken を取得。
  4. ページが /callback にトークンを POST → アプリが受け取りセッション保存。

localhost は Firebase のデフォルト認証許可ドメインなので追加設定不要。
セッション（refresh_token 等）は ~/.tomato_clip/account.json に保存する。
この refresh_token を「サーバーに渡す1つの鍵」としても使える（サーバーが自分の設定を取得）。
"""
import os
import json
import time
import threading
import webbrowser
import urllib.request
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

# Firebase Web 設定（公開値。埋め込み可）
FB_API_KEY = "AIzaSyBxIebU7HcGdzrb6gx9peAsMKafbgkA_dM"
FB_AUTH_DOMAIN = "tomatoshorts.firebaseapp.com"
FB_PROJECT_ID = "tomatoshorts"

_SESSION_PATH = Path.home() / ".tomato_clip" / "account.json"
_FS_BASE = f"https://firestore.googleapis.com/v1/projects/{FB_PROJECT_ID}/databases/(default)/documents"


# ─────────────────────────── セッション保存 ───────────────────────────
def load_session() -> dict:
    try:
        if _SESSION_PATH.exists():
            return json.loads(_SESSION_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def save_session(sess: dict):
    try:
        _SESSION_PATH.parent.mkdir(parents=True, exist_ok=True)
        _SESSION_PATH.write_text(json.dumps(sess, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def logout():
    try:
        _SESSION_PATH.unlink()
    except FileNotFoundError:
        pass
    except Exception:
        pass


def is_logged_in() -> bool:
    return bool(load_session().get("refresh_token"))


def get_refresh_token() -> str:
    """サーバーに渡す「アカウントの鍵」。これ1つでサーバーが設定を取得できる。"""
    return load_session().get("refresh_token", "")


def account_state() -> dict:
    s = load_session()
    return {"logged_in": bool(s.get("refresh_token")),
            "email": s.get("email", ""), "uid": s.get("uid", ""),
            "channel_id": s.get("channel_id", ""),
            "channel_title": s.get("channel_title", ""),
            "channel_thumb": s.get("channel_thumb", ""),
            "channel_subs": s.get("channel_subs", "")}


# ─────────────────────────── トークン更新 ───────────────────────────
def refresh_id_token() -> str:
    """保存済み refresh_token から新しい idToken を取得（1時間有効）。失敗時は空。"""
    s = load_session()
    rt = s.get("refresh_token")
    if not rt:
        return ""
    try:
        url = f"https://securetoken.googleapis.com/v1/token?key={FB_API_KEY}"
        body = urllib.parse.urlencode({"grant_type": "refresh_token", "refresh_token": rt}).encode()
        req = urllib.request.Request(url, data=body,
                                     headers={"Content-Type": "application/x-www-form-urlencoded"})
        d = json.loads(urllib.request.urlopen(req, timeout=10).read())
        # refresh_token はローテーションされることがあるので更新
        s["refresh_token"] = d.get("refresh_token", rt)
        s["uid"] = d.get("user_id", s.get("uid", ""))
        save_session(s)
        return d.get("id_token", "")
    except Exception:
        return ""


# ─────────────────────────── Firestore（本人ドキュメント） ───────────────────────────
def _fs_headers(id_token):
    return {"Authorization": "Bearer " + id_token, "Content-Type": "application/json"}


def firestore_get(id_token: str, uid: str) -> dict:
    """users/{uid} ドキュメントを取得。無ければ {}。"""
    try:
        url = f"{_FS_BASE}/users/{uid}"
        req = urllib.request.Request(url, headers=_fs_headers(id_token))
        d = json.loads(urllib.request.urlopen(req, timeout=10).read())
        return _fs_from_fields(d.get("fields", {}))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {}
        raise
    except Exception:
        return {}


def firestore_set(id_token: str, uid: str, data: dict) -> bool:
    """users/{uid} を data で更新（部分マージ）。"""
    try:
        fields = _fs_to_fields(data)
        mask = "&".join("updateMask.fieldPaths=" + urllib.parse.quote(k) for k in data.keys())
        url = f"{_FS_BASE}/users/{uid}?{mask}"
        body = json.dumps({"fields": fields}).encode()
        req = urllib.request.Request(url, data=body, method="PATCH", headers=_fs_headers(id_token))
        urllib.request.urlopen(req, timeout=10)
        return True
    except Exception:
        return False


def push_settings(config: dict) -> bool:
    """移送対象の設定をアカウントの Firestore に保存する（本人のみ読み書き可）。

    Firestore ルールが本人アクセスを保証するので、暗号化は不要（アカウント＝鍵）。
    """
    import time as _t
    idt = refresh_id_token()
    s = load_session()
    uid = s.get("uid", "")
    if not (idt and uid):
        return False
    try:
        import cloud_bundle
        payload = cloud_bundle.collect_payload(config, include_youtube_token=True, include_discord=True)
    except Exception:
        payload = {}
    data = {
        "settings": json.dumps(payload, ensure_ascii=False),
        "settings_updated": str(int(_t.time())),
        "channel_title": s.get("channel_title", ""),
        "channel_id": s.get("channel_id", ""),
    }
    return firestore_set(idt, uid, data)


def register_server_with_token(refresh_token: str, url: str, status: str = "online") -> bool:
    """サーバーが自分のURL・生存時刻をアカウントに登録する（heartbeat）。

    サイト/アプリはこれを読んで「あなたのクラウドがどこで動いているか」を発見する。
    """
    import time as _t
    try:
        u = f"https://securetoken.googleapis.com/v1/token?key={FB_API_KEY}"
        body = urllib.parse.urlencode(
            {"grant_type": "refresh_token", "refresh_token": refresh_token}).encode()
        req = urllib.request.Request(u, data=body,
                                     headers={"Content-Type": "application/x-www-form-urlencoded"})
        d = json.loads(urllib.request.urlopen(req, timeout=10).read())
        idt = d.get("id_token", "")
        uid = d.get("user_id", "")
        if not (idt and uid):
            return False
        return firestore_set(idt, uid, {
            "server_url": (url or "").rstrip("/"),
            "server_last_seen": str(int(_t.time())),
            "server_status": status,
        })
    except Exception:
        return False


def get_server_state() -> dict:
    """ログイン中アカウントの、登録済みサーバー情報を返す（アプリ側の表示用）。

    戻り値: {"url": str, "online": bool, "last_seen": int}
    """
    import time as _t
    idt = refresh_id_token()
    s = load_session()
    uid = s.get("uid", "")
    if not (idt and uid):
        return {"url": "", "online": False, "last_seen": 0}
    try:
        doc = firestore_get(idt, uid)
        url = doc.get("server_url", "")
        last = int(doc.get("server_last_seen", "0") or 0)
        online = bool(url) and (int(_t.time()) - last < 300)  # 5分以内=オンライン
        return {"url": url, "online": online, "last_seen": last}
    except Exception:
        return {"url": "", "online": False, "last_seen": 0}


_WORKER_URL = "https://tomato-shorts-license.clipflowlicense.workers.dev"


def link_pro_to_worker(key: str, machine_id: str = "") -> dict:
    """有効なライセンスキーを提示して、このアカウント(uid)をProとして worker に登録する。

    worker が「uid ↔ 有効ライセンス」を記録する（operator権威＝Firestore plan の偽装を無効化）。
    ※ worker 側に /account/link がデプロイされている必要がある。未デプロイなら失敗を返す。
    """
    uid = load_session().get("uid", "")
    if not (uid and key):
        return {"ok": False}
    try:
        body = json.dumps({"uid": uid, "key": key, "machine_id": machine_id}).encode()
        req = urllib.request.Request(_WORKER_URL + "/account/link", data=body, method="POST",
                                     headers={"Content-Type": "application/json",
                                              "User-Agent": "TomatoClip/1.0"})
        d = json.loads(urllib.request.urlopen(req, timeout=10).read())
        return {"ok": d.get("status") == "ok", "plan": d.get("plan", "")}
    except Exception:
        return {"ok": False}


def worker_plan(uid: str) -> str:
    """worker に uid のプランを照会する（クラウドサーバーが権威判定に使う）。未デプロイ/不通は空。"""
    if not uid:
        return ""
    try:
        body = json.dumps({"uid": uid}).encode()
        req = urllib.request.Request(_WORKER_URL + "/account/plan", data=body, method="POST",
                                     headers={"Content-Type": "application/json",
                                              "User-Agent": "TomatoClip/1.0"})
        d = json.loads(urllib.request.urlopen(req, timeout=8).read())
        return d.get("plan", "") if d.get("status") == "ok" else ""
    except Exception:
        return ""


def set_plan(plan: str) -> bool:
    """アカウントにプラン（"pro" / "free"）を記録する。クラウドの Pro 判定に使う。"""
    import time as _t
    idt = refresh_id_token()
    s = load_session()
    uid = s.get("uid", "")
    if not (idt and uid):
        return False
    return firestore_set(idt, uid, {"plan": plan, "plan_updated": str(int(_t.time()))})


def pull_account_with_token(refresh_token: str) -> dict:
    """refresh_token だけからアカウント情報一式を取得する（サーバー側で使う）。

    戻り値: {"settings": dict, "plan": str, "channel_title": str, "uid": str}
    """
    try:
        url = f"https://securetoken.googleapis.com/v1/token?key={FB_API_KEY}"
        body = urllib.parse.urlencode(
            {"grant_type": "refresh_token", "refresh_token": refresh_token}).encode()
        req = urllib.request.Request(url, data=body,
                                     headers={"Content-Type": "application/x-www-form-urlencoded"})
        d = json.loads(urllib.request.urlopen(req, timeout=10).read())
        idt = d.get("id_token", "")
        uid = d.get("user_id", "")
        if not (idt and uid):
            return {}
        doc = firestore_get(idt, uid)
        raw = doc.get("settings", "")
        settings = json.loads(raw) if raw else {}
        return {"settings": settings, "plan": doc.get("plan", ""),
                "channel_title": doc.get("channel_title", ""), "uid": uid}
    except Exception:
        return {}


def pull_settings_with_token(refresh_token: str) -> dict:
    """設定だけ欲しいとき用（後方互換）。"""
    return pull_account_with_token(refresh_token).get("settings", {})


def _fs_to_fields(data: dict) -> dict:
    out = {}
    for k, v in data.items():
        if isinstance(v, bool):
            out[k] = {"booleanValue": v}
        elif isinstance(v, int):
            out[k] = {"integerValue": str(v)}
        elif isinstance(v, float):
            out[k] = {"doubleValue": v}
        else:
            out[k] = {"stringValue": str(v)}
    return out


def _fs_from_fields(fields: dict) -> dict:
    out = {}
    for k, v in fields.items():
        if "booleanValue" in v:
            out[k] = v["booleanValue"]
        elif "integerValue" in v:
            out[k] = int(v["integerValue"])
        elif "doubleValue" in v:
            out[k] = float(v["doubleValue"])
        else:
            out[k] = v.get("stringValue", "")
    return out


# ─────────────────────────── ブラウザ ログイン ───────────────────────────
def _logo_data_uri() -> str:
    """本物のロゴ(logo.png)を data URI にして返す（ローカル配信ページに埋め込む）。"""
    import base64
    for p in (Path(__file__).parent / "logo.png", Path(__file__).parent / "webui" / "logo.png"):
        try:
            if p.exists():
                return "data:image/png;base64," + base64.b64encode(p.read_bytes()).decode("ascii")
        except Exception:
            pass
    return ""


def _login_page_html(port: int) -> str:
    return """<!doctype html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Tomato Clip ログイン</title>
<style>
 body{font-family:system-ui,"Segoe UI","Hiragino Kaku Gothic ProN",sans-serif;background:#fff;color:#1d1d20;
   display:flex;min-height:100vh;margin:0;align-items:center;justify-content:center;text-align:center;padding:24px;}
 .box{max-width:380px;}
 h1{font-size:22px;margin:14px 0 6px;} p{color:#6b6b76;font-size:14px;line-height:1.7;}
 .logo{width:56px;height:56px;object-fit:contain;}
 button{margin-top:18px;padding:12px 22px;border:1px solid #dadce0;border-radius:12px;background:#fff;
   font-size:15px;font-weight:600;cursor:pointer;display:inline-flex;align-items:center;gap:10px;}
 button:hover{background:#f7f7f8;}
 .ok{color:#3aa552;font-weight:600;} .err{color:#e5503c;}
 .g{width:18px;height:18px;}
</style></head><body><div class="box">
 <img class="logo" src="__LOGO__" alt="">
 <h1>Tomato Clip にログイン</h1>
 <p>Google アカウントでログインします。<br>YouTube チャンネルもそのまま連携します。</p>
 <button id="btn"><svg class="g" viewBox="0 0 48 48"><path fill="#4285F4" d="M45 24c0-1.6-.1-2.7-.4-3.9H24v7.2h11.8c-.2 1.9-1.5 4.8-4.3 6.7l-.04.3 6.2 4.8.4.04C42.6 35.6 45 30.3 45 24z"/><path fill="#34A853" d="M24 46c5.7 0 10.5-1.9 14-5.1l-6.7-5.2c-1.8 1.2-4.2 2.1-7.3 2.1-5.6 0-10.3-3.7-12-8.8l-.3.02-6.4 5-.1.3C8.6 41.1 15.7 46 24 46z"/><path fill="#FBBC05" d="M12 29c-.5-1.4-.7-2.9-.7-4.4s.3-3 .7-4.4l-.02-.3-6.5-5-.2.1C3.9 18 3 20.9 3 24s.9 6 2.3 8.6l6.7-5.2z"/><path fill="#EB4335" d="M24 10.7c3.9 0 6.6 1.7 8.1 3.1l5.9-5.8C34.5 4.7 29.7 3 24 3 15.7 3 8.6 7.9 5.3 14.8l6.7 5.2c1.7-5.1 6.4-9.3 12-9.3z"/></svg>Google でログイン</button>
 <p id="msg"></p>
</div>
<script type="module">
 import { initializeApp } from "https://www.gstatic.com/firebasejs/10.12.0/firebase-app.js";
 import { getAuth, GoogleAuthProvider, signInWithPopup } from "https://www.gstatic.com/firebasejs/10.12.0/firebase-auth.js";
 const app = initializeApp({ apiKey:"__API__", authDomain:"__DOMAIN__", projectId:"__PROJECT__" });
 const auth = getAuth(app);
 const btn = document.getElementById("btn"), msg = document.getElementById("msg");
 btn.onclick = async () => {
   msg.textContent = "";
   try {
     const provider = new GoogleAuthProvider();
     provider.addScope("email"); provider.addScope("profile");
     provider.addScope("https://www.googleapis.com/auth/youtube.readonly");
     const res = await signInWithPopup(auth, provider);
     const user = res.user;
     const idToken = await user.getIdToken();
     const payload = { id_token: idToken, refresh_token: user.stsTokenManager.refreshToken,
       email: user.email, uid: user.uid, name: user.displayName || "" };
     // YouTube チャンネルも取得（アクセストークンで Data API を叩く）
     try {
       const cred = GoogleAuthProvider.credentialFromResult(res);
       const at = cred && cred.accessToken;
       if (at) {
         const r = await fetch("https://www.googleapis.com/youtube/v3/channels?part=snippet,statistics&mine=true",
           { headers: { Authorization: "Bearer " + at } });
         const d = await r.json();
         const it = d.items && d.items[0];
         if (it) {
           payload.channel_id = it.id;
           payload.channel_title = (it.snippet||{}).title || "";
           payload.channel_thumb = (((it.snippet||{}).thumbnails||{}).default||{}).url || "";
           payload.channel_subs = ((it.statistics||{}).subscriberCount) || "0";
         }
       }
     } catch (e2) { /* チャンネル取得失敗でもログインは成立 */ }
     await fetch("/callback", { method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify(payload) });
     btn.style.display = "none";
     var chMsg = payload.channel_title ? ('<br>チャンネル「' + payload.channel_title + '」を連携しました。') : '';
     msg.innerHTML = '<span class="ok">✓ ログインしました！' + chMsg + '<br>このタブは閉じてアプリに戻ってください。</span>';
   } catch (e) {
     msg.innerHTML = '<span class="err">ログインに失敗しました: ' + (e.code || e.message) + '</span>';
   }
 };
</script></body></html>""".replace("__API__", FB_API_KEY).replace("__DOMAIN__", FB_AUTH_DOMAIN).replace("__PROJECT__", FB_PROJECT_ID).replace("__LOGO__", _logo_data_uri())


def login_via_browser(timeout=300) -> dict:
    """システムブラウザでログインし、成功したらセッションを保存して state を返す。

    ブロッキング（最大 timeout 秒）。UI からは別スレッドで呼ぶこと。
    """
    result = {"ok": False}
    done = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(_login_page_html(self.server.server_address[1]).encode("utf-8"))

        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            try:
                data = json.loads(self.rfile.read(length).decode("utf-8"))
            except Exception:
                data = {}
            if data.get("refresh_token") and data.get("uid"):
                save_session({"refresh_token": data["refresh_token"], "uid": data["uid"],
                              "email": data.get("email", ""), "name": data.get("name", ""),
                              "channel_id": data.get("channel_id", ""),
                              "channel_title": data.get("channel_title", ""),
                              "channel_thumb": data.get("channel_thumb", ""),
                              "channel_subs": data.get("channel_subs", "")})
                result.update({"ok": True, "email": data.get("email", ""), "uid": data["uid"],
                               "channel_id": data.get("channel_id", ""),
                               "channel_title": data.get("channel_title", "")})
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(b'{"ok":true}')
            done.set()

    server = HTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        # localhost を使う（Firebase の許可ドメイン。127.0.0.1 は auth/unauthorized-domain になる）
        webbrowser.open(f"http://localhost:{port}/")
    except Exception:
        pass
    done.wait(timeout)
    try:
        server.shutdown()
    except Exception:
        pass
    return result if result["ok"] else {"ok": False}


if __name__ == "__main__":
    print("Opening browser for Google login…")
    r = login_via_browser()
    print("result:", r)
    if r.get("ok"):
        idt = refresh_id_token()
        print("refreshed idToken:", bool(idt))
        print("account_state:", account_state())
