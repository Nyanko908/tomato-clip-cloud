"""
assets_manager.py
素材集管理モジュール
  - BGM（mp3/wav）
  - 画像（ドクロ・透過PNG・オーバーレイ）
  - フォント（ttf/otf）
  のアップロード・プレビュー・選択・削除
"""

import shutil, base64, json
from pathlib import Path
from typing import Callable

ASSETS_DIR = Path.home() / ".tomato_clip" / "assets"
CATEGORIES = {
    "bgm":    {"label": "🎵 BGM",    "exts": [".mp3", ".wav", ".m4a"], "dir": "bgm"},
    "image":  {"label": "🖼 画像",   "exts": [".png", ".jpg", ".jpeg", ".gif"], "dir": "images"},
    "font":   {"label": "🔤 フォント","exts": [".ttf", ".otf"], "dir": "fonts"},
}


def ensure_dirs():
    for cat in CATEGORIES.values():
        (ASSETS_DIR / cat["dir"]).mkdir(parents=True, exist_ok=True)


def import_from_youtube(url: str, log=print) -> dict | None:
    """
    YouTube URL から音声をダウンロードしてBGMとして登録。
    yt-dlp を使用。
    """
    ensure_dirs()
    try:
        import yt_dlp
        log(f"⬇️  YouTube BGM ダウンロード中: {url}")
        out_tmpl = str(ASSETS_DIR / "bgm" / "%(title)s.%(ext)s")
        opts = {
            "format":            "bestaudio/best",
            "outtmpl":           out_tmpl,
            "postprocessors":    [{
                "key":            "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }],
            "quiet":      True,
            "no_warnings": True,
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get("title", "bgm")

        # ダウンロードされたファイルを探す
        mp3 = next((ASSETS_DIR / "bgm").glob(f"*.mp3"), None)
        if not mp3:
            log("⚠️ ダウンロードファイルが見つかりません")
            return None

        rec = {
            "id":       mp3.stem[:32],
            "name":     mp3.name,
            "path":     str(mp3),
            "category": "bgm",
            "size_kb":  round(mp3.stat().st_size / 1024, 1),
        }
        _save_index(rec)
        log(f"✅ BGM登録: {mp3.name}")
        return rec
    except ImportError:
        log("❌ yt-dlp が必要です: pip install yt-dlp")
        return None
    except Exception as e:
        log(f"❌ YouTube DL失敗: {e}")
        return None


def import_asset(src_path: str, category: str) -> dict:
    """
    ファイルをアセットフォルダにコピーして登録。
    戻り値: {"id": ..., "name": ..., "path": ..., "category": ...}
    """
    ensure_dirs()
    src  = Path(src_path)
    cat  = CATEGORIES.get(category)
    if not cat:
        raise ValueError(f"不明なカテゴリ: {category}")
    if src.suffix.lower() not in cat["exts"]:
        raise ValueError(f"{category} は {cat['exts']} のみ対応")

    dst = ASSETS_DIR / cat["dir"] / src.name
    # 同名ファイルが既にある場合は番号を付ける
    counter = 1
    while dst.exists():
        dst = ASSETS_DIR / cat["dir"] / f"{src.stem}_{counter}{src.suffix}"
        counter += 1
    shutil.copy2(str(src), str(dst))

    record = {
        "id":       dst.stem,
        "name":     src.name,
        "path":     str(dst),
        "category": category,
        "size_kb":  round(dst.stat().st_size / 1024, 1),
    }
    _save_index(record)
    return record


def get_assets(category: str = None) -> list[dict]:
    """アセット一覧取得"""
    index = _load_index()
    if category:
        return [a for a in index if a["category"] == category]
    return index


def delete_asset(asset_id: str) -> bool:
    """アセット削除"""
    index = _load_index()
    for a in index:
        if a["id"] == asset_id:
            try:
                Path(a["path"]).unlink()
            except Exception:
                pass
            index.remove(a)
            _write_index(index)
            return True
    return False


def get_asset_path(asset_id: str) -> str | None:
    for a in _load_index():
        if a["id"] == asset_id:
            return a["path"] if Path(a["path"]).exists() else None
    return None


def get_preview_b64(asset_id: str) -> str:
    """画像アセットの base64 プレビュー"""
    path = get_asset_path(asset_id)
    if not path:
        return ""
    try:
        from PIL import Image
        from io import BytesIO
        img = Image.open(path).convert("RGBA")
        img.thumbnail((120, 120))
        buf = BytesIO()
        img.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return ""


# ── インデックス管理
INDEX_PATH = ASSETS_DIR / "index.json"

def _load_index() -> list:
    if INDEX_PATH.exists():
        try:
            return json.loads(INDEX_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []

def _save_index(record: dict):
    index = _load_index()
    # 同パスが既にある場合は上書き
    index = [a for a in index if a["path"] != record["path"]]
    index.append(record)
    _write_index(index)

def _write_index(index: list):
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    INDEX_PATH.write_text(
        json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")


# ════════════════════════════════════════════════════════
#  GUI タブ（app.py から呼ばれる）
# ════════════════════════════════════════════════════════
def build_assets_tab(parent, config: dict, on_change: Callable = None):
    """
    アセット管理タブのUIを構築して parent に pack する。
    app.py の _tab_assets から呼ぶ。
    """
    import tkinter as tk
    from tkinter import ttk, filedialog

    BG     = "#0a0a12"
    PANEL  = "#12121e"
    PANEL2 = "#1a1a2e"
    ACCENT = "#6c63ff"
    TEXT   = "#e0e0f0"
    MUTED  = "#55556a"
    ERROR  = "#ff5566"
    GREEN  = "#4cffb0"
    FN     = ("Segoe UI", 10)
    FNB    = ("Segoe UI", 10, "bold")

    ensure_dirs()

    # カテゴリタブ
    nb = ttk.Notebook(parent)
    nb.pack(fill="both", expand=True, padx=12, pady=8)

    frames = {}
    trees  = {}

    for cat_id, cat_info in CATEGORIES.items():
        f = tk.Frame(nb, bg=BG, padx=12, pady=10)
        nb.add(f, text=cat_info["label"])
        frames[cat_id] = f

        # ── ツールバー
        toolbar = tk.Frame(f, bg=BG)
        toolbar.pack(fill="x", pady=(0, 8))

        def _upload(cid=cat_id, ci=cat_info):
            exts   = [(f"{ci['label']}ファイル", " ".join(f"*{e}" for e in ci["exts"])),
                      ("すべてのファイル", "*.*")]
            paths  = filedialog.askopenfilenames(
                filetypes=exts,
                title=f"{ci['label']} をアップロード（複数選択OK）"
            )
            if not paths:
                return
            ok, ng = 0, []
            for p in paths:
                try:
                    import_asset(p, cid)
                    ok += 1
                except Exception as e:
                    ng.append(f"{Path(p).name}: {e}")
            _refresh(cid)
            if on_change:
                on_change({"category": cid})
            msg = f"✅ {ok} 件追加"
            if ng:
                msg += f"\n⚠️ 失敗 {len(ng)} 件:\n" + "\n".join(ng)
            tk.messagebox.showinfo("アップロード完了", msg)

        btn_row_top = tk.Frame(toolbar, bg=BG)
        btn_row_top.pack(side="left")
        # YouTube URL 入力欄
        yt_frame = tk.Frame(f, bg=BG); yt_frame.pack(fill="x", pady=(0,6))
        tk.Label(yt_frame, text="🎵 YouTube URL から追加:", bg=BG, fg=MUTED,
                 font=("Segoe UI",10)).pack(side="left")
        yt_url_var = tk.StringVar()
        tk.Entry(yt_frame, textvariable=yt_url_var, bg=PANEL2, fg=TEXT,
                 insertbackground=TEXT, relief="flat",
                 font=("Consolas",9), width=38).pack(side="left", ipady=5, padx=4)

        def _yt_import(cid=cat_id, yuv=yt_url_var):
            if cid != "bgm":
                return
            url = yuv.get().strip()
            if not url:
                return
            import threading
            def _run():
                rec = import_from_youtube(url)
                if rec:
                    _refresh(cid)
                    if on_change: on_change(rec)
            threading.Thread(target=_run, daemon=True).start()
            yuv.set("")

        tk.Button(yt_frame, text="⬇ DL", command=_yt_import,
                  bg="#6c63ff", fg="white", relief="flat",
                  font=("Segoe UI",10,"bold"), padx=10).pack(side="left")

        tk.Button(btn_row_top, text="+ ファイルを追加（複数OK）", command=_upload,
                  bg=ACCENT, fg="white", relief="flat",
                  font=FNB, padx=14, pady=5).pack(side="left")
        # ファイル数バッジ
        count_var = tk.StringVar(value="0 件")
        tk.Label(btn_row_top, textvariable=count_var,
                 bg=BG, fg=MUTED, font=FN).pack(side="left", padx=8)

        # 使用中バッジ
        tk.Label(toolbar, text=f"保存先: {ASSETS_DIR / cat_info['dir']}",
                 bg=BG, fg=MUTED, font=("Segoe UI", 8)).pack(side="right")

        # ── テーブル
        cols = ("name", "size_kb")
        tree = ttk.Treeview(f, columns=cols, show="headings", height=12)
        tree.heading("name",    text="ファイル名")
        tree.heading("size_kb", text="サイズ")
        tree.column("name",    width=320)
        tree.column("size_kb", width=80, anchor="e")
        sb = ttk.Scrollbar(f, command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        tree.pack(fill="both", expand=True)
        trees[cat_id] = tree

        # ── ボタン行
        btn_row = tk.Frame(f, bg=BG)
        btn_row.pack(fill="x", pady=(6, 0))

        def _delete(cid=cat_id):
            sel = trees[cid].selection()
            if not sel:
                return
            aid = trees[cid].item(sel[0])["values"][0]
            # name列からidを逆引き
            assets = get_assets(cid)
            for a in assets:
                if a["name"] == aid:
                    delete_asset(a["id"])
                    _refresh(cid)
                    break

        def _set_active(cid=cat_id):
            """選択した素材をアクティブに設定"""
            sel = trees[cid].selection()
            if not sel:
                return
            name = trees[cid].item(sel[0])["values"][0]
            assets = get_assets(cid)
            for a in assets:
                if a["name"] == name:
                    if cid == "bgm":
                        config["phonk_path"] = a["path"]
                    elif cid == "image":
                        config["skull_path"] = a["path"]
                    elif cid == "font":
                        import editor
                        editor.FONT_PATH = a["path"]
                    if on_change:
                        on_change(a)
                    tk.messagebox.showinfo("設定完了", f"✅ {a['name']} をアクティブに設定しました")
                    break

        tk.Button(btn_row, text="✓ アクティブに設定", command=_set_active,
                  bg=PANEL2, fg=GREEN, relief="flat", font=FN, padx=10).pack(side="left", padx=(0,4))
        tk.Button(btn_row, text="🗑 削除", command=_delete,
                  bg=PANEL2, fg=ERROR, relief="flat", font=FN, padx=10).pack(side="left")

        # 初期ロード
        def _refresh(cid=cat_id):
            for row in trees[cid].get_children():
                trees[cid].delete(row)
            visible = []
            for a in get_assets(cid):
                if Path(a["path"]).exists():
                    trees[cid].insert("", "end", values=(a["name"], f"{a['size_kb']} KB"))
                    visible.append(a)
            try:
                count_var.set(f"{len(visible)} 件")
            except Exception:
                pass

        _refresh(cat_id)
