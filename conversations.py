# -*- coding: utf-8 -*-
"""conversations.py — 新UI（pywebview版）の会話履歴ストア。

会話1件 = 1 JSONファイル（~/.tomato_clip/conversations/<id>.json）。
共有の db.py(SQLite) は触らず、新UIの履歴保存/復元だけをここに隔離する。

message の kind:
  "user"  : {"kind":"user",  "text": "..."}
  "ai"    : {"kind":"ai",    "text": "...（Markdown）"}
  "video" : {"kind":"video", "data": {"path","title","subtitle"}}
"""
import json
import time
import uuid
import threading
from pathlib import Path

_DIR = Path.home() / ".tomato_clip" / "conversations"
_lock = threading.Lock()


def _ensure():
    _DIR.mkdir(parents=True, exist_ok=True)


def _path(cid: str) -> Path:
    return _DIR / f"{cid}.json"


def _load(cid: str):
    p = _path(cid)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _save(d: dict):
    _ensure()
    _path(d["id"]).write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")


def create(title: str = "") -> str:
    now = time.time()
    cid = uuid.uuid4().hex[:12]
    d = {"id": cid, "title": (title or "新しい会話")[:40],
         "created": now, "updated": now, "messages": []}
    with _lock:
        _save(d)
    return cid


def add_message(cid: str, kind: str, **fields):
    with _lock:
        d = _load(cid)
        if not d:
            return
        d["messages"].append({"kind": kind, **fields})
        d["updated"] = time.time()
        # 既定タイトルのまま最初の user 発話が来たらタイトルに採用
        if kind == "user" and fields.get("text") and \
                (not d.get("title") or d["title"] == "新しい会話"):
            d["title"] = fields["text"][:40]
        _save(d)


def get(cid: str):
    return _load(cid)


def set_title(cid: str, title: str):
    title = (title or "").strip()[:60]
    if not title:
        return
    with _lock:
        d = _load(cid)
        if not d:
            return
        d["title"] = title
        _save(d)


def _msg_text(m: dict) -> str:
    if m.get("kind") in ("user", "ai"):
        return m.get("text", "") or ""
    if m.get("kind") == "video":
        data = m.get("data") or {}
        return " ".join(str(data.get(k, "")) for k in ("title", "subtitle"))
    return ""


def search(query: str):
    """タイトル＆本文を横断検索。ヒットした会話を、最初の一致スニペット付きで返す（新しい順）。"""
    q = (query or "").strip().lower()
    if not q:
        return []
    _ensure()
    out = []
    for p in _DIR.glob("*.json"):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        title = d.get("title", "") or ""
        snippet, matched = "", False
        if q in title.lower():
            matched = True
        for m in d.get("messages", []):
            t = _msg_text(m)
            if q in t.lower():
                matched = True
                if not snippet:
                    snippet = _excerpt(t, q)
        if matched:
            out.append({"id": d["id"], "title": title or "会話",
                        "snippet": snippet, "updated": d.get("updated", 0)})
    out.sort(key=lambda x: x["updated"], reverse=True)
    return out


def _excerpt(text: str, q: str, width: int = 60) -> str:
    """一致箇所を中心に前後を切り出したスニペット。"""
    low = text.lower()
    i = low.find(q)
    if i < 0:
        return text[:width]
    start = max(0, i - width // 3)
    end = min(len(text), i + len(q) + width)
    s = text[start:end].replace("\n", " ").strip()
    return ("…" if start > 0 else "") + s + ("…" if end < len(text) else "")


def list_all():
    """サイドバー用の一覧（新しい順）。空の会話は除外。"""
    _ensure()
    out = []
    for p in _DIR.glob("*.json"):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            if not d.get("messages"):
                continue
            out.append({"id": d["id"], "title": d.get("title", "新しい会話"),
                        "updated": d.get("updated", 0)})
        except Exception:
            pass
    out.sort(key=lambda x: x["updated"], reverse=True)
    return out


def delete(cid: str):
    with _lock:
        try:
            _path(cid).unlink()
        except FileNotFoundError:
            pass
        except Exception:
            pass
