# -*- coding: utf-8 -*-
"""
web_app.py — Tomato Clip の新UI（pywebview版）エントリポイント。

webui/index.html を WebView2 で表示し、Api クラスを JS に公開する。
チャット処理は chat_engine.ChatEngine に委譲し、その出力コールバックを
window.evaluate_js() 経由で JS(window.chatUI.*) に反映する。

現行の Tkinter 版（main.py）とは独立。壊さず並行で動く。
起動: python web_app.py
"""
import os, sys, json, threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


def resource_path(*parts) -> Path:
    """同梱リソースの絶対パスを返す。

    PyInstaller で凍結された場合、同梱データは onedir なら _internal/、
    onefile なら sys._MEIPASS 以下に展開される。どちらも sys._MEIPASS で
    参照できる。通常実行時はソースの隣（このファイルの親）を基準にする。
    """
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
    return base.joinpath(*parts)


CONFIG_PATH = Path.home() / ".tomato_clip_config.json"

# 使うモデルは pipeline.py に一元化（-latest エイリアス＝Googleの廃止で死なない）
try:
    from pipeline import DEFAULT_MODEL as _DEFAULT_MODEL
except Exception:
    _DEFAULT_MODEL = "gemini-flash-lite-latest"

# 既定値（app.py の DEFAULT_CONFIG と同義。新UIでも既定が欠落しないようマージする）
_DEFAULTS = {
    "gemini_key": "", "youtube_key": "", "credentials_path": "",
    "gemini_model": _DEFAULT_MODEL,
    "output_resolution": "1080p", "encode_preset": "fast", "freshness_hours": 72,
    "search_keywords": "", "my_channel_id": "", "auto_memory": True,
    "agreed_terms": False, "ui_lang": "ja", "seen_tutorial": False,
    "output_language": "ja", "monthly_goal": 10, "dev_mode": False,
    # 検索の素性設定: prefer_original(既定・原典優先) / original_only / any
    "source_preference": "prefer_original",
    # Python編集（AIがコードを書いて編集）。常時有効・障害時の切り戻し用スイッチ
    "python_edit": True,
}


# 廃止済みモデル。設定に残っていると 404 で解析が全滅するので起動時に移行する。
_RETIRED_MODELS = {
    "gemini-2.5-flash-lite", "gemini-2.5-flash", "gemini-2.0-flash",
    "gemini-1.5-flash", "gemini-1.5-pro", "gemini-1.5-flash-8b",
}


def load_config() -> dict:
    try:
        if CONFIG_PATH.exists():
            cfg = {**_DEFAULTS, **json.loads(CONFIG_PATH.read_text(encoding="utf-8"))}
            if cfg.get("gemini_model") in _RETIRED_MODELS:
                cfg["gemini_model"] = _DEFAULT_MODEL   # 廃止モデルを掴んだままにしない
                save_config(cfg)
            return cfg
    except Exception:
        pass
    return dict(_DEFAULTS)


def save_config(cfg: dict):
    # クラウド(server/*)では設定の真実の源は環境変数。ここで書くと、ローカルPCで
    # クラウド版を起動してテストしたときに env由来のほぼ空のconfigが
    # ~/.tomato_clip_config.json を上書きしてAPIキーが消える（実際に起きた）。
    # メモリ上のconfigは更新済みなので、ファイルには書かず成功扱いにする。
    if os.environ.get("TOMATO_CLOUD") == "1":
        return True
    try:
        CONFIG_PATH.write_text(
            json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        return True
    except Exception:
        return False


def _setup_media_env():
    """生成（moviepy編集）のための ffmpeg パス設定 & PIL 互換パッチ。"""
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


class Api:
    def __init__(self):
        # UI更新はキューに貯め、JSがpoll()で取りに来る。
        # （WebView2は evaluate_js をバックグラウンドスレッドから呼べない＝UIスレッド制約のため）
        # ※pywebviewウィンドウ参照(self.window)はApiに持たせない：
        #   js_api公開時に window.native を無限に走査してRecursionErrorになるため。
        self._queue = []
        self._lock = threading.Lock()
        self.config = load_config()
        self.current_cid = None   # 現在の会話ID（会話履歴の保存/復元用）
        self._license = None
        try:
            from license import get_license
            self._license = get_license()
        except Exception:
            self._license = None
        self.engine = self._new_engine()
        # 既存の予約があれば起動時にウォッチャーを再開
        try:
            self._ensure_schedule_watcher()
        except Exception:
            pass

    # ---- engine ----
    def _new_engine(self):
        from chat_engine import ChatEngine
        cb = {
            "on_text":          lambda t: self._on_ai_text(t),
            "on_progress_start": lambda pid, title: self._js("startProgress", pid, title),
            "on_progress":      lambda pid, step: self._js("updateProgress", pid, step),
            "on_progress_done": lambda pid, title: self._js("finishProgress", pid, title),
            "on_video":         lambda d: self._on_ai_video(d),
            "on_error":         lambda t: self._js("addError", t),
            "on_done":          lambda: self._js("done"),
        }
        return ChatEngine(self.config, lambda: self._license, cb)

    # AI応答/動画を UI へ流しつつ、現在の会話にも保存する
    def _on_ai_text(self, t):
        self._js("addAiText", t)
        cid = getattr(self, "current_cid", None)
        if cid:
            try:
                import conversations
                conversations.add_message(cid, "ai", text=t)
            except Exception:
                pass

    def _on_ai_video(self, d):
        self._js("addVideoCard", d)
        cid = getattr(self, "current_cid", None)
        if cid:
            try:
                import conversations
                data = d if isinstance(d, dict) else {}
                conversations.add_message(cid, "video", data=data)
            except Exception:
                pass

    def _js(self, fn, *args):
        # UI更新をキューに積む（JSが poll() で取得して chatUI.fn(...args) を実行）
        with self._lock:
            self._queue.append({"fn": fn, "args": list(args)})

    # ---- JSから呼ばれるメソッド ----
    def poll(self):
        with self._lock:
            out = self._queue
            self._queue = []
        return out

    def send_message(self, text):
        # 会話が無ければ作成し、user発話を記録してから生成へ
        is_new = False
        try:
            import conversations
            if not self.current_cid:
                self.current_cid = conversations.create(text or "")
                is_new = True
            conversations.add_message(self.current_cid, "user", text=text)
        except Exception:
            pass
        threading.Thread(target=self.engine.send, args=(text,), daemon=True).start()
        # 新規会話は ChatGPT 風にタイトルを自動生成（非同期・失敗しても既定タイトルのまま）
        if is_new and self.current_cid:
            _cid = self.current_cid
            threading.Thread(target=self._gen_title, args=(_cid, text), daemon=True).start()
        return {"cid": self.current_cid}

    def _gen_title(self, cid, first_message):
        """最初の発話から短いタイトルを Gemini で生成して会話に設定する。"""
        try:
            import conversations
            key = self.config.get("gemini_key", "")
            if not key:
                return
            from pipeline import init_gemini
            from google.genai import types as gt
            client = init_gemini(key, self.config.get("gemini_model") or _DEFAULT_MODEL)
            prompt = ("次のメッセージにふさわしい、ごく短いタイトルを1つだけ付けてください。"
                      "入力と同じ言語で、最大18文字程度、記号・引用符・句読点なし、タイトルのみ出力。\n"
                      f"メッセージ: {first_message}")
            resp = client.models.generate_content(
                model=client._model_name, contents=[gt.Content(role="user", parts=[gt.Part(text=prompt)])])
            title = (getattr(resp, "text", "") or "").strip().strip('"「」『』').splitlines()[0][:40]
            if title:
                conversations.set_title(cid, title)
                # サイドバーに反映
                self._js("renameConversation", cid, title)
        except Exception:
            pass

    def search_conversations(self, query):
        try:
            import conversations
            return conversations.search(query)
        except Exception:
            return []

    def new_conversation(self):
        self.current_cid = None
        self.engine = self._new_engine()
        return True

    # ── 会話履歴（保存/復元） ──
    def list_conversations(self):
        try:
            import conversations
            return conversations.list_all()
        except Exception:
            return []

    def load_conversation(self, cid):
        """保存済み会話を復元。UI再生用メッセージ＋engine履歴の再構築を行う。"""
        try:
            import conversations
            d = conversations.get(cid)
        except Exception:
            d = None
        if not d:
            return {"ok": False}
        self.current_cid = cid
        # engine を作り直し、LLMコンテキスト(history)を会話から復元
        self.engine = self._new_engine()
        hist = []
        for m in d.get("messages", []):
            if m.get("kind") == "user":
                hist.append({"role": "user", "parts": [m.get("text", "")]})
            elif m.get("kind") == "ai":
                hist.append({"role": "model", "parts": [m.get("text", "")]})
        self.engine.history = hist
        return {"ok": True, "id": cid, "title": d.get("title", ""),
                "messages": d.get("messages", [])}

    def delete_conversation(self, cid):
        try:
            import conversations
            conversations.delete(cid)
        except Exception:
            pass
        if self.current_cid == cid:
            self.current_cid = None
        return True

    def get_init(self):
        lang = self.config.get("ui_lang", "ja")
        try:
            import i18n
            i18n.set_lang(lang)
            _T = i18n.T
        except Exception:
            _T = lambda s: s
        is_demo = (self._license is None or getattr(self._license, "is_demo", True))
        plan = _T("デモモード") if is_demo else "Pro"
        return {"plan": plan, "lang": lang}

    def get_strings(self, lang, keys=None):
        """新UIの日本語原文キー一覧(keys)を、指定言語に翻訳して返す。
        未収録は i18n.T() が原文（＝日本語）をそのまま返すので崩れない。"""
        lang = lang or self.config.get("ui_lang", "ja")
        try:
            import i18n
            i18n.set_lang(lang)
            _T = i18n.T
        except Exception:
            _T = lambda s: s
        keys = keys or []
        return {"lang": lang, "map": {k: _T(k) for k in keys}}

    def set_ui_lang(self, lang):
        """表示言語を変更して config に保存（次回起動で復元）。設定画面から使う。"""
        self.config["ui_lang"] = lang
        save_config(self.config)
        return True

    # ── アカウント / オンボーディング（既存ロジックを流用） ──
    def _reload_license(self):
        try:
            from license import get_license
            self._license = get_license()
        except Exception:
            self._license = None
        return self._license

    def get_account_state(self):
        """初回セットアップ・設定・ヘッダー表示に必要な状態をまとめて返す。"""
        lic = self._license
        is_demo = (lic is None or getattr(lic, "is_demo", True))
        try:
            from chat_engine import credits_load, CREDIT_MAX
            credits, cmax = credits_load(), CREDIT_MAX
        except Exception:
            credits, cmax = 0, 20
        google_linked = False
        try:
            cp = self.config.get("credentials_path", "")
            tok = (Path(cp).parent / "yt_token.pickle") if cp else (Path.home() / "yt_token.pickle")
            google_linked = tok.exists()
        except Exception:
            pass
        return {
            "agreed_terms": bool(self.config.get("agreed_terms")),
            "seen_tutorial": bool(self.config.get("seen_tutorial")),
            "has_gemini": bool(self.config.get("gemini_key")),
            "has_youtube": bool(self.config.get("youtube_key")),
            "has_credentials": bool(self.config.get("credentials_path")),
            "plan": "demo" if is_demo else "pro",
            "credits": credits, "credit_max": cmax,
            "google_linked": google_linked,
            "uid": (getattr(lic, "uid", "") or ""),
            "ui_lang": self.config.get("ui_lang", "ja"),
            "output_language": self.config.get("output_language", "ja"),
            "gemini_model": self.config.get("gemini_model") or _DEFAULT_MODEL,
        }

    def get_youtube_dashboard(self, force=False):
        """統計ダッシュボード用：YouTube Data API v3 のチャンネル/動画統計一式。

        ネットワーク取得は2〜5秒かかるので5分メモリキャッシュ。force=True で無視。
        """
        import time as _t
        cache = getattr(self, "_yt_cache", None)
        if not force and cache and (_t.time() - cache[0] < 300):
            return cache[1]
        try:
            import youtube_stats
            data = youtube_stats.build_dashboard(self.config)
        except Exception as e:
            data = {"error": "api", "message": str(e)}
        self._yt_cache = (_t.time(), data)
        return data

    # ── TomatoAI アカウント（Firebase / Google ログイン） ──
    def account_state(self):
        try:
            import account
            return account.account_state()
        except Exception:
            return {"logged_in": False, "email": "", "uid": ""}

    def account_login(self):
        """システムブラウザで Google ログイン（別スレッドでブロッキング実行）。

        即 {"started": True} を返し、完了/失敗は poll 経由で account_result を JS へ通知する。
        """
        def _do():
            try:
                import account
                r = account.login_via_browser()
                st = account.account_state()
                # 連携したチャンネルを config に反映（統計ダッシュボード等が使う）
                if st.get("logged_in") and st.get("channel_id"):
                    self.config["my_channel_id"] = st["channel_id"]
                    self.config["linked_channel_id"] = st["channel_id"]
                    self.config["linked_channel_title"] = st.get("channel_title", "")
                    save_config(self.config)
                self._js("accountResult", {"ok": bool(r.get("ok")), **st})
            except Exception as e:
                self._js("accountResult", {"ok": False, "message": str(e)})
        threading.Thread(target=_do, daemon=True).start()
        return {"started": True}

    def account_logout(self):
        try:
            import account
            account.logout()
        except Exception:
            pass
        return {"ok": True}

    def cloud_push_settings(self):
        """今の設定をアカウント(Firestore)に保存。サーバーが自動で引き継げるようになる。

        併せてプラン（pro/free）も記録する。クラウドは Pro のみ起動できる。
        """
        try:
            import account
            if not account.is_logged_in():
                return {"ok": False, "message": "ログインしてください"}
            ok = account.push_settings(self.config)
            # ライセンスからプランを判定して記録
            lic = self._license
            is_pro = bool(lic is not None and getattr(lic, "is_pro", False))
            try:
                account.set_plan("pro" if is_pro else "free")
            except Exception:
                pass
            return {"ok": bool(ok), "plan": "pro" if is_pro else "free"}
        except Exception as e:
            return {"ok": False, "message": str(e)}

    def account_token(self):
        """サーバーに貼る「アカウントの鍵」（refresh token）を返す。"""
        try:
            import account
            return {"token": account.get_refresh_token()}
        except Exception:
            return {"token": ""}

    def cloud_server_state(self):
        """あなたのクラウドサーバーの状態（発見用）。ログイン中のみ。"""
        try:
            import account
            if not account.is_logged_in():
                return {"logged_in": False, "url": "", "online": False}
            st = account.get_server_state()
            st["logged_in"] = True
            return st
        except Exception:
            return {"logged_in": False, "url": "", "online": False}

    # ── クラウド（BYO-deploy 設定移送） ──
    def cloud_get_state(self):
        """Cloudタブ用：移送できる設定の有無・保存済みURL・接続状態。"""
        cp = self.config.get("credentials_path", "")
        google_linked = False
        try:
            tok = (Path(cp).parent / "yt_token.pickle") if cp else None
            google_linked = bool(tok and tok.exists())
        except Exception:
            pass
        lic = self._license
        is_demo = (lic is None or getattr(lic, "is_demo", True))
        return {
            "has_gemini": bool(self.config.get("gemini_key")),
            "has_youtube": bool(self.config.get("youtube_key")),
            "has_credentials": bool(cp),
            "google_linked": google_linked,
            "has_discord": bool(self.config.get("discord_bot_token")),
            "channel_id": self.config.get("my_channel_id", ""),
            "cloud_url": self.config.get("cloud_url", ""),
            "plan": "demo" if is_demo else "pro",
        }

    def cloud_make_bundle(self, passphrase="", include_youtube_token=True, include_discord=True):
        """設定を暗号バンドルにして返す。passphrase 空なら安全な合言葉を自動生成。"""
        try:
            import cloud_bundle, secrets
            pw = (passphrase or "").strip() or secrets.token_urlsafe(12)
            bundle = cloud_bundle.make_bundle(
                self.config, pw,
                include_youtube_token=bool(include_youtube_token),
                include_discord=bool(include_discord))
            summ = cloud_bundle.bundle_summary(
                self.config, bool(include_youtube_token), bool(include_discord))
            return {"ok": True, "bundle": bundle, "passphrase": pw,
                    "length": len(bundle), "includes": summ}
        except Exception as e:
            return {"ok": False, "message": str(e)}

    def cloud_launch_setup(self):
        """「今すぐセットアップ」→ 新しいコンソール画面で TUI セットアップを起動する。

        アプリの表示言語をスクリプトに渡し、矢印キー＋Enter で進められる別ウィンドウを開く。
        """
        try:
            import subprocess
            lang = self.config.get("ui_lang", "ja")
            here = Path(__file__).parent
            script = here / "cloud_setup.py"
            if getattr(sys, "frozen", False):
                # 凍結EXE（--windowed）：バンドルした python で起動できないため、
                # 自身を --setup フラグで新コンソール起動する経路にフォールバック。
                exe = sys.executable
                args = [exe, "--setup", "--lang", lang]
            else:
                args = [sys.executable, str(script), "--lang", lang]
            creation = 0
            if os.name == "nt":
                creation = 0x00000010  # CREATE_NEW_CONSOLE
            subprocess.Popen(args, cwd=str(here), creationflags=creation)
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "message": str(e)}

    def cloud_save_url(self, url):
        self.config["cloud_url"] = (url or "").strip()
        save_config(self.config)
        return {"ok": True}

    def cloud_test(self, url):
        """自前サーバーの /healthz を叩いて接続確認する。"""
        url = (url or "").strip().rstrip("/")
        if not url:
            return {"ok": False, "message": "URLが空です"}
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        try:
            import urllib.request, json as _json
            with urllib.request.urlopen(url + "/healthz", timeout=6) as r:
                data = _json.loads(r.read())
            ok = bool(data.get("ok"))
            if ok:
                self.config["cloud_url"] = url
                save_config(self.config)
            return {"ok": ok, "url": url}
        except Exception as e:
            return {"ok": False, "message": str(e), "url": url}

    # ── スケジュール（週間タイムライン・DnD） ──
    def list_schedule(self):
        """未来/過去を問わず pending の予約一覧を UI 用に整形して返す。"""
        try:
            import schedule_engine
            out = []
            for t in schedule_engine.load_tasks():
                if t.get("status") != "pending":
                    continue
                out.append({
                    "id": t.get("id"),
                    "run_at": t.get("run_at", ""),
                    "prompt": self._task_prompt(t),
                    "count": (t.get("params") or {}).get("count", 1),
                    "repeat": t.get("repeat"),
                    "type": t.get("type", "prompt"),
                    "created_at": t.get("created_at", ""),
                })
            out.sort(key=lambda x: x.get("run_at", ""))
            return out
        except Exception:
            return []

    def list_videos(self, limit=60):
        """エディタの素材レール用：これまでに作った動画（新しい順）。"""
        out = []
        try:
            import db, os
            db.init_db()
            rows = db.get_conn().execute(
                "SELECT id, title, output_path, yt_url, posted_at FROM videos "
                "WHERE output_path IS NOT NULL AND output_path <> '' "
                "ORDER BY COALESCE(posted_at,'') DESC LIMIT ?", (int(limit),)).fetchall()
            for r in rows:
                path = r["output_path"] or ""
                if not path or not os.path.exists(path):
                    continue          # 消された動画は出さない
                out.append({"id": r["id"], "title": r["title"] or "動画",
                            "path": path, "yt_url": r["yt_url"] or "",
                            "posted_at": r["posted_at"] or ""})
        except Exception:
            return []
        return out

    # ── 台本（ChatCut風・文字起こしベース編集） ──
    def get_transcript(self, video_id):
        """
        生成済み動画の台本（時刻つき字幕）を返す。字幕は YouTube ソースから取る
        （highlights.fetch_transcript 再利用。ローカル素材にはASRが無いため）。

        エディタが再生するのは「編集後の出力動画」で、ソース字幕とは時間軸がズレる。
        ここで (1)区間DLのオフセット segment_start → (2)編集の TimeMap の順に写像し、
        出力動画上の秒数 o/o2 を付けて返す＝UIは o にシークするだけでよい。
        {"lines":[{"s":元動画秒, "o":出力開始秒, "o2":出力終了秒, "text":…, "gone":AIカット済み}]}
        """
        import re
        video_id = str(video_id or "")
        if not hasattr(self, "_tr_cache"):
            self._tr_cache = {}
        if video_id in self._tr_cache:
            return self._tr_cache[video_id]

        meta = {}
        try:
            import db
            db.init_db()
            row = db.get_conn().execute(
                "SELECT meta_json FROM videos WHERE id=?", (video_id,)).fetchone()
            if row:
                meta = json.loads(row["meta_json"] or "{}")
        except Exception:
            meta = {}
        if not re.match(r"^[A-Za-z0-9_-]{11}$", video_id):
            return {"error": "この動画には台本がありません（YouTube由来の動画のみ）"}

        import highlights
        url = f"https://www.youtube.com/watch?v={video_id}"
        info = highlights.fetch_video_meta(url, lambda m: None)
        raw = highlights.fetch_transcript(info, lambda m: None)
        if not raw:
            return {"error": "この動画の字幕を取得できませんでした"}
        dur = float(info.get("duration") or 0)

        # 自動字幕は細切れ＆繰り返しが多いので、数秒ごとの「行」に統合する。
        # 各行の終わり＝次の行の始まり（#37 のカット区間にそのまま使う）。
        bucket = 6.0
        lines, cur_t, cur_txt = [], None, []
        for t, txt in raw:
            if cur_t is None:
                cur_t, cur_txt = t, [txt]
            elif t - cur_t >= bucket:
                lines.append([cur_t, t, " ".join(cur_txt)])
                cur_t, cur_txt = t, [txt]
            else:
                cur_txt.append(txt)
        if cur_t is not None:
            end = min(cur_t + bucket, dur) if dur else cur_t + bucket
            lines.append([cur_t, max(end, cur_t + 0.5), " ".join(cur_txt)])

        # 区間DLのオフセット（無ければ全体DL＝0）と、編集の時間写像
        seg_s = float(meta.get("segment_start") or 0.0)
        seg_e = meta.get("segment_end")
        seg_e = float(seg_e) if seg_e is not None else (dur or None)
        try:
            tmap, cut_list = self._build_timemap(meta)
        except Exception:
            from editor import TimeMap
            tmap, cut_list = TimeMap(), []

        out_lines = []
        for t0, t1, text in lines:
            if t1 <= seg_s or (seg_e is not None and t0 >= seg_e):
                continue          # 切り抜きに使っていない部分は出さない
            r0 = max(0.0, t0 - seg_s)
            r1 = max(r0, (min(t1, seg_e) if seg_e is not None else t1) - seg_s)
            gone = any(s <= r0 and r1 <= e for s, e in cut_list)   # 生成時にAIがカット済み
            out_lines.append({
                "s": round(t0, 2),
                "o": round(tmap.map(r0), 2),
                "o2": round(tmap.map(r1), 2),
                "text": text,
                "gone": bool(gone),
            })
        res = {"lines": out_lines}
        if out_lines:
            self._tr_cache[video_id] = res
        return res

    @staticmethod
    def _build_timemap(meta):
        """editor.run_edit と同じ順序・同じ規則で TimeMap を再構築する。
        （クリップ上の秒 → 出力動画上の秒。run_edit 側を変えたらここも合わせる）"""
        from editor import TimeMap
        ep = meta.get("edit_params", {}) or {}
        tmap = TimeMap()
        cuts = meta.get("cut_sections") or []
        cut_list = []
        for c in cuts:
            try:
                s, e = float(c["start"]), float(c["end"])
                if e > s:
                    cut_list.append((s, e))
            except Exception:
                pass
        tmap.add_cuts([{"start": s, "end": e} for s, e in cut_list])
        ff_at, ff_end = meta.get("fastforward_at"), meta.get("fastforward_end")
        if ep.get("fastforward_enabled", True) and ff_at is not None and ff_end is not None:
            s, e = tmap.map(ff_at), tmap.map(ff_end)
            tmap.add_speed(s, e, float(ep.get("fastforward_speed", 2.0)))
        rw = meta.get("rewind_at")
        if ep.get("rewind_enabled", True) and rw is not None:
            tmap.add_insert(tmap.map(rw) - 1.5, 1.5)   # apply_rewind の既定 rewind_dur
        fz = meta.get("freeze_at")
        if ep.get("freeze_enabled", True) and fz is not None:
            tmap.add_insert(tmap.map(fz), float(meta.get("freeze_duration", 1.5)))
        return tmap, cut_list

    def get_edit_log(self, video_id):
        """
        生成時にAIが行った編集の記録（編集タブの読み取り専用履歴）。
        meta_json の解析結果から復元する。時刻はソースクリップ基準のMM:SS表記。
        {"items":[{"k":"cut|fastforward|rewind|freeze|zoom|monochrome|flip|mosaic|captions",
                   "t":秒, "label":"MM:SS–MM:SS（理由）"}]}
        """
        meta = {}
        try:
            import db
            db.init_db()
            row = db.get_conn().execute(
                "SELECT meta_json FROM videos WHERE id=?", (str(video_id),)).fetchone()
            if row:
                meta = json.loads(row["meta_json"] or "{}")
        except Exception:
            meta = {}
        if not meta:
            return {"items": [], "code": ""}
        ep = meta.get("edit_params", {}) or {}

        def _fmt(s):
            try:
                s = float(s)
            except (TypeError, ValueError):
                return "?"
            return f"{int(s) // 60:02d}:{int(s) % 60:02d}"

        def _num(v):
            try:
                return float(v)
            except (TypeError, ValueError):
                return None

        items = []
        for c in meta.get("cut_sections") or []:
            s, e = _num(c.get("start")), _num(c.get("end"))
            if s is None or e is None:
                continue
            why = str(c.get("reason") or "").strip()
            items.append({"k": "cut", "t": s,
                          "label": f"{_fmt(s)}–{_fmt(e)}" + (f"（{why}）" if why else "")})
        # 区間エフェクト（enabledフラグは editor.run_edit と同じ規則で尊重）
        for k, at_k, end_k, flag in (
                ("fastforward", "fastforward_at", "fastforward_end", "fastforward_enabled"),
                ("zoom", "zoom_at", "zoom_end", "zoom_enabled"),
                ("monochrome", "monochrome_at", "monochrome_end", "monochrome_enabled"),
                ("flip", "flip_at", "flip_end", "flip_enabled"),
                ("mosaic", "mosaic_at", "mosaic_end", "mosaic_enabled")):
            s, e = _num(meta.get(at_k)), _num(meta.get(end_k))
            if not ep.get(flag, True) or s is None or e is None:
                continue
            extra = ""
            if k == "fastforward":
                extra = f" ×{ep.get('fastforward_speed', 2.0)}"
            elif k == "zoom":
                extra = f" ×{meta.get('zoom_scale', 1.5)}"
            items.append({"k": k, "t": s, "label": f"{_fmt(s)}–{_fmt(e)}{extra}"})
        # 点エフェクト
        s = _num(meta.get("rewind_at"))
        if ep.get("rewind_enabled", True) and s is not None:
            items.append({"k": "rewind", "t": s, "label": _fmt(s)})
        s = _num(meta.get("freeze_at"))
        if ep.get("freeze_enabled", True) and s is not None:
            items.append({"k": "freeze", "t": s,
                          "label": f"{_fmt(s)} · {meta.get('freeze_duration', 1.5)}s"})
        items.sort(key=lambda x: x["t"])
        n_caps = len(meta.get("captions") or [])
        if n_caps:
            items.insert(0, {"k": "captions", "t": -1, "label": f"{n_caps}"})
        # Python編集で生成されたコード（編集タブでクリック表示）
        return {"items": items, "code": str(meta.get("edit_code") or "")}

    def export_cuts(self, video_id, cuts):
        """
        台本編集で消した区間（出力動画上の秒）を出力動画から取り除いて書き出す(#37)。
        出力動画は字幕・演出が焼き込み済みなので、映像を切るだけで全部一緒に消える。
        完了は非同期：完成カード(addVideoCard)＋ exportDone(ok, path) をUIへ送る。
        """
        try:
            import db
            db.init_db()
            row = db.get_conn().execute(
                "SELECT title, output_path FROM videos WHERE id=?",
                (str(video_id),)).fetchone()
        except Exception:
            row = None
        if not row or not row["output_path"] or not os.path.exists(row["output_path"]):
            return {"error": "元の動画ファイルが見つかりません"}
        try:
            ranges = sorted((max(0.0, float(c["s"])), float(c["e"]))
                            for c in (cuts or []) if float(c["e"]) > float(c["s"]))
        except Exception:
            ranges = []
        if not ranges:
            return {"error": "カットする行がありません"}
        src, title = row["output_path"], row["title"] or "動画"

        def _work():
            out = self._run_export(src, ranges)
            if out:
                self._on_ai_video({"path": out, "id": "",
                                   "title": f"{title}（編集版）",
                                   "subtitle": "台本編集のカットを適用しました"})
                self._js("exportDone", True, out)
            else:
                self._js("exportDone", False, "")
                self._js("addError", "書き出しに失敗しました")
        threading.Thread(target=_work, daemon=True).start()
        return {"ok": True}

    @staticmethod
    def _run_export(src, ranges):
        """ranges を取り除いた動画を src の隣に書き出してパスを返す（失敗は None）。"""
        import re, time, subprocess
        from pipeline import _get_ffmpeg_exe
        ff = _get_ffmpeg_exe()
        if not ff:
            return None
        # 元動画の尺（ffprobe は同梱されないので ffmpeg -i のログから読む）
        dur = None
        try:
            r = subprocess.run([ff, "-hide_banner", "-i", src],
                               capture_output=True, timeout=60)
            m = re.search(rb"Duration: (\d+):(\d+):(\d+\.?\d*)", r.stderr)
            if m:
                dur = (int(m.group(1)) * 3600 + int(m.group(2)) * 60
                       + float(m.group(3)))
        except Exception:
            pass
        # 重なるカットをマージ → 「残す区間」を組み立てる
        merged = []
        for s, e in ranges:
            if merged and s <= merged[-1][1] + 0.01:
                merged[-1][1] = max(merged[-1][1], e)
            else:
                merged.append([s, e])
        keeps, prev = [], 0.0
        for s, e in merged:
            if dur is not None:
                s, e = min(s, dur), min(e, dur)
            if s > prev + 0.05:
                keeps.append((prev, s))
            prev = max(prev, e)
        if dur is None or prev < dur - 0.05:
            keeps.append((prev, dur))   # dur 不明なら末尾まで(end 指定なし)
        if not keeps:
            return None
        parts, refs = [], []
        for i, (s, e) in enumerate(keeps):
            end_v = f":end={e:.3f}" if e is not None else ""
            parts.append(f"[0:v]trim=start={s:.3f}{end_v},setpts=PTS-STARTPTS[v{i}]")
            parts.append(f"[0:a]atrim=start={s:.3f}{end_v},asetpts=PTS-STARTPTS[a{i}]")
            refs.append(f"[v{i}][a{i}]")
        fc = (";".join(parts) + ";" + "".join(refs)
              + f"concat=n={len(keeps)}:v=1:a=1[vo][ao]")
        p = Path(src)
        dst = str(p.with_name(f"{p.stem}_cut{int(time.time()) % 100000}.mp4"))
        try:
            r = subprocess.run(
                [ff, "-y", "-hide_banner", "-loglevel", "error", "-i", src,
                 "-filter_complex", fc, "-map", "[vo]", "-map", "[ao]",
                 "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                 "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", dst],
                capture_output=True, timeout=1800)
            if r.returncode == 0 and os.path.exists(dst):
                return dst
        except Exception:
            pass
        return None

    @staticmethod
    def _task_prompt(t) -> str:
        """タスクから実行するプロンプトを取り出す。旧 pipeline_batch は文章に変換。"""
        params = t.get("params") or {}
        p = (params.get("prompt") or "").strip()
        if p:
            return p
        return f"動画を{params.get('count', 1)}本つくって"   # 旧タスク互換

    def add_schedule(self, run_at_iso, prompt="", repeat=None):
        """
        指定時刻に「このプロンプトを送る」予約を登録する。
        スケジュール＝チャットに打つのと同じ文章。何をするかは AI が解釈する。
        """
        try:
            import schedule_engine
            prompt = (prompt or "").strip()
            if not prompt:
                return {"error": "プロンプトが空です"}
            rep = repeat if repeat in ("daily", "weekly") else None
            schedule_engine.add_task("prompt", run_at_iso, {"prompt": prompt}, repeat=rep)
            self._ensure_schedule_watcher()
        except Exception as e:
            return {"error": str(e)}
        return self.list_schedule()

    def update_schedule_prompt(self, task_id, prompt):
        """予約のプロンプトだけ書き換える（時刻・繰り返しは維持）。"""
        try:
            import schedule_engine
            prompt = (prompt or "").strip()
            if not prompt:
                return {"error": "プロンプトが空です"}
            tasks = schedule_engine.load_tasks()
            for t in tasks:
                if t.get("id") == task_id:
                    t.setdefault("params", {})["prompt"] = prompt
                    t["type"] = "prompt"
                    break
            schedule_engine._write(tasks)
        except Exception as e:
            return {"error": str(e)}
        return self.list_schedule()

    def reschedule(self, task_id, run_at_iso):
        """DnD 移動用：該当タスクの run_at だけ差し替える（count/repeat 維持）。"""
        try:
            import schedule_engine
            tasks = schedule_engine.load_tasks()
            for t in tasks:
                if t.get("id") == task_id:
                    t["run_at"] = run_at_iso
                    break
            schedule_engine._write(tasks)
        except Exception as e:
            return {"error": str(e)}
        return self.list_schedule()

    def cancel_schedule(self, task_id):
        try:
            import schedule_engine
            schedule_engine.cancel_task(task_id)
        except Exception as e:
            return {"error": str(e)}
        return self.list_schedule()

    def _ensure_schedule_watcher(self):
        """60秒毎に到来した予約を実行するデーモン（多重起動防止）。"""
        if getattr(self, "_sched_watcher_on", False):
            return
        self._sched_watcher_on = True

        def _watch():
            import time as _t
            while getattr(self, "_sched_watcher_on", False):
                try:
                    import schedule_engine
                    for task in schedule_engine.get_pending():
                        schedule_engine.mark_done(task["id"])
                        # スケジュール＝プロンプト。自分で打ったのと同じ経路に流す
                        prompt = self._task_prompt(task)
                        try:
                            self._js("addUser", prompt)     # ユーザー発話として表示
                            self._js("thinking", True)      # 🍅 THINKING…
                            self.send_message(prompt)       # 会話に記録＋生成（別スレッド）
                        except Exception:
                            pass
                except Exception:
                    pass
                for _ in range(60):
                    if not getattr(self, "_sched_watcher_on", False):
                        return
                    _t.sleep(1)

        threading.Thread(target=_watch, daemon=True).start()

    def get_stats(self):
        """統計モーダル用：プラン・クレジット・生成した動画数。"""
        st = self.get_account_state()
        videos = 0
        try:
            import db
            db.init_db()
            row = db.get_conn().execute("SELECT COUNT(*) AS c FROM videos").fetchone()
            videos = int(row["c"]) if row else 0
        except Exception:
            videos = 0
        return {"plan": st["plan"], "credits": st["credits"],
                "credit_max": st["credit_max"], "videos": videos}

    def get_settings(self):
        """設定モーダルのフォーム初期値（実キー値含む。ローカルのユーザー自身のキー）。"""
        st = self.get_account_state()
        st.update({
            "gemini_key": self.config.get("gemini_key", ""),
            "youtube_key": self.config.get("youtube_key", ""),
            "credentials_path": self.config.get("credentials_path", ""),
            "source_preference": self.config.get("source_preference", "prefer_original"),
        })
        return st

    def set_source_preference(self, value):
        """検索ソースの素性設定（原典優先/原典のみ/こだわらない）を保存する。"""
        if value in ("prefer_original", "original_only", "any"):
            self.config["source_preference"] = value
            save_config(self.config)
            return True
        return False

    def agree_terms(self, ui_lang="ja", output_language="ja"):
        self.config["agreed_terms"] = True
        if ui_lang:
            self.config["ui_lang"] = ui_lang
        if output_language:
            self.config["output_language"] = output_language
        save_config(self.config)
        return True

    def mark_tutorial_seen(self):
        self.config["seen_tutorial"] = True
        save_config(self.config)
        return True

    def get_legal_text(self, kind="terms", lang="ja"):
        """利用規約/プライバシー本文（legal_text.TERMS/PRIVACY。ja/enのみ、他はenフォールバック）。"""
        try:
            import legal_text
            src = legal_text.TERMS if kind == "terms" else legal_text.PRIVACY
            data = src.get(lang) or src.get("en") or src.get("ja") or {}
            return {"updated": data.get("updated", ""),
                    "sections": [list(s) for s in data.get("sections", [])]}
        except Exception as e:
            return {"updated": "", "sections": [], "error": str(e)}

    def save_api_keys(self, gemini="", youtube="", credentials_path="", gemini_model=""):
        """APIキー等を config に保存（self.config を in-place 更新＝engineにも即反映）。"""
        if gemini is not None:
            self.config["gemini_key"] = (gemini or "").strip()
        if youtube is not None:
            self.config["youtube_key"] = (youtube or "").strip()
        if credentials_path:
            self.config["credentials_path"] = credentials_path.strip()
        if gemini_model:
            self.config["gemini_model"] = gemini_model.strip()
        save_config(self.config)
        return True

    def test_api_key(self, kind, value):
        """接続テスト（app.py SetupWizard._test_* を移植）。{ok, message} を返す。"""
        value = (value or "").strip()
        if not value:
            return {"ok": False, "message": "値が空です"}
        try:
            if kind == "gemini":
                from google import genai
                client = genai.Client(api_key=value)
                list(client.models.list())
                return {"ok": True, "message": "接続できました"}
            if kind == "youtube":
                import urllib.request, urllib.parse
                url = "https://www.googleapis.com/youtube/v3/videoCategories?" + urllib.parse.urlencode(
                    {"part": "snippet", "regionCode": "US", "key": value})
                with urllib.request.urlopen(url, timeout=10) as r:
                    ok = (r.status == 200)
                return {"ok": ok, "message": "接続できました" if ok else f"HTTP {r.status}"}
            if kind == "credentials":
                with open(value, encoding="utf-8") as f:
                    data = json.load(f)
                block = data.get("installed") or data.get("web") or {}
                ok = ("client_id" in block and "client_secret" in block)
                return {"ok": ok, "message": "有効なファイルです" if ok else "正しいclient_secrets.jsonではないようです"}
        except Exception as e:
            return {"ok": False, "message": f"接続できませんでした: {e}"}
        return {"ok": False, "message": "不明な種別"}

    def activate_license(self, key):
        lic = self._reload_license()
        if lic is None:
            return {"ok": False, "message": "ライセンス機能を利用できません"}
        key = (key or "").strip()
        try:
            ok, msg = lic.activate(key)
        except Exception as e:
            return {"ok": False, "message": f"認証に失敗しました: {e}"}
        self._reload_license()
        # 認証成功かつログイン済みなら、このアカウント(uid)をProとして worker に紐付ける
        # （operator権威＝クラウドのProゲートを偽装不可にする。worker未デプロイ時は失敗しても無害）
        if ok:
            try:
                import account, license as _lic
                if account.is_logged_in():
                    account.link_pro_to_worker(key, _lic._get_machine_id())
                    account.set_plan("pro")
            except Exception:
                pass
        return {"ok": bool(ok), "message": msg, "plan": self.get_account_state()["plan"]}

    def deactivate_license(self):
        lic = self._license
        try:
            if lic is not None:
                lic.deactivate()
        except Exception as e:
            return {"ok": False, "message": f"{e}"}
        self._reload_license()
        return {"ok": True, "plan": self.get_account_state()["plan"]}

    def apply_promo(self, code):
        """プロモ/クレジットコードを Worker /credit/redeem で換金（app.py _redeem_credit_code 流用）。"""
        code = (code or "").strip().upper()
        if not code:
            return {"status": "empty", "message": "コードを入力してください"}
        import urllib.request
        _WORKER = "https://tomato-shorts-license.clipflowlicense.workers.dev"
        try:
            body = json.dumps({"code": code}).encode()
            req = urllib.request.Request(
                f"{_WORKER}/credit/redeem", data=body,
                headers={"Content-Type": "application/json", "User-Agent": "TomatoClip/1.0"},
                method="POST")
            with urllib.request.urlopen(req, timeout=8) as r:
                res = json.loads(r.read())
        except Exception as e:
            return {"status": "error", "message": f"通信に失敗しました: {e}"}
        if res.get("status") == "ok":
            total = None
            try:
                from chat_engine import credits_add
                total = credits_add(int(res.get("credits", 0)))
            except Exception:
                pass
            return {"status": "ok", "credits": int(res.get("credits", 0)), "total": total}
        return {"status": res.get("status") or "error"}

    def open_file(self, path):
        try:
            folder = str(Path(path).parent)
            os.startfile(folder)  # Windows
        except Exception:
            pass
        return True

    def post_video(self, path):
        # Phase 1 では投稿は未実装（次フェーズ）。案内だけ返す。
        self._js("addAiText", "YouTube への投稿は次のアップデートで対応予定です（動画は保存済みです）。")
        return True


def main():
    # 凍結EXE でクラウドセットアップTUIを起動する経路（--setup）
    if "--setup" in sys.argv:
        try:
            import cloud_setup
            cloud_setup.main()
        except Exception as e:
            print("setup error:", e)
            try:
                input("Press Enter to close...")
            except Exception:
                pass
        return
    # 旧ブランド(Tomato Shorts)の設定/ライセンスを新パスへ移行（ライセンス読込前に）
    try:
        from brand_migrate import migrate_legacy_paths
        migrate_legacy_paths(print)
    except Exception:
        pass
    _setup_media_env()
    import webview
    api = Api()
    win = webview.create_window(
        "Tomato Clip",
        url=str(resource_path("webui", "index.html")),
        js_api=api,
        width=1180, height=800, min_size=(900, 620),
    )
    # 注意: api.window = win はしない。
    # js_api公開時に pywebview が window.native を無限走査して RecursionError になるため。
    # UI更新は _js() のキュー方式（JSが poll() で取得）で行い、window参照は不要。

    # 起動後に自動でメッセージを送って橋渡し＋Gemini＋描画を検証する（開発補助）
    #   --selftest         … 既定の挨拶メッセージ
    #   --send "<message>" … 任意メッセージ（生成E2E等に使用）
    send_msg = None
    if "--selftest" in sys.argv:
        send_msg = "こんにちは！あなたは何ができますか？簡潔に教えて"
    if "--send" in sys.argv:
        _i = sys.argv.index("--send")
        if _i + 1 < len(sys.argv):
            send_msg = sys.argv[_i + 1]
    if send_msg:
        import time as _t
        def _st(_m=send_msg):
            _t.sleep(5)
            api._js("addUser", _m)
            api.send_message(_m)   # 実UIと同じ経路（会話記録＋自動タイトル生成を通す）
        threading.Thread(target=_st, daemon=True).start()

    # --openui <fn> … 起動後にJSの chatUI.<fn>() を呼ぶ（設定/オンボ画面の実機検証用）
    if "--openui" in sys.argv:
        import time as _t2
        _j = sys.argv.index("--openui")
        _fn = sys.argv[_j + 1] if _j + 1 < len(sys.argv) else "openSettings"
        def _ou(_f=_fn):
            _t2.sleep(6)
            api._js(_f)
        threading.Thread(target=_ou, daemon=True).start()

    webview.start(debug=("--debug" in sys.argv))


if __name__ == "__main__":
    main()
