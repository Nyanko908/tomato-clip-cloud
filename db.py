"""
db.py - SQLite データベース管理
全データの永続化（動画履歴・ホワイトリスト・テンプレート・アナリティクス・Discordキュー）
"""
import sqlite3, json, threading, time
from pathlib import Path
from datetime import datetime

DB_PATH = Path.home() / ".tomato_clip" / "data.db"

# ── スレッドローカル永続接続 ─────────────────────────────
# 毎回 connect/close する代わりにスレッドごとに接続を使い回す
_local = threading.local()

def get_conn() -> sqlite3.Connection:
    if not getattr(_local, "conn", None):
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")       # 読み書き並行
        c.execute("PRAGMA synchronous=NORMAL")     # FULL比3〜5倍速（WAL下で安全）
        c.execute("PRAGMA cache_size=-16384")      # 16MB ページキャッシュ
        c.execute("PRAGMA temp_store=MEMORY")      # 一時テーブルをRAMに
        c.execute("PRAGMA mmap_size=134217728")    # 128MB メモリマップI/O
        _local.conn = c
    return _local.conn

# ── TTLキャッシュ（hot readの重複クエリを排除）────────────
_cache: dict = {}  # {key: (value, expires_at)}

def _cached(key: str, ttl: float, fn):
    now = time.monotonic()
    if key in _cache and _cache[key][1] > now:
        return _cache[key][0]
    val = fn()
    _cache[key] = (val, now + ttl)
    return val

def _invalidate(*keys: str):
    for k in keys:
        _cache.pop(k, None)

def _invalidate_prefix(prefix: str):
    for k in list(_cache.keys()):
        if k.startswith(prefix):
            _cache.pop(k, None)


def init_db():
    conn = get_conn()
    c = conn.cursor()

    # 投稿済み動画
    c.execute("""CREATE TABLE IF NOT EXISTS videos (
        id          TEXT PRIMARY KEY,
        title       TEXT,
        channel     TEXT,
        score       INTEGER,
        output_path TEXT,
        yt_url      TEXT,
        posted_at   TEXT,
        template_id TEXT,
        meta_json   TEXT
    )""")

    # アナリティクス（YouTube統計）
    c.execute("""CREATE TABLE IF NOT EXISTS analytics (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        video_id    TEXT,
        checked_at  TEXT,
        views       INTEGER,
        likes       INTEGER,
        comments    INTEGER,
        watch_time  INTEGER
    )""")

    # ホワイトリスト
    c.execute("""CREATE TABLE IF NOT EXISTS whitelist (
        channel_id   TEXT PRIMARY KEY,
        channel_name TEXT,
        added_at     TEXT,
        score_bonus  INTEGER DEFAULT 15,
        notes        TEXT
    )""")

    # テンプレート（廃止済み・互換性のため残す）
    c.execute("""CREATE TABLE IF NOT EXISTS templates (
        id          TEXT PRIMARY KEY,
        name        TEXT,
        preview_b64 TEXT,
        config_json TEXT,
        created_at  TEXT
    )""")

    # ── トレンドログ
    c.execute("""CREATE TABLE IF NOT EXISTS trend_log (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        summary         TEXT,
        genres_json     TEXT,
        keywords_json   TEXT,
        tips_json       TEXT,
        hot_title       TEXT,
        top_videos_json TEXT,
        recorded_at     TEXT
    )""")

    # ── 検索意図
    c.execute("""CREATE TABLE IF NOT EXISTS search_intent (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        category    TEXT,
        value       TEXT,
        priority    INTEGER DEFAULT 5,
        notes       TEXT,
        active      INTEGER DEFAULT 1,
        added_at    TEXT
    )""")

    # ── 編集のDNA
    c.execute("""CREATE TABLE IF NOT EXISTS dna_table (
        id                   INTEGER PRIMARY KEY CHECK (id=1),
        avg_cut_interval_sec REAL,
        fade_in_tendency     REAL,
        bgm_sync_level       REAL,
        preferred_materials  TEXT,
        avoided_materials    TEXT,
        contrast_preference  REAL,
        effect_intensity     REAL,
        aesthetic_summary    TEXT,
        draft_json           TEXT,
        last_drafted_at      TEXT,
        last_committed_at    TEXT,
        commit_count         INTEGER DEFAULT 0
    )""")
    c.execute("INSERT OR IGNORE INTO dna_table(id) VALUES(1)")

    # ── 成功と失敗のアーカイブ
    c.execute("""CREATE TABLE IF NOT EXISTS learning_log (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        video_id         TEXT,
        project_name     TEXT,
        peak_views       INTEGER DEFAULT 0,
        peak_likes       INTEGER DEFAULT 0,
        performance_at   TEXT,
        avg_cut_sec      REAL,
        effect_count     INTEGER,
        bgm_path         TEXT,
        feedback_text    TEXT,
        feedback_score   INTEGER,
        scene_pins       TEXT,
        edit_changes     TEXT,
        dna_draft_json   TEXT,
        committed_to_dna INTEGER DEFAULT 0,
        logged_at        TEXT
    )""")

    # ── 文脈の地図
    c.execute("""CREATE TABLE IF NOT EXISTS context_map (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        source_path     TEXT UNIQUE,
        source_type     TEXT,
        source_name     TEXT,
        tags            TEXT,
        personality     TEXT,
        usage_context   TEXT,
        avoid_context   TEXT,
        pairs_well_with TEXT,
        conflicts_with  TEXT,
        used_count      INTEGER DEFAULT 0,
        last_used_at    TEXT,
        avg_performance REAL,
        ai_analysis     TEXT,
        user_notes      TEXT,
        added_at        TEXT,
        updated_at      TEXT
    )""")

    # スケジュール設定
    c.execute("""CREATE TABLE IF NOT EXISTS schedule (
        id           INTEGER PRIMARY KEY CHECK (id=1),
        enabled      INTEGER DEFAULT 0,
        interval_hrs INTEGER DEFAULT 4,
        next_run     TEXT,
        last_run     TEXT,
        run_count    INTEGER DEFAULT 0
    )""")
    c.execute("INSERT OR IGNORE INTO schedule(id,enabled,interval_hrs) VALUES(1,0,4)")

    # ── インデックス
    c.execute("CREATE INDEX IF NOT EXISTS idx_videos_posted   ON videos(posted_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_analytics_vid   ON analytics(video_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_analytics_check ON analytics(checked_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_learning_logged ON learning_log(logged_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_trend_recorded  ON trend_log(recorded_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_intent_active   ON search_intent(active, priority DESC)")

    conn.commit()
    _auto_prune()


def _auto_prune():
    conn = get_conn()
    conn.execute("""DELETE FROM trend_log WHERE id NOT IN (
        SELECT id FROM trend_log ORDER BY recorded_at DESC LIMIT 60
    )""")
    conn.execute("""DELETE FROM learning_log
        WHERE committed_to_dna=0
          AND (feedback_score IS NULL OR feedback_score < 2)
          AND id NOT IN (
              SELECT id FROM learning_log ORDER BY logged_at DESC LIMIT 500
          )""")
    conn.execute("""DELETE FROM analytics WHERE id NOT IN (
        SELECT id FROM (
            SELECT id, ROW_NUMBER() OVER (
                PARTITION BY video_id ORDER BY checked_at DESC
            ) AS rn FROM analytics
        ) WHERE rn <= 50
    )""")
    conn.commit()


# ── 動画 ──────────────────────────────────────────────
def save_video(video_id, title, channel, score, output_path, yt_url, template_id, meta):
    conn = get_conn()
    conn.execute("""INSERT OR REPLACE INTO videos
        (id,title,channel,score,output_path,yt_url,posted_at,template_id,meta_json)
        VALUES(?,?,?,?,?,?,?,?,?)""",
        (video_id, title, channel, score, output_path, yt_url,
         datetime.now().isoformat(), template_id, json.dumps(meta, ensure_ascii=False)))
    conn.commit()
    _invalidate("used_video_ids")

def get_videos(limit=50):
    conn = get_conn()
    rows = conn.execute("SELECT * FROM videos ORDER BY posted_at DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]

def delete_video(video_id: str):
    conn = get_conn()
    conn.execute("DELETE FROM videos WHERE id=?", (video_id,))
    conn.commit()
    _invalidate("used_video_ids")

def get_used_video_ids() -> set:
    return _cached("used_video_ids", 60.0, lambda: {
        r["id"] for r in get_conn().execute("SELECT id FROM videos").fetchall()
    })


# ── アナリティクス ──────────────────────────────────
def save_analytics(video_id, views, likes, comments, watch_time=0):
    conn = get_conn()
    conn.execute("""INSERT INTO analytics(video_id,checked_at,views,likes,comments,watch_time)
        VALUES(?,?,?,?,?,?)""",
        (video_id, datetime.now().isoformat(), views, likes, comments, watch_time))
    conn.commit()

def get_analytics(video_id):
    conn = get_conn()
    rows = conn.execute("SELECT * FROM analytics WHERE video_id=? ORDER BY checked_at",
                        (video_id,)).fetchall()
    return [dict(r) for r in rows]

def get_all_analytics_summary():
    conn = get_conn()
    rows = conn.execute("""
        SELECT v.id, v.title, v.channel, v.score, v.template_id, v.posted_at,
               MAX(a.views) as peak_views, MAX(a.likes) as peak_likes
        FROM videos v LEFT JOIN analytics a ON v.id=a.video_id
        GROUP BY v.id ORDER BY peak_views DESC NULLS LAST
    """).fetchall()
    return [dict(r) for r in rows]


def get_video_count_since(since_iso: str) -> int:
    """posted_at が since_iso 以降の動画本数（月間目標の進捗用）"""
    conn = get_conn()
    row = conn.execute(
        "SELECT COUNT(*) AS c FROM videos WHERE posted_at >= ?", (since_iso,)
    ).fetchone()
    return row["c"] if row else 0


def get_period_summary(since_iso: str) -> dict:
    """指定期間以降の生成本数・再生数合計・いいね数合計（週次/月次サマリー用）"""
    conn = get_conn()
    rows = conn.execute("""
        SELECT v.id, MAX(a.views) AS peak_views, MAX(a.likes) AS peak_likes
        FROM videos v LEFT JOIN analytics a ON v.id = a.video_id
        WHERE v.posted_at >= ?
        GROUP BY v.id
    """, (since_iso,)).fetchall()
    return {
        "count": len(rows),
        "views": sum(r["peak_views"] or 0 for r in rows),
        "likes": sum(r["peak_likes"] or 0 for r in rows),
    }


def get_tag_performance(top_n: int = 6) -> list:
    """
    meta_json 内の tags を集計し、タグごとの平均再生数を返す。
    戻り値: [{"tag": str, "avg_views": int, "count": int}, ...] 平均再生数の降順
    """
    conn = get_conn()
    rows = conn.execute("""
        SELECT v.meta_json AS meta_json, MAX(a.views) AS peak_views
        FROM videos v LEFT JOIN analytics a ON v.id = a.video_id
        GROUP BY v.id
    """).fetchall()
    from collections import defaultdict
    buckets = defaultdict(list)
    for r in rows:
        try:
            meta = json.loads(r["meta_json"] or "{}")
        except Exception:
            continue
        views = r["peak_views"] or 0
        for tag in (meta.get("tags") or [])[:6]:
            tag = str(tag).strip()
            if tag and tag != "MadeWithTomatoClip":
                buckets[tag].append(views)
    result = [
        {"tag": t, "avg_views": int(sum(vs) / len(vs)), "count": len(vs)}
        for t, vs in buckets.items()
    ]
    result.sort(key=lambda x: x["avg_views"], reverse=True)
    return result[:top_n]


# ── ホワイトリスト ─────────────────────────────────
def add_whitelist(channel_id, channel_name, score_bonus=15, notes=""):
    conn = get_conn()
    conn.execute("""INSERT OR REPLACE INTO whitelist(channel_id,channel_name,added_at,score_bonus,notes)
        VALUES(?,?,?,?,?)""", (channel_id, channel_name, datetime.now().isoformat(), score_bonus, notes))
    conn.commit()

def remove_whitelist(channel_id):
    conn = get_conn()
    conn.execute("DELETE FROM whitelist WHERE channel_id=?", (channel_id,))
    conn.commit()

def get_whitelist():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM whitelist ORDER BY channel_name").fetchall()
    return [dict(r) for r in rows]


# ── テンプレート（廃止済み・互換性のため残す）────────────
def save_template(tid, name, config, preview_b64=""):
    conn = get_conn()
    conn.execute("""INSERT OR REPLACE INTO templates(id,name,preview_b64,config_json,created_at)
        VALUES(?,?,?,?,?)""",
        (tid, name, preview_b64, json.dumps(config, ensure_ascii=False), datetime.now().isoformat()))
    conn.commit()

def get_templates():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM templates ORDER BY name").fetchall()
    return [dict(r) for r in rows]

def delete_template(tid):
    conn = get_conn()
    conn.execute("DELETE FROM templates WHERE id=?", (tid,))
    conn.commit()


# ── トレンドログ ────────────────────────────────────
def save_trend(result: dict):
    conn = get_conn()
    conn.execute("""INSERT INTO trend_log
        (summary,genres_json,keywords_json,tips_json,hot_title,top_videos_json,recorded_at)
        VALUES(?,?,?,?,?,?,?)""",
        (
            result.get("summary", ""),
            json.dumps(result.get("genres", []),     ensure_ascii=False),
            json.dumps(result.get("keywords", []),   ensure_ascii=False),
            json.dumps(result.get("tips", []),       ensure_ascii=False),
            result.get("hot_title", ""),
            json.dumps(result.get("top_videos", []), ensure_ascii=False),
            datetime.now().isoformat(),
        ))
    conn.commit()
    _invalidate_prefix("trend_logs")

def get_trend_logs(limit: int = 10) -> list:
    def _fetch():
        conn = get_conn()
        rows = conn.execute(
            "SELECT * FROM trend_log ORDER BY recorded_at DESC LIMIT ?", (limit,)
        ).fetchall()
        now = datetime.now()
        result = []
        for r in rows:
            d = dict(r)
            for field in ("genres_json", "keywords_json", "tips_json", "top_videos_json"):
                try:
                    d[field.replace("_json", "")] = json.loads(d.pop(field) or "[]")
                except Exception:
                    d[field.replace("_json", "")] = []
            try:
                age_days = (now - datetime.fromisoformat(d["recorded_at"])).days
                if age_days <= 1:    freshness = 1.0
                elif age_days <= 7:  freshness = 0.7
                elif age_days <= 30: freshness = 0.4
                else:                freshness = max(0.1, 0.4 - (age_days - 30) * 0.005)
            except Exception:
                age_days, freshness = 0, 0.5
            d["freshness"] = round(freshness, 2)
            d["age_days"]  = age_days
            result.append(d)
        return result
    return _cached(f"trend_logs_{limit}", 300.0, _fetch)


# ── 検索意図 ───────────────────────────────────────
def add_search_intent(category: str, value: str, priority: int = 5, notes: str = ""):
    conn = get_conn()
    conn.execute("""INSERT INTO search_intent(category,value,priority,notes,active,added_at)
        VALUES(?,?,?,?,1,?)""",
        (category, value, priority, notes, datetime.now().isoformat()))
    conn.commit()
    _invalidate("search_intents")

def get_search_intents(active_only: bool = True) -> list:
    def _fetch():
        conn = get_conn()
        q = "SELECT * FROM search_intent"
        if active_only:
            q += " WHERE active=1"
        q += " ORDER BY priority DESC, added_at"
        return [dict(r) for r in conn.execute(q).fetchall()]
    return _cached("search_intents", 120.0, _fetch)

def remove_search_intent(intent_id: int):
    conn = get_conn()
    conn.execute("DELETE FROM search_intent WHERE id=?", (intent_id,))
    conn.commit()
    _invalidate("search_intents")


# ── 編集のDNA ──────────────────────────────────────
def get_dna() -> dict:
    def _fetch():
        row = get_conn().execute("SELECT * FROM dna_table WHERE id=1").fetchone()
        return dict(row) if row else {}
    return _cached("dna", 300.0, _fetch)

def update_dna_draft(draft: dict):
    conn = get_conn()
    conn.execute("""UPDATE dna_table SET draft_json=?, last_drafted_at=? WHERE id=1""",
        (json.dumps(draft, ensure_ascii=False), datetime.now().isoformat()))
    conn.commit()
    _invalidate("dna")

def update_dna_fields(**kwargs):
    """数値フィールドを直接上書きする（UIからの手動編集用）"""
    conn = get_conn()
    allowed = {"avg_cut_interval_sec","fade_in_tendency","bgm_sync_level",
               "contrast_preference","effect_intensity","aesthetic_summary"}
    filtered = {k: v for k, v in kwargs.items() if k in allowed}
    if not filtered:
        return
    sets = ", ".join(f"{k}=?" for k in filtered)
    conn.execute(f"UPDATE dna_table SET {sets} WHERE id=1", list(filtered.values()))
    conn.commit()
    _invalidate("dna")

def commit_dna(dna: dict):
    conn = get_conn()
    conn.execute("""UPDATE dna_table SET
        avg_cut_interval_sec=?, fade_in_tendency=?, bgm_sync_level=?,
        preferred_materials=?, avoided_materials=?,
        contrast_preference=?, effect_intensity=?,
        aesthetic_summary=?, draft_json=NULL,
        last_committed_at=?, commit_count=commit_count+1
        WHERE id=1""",
        (dna.get("avg_cut_interval_sec"), dna.get("fade_in_tendency"),
         dna.get("bgm_sync_level"),
         json.dumps(dna.get("preferred_materials", []), ensure_ascii=False),
         json.dumps(dna.get("avoided_materials", []), ensure_ascii=False),
         dna.get("contrast_preference"), dna.get("effect_intensity"),
         dna.get("aesthetic_summary"), datetime.now().isoformat()))
    conn.commit()
    _invalidate("dna")


# ── 成功と失敗のアーカイブ ──────────────────────────
def log_learning(video_id: str, project_name: str, **kwargs):
    conn = get_conn()
    kwargs["video_id"]      = video_id
    kwargs["project_name"]  = project_name
    kwargs["logged_at"]     = datetime.now().isoformat()
    cols         = ", ".join(kwargs.keys())
    placeholders = ", ".join("?" * len(kwargs))
    conn.execute(f"INSERT INTO learning_log ({cols}) VALUES ({placeholders})",
                 list(kwargs.values()))
    conn.commit()

def add_feedback(log_id: int, feedback_text: str, score: int = None, scene_pins: list = None):
    conn = get_conn()
    conn.execute("""UPDATE learning_log SET feedback_text=?, feedback_score=?, scene_pins=? WHERE id=?""",
        (feedback_text, score, json.dumps(scene_pins or [], ensure_ascii=False), log_id))
    conn.commit()

def get_learning_logs(limit: int = 50) -> list:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM learning_log ORDER BY logged_at DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]

def mark_dna_committed(log_id: int):
    conn = get_conn()
    conn.execute("UPDATE learning_log SET committed_to_dna=1 WHERE id=?", (log_id,))
    conn.commit()

def delete_learning_log(log_id: int):
    conn = get_conn()
    conn.execute("DELETE FROM learning_log WHERE id=?", (log_id,))
    conn.commit()


# ── 文脈の地図 ─────────────────────────────────────
def upsert_context(source_path: str, **kwargs):
    conn = get_conn()
    existing = conn.execute(
        "SELECT id FROM context_map WHERE source_path=?", (source_path,)).fetchone()
    if existing:
        kwargs["updated_at"] = datetime.now().isoformat()
        sets = ", ".join(f"{k}=?" for k in kwargs)
        conn.execute(f"UPDATE context_map SET {sets} WHERE source_path=?",
                     [*kwargs.values(), source_path])
    else:
        kwargs["source_path"] = source_path
        kwargs["added_at"]    = datetime.now().isoformat()
        kwargs["updated_at"]  = kwargs["added_at"]
        cols         = ", ".join(kwargs.keys())
        placeholders = ", ".join("?" * len(kwargs))
        conn.execute(f"INSERT INTO context_map ({cols}) VALUES ({placeholders})",
                     list(kwargs.values()))
    conn.commit()

def get_context(source_path: str) -> dict:
    row = get_conn().execute(
        "SELECT * FROM context_map WHERE source_path=?", (source_path,)).fetchone()
    return dict(row) if row else {}

def get_all_contexts() -> list:
    rows = get_conn().execute(
        "SELECT * FROM context_map ORDER BY used_count DESC").fetchall()
    return [dict(r) for r in rows]


# ── スケジュール ───────────────────────────────────
def get_schedule():
    row = get_conn().execute("SELECT * FROM schedule WHERE id=1").fetchone()
    return dict(row) if row else {}

def update_schedule(**kwargs):
    conn = get_conn()
    sets = ", ".join(f"{k}=?" for k in kwargs)
    conn.execute(f"UPDATE schedule SET {sets} WHERE id=1", list(kwargs.values()))
    conn.commit()
