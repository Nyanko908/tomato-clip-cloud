"""
key_rotator.py
API キーローリング管理
  - 複数キーを登録してラウンドロビンで使い回す
  - クールタイム = 20 ÷ キー数 秒
  - レート制限エラー時は自動で次のキーへ
  - GUI から追加・削除可能
"""

import time, threading, json
from pathlib import Path
from typing import Callable
from i18n import T

LOG_CB    = Callable[[str], None]
KEYS_PATH = Path.home() / ".tomato_clip" / "api_keys.json"


class KeyRotator:
    """
    使い方:
        rotator = KeyRotator("gemini")
        rotator.add_key("AIza...")
        rotator.add_key("AIzb...")
        key = rotator.next()   # クールタイム付きで次のキーを返す
    """

    def __init__(self, service: str, log: LOG_CB = print):
        self.service  = service   # "gemini" / "youtube" / "pexels"
        self.log      = log
        self._lock    = threading.Lock()
        self._keys    = []        # [{"key": str, "last_used": float, "errors": int}]
        self._idx     = 0
        self._load()

    # ── キー管理
    def add_key(self, key: str):
        with self._lock:
            if not key or any(k["key"] == key for k in self._keys):
                return
            self._keys.append({"key": key, "last_used": 0.0, "errors": 0})
            self._save()
            self.log(f"🔑 [{self.service}] キー追加 ({len(self._keys)}個目)")

    def remove_key(self, key: str):
        with self._lock:
            self._keys = [k for k in self._keys if k["key"] != key]
            self._save()

    def get_keys(self) -> list[str]:
        return [k["key"] for k in self._keys]

    def count(self) -> int:
        return len(self._keys)

    @property
    def cooltime(self) -> float:
        """クールタイム = 20 ÷ キー数（最低0.5秒）"""
        n = max(len(self._keys), 1)
        return max(20.0 / n, 0.5)

    # ── 次のキーを取得（クールタイム付き）
    def next(self) -> str | None:
        with self._lock:
            if not self._keys:
                return None

            n = len(self._keys)
            # クールタイムが過ぎているキーを探す
            now = time.time()
            for attempt in range(n):
                idx  = (self._idx + attempt) % n
                rec  = self._keys[idx]
                wait = self.cooltime - (now - rec["last_used"])
                if wait <= 0:
                    self._idx = (idx + 1) % n
                    rec["last_used"] = now
                    key_masked = rec["key"][:8] + "..."
                    self.log(f"🔑 [{self.service}] キー#{idx+1} 使用 (CT:{self.cooltime:.1f}s)")
                    return rec["key"]

            # 全キーがクールタイム中 → 最も早く解放されるキーを待つ
            wait_times = [
                (self.cooltime - (now - k["last_used"]), i)
                for i, k in enumerate(self._keys)
            ]
            min_wait, min_idx = min(wait_times)
            self.log(f"⏱ [{self.service}] 全キーCT中 → {min_wait:.1f}秒待機...")
            time.sleep(min_wait + 0.1)
            rec = self._keys[min_idx]
            rec["last_used"] = time.time()
            self._idx = (min_idx + 1) % n
            return rec["key"]

    # ── エラー時に次のキーへ
    def report_error(self, key: str):
        with self._lock:
            for rec in self._keys:
                if rec["key"] == key:
                    rec["errors"] += 1
                    rec["last_used"] = time.time() + 60  # 1分ペナルティ
                    self.log(f"⚠️ [{self.service}] キーエラー → 1分スキップ (errors:{rec['errors']})")
                    break

    def ban_key(self, key: str, seconds: float = 86400):
        """日次クォータ超過キーを指定秒数（デフォルト24時間）使用禁止にする"""
        with self._lock:
            for rec in self._keys:
                if rec["key"] == key:
                    rec["errors"] += 1
                    rec["last_used"] = time.time() + seconds - self.cooltime
                    h = int(seconds / 3600)
                    self.log(f"🚫 [{self.service}] キー#{self._keys.index(rec)+1} を{h}時間BAN (日次クォータ超過)")
                    break

    # ── 保存・読み込み
    def _save(self):
        KEYS_PATH.parent.mkdir(parents=True, exist_ok=True)
        data = json.loads(KEYS_PATH.read_text()) if KEYS_PATH.exists() else {}
        data[self.service] = [{"key": k["key"], "errors": k["errors"]}
                               for k in self._keys]
        KEYS_PATH.write_text(json.dumps(data, indent=2))

    def _load(self):
        if not KEYS_PATH.exists():
            return
        try:
            data = json.loads(KEYS_PATH.read_text())
            for rec in data.get(self.service, []):
                self._keys.append({
                    "key":       rec["key"],
                    "last_used": 0.0,
                    "errors":    rec.get("errors", 0)
                })
        except Exception:
            pass


# ════════════════════════════════════════════════════════
#  グローバルローテーター（pipeline から使う）
# ════════════════════════════════════════════════════════
_rotators: dict[str, KeyRotator] = {}

def get_rotator(service: str, log: LOG_CB = print) -> KeyRotator:
    if service not in _rotators:
        _rotators[service] = KeyRotator(service, log)
    return _rotators[service]

def setup_rotators(config: dict, log: LOG_CB):
    """
    config から複数キーを読み込んでローテーターに登録。
    config キー例:
      "gemini_keys":  ["AIza1...", "AIza2..."]
      "youtube_keys": ["AIza3..."]
      "gemini_key":   "AIza1..."  ← 後方互換（1つ）
    """
    for service, single_key, plural_key in [
        ("gemini",  "gemini_key",  "gemini_keys"),
        ("youtube", "youtube_key", "youtube_keys"),
        ("pexels",  "pexels_key",  "pexels_keys"),
    ]:
        rot = get_rotator(service, log)
        # 複数キー（リスト形式）
        for k in config.get(plural_key, []):
            if k:
                rot.add_key(k)
        # 単一キー（後方互換）
        single = config.get(single_key, "")
        if single:
            rot.add_key(single)
        if rot.count() > 0:
            log(f"🔑 [{service}] {rot.count()}個のキー登録 / CT:{rot.cooltime:.1f}s")


# ════════════════════════════════════════════════════════
#  GUI タブ（app.py から呼ぶ）
# ════════════════════════════════════════════════════════
def build_keyrotator_tab(parent, config: dict, on_change: Callable = None):
    """APIキーローリング設定UIを構築"""
    import tkinter as tk
    from tkinter import ttk

    # アプリ本体のテーマ色を使用（ライト/ダーク対応）
    try:
        import app as _app
        BG, PANEL, PANEL2 = _app.BG, _app.PANEL, _app.PANEL2
        ACCENT, TEXT, MUTED = _app.ACCENT, _app.TEXT, _app.MUTED
        ERROR, GREEN, WARN  = _app.ERROR, _app.SUCCESS, _app.WARN
    except Exception:
        BG     = "#0a0a12"
        PANEL  = "#12121e"
        PANEL2 = "#1a1a2e"
        ACCENT = "#6c63ff"
        TEXT   = "#e0e0f0"
        MUTED  = "#55556a"
        ERROR  = "#ff5566"
        GREEN  = "#4cffb0"
        WARN   = "#ffcc44"
    FN     = ("Segoe UI", 10)
    FNB    = ("Segoe UI", 10, "bold")
    MONO   = ("Consolas", 10)

    # config に保存済みのキーをローテーターへロード（未ロードだと一覧が空に見える）
    try:
        setup_rotators(config, lambda m: None)
    except Exception:
        pass

    SERVICES = [
        ("gemini",  "🤖 Gemini",  "gemini_keys"),
        ("youtube", "📺 YouTube", "youtube_keys"),
        ("pexels",  "🎥 Pexels",  "pexels_keys"),
    ]

    nb = ttk.Notebook(parent)
    nb.pack(fill="both", expand=True, padx=12, pady=8)

    for service, label, cfg_key in SERVICES:
        f = tk.Frame(nb, bg=BG, padx=16, pady=12)
        nb.add(f, text=label)

        rot = get_rotator(service)

        # ── ステータスカード
        card = tk.Frame(f, bg=PANEL, padx=14, pady=10)
        card.pack(fill="x", pady=(0, 10))

        info_var = tk.StringVar()
        def _refresh_info(r=rot, v=info_var):
            n  = r.count()
            ct = r.cooltime
            v.set(f"登録キー数: {n}個  /  クールタイム: 20÷{n} = {ct:.1f}秒")

        tk.Label(card, textvariable=info_var, bg=PANEL,
                 fg=GREEN, font=FNB).pack(anchor="w")
        _refresh_info()

        # ── キー追加
        add_frame = tk.Frame(f, bg=BG)
        add_frame.pack(fill="x", pady=(0, 8))
        new_key_var = tk.StringVar()
        ent = tk.Entry(add_frame, textvariable=new_key_var,
                       bg=PANEL2, fg=TEXT, insertbackground=TEXT,
                       relief="flat", font=MONO, show="•", width=44)
        ent.pack(side="left", ipady=6, fill="x", expand=True, padx=(0, 6))

        # 表示/非表示
        def _toggle_show(e=ent):
            e.configure(show="" if e.cget("show") else "•")
        tk.Button(add_frame, text="👁", command=_toggle_show,
                  bg=PANEL2, fg=MUTED, relief="flat",
                  font=FN, padx=6).pack(side="left", padx=(0, 4))

        add_btn = tk.Button(add_frame, text=T("+ 追加"),
                            bg=ACCENT, fg="white", relief="flat",
                            font=FNB, padx=14)
        add_btn.pack(side="left")

        # ── キー一覧
        tk.Label(f, text=T("登録済みキー"), bg=BG, fg=MUTED, font=FN).pack(anchor="w", pady=(4, 2))
        cols = ("num", "key_masked", "errors", "cooltime")
        tree = ttk.Treeview(f, columns=cols, show="headings", height=6)
        tree.heading("num",        text="#")
        tree.heading("key_masked", text=T("キー（マスク済み）"))
        tree.heading("errors",     text=T("エラー数"))
        tree.heading("cooltime",   text=T("CT (秒)"))
        tree.column("num",        width=30,  anchor="center")
        tree.column("key_masked", width=260)
        tree.column("errors",     width=70,  anchor="center")
        tree.column("cooltime",   width=80,  anchor="center")
        sb = ttk.Scrollbar(f, command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        tree.pack(fill="x")

        def _refresh_tree(t, r=rot, rfi=_refresh_info):
            if t is None:
                return
            for row in t.get_children():
                t.delete(row)
            for i, rec in enumerate(r._keys):
                k  = rec["key"]
                masked = k[:6] + "•" * (len(k) - 10) + k[-4:] if len(k) > 10 else "•" * len(k)
                t.insert("", "end", values=(
                    f"#{i+1}", masked,
                    rec["errors"],
                    f"{r.cooltime:.1f}s"
                ))
            rfi()

        def _add(r=rot, v=new_key_var, rfi=_refresh_info, ck=cfg_key, t=tree):
            key = v.get().strip()
            if not key:
                return
            r.add_key(key)
            keys_list = config.get(ck, [])
            if key not in keys_list:
                keys_list.append(key)
                config[ck] = keys_list
            v.set("")
            _refresh_tree(t, r, rfi)
            if on_change:
                on_change()

        add_btn.config(command=_add)
        ent.bind("<Return>", lambda e, fn=_add: fn())

        def _delete(r=rot, t=tree, ck=cfg_key, rfi=_refresh_info):
            sel = t.selection()
            if not sel:
                return
            idx = int(t.item(sel[0])["values"][0].replace("#","")) - 1
            if 0 <= idx < len(r._keys):
                key = r._keys[idx]["key"]
                r.remove_key(key)
                keys_list = config.get(ck, [])
                if key in keys_list:
                    keys_list.remove(key)
                _refresh_tree(t, r, rfi)

        tk.Button(f, text=T("🗑 選択を削除"), command=_delete,
                  bg=PANEL2, fg=ERROR, relief="flat",
                  font=FN, padx=10, pady=4).pack(anchor="e", pady=4)

        # ── クールタイム説明
        tk.Label(f,
                 text="💡 クールタイム = 20 ÷ キー数\n"
                      "   例: 4個 → 5秒ごとに切り替え / 1個 → 20秒",
                 bg=BG, fg=MUTED, font=FN, justify="left").pack(anchor="w", pady=(6, 0))

        _refresh_tree(tree, rot)
