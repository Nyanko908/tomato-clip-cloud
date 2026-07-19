# -*- coding: utf-8 -*-
"""
tc_db.py — TC_DB 素材ストア（Web検索で素材を取得し、ライセンスを必ず記録する）。

買い切り商品でユーザーの動画に他人の素材が焼き込まれるため、出所不明の素材は
絶対に扱わない。方針：

  - 素材源は Wikimedia Commons API（キー不要・ライセンスが機械可読）。
    画像も音声（効果音等）もここから探せる。
  - 保存できるのは商用利用可のライセンスのみ：CC0 / パブリックドメイン /
    CC BY / CC BY-SA。NC（非商用）・ND（改変不可）・不明は拒否する。
  - 全素材に meta.json（出所URL・作者・ライセンス・クレジット文・取得日時・
    検索語）を必ず添える。クレジットが必要な素材が動画で使われたら、
    呼び出し側が analysis["sources"]（引用元表示）へ credit を積む。

保存場所: ~/TomatoClip/TC_DB/assets/<slug>/（プラグインフォルダに集約）
"""
from __future__ import annotations

import json
import re
import time
import hashlib
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable, Optional

LOG_CB = Callable[[str], None]

ASSETS_DIR = Path.home() / "TomatoClip" / "TC_DB" / "assets"

_UA = "TomatoClip/1.0 (asset fetcher; contact: support@tomatoclip)"
_COMMONS_API = "https://commons.wikimedia.org/w/api.php"
_MAX_BYTES = 30 * 1024 * 1024   # 30MB。ショート素材にこれ以上は不要


# ════════════════════════════════════════════════════════
#  ライセンス判定（保守的に。迷ったら拒否）
# ════════════════════════════════════════════════════════
def classify_license(short_name: str) -> Optional[dict]:
    """
    商用利用可なら {"ok": True, "attribution": bool} を返す。不可・不明は None。
    NC(非商用)/ND(改変不可)は動画編集素材として使えないので拒否。
    GFDL等のコピーレフト系は表示義務が重いので v1 では扱わない。
    """
    s = (short_name or "").strip().lower()
    if not s:
        return None
    if "nc" in s or "nd" in s:
        return None
    if s in ("cc0", "cc-0", "cc zero") or "public domain" in s or s in ("pd", "pdm"):
        return {"ok": True, "attribution": False}
    if s.startswith(("cc by", "cc-by", "attribution")):
        return {"ok": True, "attribution": True}
    return None


def _strip_html(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s or "").strip()


def _slug(text: str) -> str:
    base = re.sub(r"[^A-Za-z0-9]+", "-", (text or "")).strip("-").lower()[:40]
    h = hashlib.sha1((text or str(time.time())).encode("utf-8")).hexdigest()[:6]
    return f"{base}-{h}" if base else f"asset-{h}"


# ════════════════════════════════════════════════════════
#  検索（Wikimedia Commons）
# ════════════════════════════════════════════════════════
def search_commons(query: str, kind: str = "image", limit: int = 8,
                   log: LOG_CB = print) -> list[dict]:
    """
    候補を返す: [{title, page_url, source_url, mime, size, author, license,
                 license_ok, attribution}]
    kind: "image" | "audio"
    """
    ftype = "audio" if kind == "audio" else "bitmap"
    params = {
        "action": "query", "format": "json",
        "generator": "search",
        "gsrsearch": f"{query} filetype:{ftype}",
        "gsrnamespace": 6, "gsrlimit": limit,
        "prop": "imageinfo",
        "iiprop": "url|mime|size|extmetadata",
        "iiextmetadatafilter": "LicenseShortName|Artist|UsageTerms|AttributionRequired",
    }
    url = _COMMONS_API + "?" + urllib.parse.urlencode(params)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read().decode("utf-8", "ignore"))
    except Exception as e:
        log(f"⚠️ 素材検索に失敗: {str(e)[:80]}")
        return []

    out = []
    for page in (data.get("query", {}).get("pages") or {}).values():
        try:
            ii = (page.get("imageinfo") or [{}])[0]
            meta = ii.get("extmetadata") or {}
            lic = _strip_html(meta.get("LicenseShortName", {}).get("value", ""))
            cls = classify_license(lic)
            title = re.sub(r"^File:", "", page.get("title", ""))
            out.append({
                "title": title,
                "page_url": ii.get("descriptionurl", ""),
                "source_url": ii.get("url", ""),
                "mime": ii.get("mime", ""),
                "size": int(ii.get("size") or 0),
                "author": _strip_html(meta.get("Artist", {}).get("value", ""))[:80],
                "license": lic or "不明",
                "license_ok": bool(cls),
                "attribution": bool(cls and cls.get("attribution")),
            })
        except Exception:
            continue
    # 商用可を先頭に、サイズが軽い順
    out.sort(key=lambda c: (not c["license_ok"], c["size"]))
    return out


# ════════════════════════════════════════════════════════
#  取得・保存（ライセンス記録つき）
# ════════════════════════════════════════════════════════
def download_asset(cand: dict, query: str, log: LOG_CB = print) -> Optional[dict]:
    """候補を TC_DB に保存して meta を返す。ライセンス不可・失敗は None。"""
    if not cand.get("license_ok"):
        log(f"🚫 ライセンス不可のため保存しません: {cand.get('title')}（{cand.get('license')}）")
        return None
    if cand.get("size", 0) > _MAX_BYTES:
        log(f"⚠️ サイズが大きすぎるためスキップ: {cand.get('title')}")
        return None
    # 種別判定：音声のMIMEは "audio/*" だけでなく "application/ogg"(.oga) でも来る
    mime = str(cand.get("mime", ""))
    ext = Path(urllib.parse.urlparse(cand["source_url"]).path).suffix.lower()
    _AUDIO_EXT = {".oga", ".ogg", ".wav", ".mp3", ".flac", ".opus", ".mid"}
    kind = "audio" if (mime.startswith("audio") or mime == "application/ogg"
                       or ext in _AUDIO_EXT) else "image"
    name = _slug(cand.get("title") or query)
    folder = ASSETS_DIR / name
    if not ext:
        ext = ".ogg" if kind == "audio" else ".jpg"
    file_path = folder / f"asset{ext}"
    try:
        folder.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(cand["source_url"], headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=60) as r:
            blob = r.read(_MAX_BYTES + 1)
        if len(blob) > _MAX_BYTES:
            raise ValueError("size over")
        file_path.write_bytes(blob)
    except Exception as e:
        log(f"⚠️ 素材のダウンロードに失敗: {str(e)[:80]}")
        return None

    author = cand.get("author") or "unknown"
    lic = cand.get("license", "不明")
    credit = f"{cand.get('title', name)} — {author} ({lic}, Wikimedia Commons)"
    meta = {
        "name": name,
        "kind": kind,
        "file": file_path.name,
        "query": query,
        "title": cand.get("title", ""),
        "page_url": cand.get("page_url", ""),
        "source_url": cand.get("source_url", ""),
        "author": author,
        "license": lic,
        "attribution_required": bool(cand.get("attribution")),
        "credit": credit,
        "retrieved_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    (folder / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"✅ 素材を保存: {name}（{kind} / {lic}"
        + (" / クレジット必要" if meta["attribution_required"] else "") + "）")
    return meta


def acquire(query: str, kind: str = "image", log: LOG_CB = print) -> Optional[dict]:
    """検索→商用可の最良候補を1つ保存。チャットツールとコード生成の共通入口。"""
    cands = search_commons(query, kind=kind, log=log)
    usable = [c for c in cands if c["license_ok"]]
    if not usable:
        rejected = len(cands)
        log(f"⚠️ 商用利用可の素材が見つかりませんでした（候補{rejected}件は全てライセンス不可/不明）"
            if rejected else "⚠️ 素材が見つかりませんでした")
        return None
    return download_asset(usable[0], query, log)


# ════════════════════════════════════════════════════════
#  一覧・参照（コード生成のINDEX注入と tc.asset() 用）
# ════════════════════════════════════════════════════════
def list_assets() -> list[dict]:
    out = []
    try:
        for meta_path in sorted(ASSETS_DIR.glob("*/meta.json")):
            try:
                m = json.loads(meta_path.read_text(encoding="utf-8"))
                if (meta_path.parent / m.get("file", "")).exists():
                    out.append(m)
            except Exception:
                continue
    except Exception:
        pass
    return out


def find_asset(name: str) -> Optional[dict]:
    for m in list_assets():
        if m.get("name") == name:
            m["path"] = str(ASSETS_DIR / name / m["file"])
            return m
    return None


def asset_index_text(limit: int = 12) -> str:
    """コード生成プロンプトに注入する1行INDEX（内容全部は入れない）。"""
    assets = list_assets()[:limit]
    if not assets:
        return ""
    lines = [f'- "{m["name"]}" | {m["kind"]} | {m["license"]}'
             f'{"・クレジット必要" if m.get("attribution_required") else ""}'
             f' | 検索語: {m.get("query", "")}' for m in assets]
    return "【使える素材（TC_DB・tc.asset(\"名前\")でパス取得）】\n" + "\n".join(lines) + "\n"
