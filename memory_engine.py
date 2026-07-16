"""
memory_engine.py
チャットの重要情報を永続保存し、次回会話のコンテキストに注入する。
~/.tomato_clip_memory.json に保存
- 通常メモリ: 最大100件（古いものから自動削除）
- 永久メモリ: permanent=True のエントリは削除されない
"""

import json, time
from pathlib import Path
from typing import Callable

MEMORY_PATH = Path.home() / ".tomato_clip_memory.json"
MAX_NORMAL  = 100


def load_memories() -> list[dict]:
    if MEMORY_PATH.exists():
        try:
            with open(MEMORY_PATH, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []


def save_memory(content: str, tags: list[str] | None = None,
                source: str = "manual", permanent: bool = False):
    memories = load_memories()
    memories.append({
        "content":   content,
        "tags":      tags or [],
        "source":    source,
        "permanent": permanent,
        "saved_at":  time.strftime("%Y-%m-%d %H:%M:%S"),
    })
    _prune(memories)
    _write(memories)
    return memories[-1]


def pin_memory(index: int):
    """指定インデックスのメモリを永久固定する"""
    memories = load_memories()
    if 0 <= index < len(memories):
        memories[index]["permanent"] = True
        _write(memories)
        return memories[index]
    return None


def unpin_memory(index: int):
    memories = load_memories()
    if 0 <= index < len(memories):
        memories[index]["permanent"] = False
        _write(memories)


def delete_memory(index: int):
    memories = load_memories()
    if 0 <= index < len(memories):
        memories.pop(index)
        _write(memories)


def clear_memories(permanent_too: bool = False):
    if permanent_too:
        _write([])
    else:
        _write([m for m in load_memories() if m.get("permanent")])


def _prune(memories: list):
    """永久メモリを残しつつ通常メモリを MAX_NORMAL 件に制限"""
    permanent = [m for m in memories if m.get("permanent")]
    normal    = [m for m in memories if not m.get("permanent")]
    if len(normal) > MAX_NORMAL:
        normal = normal[-MAX_NORMAL:]
    memories[:] = permanent + normal
    memories.sort(key=lambda m: m.get("saved_at", ""))


def _write(data: list):
    with open(MEMORY_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def build_memory_context() -> str:
    """Geminiシステムプロンプトに注入するメモリ文字列を生成"""
    memories = load_memories()
    if not memories:
        return ""

    permanent = [m for m in memories if m.get("permanent")]
    recent    = [m for m in memories if not m.get("permanent")][-20:]

    lines = []
    if permanent:
        lines.append("\n【永久メモリ（常に参照すべき重要情報）】")
        for m in permanent:
            lines.append(f"  📌 {m['content']}")
    if recent:
        lines.append("\n【AIメモリ（直近の重要情報）】")
        for m in recent:
            src = "👤" if m.get("source") == "manual" else "🤖"
            lines.append(f"  {src} [{m['saved_at'][:10]}] {m['content']}")
    lines.append("\n上記の情報を考慮して返答してください。")
    return "\n".join(lines)


def auto_extract(client, recent_exchange: str, log: Callable | None = None) -> str | None:
    """直近のやり取りから重要情報を自動抽出・保存する"""
    prompt = (
        "次の会話を見て、将来の動画制作に役立つ重要な情報・好み・決定事項があれば"
        "1〜2文で要約してください。特になければ「なし」とだけ答えてください。\n\n"
        "会話:\n" + recent_exchange
    )
    try:
        resp = client.models.generate_content(model=client._model_name, contents=[prompt])
        result = (resp.text or "").strip()
        if result and result != "なし" and len(result) > 8:
            save_memory(result, source="auto")
            if log:
                log(f"🧠 自動メモリ保存: {result[:40]}...")
            return result
    except Exception:
        pass
    return None
