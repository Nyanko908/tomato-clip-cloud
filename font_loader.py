"""
font_loader.py
GitHub Releases から TTF/OTF を直接ダウンロードして Windows GDI に登録する。
"""

import re
import io
import zipfile
import urllib.request
from pathlib import Path

FONTS_DIR = Path.home() / ".tomato_clip" / "fonts"
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"

# (tkinterファミリー名, ダウンロードURL, zip内のパス or None, 保存ファイル名)
_FONT_TARGETS: list[tuple] = [
    (
        "Inter",
        "https://github.com/rsms/inter/releases/download/v4.0/Inter-4.0.zip",
        "extras/ttf/Inter-Regular.ttf",
        "Inter-Regular.ttf",
    ),
    (
        "Noto Sans JP",
        "https://github.com/notofonts/noto-cjk/releases/download/Sans2.004/16_NotoSansJP.zip",
        "NotoSansJP-Regular.otf",
        "NotoSansJP-Regular.otf",
    ),
]

# TTF マジックバイト（先頭 4 バイト）
_VALID_MAGIC = {
    b"\x00\x01\x00\x00",  # TTF
    b"OTTO",              # OTF/CFF
    b"true",              # Apple TrueType
    b"typ1",              # PostScript
}


def _is_valid_font(path: Path) -> bool:
    try:
        return path.read_bytes()[:4] in _VALID_MAGIC
    except Exception:
        return False


def _download_bytes(url: str) -> bytes | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.read()
    except Exception:
        return None


def _extract_from_zip(data: bytes, inner_path: str) -> bytes | None:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            # 完全一致 or 末尾一致で検索
            names = zf.namelist()
            target = next(
                (n for n in names if n == inner_path or n.endswith("/" + inner_path)),
                None,
            )
            if target:
                return zf.read(target)
    except Exception:
        pass
    return None


def _register_win(path: Path) -> bool:
    try:
        from ctypes import windll
        n = windll.gdi32.AddFontResourceW(str(path))
        if n > 0:
            windll.user32.SendMessageW(0xFFFF, 0x001D, 0, 0)
            return True
    except Exception:
        pass
    return False


def preload_fonts(log=None) -> list[str]:
    """
    フォントをダウンロード・登録して利用可能なファミリー名リストを返す。
    tkinter ウィンドウ作成前に呼ぶこと（main.py から呼ぶ）。
    """
    FONTS_DIR.mkdir(parents=True, exist_ok=True)
    loaded: list[str] = []

    for family, url, inner_path, filename in _FONT_TARGETS:
        dest = FONTS_DIR / filename

        # キャッシュが壊れていたら削除
        if dest.exists() and not _is_valid_font(dest):
            dest.unlink(missing_ok=True)

        if not dest.exists():
            if log:
                log(f"🔤 フォントDL中: {family} ...")
            raw = _download_bytes(url)
            if not raw:
                if log:
                    log(f"⚠️ フォントDL失敗: {family}（スキップ）")
                continue

            if inner_path:
                font_data = _extract_from_zip(raw, inner_path)
            else:
                font_data = raw

            if not font_data:
                if log:
                    log(f"⚠️ フォントファイル抽出失敗: {family}（スキップ）")
                continue

            dest.write_bytes(font_data)

        if not _is_valid_font(dest):
            dest.unlink(missing_ok=True)
            if log:
                log(f"⚠️ 不正フォントファイル: {family}（スキップ）")
            continue

        if _register_win(dest):
            loaded.append(family)
            if log:
                log(f"✅ フォント登録: {family}")
        else:
            if log:
                log(f"⚠️ フォント登録失敗: {family}")

    return loaded
