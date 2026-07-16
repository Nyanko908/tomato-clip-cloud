"""
schedule_engine.py
「3本動画を作って明日の6時に投稿」などの複合タスクを管理する。
~/.tomato_clip_schedule.json に永続保存し、アプリ起動時に再開できる。
"""

import json, time, re
from datetime import datetime, timedelta
from pathlib import Path

SCHEDULE_PATH = Path.home() / ".tomato_clip_schedule.json"


def load_tasks() -> list[dict]:
    if SCHEDULE_PATH.exists():
        try:
            with open(SCHEDULE_PATH, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []


def _write(tasks: list):
    with open(SCHEDULE_PATH, "w", encoding="utf-8") as f:
        json.dump(tasks, f, ensure_ascii=False, indent=2)


def add_task(task_type: str, run_at: str, params: dict, repeat: str = None) -> dict:
    """
    repeat: None（単発） / "daily"（毎日） / "weekly"（毎週）
    """
    tasks = load_tasks()
    task = {
        "id":         int(time.time() * 1000),
        "type":       task_type,
        "run_at":     run_at,
        "params":     params,
        "repeat":     repeat,
        "status":     "pending",
        "runs":       0,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    tasks.append(task)
    _write(tasks)
    return task


def cancel_task(task_id: int):
    tasks = [t for t in load_tasks() if t["id"] != task_id]
    _write(tasks)


def mark_done(task_id: int):
    """
    単発タスク → done にする。
    繰り返しタスク → 実行回数を記録し、次の未来の実行時刻へ進めて pending のまま。
    （アプリを数日閉じていても連続実行にならないよう、必ず未来まで進める）
    """
    now = datetime.now()
    tasks = load_tasks()
    for t in tasks:
        if t["id"] != task_id:
            continue
        t["runs"]     = t.get("runs", 0) + 1
        t["last_run"] = now.strftime("%Y-%m-%d %H:%M:%S")
        repeat = t.get("repeat")
        step = None
        if repeat in ("daily", "weekly"):
            step = timedelta(days=1 if repeat == "daily" else 7)
        elif repeat and repeat.startswith("every_") and repeat.endswith("h"):
            # "every_4h" のようなN時間おきの繰り返し(booth_csv_sync等の定期同期タスク用)
            try:
                step = timedelta(hours=int(repeat[len("every_"):-1]))
            except Exception:
                step = None
        if step is not None:
            try:
                nxt = datetime.fromisoformat(t["run_at"])
            except Exception:
                nxt = now
            while nxt <= now:
                nxt += step
            t["run_at"] = nxt.isoformat()
        else:
            t["status"] = "done"
    _write(tasks)


def get_pending() -> list[dict]:
    """実行時刻が来たペンディングタスクを返す"""
    now = datetime.now()
    result = []
    for t in load_tasks():
        if t["status"] != "pending":
            continue
        try:
            if datetime.fromisoformat(t["run_at"]) <= now:
                result.append(t)
        except Exception:
            pass
    return result


def list_pending() -> list[dict]:
    """未来のペンディングタスク一覧（UI表示用）"""
    now = datetime.now()
    result = []
    for t in load_tasks():
        if t["status"] != "pending":
            continue
        try:
            if datetime.fromisoformat(t["run_at"]) > now:
                result.append(t)
        except Exception:
            pass
    return result


_WEEKDAYS = {"月": 0, "火": 1, "水": 2, "木": 3, "金": 4, "土": 5, "日": 6}


def parse_schedule_spec(text: str) -> tuple[datetime | None, str | None]:
    """
    時刻表現を (datetime, repeat) に変換する。
    repeat: None / "daily" / "weekly"
    例: "毎朝8時" → (明日または今日の8:00, "daily")
        "毎週月曜9時" → (次の月曜9:00, "weekly")
        "明日の6時" → (明日6:00, None)
    """
    now = datetime.now()
    t   = text.strip()

    # 毎週X曜H時
    m = re.search(r"毎週\s*([月火水木金土日])曜?日?\s*の?\s*(\d{1,2})\s*時", t)
    if m:
        wd, h = _WEEKDAYS[m.group(1)], int(m.group(2))
        dt = now.replace(hour=h, minute=0, second=0, microsecond=0)
        while dt.weekday() != wd or dt <= now:
            dt += timedelta(days=1)
        return dt, "weekly"

    # 毎日・毎朝・毎晩 H時
    m = re.search(r"(毎日|毎朝|毎晩|毎夜)\s*の?\s*(\d{1,2})\s*時", t)
    if m:
        kind, h = m.group(1), int(m.group(2))
        if kind in ("毎晩", "毎夜") and h < 12:
            h += 12
        dt = now.replace(hour=h, minute=0, second=0, microsecond=0)
        if dt <= now:
            dt += timedelta(days=1)
        return dt, "daily"

    # 「毎日」だけ（時刻なし）→ 明日の朝8時
    if re.search(r"毎日|毎朝", t):
        dt = (now + timedelta(days=1)).replace(hour=8, minute=0, second=0, microsecond=0)
        return dt, "daily"

    # 単発
    return parse_schedule_time(t), None


def parse_schedule_time(text: str) -> datetime | None:
    """
    自然言語の時刻表現をdatetimeに変換する。
    例: "明日の6時", "今日の18時", "2024-12-01 09:00", "18:00"
    """
    now = datetime.now()
    t   = text.strip()

    # ISO形式 YYYY-MM-DD HH:MM
    m = re.match(r"(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2})", t)
    if m:
        try:
            return datetime.fromisoformat(f"{m.group(1)} {m.group(2)}")
        except Exception:
            pass

    # HH:MM のみ
    m = re.match(r"^(\d{1,2}):(\d{2})$", t)
    if m:
        dt = now.replace(hour=int(m.group(1)), minute=int(m.group(2)), second=0)
        if dt <= now:
            dt += timedelta(days=1)
        return dt

    # 「明日のH時」「明日H時」
    m = re.search(r"明日.*?(\d{1,2})\s*時", t)
    if m:
        h = int(m.group(1))
        return (now + timedelta(days=1)).replace(hour=h, minute=0, second=0, microsecond=0)

    # 「今日のH時」「今日H時」
    m = re.search(r"今日.*?(\d{1,2})\s*時", t)
    if m:
        h = int(m.group(1))
        dt = now.replace(hour=h, minute=0, second=0, microsecond=0)
        if dt <= now:
            dt += timedelta(days=1)
        return dt

    # 「H時」だけ
    m = re.search(r"(\d{1,2})\s*時", t)
    if m:
        h = int(m.group(1))
        dt = now.replace(hour=h, minute=0, second=0, microsecond=0)
        if dt <= now:
            dt += timedelta(days=1)
        return dt

    return None
