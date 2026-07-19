"""
pipeline.py
発見 → ダウンロード → カット → 編集 → アップロード の全工程を管理
"""

import os, json, time, tempfile, subprocess, threading
from pathlib import Path
from typing import Callable, Optional

# ─── 外部ライブラリ ──────────────────────────────────────
try:
    from google import genai
    from google.genai import types as genai_types
    import yt_dlp
except ImportError:
    pass  # 起動時チェックは main.py で行う

from key_rotator import setup_rotators, get_rotator


LOG_CB  = Callable[[str], None]   # ログコールバック型

# ════════════════════════════════════════════════════════
#  使用モデル（ここが全アプリの単一の真実の源）
# ════════════════════════════════════════════════════════
# Google はモデルを予告なく廃止し、既存ユーザーだけ猶予を与える。
# 具体的なバージョン名（gemini-2.5-flash-lite 等）を直接書くと、
# 廃止された瞬間に「新規ユーザーだけ 404 で動かない」状態になり、
# 開発者の環境では永遠に再現しない。必ず -latest エイリアスを使うこと。
DEFAULT_MODEL  = "gemini-flash-lite-latest"   # 最速・最安（既定）
FALLBACK_MODEL = "gemini-flash-latest"        # 既定が使えない時の逃げ先（既定と別物であること）


# ════════════════════════════════════════════════════════
#  Step 0: 初期化
# ════════════════════════════════════════════════════════
def init_gemini(api_key: str, model: str = DEFAULT_MODEL):
    """APIキーからClientを作成して返す（model名は別途保持）"""
    client = genai.Client(api_key=api_key)
    client._model_name = model
    client._api_key    = api_key  # ban_key で参照するため保持
    return client


def init_gemini_rotated(log: LOG_CB, model: str = DEFAULT_MODEL):
    """キーローリング対応版 Gemini 初期化"""
    rot = get_rotator("gemini", log)
    key = rot.next()
    if not key:
        raise ValueError("Gemini APIキーが登録されていません")
    return init_gemini(key, model), rot


# ════════════════════════════════════════════════════════
#  Step 1: 海外ショート発見
# ════════════════════════════════════════════════════════
def discover_shorts(youtube_key: str,
                    priority_channels: list[dict],
                    categories: list[str],
                    log: LOG_CB,
                    freshness_hours: int = 72,
                    search_keywords: str = "",
                    ai_queries: list[dict] = None,
                    source_preference: str = "any") -> list[dict]:
    """
    YouTube Data API で海外ショートを取得。
    優先チャンネル → 新着検索 → トレンドの順。
    処理済みIDはDBで照合してスキップ。
    freshness_hours: この時間以内の動画を新着優先で取得（0=制限なし）
    source_preference: "prefer_original"/"original_only" なら 4分未満の強制を外し
      配信アーカイブ等の原典（長尺）も候補に含める（見せ場は区間DLで切り出す）。
      素性の判定と重み付けは score_videos が行う。"any"=従来通りショートのみ。
    """
    import urllib.request, urllib.parse
    from datetime import datetime, timezone, timedelta
    import db as db_mod

    results  = []
    seen     = set()
    used_ids = db_mod.get_used_video_ids()
    log(f"🚫 処理済みID: {len(used_ids)}件 をスキップ")

    # 新着優先の publishedAfter 時刻
    if freshness_hours > 0:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=freshness_hours)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
    else:
        cutoff = None

    def api_get(url):
        with urllib.request.urlopen(url, timeout=10) as r:
            return json.loads(r.read())

    # 原典（長尺）も拾うか。拾った長尺は pick_highlight_segment が見せ場だけ区間DLする。
    allow_long = source_preference in ("prefer_original", "original_only")
    dur_max    = 7200 if allow_long else 65   # 原典許可時は2時間まで（配信アーカイブ想定）
    if allow_long:
        log("🔎 検索ソース: 原典を含める（4分未満の強制を解除）")

    def _add(vid, title, channel, views, thumb, priority, desc="", dur_sec=0):
        if vid in seen or vid in used_ids:
            return False
        seen.add(vid)
        results.append({
            "id": vid, "title": title, "channel": channel,
            "views": views, "thumbnail": thumb, "priority": priority,
            "desc": (desc or "")[:300], "dur_sec": int(dur_sec or 0),
        })
        return True

    def _region_locked(item):
        # regionRestriction.allowed（特定国のみ許可＝例:米国限定）は他国からDLできず、
        # 採用すると「生成できませんでした」になる（実際に起きた）ので検索段階で弾く。
        rr = (item.get("contentDetails") or {}).get("regionRestriction") or {}
        return bool(rr.get("allowed"))

    def _get_detail(vid):
        try:
            d = api_get(
                f"https://www.googleapis.com/youtube/v3/videos"
                f"?part=snippet,statistics,contentDetails&id={vid}&key={youtube_key}"
            )
            item = d["items"][0] if d.get("items") else {}
            views = int(item.get("statistics", {}).get("viewCount", 0))
            dur   = item.get("contentDetails", {}).get("duration", "PT999S")
            desc  = item.get("snippet", {}).get("description", "")
            return views, dur, desc, _region_locked(item)
        except Exception:
            return 0, "PT999S", "", False

    # ── 優先チャンネル
    for ch in priority_channels[:5]:
        log(f"📡 優先チャンネル: {ch.get('name','?')}")
        try:
            p = {"part": "snippet", "channelId": ch["id"], "type": "video",
                 "videoDuration": "short", "order": "date",
                 "maxResults": 5, "key": youtube_key}
            if allow_long:
                p.pop("videoDuration", None)   # 原典（配信アーカイブ等）も拾う
            if cutoff:
                p["publishedAfter"] = cutoff
            data = api_get(f"https://www.googleapis.com/youtube/v3/search?{urllib.parse.urlencode(p)}")
            for item in data.get("items", []):
                vid = item["id"].get("videoId")
                if not vid:
                    continue
                views, dur, desc, locked = _get_detail(vid)
                if locked or not (5 <= _parse_duration(dur) <= dur_max):
                    continue
                _add(vid, item["snippet"]["title"], item["snippet"]["channelTitle"],
                     views, item["snippet"]["thumbnails"].get("medium", {}).get("url", ""), True,
                     desc=desc, dur_sec=_parse_duration(dur))
        except Exception as e:
            log(f"⚠️ {ch.get('name','?')} 取得失敗: {e}")

    # ── AI生成クエリ検索（DBの検索意図をGeminiが解釈したもの）
    if ai_queries:
        for q in ai_queries:
            kw = q.get("keyword", "")
            if not kw:
                continue
            log(f"🧠 AI検索: '{kw}' [{q.get('category','')}]")
            try:
                p = {"part": "snippet", "q": kw, "type": "video",
                     "videoDuration": "short", "order": "date",
                     "maxResults": 10, "key": youtube_key}
                if allow_long:
                    p.pop("videoDuration", None)
                if cutoff:
                    p["publishedAfter"] = cutoff
                data = api_get(f"https://www.googleapis.com/youtube/v3/search?{urllib.parse.urlencode(p)}")
                vids = [item["id"].get("videoId") for item in data.get("items", [])
                        if item["id"].get("videoId")]
                if not vids:
                    continue
                d2 = api_get(
                    f"https://www.googleapis.com/youtube/v3/videos"
                    f"?part=snippet,statistics,contentDetails&id={','.join(vids)}&key={youtube_key}"
                )
                for item in d2.get("items", []):
                    vid = item["id"]
                    if _region_locked(item):
                        continue
                    dur = item.get("contentDetails", {}).get("duration", "PT999S")
                    if not (5 <= _parse_duration(dur) <= dur_max):
                        continue
                    views = int(item["statistics"].get("viewCount", 0))
                    thumb = item["snippet"]["thumbnails"].get("medium", {}).get("url", "")
                    _add(vid, item["snippet"]["title"], item["snippet"]["channelTitle"],
                         views, thumb, False,
                         desc=item["snippet"].get("description", ""),
                         dur_sec=_parse_duration(dur))
            except Exception as e:
                log(f"⚠️ AI検索失敗({kw}): {e}")

    # ── 新着検索（AIクエリがない場合のフォールバック）
    if not ai_queries:
        FRESH_KEYWORDS = ["funny", "amazing", "viral", "wtf", "unexpected",
                          "satisfying", "shocking", "insane", "try not to laugh"]
        import random
        if search_keywords:
            custom = [k.strip() for k in search_keywords.split(",") if k.strip()]
            kw = random.choice(custom)
        else:
            kw = random.choice(FRESH_KEYWORDS)
        for cat in categories[:2]:
            log(f"🆕 新着検索(fallback): '{kw}' / カテゴリ{cat}")
            try:
                p = {"part": "snippet", "q": kw, "type": "video",
                     "videoDuration": "short",
                     "videoCategoryId": cat, "order": "date",
                     "maxResults": 10, "key": youtube_key}
                if allow_long:
                    p.pop("videoDuration", None)
                if cutoff:
                    p["publishedAfter"] = cutoff
                data = api_get(f"https://www.googleapis.com/youtube/v3/search?{urllib.parse.urlencode(p)}")
                vids = [item["id"].get("videoId") for item in data.get("items", [])
                        if item["id"].get("videoId")]
                if not vids:
                    continue
                d2 = api_get(
                    f"https://www.googleapis.com/youtube/v3/videos"
                    f"?part=snippet,statistics,contentDetails&id={','.join(vids)}&key={youtube_key}"
                )
                for item in d2.get("items", []):
                    vid = item["id"]
                    if _region_locked(item):
                        continue
                    dur = item.get("contentDetails", {}).get("duration", "PT999S")
                    if not (5 <= _parse_duration(dur) <= dur_max):
                        continue
                    views = int(item["statistics"].get("viewCount", 0))
                    thumb = item["snippet"]["thumbnails"].get("medium", {}).get("url", "")
                    _add(vid, item["snippet"]["title"], item["snippet"]["channelTitle"],
                         views, thumb, False,
                         desc=item["snippet"].get("description", ""),
                         dur_sec=_parse_duration(dur))
            except Exception as e:
                log(f"⚠️ 新着検索失敗: {e}")

    # ── トレンド（fallback：新着で足りない場合）
    if len(results) < 3:
        for cat in categories[:3]:
            log(f"🔍 トレンド(fallback): カテゴリ {cat}")
            try:
                p = urllib.parse.urlencode({
                    "part": "snippet,statistics,contentDetails",
                    "chart": "mostPopular",
                    "videoCategoryId": cat, "maxResults": 10, "key": youtube_key
                })
                data = api_get(f"https://www.googleapis.com/youtube/v3/videos?{p}")
                for item in data.get("items", []):
                    vid = item["id"]
                    if _region_locked(item):
                        continue
                    dur = item.get("contentDetails", {}).get("duration", "PT999S")
                    if not (5 <= _parse_duration(dur) <= dur_max):
                        continue
                    views = int(item["statistics"].get("viewCount", 0))
                    thumb = item["snippet"]["thumbnails"].get("medium", {}).get("url", "")
                    _add(vid, item["snippet"]["title"], item["snippet"]["channelTitle"],
                         views, thumb, False,
                         desc=item["snippet"].get("description", ""),
                         dur_sec=_parse_duration(dur))
            except Exception as e:
                log(f"⚠️ トレンド取得失敗: {e}")

    # ── 最終ダブりチェック（念のため再照合）
    before = len(results)
    results = [v for v in results if v["id"] not in used_ids]
    dupes = before - len(results)
    if dupes:
        log(f"🚫 重複除去: {dupes}件を除外")
    log(f"✅ 合計 {len(results)} 件発見（新規のみ・処理済みスキップ済み）")
    return results


def generate_search_queries(model, log: LOG_CB, gemini_rot=None) -> list[dict]:
    """
    DBの検索意図・学習ログ・DNAをGeminiに読ませて
    今回の検索クエリを動的生成する。
    Returns: [{"keyword": str, "category": str, "note": str}, ...]
    """
    import db
    intents     = db.get_search_intents()
    dna         = db.get_dna()
    logs        = db.get_learning_logs(20)
    trend_logs  = db.get_trend_logs(5)   # 直近5回のトレンド
    used_cnt    = len(db.get_used_video_ids())

    if not intents:
        log("💡 search_intentが未登録 → デフォルトキーワードを使用")
        return []

    perf_summary = [
        {"name": l.get("project_name", ""), "score": l.get("feedback_score"),
         "views": l.get("peak_views", 0)}
        for l in logs if l.get("peak_views", 0) > 0
    ][:5]

    # 鮮度スコア付きトレンドサマリを構築
    trend_summary = []
    for t in trend_logs:
        freshness = t.get("freshness", 0.5)
        age_days  = t.get("age_days", 0)
        # 鮮度0.2未満は古すぎるので除外
        if freshness < 0.2:
            continue
        trend_summary.append({
            "date":      t.get("recorded_at", "")[:10],
            "age_days":  age_days,
            "freshness": freshness,
            "keywords":  t.get("keywords", [])[:6],
            "genres":    [g.get("name", "") for g in t.get("genres", [])][:4],
            "summary":   t.get("summary", "")[:80],
        })

    prompt = f"""
あなたはYouTube動画検索の専門家です。
以下の情報を元に、今回のYouTube検索クエリを生成してください。

【ユーザーが登録した検索意図（最優先）】
{json.dumps(intents, ensure_ascii=False, indent=2)}

【編集スタイルの好み（DNA）】
{dna.get("aesthetic_summary", "未設定")}

【過去の成功実績】
{json.dumps(perf_summary, ensure_ascii=False)}

【トレンド履歴（freshness=鮮度: 1.0が最新、0.1が古い）】
{json.dumps(trend_summary, ensure_ascii=False, indent=2)}

【処理済み動画数】
{used_cnt}件（重複は自動スキップされます）

JSONのみ返答（コードブロック不要）:
[
  {{"keyword": "検索キーワード", "category": "カテゴリ（vtuber/funny/gaming等）", "note": "選んだ理由（日本語）"}},
  ...最大8件
]

注意:
- ユーザーの検索意図（VTuberなど）を最優先にする
- VTuberの場合は「VTuber名 切り抜き」「VTuber名 面白い」「VTuber名 神回」などを組み合わせる
- freshness が高いトレンドほど重視し、古いトレンド（freshness低）は参考程度にとどめる
- トレンドキーワードと検索意図を掛け合わせると相乗効果がある
- 同じ対象が重複しないよう多様性を持たせる
"""

    raw = _gemini_generate_with_retry(model, prompt, log, gemini_rot=gemini_rot)
    if not raw:
        log("⚠️ クエリ生成失敗 → デフォルトキーワードを使用")
        return []

    try:
        raw = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        queries = json.loads(raw)
        log(f"🧠 Geminiが{len(queries)}件の検索クエリを生成:")
        for q in queries:
            log(f"   • [{q.get('category','')}] {q.get('keyword','')} → {q.get('note','')}")
        return queries
    except Exception as e:
        log(f"⚠️ クエリJSON解析失敗: {e}")
        return []


def _parse_duration(iso: str) -> int:
    """ISO 8601 duration → 秒数"""
    import re
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso)
    if not m:
        return 999
    h, mn, s = (int(x or 0) for x in m.groups())
    return h * 3600 + mn * 60 + s


# ════════════════════════════════════════════════════════
#  Step 2: AI スコアリング（どの動画を採用するか）
# ════════════════════════════════════════════════════════
def score_videos(model, videos: list[dict], log: LOG_CB, gemini_rot=None,
                 source_preference: str = "any") -> list[dict]:
    """
    Gemini にタイトル・チャンネル・概要欄・尺・再生数を渡してスコアリング＋素性判定。
    score: 0–100、reason: 理由、source_type: original/clip/repost

    素性判定はキーワードでは12言語に対応できないため Gemini に分類させる。
    弾かずに信号として使い、source_preference で重み付けする：
      prefer_original … 原典+15 / 切り抜き-10 / 転載-25
      original_only   … 切り抜き・転載を除外（判定不能 unknown は残す）
      any             … 重み付けなし（従来通り）
    """
    log("🤖 AI スコアリング中...")
    if not videos:
        return []

    from channel_learner import build_learning_prompt_context
    learning_ctx = build_learning_prompt_context()

    items_json = json.dumps([
        {"id": v["id"], "title": v["title"],
         "channel": v["channel"], "views": v["views"],
         "duration_sec": v.get("dur_sec", 0),
         "description": (v.get("desc") or "")[:200]}
        for v in videos
    ], ensure_ascii=False)

    prompt = f"""
以下の海外動画リストを、日本語解説チャンネルとして採用すべきか評価してください。
JSONのみ返答（コードブロック不要）。
{learning_ctx}

評価基準:
- バズりやすさ（再生数・話題性）
- 日本人が知らなそうな文化的面白さ
- 字幕・解説を付けることで価値が増すか

さらに各動画の「素性」を、タイトル・チャンネル名・概要欄・尺から判定してください:
- "original": 本人・公式チャンネルの投稿（配信アーカイブや長尺はほぼこれ）
- "clip":     他人が本人の映像を切り抜き・編集した動画（クレジット表記・許可切り抜きを含む）
- "repost":   無断転載・コンピレーション・出所不明の寄せ集め
- "unknown":  判断材料が足りない

返答形式:
[
  {{"id": "動画ID", "score": 0-100の整数, "reason": "30文字以内の理由", "title_jp": "日本語タイトル案", "source_type": "original/clip/repost/unknown"}},
  ...
]

動画リスト:
{items_json}
"""
    raw = _gemini_generate_with_retry(model, prompt, log, gemini_rot=gemini_rot)
    if raw is None:
        for v in videos:
            v["score"]    = 65 + (10 if v.get("priority") else 0)
            v["reason"]   = ""
            v["title_jp"] = v["title"]
            v["source_type"] = "unknown"
    else:
        try:
            raw = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
            scores = json.loads(raw)
            score_map = {s["id"]: s for s in scores}
            for v in videos:
                s = score_map.get(v["id"], {})
                v["score"]    = s.get("score", 50)
                v["reason"]   = s.get("reason", "")
                v["title_jp"] = s.get("title_jp", v["title"])
                st = str(s.get("source_type", "unknown")).lower()
                v["source_type"] = st if st in ("original", "clip", "repost") else "unknown"
        except Exception as e:
            log(f"⚠️ スコアリングJSON解析失敗: {e}")
            for v in videos:
                v["score"]    = 65 + (10 if v.get("priority") else 0)
                v["reason"]   = ""
                v["title_jp"] = v["title"]
                v["source_type"] = "unknown"

    # 素性による重み付け（弾くのは original_only の明確な clip/repost だけ）
    _ST_JP = {"original": "原典", "clip": "切り抜き", "repost": "転載", "unknown": "不明"}
    if source_preference == "prefer_original":
        bonus = {"original": 15, "clip": -10, "repost": -25}
        for v in videos:
            b = bonus.get(v.get("source_type"), 0)
            if b:
                v["score"] = max(0, min(100, v["score"] + b))
    elif source_preference == "original_only":
        before = len(videos)
        dropped = [v for v in videos if v.get("source_type") in ("clip", "repost")]
        videos  = [v for v in videos if v.get("source_type") not in ("clip", "repost")]
        if dropped:
            log(f"🚫 原典のみ設定: {before - len(videos)}件を除外"
                f"（{'、'.join(_ST_JP[d['source_type']] + ':' + d['title'][:18] for d in dropped[:3])}…）")
        if not videos:
            log("⚠️ 原典が見つかりませんでした（設定「原典のみ」）")
            return []

    # 優先チャンネル +10 ボーナス
    for v in videos:
        if v.get("priority"):
            v["score"] = min(100, v["score"] + 10)

    videos.sort(key=lambda x: x["score"], reverse=True)
    top = videos[0]
    log(f"✅ スコアリング完了 (Top: {top['title'][:30]} / {top['score']}点"
        f" / 素性:{_ST_JP.get(top.get('source_type', 'unknown'), '不明')})")
    return videos


# ════════════════════════════════════════════════════════
#  Step 3: ダウンロード（yt-dlp）
# ════════════════════════════════════════════════════════
def _get_ffmpeg_exe() -> Optional[str]:
    """imageio_ffmpeg からffmpegの実行ファイルパスを取得"""
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def _ffmpeg_dir_for_ytdlp() -> Optional[str]:
    """
    yt-dlp に渡せる ffmpeg のディレクトリを返す。

    imageio_ffmpeg の実体は "ffmpeg-win-x86_64-v7.1.exe" のような名前で、
    yt-dlp は "ffmpeg(.exe)" という名前しか認識しない。そのままでは
    区間DL(download_ranges)が「ffmpeg is not installed」で失敗する。
    正しい名前の複製を一度だけ作り、そのディレクトリを渡す。
    """
    exe = _get_ffmpeg_exe()
    if not exe:
        return None
    src = Path(exe)
    if src.stem == "ffmpeg":
        return str(src.parent)
    import tempfile, shutil
    d = Path(tempfile.gettempdir()) / "tomato_ffmpeg"
    dst = d / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
    try:
        if not dst.exists() or dst.stat().st_size != src.stat().st_size:
            d.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        return str(d)
    except Exception:
        return None


def probe_rotation(path: str) -> int:
    """
    動画の回転メタデータ（度）を返す。無ければ 0。
    ffprobe は同梱していないので ffmpeg のログから読む。
    ffmpeg 5+ は "displaymatrix: rotation of -90.00 degrees" 形式
    （moviepy 1.0.3 は旧形式の "rotate :" しか見ないので常に0と誤検出する）。
    """
    ff = _get_ffmpeg_exe()
    if not ff:
        return 0
    try:
        import subprocess, re
        r = subprocess.run([ff, "-hide_banner", "-i", str(path)],
                           capture_output=True, timeout=30)
        log_text = r.stderr.decode("utf-8", "ignore")
        m = re.search(r"rotation of (-?[\d.]+) degrees", log_text)
        if m:
            return int(round(float(m.group(1)))) % 360
        m = re.search(r"rotate\s*:\s*(\d+)", log_text)   # 旧形式も一応見る
        if m:
            return int(m.group(1)) % 360
    except Exception:
        pass
    return 0


# これより長い動画は「見せ場を選んでから切る」。
# 元々ショートだけを対象にしていた頃はDLしてから丸ごと解析していたが、
# 長尺（配信アーカイブ＝原典）は丸ごと解析できない：
# 2時間 = 7200秒 x 300トークン/秒 = 216万トークンでコンテキスト上限を超える。
_LONG_VIDEO_SEC = 180
_CLIP_SEC = 60


def pick_highlight_segment(video_id: str, model, config: dict, log: LOG_CB):
    """
    長尺動画なら (start, end) を返す。短い動画・材料が無い動画は None
    （＝従来どおり全体をDLして解析する）。
    """
    url = f"https://www.youtube.com/watch?v={video_id}"
    try:
        import highlights
        info = highlights.fetch_video_meta(url, log)
        dur = float(info.get("duration") or 0)
        if dur and dur <= _LONG_VIDEO_SEC:
            return None                     # 短い動画はそのまま扱える
        if not dur:
            return None
        log(f"🔎 長さ {int(dur)//60}分 の動画 → 見せ場を探します")
        hs = highlights.find_highlights(
            url, model, log=log, want=1, clip_sec=_CLIP_SEC,
            lang=config.get("output_language", "ja"))
        if not hs:
            log("⚠️ 見せ場を特定できませんでした → 冒頭から切り出します")
            return (0.0, min(dur, _CLIP_SEC))
        return (hs[0]["start"], hs[0]["end"])
    except Exception as e:
        log(f"⚠️ 見せ場の検出に失敗（全体をDLします）: {e}")
        return None


def normalize_video(path: str, log: LOG_CB) -> str:
    """
    回転メタデータを映像に焼き込み、メタデータを取り除いた動画を返す。

    なぜ必要か: 同じファイルを ffmpeg は自動回転して縦(1080x1920)として読み、
    moviepy は回転を無視して横(1920x1080)として読む。この食い違いのせいで
    「編集後の動画が横になる」。素材の時点で回転を無くしておけば、
    以降のすべての経路が同じ寸法を見るようになる。
    回転が無い動画（大多数）は再エンコードせずそのまま返す。
    """
    rot = probe_rotation(path)
    if rot == 0:
        return path
    ff = _get_ffmpeg_exe()
    if not ff:
        log(f"⚠️ 回転{rot}°を検出しましたが ffmpeg が無く補正できません")
        return path
    src = Path(path)
    out = src.with_name(src.stem + "_upright.mp4")
    log(f"🔄 回転{rot}°を検出 → 映像に焼き込んで正規化します")
    try:
        import subprocess
        # ffmpeg は入力時に自動回転して読むので、そのまま焼き直して
        # 出力側の回転メタデータを 0 にする（=見たままの向きで固定）。
        r = subprocess.run([
            ff, "-y", "-hide_banner", "-loglevel", "error", "-i", str(src),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
            "-pix_fmt", "yuv420p", "-metadata:s:v", "rotate=0",
            "-c:a", "copy", str(out)
        ], capture_output=True, timeout=900)
        if r.returncode != 0 or not out.exists():
            log(f"⚠️ 回転補正に失敗（元の動画で続行）: {r.stderr.decode('utf-8','ignore')[-160:]}")
            return path
        log(f"✅ 回転補正しました → {out.name}")
        return str(out)
    except Exception as e:
        log(f"⚠️ 回転補正に失敗（元の動画で続行）: {e}")
        return path


def download_video(video_id: str, out_dir: str, log: LOG_CB,
                   start: float = None, end: float = None) -> Optional[str]:
    url      = f"https://www.youtube.com/watch?v={video_id}"   # 長尺・ショート両対応
    out_tmpl = str(Path(out_dir) / f"{video_id}.%(ext)s")

    ffmpeg_exe = _get_ffmpeg_exe()
    opts = {
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "outtmpl": out_tmpl,
        "quiet": True,
        "no_warnings": True,
        "merge_output_format": "mp4",
    }
    # yt-dlp に ffmpeg の場所を教える（区間DLに必須）。
    # opts["ffmpeg_location"] だけでは足りない：区間DLの可否を決める
    # FFmpegFD.available() は引数なしのクラスメソッドで、渡した opts を
    # 見ずに FFmpegPostProcessor._ffmpeg_location（ContextVar）だけを見る。
    # そこへ入れておかないと「ffmpeg is not installed」で弾かれる。
    ff_dir = _ffmpeg_dir_for_ytdlp()
    if ff_dir:
        opts["ffmpeg_location"] = ff_dir
        try:
            from yt_dlp.postprocessor.ffmpeg import FFmpegPostProcessor
            FFmpegPostProcessor._ffmpeg_location.set(ff_dir)
        except Exception:
            pass
    elif ffmpeg_exe:
        opts["ffmpeg_location"] = ffmpeg_exe
    # 区間指定。長尺の原典から見せ場だけを落とすために使う
    # （2時間の配信を丸ごと落とさずに済む）。
    if start is not None and end is not None and end > start:
        try:
            from yt_dlp.utils import download_range_func
            opts["download_ranges"] = download_range_func(None, [(float(start), float(end))])
            opts["force_keyframes_at_cuts"] = True
            log(f"⬇️  ダウンロード中（{int(start)//60:02d}:{int(start)%60:02d}"
                f"–{int(end)//60:02d}:{int(end)%60:02d} の区間のみ）: {url}")
        except Exception as e:
            log(f"⚠️ 区間指定に失敗、全体をDLします: {e}")
            log(f"⬇️  ダウンロード中: {url}")
    else:
        log(f"⬇️  ダウンロード中: {url}")
    # クラウド（データセンターIP）対策：cookies / proxy を環境変数から任意注入。
    # 未設定なら従来通り（ローカルPCでは不要）。CLOUD_NOTES.md の最重要リスク対策。
    _cookiefile = os.environ.get("YTDLP_COOKIEFILE", "")
    if _cookiefile and Path(_cookiefile).exists():
        opts["cookiefile"] = _cookiefile
    _proxy = os.environ.get("YTDLP_PROXY", "")
    if _proxy:
        opts["proxy"] = _proxy
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
        mp4 = next(Path(out_dir).glob(f"{video_id}*.mp4"), None)
        if mp4:
            log(f"✅ DL完了: {mp4.name}")
            # 回転メタデータ付き素材は ffmpeg と moviepy で解釈が食い違い、
            # 編集後の映像が横になる。ここで正規化して以降を安全にする。
            return normalize_video(str(mp4), log)
        log("⚠️ DLファイルが見つかりません")
        return None
    except Exception as e:
        log(f"❌ DL失敗: {e}")
        return None


# ════════════════════════════════════════════════════════
#  Gemini 429 リトライヘルパー
# ════════════════════════════════════════════════════════
_FALLBACK_MODEL = FALLBACK_MODEL
# 503(サーバー混雑)が続くときに順に試す代替モデル。
# 混雑しているモデルとは別の容量プールに逃がして成功率を上げる。
_CONGESTION_FALLBACK_CHAIN = [FALLBACK_MODEL, "gemini-3.5-flash"]


def _gemini_call(client, contents, log: LOG_CB = None) -> str:
    """
    新API: client.models.generate_content を呼ぶ。
    設定中のモデルが廃止・未対応（404 NOT_FOUND等）の場合は、
    安定版モデルに自動フォールバックして再試行する
    （Geminiのモデルラインナップが刷新されても壊れないための保険）。
    """
    model_name = client._model_name
    try:
        resp = client.models.generate_content(model=model_name, contents=contents)
        return resp.text
    except Exception as e:
        err = str(e)
        if "429" in err or "quota" in err.lower():
            raise  # クォータ超過は呼び出し元のキーローテーションに任せる
        if not any(x in err for x in ("NOT_FOUND", "is not found",
                                      "not supported", "no longer available")):
            raise
        # 設定モデルが廃止されていた。生きているモデルを順に試す。
        # （以前は「逃げ先＝既定モデル」だったため、既定が廃止された瞬間に
        #   保険が一切作動せず、新規ユーザーだけ解析が全滅していた）
        for alt in [FALLBACK_MODEL, DEFAULT_MODEL, "gemini-3.5-flash"]:
            if alt == model_name:
                continue
            try:
                if log:
                    log(f"⚠️ モデル「{model_name}」は利用できません → 「{alt}」に自動切替")
                resp = client.models.generate_content(model=alt, contents=contents)
                client._model_name = alt   # 以降はこのモデルを使う
                return resp.text
            except Exception:
                continue
        raise


def _gemini_generate_with_retry(client, prompt_parts, log: LOG_CB,
                                 max_retries: int = 4,
                                 gemini_rot=None) -> Optional[str]:
    """
    429 (quota exceeded) が返ったとき、別のキーで新しいClientを作ってリトライする。
    max_retries 回試みても失敗したら None を返す。
    """
    import re, random
    current_client = client
    congestion_count = 0
    tried_models = set()
    for attempt in range(1, max_retries + 1):
        try:
            return _gemini_call(current_client, prompt_parts, log=log)
        except Exception as e:
            err = str(e)
            # 503 サーバー混雑 → 「連打」せず、指数バックオフ+ジッターで待機。
            # 混雑が続く場合は別モデルに切り替えて空いている容量プールに逃がす。
            if "503" in err or "UNAVAILABLE" in err:
                congestion_count += 1
                if congestion_count >= 2:
                    cur_model = getattr(current_client, "_model_name", _FALLBACK_MODEL)
                    tried_models.add(cur_model)
                    next_model = next(
                        (m for m in _CONGESTION_FALLBACK_CHAIN if m not in tried_models), None)
                    if next_model:
                        cur_key = getattr(current_client, "_api_key", None) or getattr(client, "_api_key", "")
                        current_client = init_gemini(cur_key, next_model)
                        log(f"🔀 Gemini 503混雑が続くため「{cur_model}」→「{next_model}」にモデル切替")
                        congestion_count = 0
                        continue
                wait = min(2 ** attempt, 20) + random.uniform(0, 2)  # 初回短め+ジッター
                log(f"⏳ Gemini 503混雑 → {wait:.0f}秒待機してリトライ ({attempt}/{max_retries})...")
                time.sleep(wait)
                continue
            if "429" not in err and "quota" not in err.lower():
                raise
            # 日次クォータ超過ならキーを24時間BAN
            is_daily = any(x in err.lower() for x in ("perday", "per_day", "per day", "requestsperday"))
            if gemini_rot:
                cur_key = getattr(current_client, "_api_key", None)
                if is_daily and cur_key:
                    gemini_rot.ban_key(cur_key, 86400)
                if gemini_rot.count() >= 1:
                    try:
                        new_key = gemini_rot.next()
                        if new_key:
                            current_client = init_gemini(new_key, current_client._model_name)
                            log(f"🔄 Gemini 429 → キーローリング ({attempt}/{max_retries})")
                            continue
                    except Exception:
                        pass
            m = re.search(r"retry.*?(\d+)\s*s", err, re.IGNORECASE)
            wait = int(m.group(1)) + 3 if m else (5 if is_daily else 35)
            log(f"⏳ Gemini 429 → {wait}秒待機してリトライ ({attempt}/{max_retries})...")
            time.sleep(wait)
    log("❌ Gemini リトライ上限到達 → フォールバック使用")
    return None


_ANALYSIS_DEFAULT = {
    "title": "海外バズり動画", "subtitle": "今週の注目",
    "narration": "ご覧ください。", "description": "#海外ショート #バズり",
    "tags": ["海外ショート", "面白い", "バズり"],
    "captions": [], "cut_sections": [],
    "edit_params": {
        "font_size_title": 82, "font_size_subtitle": 54, "font_size_caption": 58,
        "rewind_enabled": True, "freeze_enabled": True,
        "fastforward_enabled": True, "fastforward_speed": 2.0,
        "zoom_enabled": True, "monochrome_enabled": True,
        "flip_enabled": True, "mosaic_enabled": True,
        "extend_target": -1, "extend_method": "endcard",
    },
}


# ════════════════════════════════════════════════════════
#  Step 4: Gemini 解析（文字起こし・カット点・字幕・メタ）
# ════════════════════════════════════════════════════════
_LANG_NAMES = {
    "ja": "日本語", "en": "English", "es": "Español", "pt": "Português",
    "de": "Deutsch", "fr": "Français", "id": "Bahasa Indonesia", "hi": "हिन्दी",
    "ko": "한국어", "it": "Italiano", "tr": "Türkçe", "nl": "Nederlands",
}

_LANG_STYLE = {
    "ja": (
        "全て日本語で\n\n"
        "【最重要】captions の text は絶対に日本語で書くこと。英語は一切禁止。\n"
        "動画の音声・会話の内容をそのまま書かず、日本語でユーモアたっぷりに意訳・実況すること。\n"
        "例: 「草生えるw」「これはヤバい（笑）」「え、待って天才すぎ」「ガチで爆笑した」など。"
    ),
    "en": (
        "Write everything in English.\n\n"
        "IMPORTANT: captions text MUST be in English only — no Japanese.\n"
        "Don't just transcribe the video's audio verbatim — add witty, reaction-style commentary in English.\n"
        'Examples: "no because how—", "I\'m actually deceased 💀", "wait this is genuinely insane", '
        '"the way he just—" etc.'
    ),
    "es": ("Escribe todo en español.\n\nIMPORTANTE: el texto de captions debe estar "
           "completamente en español, nada de inglés.\nNo transcribas literalmente el "
           "audio del video — añade comentarios ingeniosos y de reacción, en español.\n"
           'Ejemplos: "no manches, esto está brutal", "jajaja no puede ser", "esto me rompió", '
           '"quedé en shock" etc.'),
    "pt": ("Escreva tudo em português (Brasil).\n\nIMPORTANTE: o texto das captions deve "
           "estar totalmente em português, nada de inglês.\nNão transcreva literalmente o "
           "áudio do vídeo — adicione comentários engraçados e de reação, em português.\n"
           'Exemplos: "gente, isso é surreal", "eu morri 💀", "para tudo, o quê?", '
           '"kkkkk não acredito" etc.'),
    "de": ("Schreibe alles auf Deutsch.\n\nWICHTIG: Der captions-Text muss komplett auf "
           "Deutsch sein, kein Englisch.\nTranskribiere das Video-Audio nicht wörtlich — "
           "füge witzige Reaktionskommentare auf Deutsch hinzu.\n"
           'Beispiele: "das ist doch nicht dein Ernst", "ich bin fix und fertig 💀", '
           '"warte, was?!", "das ist der Wahnsinn" usw.'),
    "fr": ("Écris tout en français.\n\nIMPORTANT : le texte des captions doit être "
           "entièrement en français, aucun anglais.\nNe transcris pas simplement l'audio "
           "de la vidéo — ajoute des commentaires drôles et réactifs en français.\n"
           'Exemples : "non mais attends quoi", "je suis morte de rire 💀", '
           '"c\'est complètement dingue", "osef, c\'est énorme" etc.'),
    "id": ("Tulis semuanya dalam Bahasa Indonesia.\n\nPENTING: teks captions harus "
           "sepenuhnya dalam Bahasa Indonesia, tanpa bahasa Inggris.\nJangan hanya "
           "transkrip audio videonya — tambahkan komentar reaksi yang lucu dalam "
           'Bahasa Indonesia.\nContoh: "anjay gila sih ini", "ga nyangka banget", '
           '"ini ngakak parah", "santuy tapi mantap" dll.'),
    "hi": ("सब कुछ हिन्दी में लिखें।\n\nमहत्वपूर्ण: captions का टेक्स्ट पूरी तरह हिन्दी में "
           "होना चाहिए, अंग्रेज़ी बिल्कुल नहीं।\nवीडियो के ऑडियो को सीधे मत लिखो — मज़ेदार "
           "रिएक्शन कमेंट्री हिन्दी में जोड़ो।\n"
           'उदाहरण: "ये तो हद हो गई भाई", "मैं हस हस के मर गया 💀", "रुको क्या?!", '
           '"ये पागलपन है" आदि।'),
    "ko": ("모든 내용을 한국어로 작성하세요.\n\n중요: captions 텍스트는 반드시 한국어로만 "
           "작성하고 영어는 절대 사용하지 마세요.\n영상 음성을 그대로 옮기지 말고, 한국어로 "
           "재치있는 리액션 코멘트를 추가하세요.\n"
           '예시: "이거 실화냐 ㅋㅋㅋ", "미쳤다 진짜", "나 지금 숨넘어감", "소름 돋았잖아" 등.'),
    "it": ("Scrivi tutto in italiano.\n\nIMPORTANTE: il testo delle captions deve essere "
           "completamente in italiano, niente inglese.\nNon trascrivere semplicemente "
           "l'audio del video — aggiungi commenti divertenti e di reazione in italiano.\n"
           'Esempi: "no vabbè, aspetta", "sono morto dal ridere 💀", "questa è pazzesca", '
           '"non ci credo proprio" ecc.'),
    "tr": ("Her şeyi Türkçe yaz.\n\nÖNEMLİ: captions metni tamamen Türkçe olmalı, "
           "kesinlikle İngilizce olmamalı.\nVideonun sesini birebir yazma — Türkçe, "
           "esprili tepki yorumları ekle.\n"
           'Örnekler: "yok artık ya bu ne", "güldüm resmen 💀", "dur ne oluyor", '
           '"bu efsane olmuş" gibi.'),
    "nl": ("Schrijf alles in het Nederlands.\n\nBELANGRIJK: de captions-tekst moet volledig "
           "in het Nederlands zijn, geen Engels.\nTranscribeer het audio van de video niet "
           "letterlijk — voeg grappige reactie-commentaar toe in het Nederlands.\n"
           'Voorbeelden: "wacht even wat", "ik lig eronder 💀", "dit is echt bizar", '
           '"nee toch zeker" enz.'),
}


# 出力言語が非ラテン文字の言語（ja/ko/hi）なのに字幕がラテン文字だらけ＝
# モデルが指示を無視して音声を逐語書き起こしした取りこぼし（実例あり:
# output_language=ja で "aye. that's ripe enough for cake." が焼かれた）。
# プロンプトで禁止しても時々起きるので、解析後に検出して書き直す。
# ラテン文字言語同士（en/es等）は文字種で判定できないため対象外。
_NONLATIN_SCRIPT_LANGS = {"ja", "ko", "hi"}


def _looks_wrong_lang(text: str, lang: str) -> bool:
    if lang not in _NONLATIN_SCRIPT_LANGS:
        return False
    letters = [c for c in str(text) if c.isalpha()]
    if len(letters) < 4:          # 「w」「LOL」程度の混じりは誤検出しない
        return False
    return sum(1 for c in letters if c.isascii()) / len(letters) > 0.7


def _fix_text_language(client, data: dict, lang: str, log: LOG_CB) -> dict:
    """captions/title等が出力言語になっていなければ、テキストだけ翻訳し直す保険。"""
    import re
    caps = data.get("captions") or []
    bad = [i for i, c in enumerate(caps)
           if isinstance(c, dict) and _looks_wrong_lang(c.get("text", ""), lang)]
    singles = [k for k in ("title", "subtitle", "narration")
               if _looks_wrong_lang(data.get(k, ""), lang)]
    if not bad and not singles:
        return data
    lang_name = _LANG_NAMES.get(lang, "日本語")
    log(f"⚠️ 字幕が{lang_name}になっていません（{len(bad) + len(singles)}件）→ 書き直します")
    texts = [caps[i].get("text", "") for i in bad] + [str(data.get(k, "")) for k in singles]
    prompt = (
        f"以下はショート動画の字幕テキストです。逐語訳ではなく、{lang_name}の"
        f"視聴者向けにユーモアのある実況・意訳スタイルで、すべて{lang_name}に書き直してください。\n"
        "同じ順序・同じ件数のJSON配列（文字列のみ）で返答。コードブロック不要。\n"
        + json.dumps(texts, ensure_ascii=False)
    )
    try:
        raw = _gemini_call(client, prompt, log=log)
        raw = re.sub(r"^```(?:json)?|```$", "", (raw or "").strip(), flags=re.M).strip()
        fixed = json.loads(raw)
        if not (isinstance(fixed, list) and len(fixed) == len(texts)):
            raise ValueError(f"件数不一致: {len(texts)}→{len(fixed) if isinstance(fixed, list) else '?'}")
    except Exception as e:
        log(f"⚠️ 字幕の書き直しに失敗（原文のまま続行）: {str(e)[:80]}")
        return data
    for j, i in enumerate(bad):
        caps[i]["text"] = str(fixed[j])
    for j, k in enumerate(singles):
        data[k] = str(fixed[len(bad) + j])
    log(f"✅ 字幕を{lang_name}に書き直しました")
    return data


def _manual_cut_context() -> str:
    """
    編集DNA還流：台本編集でユーザーが手動カットした行（learning_log.edit_changes）の
    ダイジェストを解析プロンプトに注入する。記録ゼロなら空文字＝完全に従来動作。
    ユーザーがAIの完成動画から切った部分＝編集への最も純度の高いダメ出し。
    """
    try:
        import db
        logs = db.get_learning_logs(20)
    except Exception:
        return ""
    texts = []
    for l in logs:
        try:
            ec = json.loads(l.get("edit_changes") or "{}")
        except Exception:
            continue
        if ec.get("mode") != "script_edit":
            continue
        for t in ec.get("cut_texts") or []:
            t = str(t).strip()
            if t and t not in texts:
                texts.append(t)
    if not texts:
        return ""
    digest = " ／ ".join(texts[:15])[:500]
    return ("\n【ユーザーが過去に手動でカットした部分（重要な学習データ）】\n"
            f"{digest}\n"
            "→ この種の内容の区間は、最初からカットするか大幅に短くすること。\n")


def analyze_video(model, video_path: str, log: LOG_CB, gemini_rot=None, chat_context: str = "",
                  output_lang: str = "ja") -> dict:
    log("🔬 Gemini で動画解析中...")
    current_client = model  # 新APIではclientを受け取る

    def _rotate_client(err_str: str = ""):
        nonlocal current_client
        is_daily = any(x in err_str.lower() for x in ("perday", "per_day", "per day", "requestsperday"))
        if gemini_rot:
            cur_key = getattr(current_client, "_api_key", None)
            if is_daily and cur_key:
                gemini_rot.ban_key(cur_key, 86400)
            if gemini_rot.count() >= 1:
                new_key = gemini_rot.next()
                if new_key:
                    current_client = init_gemini(new_key, current_client._model_name)
                    return True
        return False

    from channel_learner import build_learning_prompt_context
    learning_ctx = build_learning_prompt_context()
    manual_ctx = _manual_cut_context()
    if manual_ctx:
        log("  🧬 過去の手動カットを学習データとして注入")

    ctx_block = ""
    if chat_context:
        ctx_block = f"\n{chat_context}\n上記のユーザー指示・嗜好を最優先で反映してください。\n"

    # フォントカタログ（Geminiが動画の雰囲気で選ぶ）
    try:
        from editor import FONT_CATALOG as _FC
        font_block = (
            "\n注意（font_style について）:\n"
            "- 動画の雰囲気・ジャンルに最も合うフォントを以下から1つ選ぶこと\n"
            + "\n".join(f'- "{k}": {v["desc"]}' for k, v in _FC.items()) + "\n"
        )
    except Exception:
        font_block = ""

    lang_header = (
        f"\n【出力言語】以下すべてのテキスト項目"
        f"（title, subtitle, narration, description, tags, captions）は"
        f"{_LANG_NAMES.get(output_lang, '日本語')}で書いてください。\n"
    )

    prompt = learning_ctx + manual_ctx + ctx_block + font_block + lang_header + """
この動画を分析して、以下のJSONのみ返答してください（コードブロック不要）。

{
  "title":      "インパクトのあるタイトル（20文字以内）",
  "subtitle":   "サブタイトル（年代・カテゴリ、20文字以内）",
  "narration":  "冒頭の場面説明ナレーション（60文字以内）",
  "description":"YouTube の説明文（200文字、ハッシュタグ含む）",
  "tags":       ["タグ1","タグ2",...最大10個],
  "captions": [
    {"start": float, "end": float, "text": "ユーモアある字幕テキスト（指定された出力言語で）", "funny": bool,
     "x": 0.5, "y": 0.9}
  ],
  "cut_sections": [
    {"start": float, "end": float, "reason": "カット理由（無音/静止/冗長など）"}
  ],
  "sources": [
    {"account": "@アカウント名（元動画の投稿者）", "url": "https://youtube.com/shorts/動画ID"}
  ],
  "layout_hint": "この動画に最適な縦型レイアウトの方針（任意・AIが自由に決定）",
  "font_style": "standard",
  "rewind_at": null,
  "freeze_at": null,
  "freeze_duration": 1.5,
  "fastforward_at": null,
  "fastforward_end": null,
  "zoom_at": null,
  "zoom_end": null,
  "zoom_scale": 1.5,
  "monochrome_at": null,
  "monochrome_end": null,
  "flip_at": null,
  "flip_end": null,
  "mosaic_at": null,
  "mosaic_end": null,
  "edit_params": {
    "font_size_title":    82,
    "font_size_subtitle": 54,
    "font_size_caption":  58,
    "rewind_enabled":     true,
    "freeze_enabled":     true,
    "fastforward_enabled": true,
    "fastforward_speed":  2.0,
    "zoom_enabled":       true,
    "monochrome_enabled": true,
    "flip_enabled":       true,
    "mosaic_enabled":     true,
    "extend_target":      -1,
    "extend_method":      "endcard"
  }
}

注意（layout_hint について）:
- あくまで一例。AIが動画の内容・ジャンル・テンポに合わせて自由に決定してよい
- 例: "3ゾーン分割（上タイトル/中動画/下字幕）"
- 例: "全画面動画に半透明タイトルを重ねる"
- 例: "ランキング形式でバッジを左配置"

注意（sources について）:
- 必ず元動画のチャンネル名とURLを含める
- ランキング動画など複数素材を使う場合は最大5件まで
- account は「@」から始まる形式で

注意（rewind_at / freeze_at について）:
- rewind_at: 巻き戻しエフェクトを入れるのに最適なタイムスタンプ（秒）。驚き・ボケ・神プレーの直前が理想。不要なら null
- freeze_at: フリーズフレームを入れるのに最適なタイムスタンプ（秒）。笑えるシーン・決定的瞬間が理想。不要なら null
- freeze_duration: フリーズする秒数（0.5〜3.0）
- fastforward_at/fastforward_end: 早送りしたい退屈な区間（開始・終了秒）。前置き・無言・移動シーンなど間延びしている箇所が理想。不要なら null
- 全部 null でも可（演出不要な動画もある）

注意（zoom_at / monochrome_at / flip_at / mosaic_at について）:
- zoom_at/zoom_end: ズームイン区間（秒）。見せ場・神プレー・インパクトシーンを強調。zoom_scale=1.5〜3.0
- monochrome_at/monochrome_end: モノクロ区間（秒）。回想・シリアス・過去シーンの演出
- flip_at/flip_end: 左右反転区間（秒）。ボケ・シュール・笑いの演出
- mosaic_at/mosaic_end: モザイク区間（秒）。顔・文字・センシティブ箇所の隠蔽、またはコミカル演出
- 全部 null でも可（不要な場合はつけない）

注意（edit_params について）:
- この動画のジャンル・テンポ・雰囲気に合わせて、すべての値をAIが自由に決定すること
- font_size_title/subtitle/caption: 文字サイズ（px）。インパクト系は大きく（90〜110）、落ち着いた内容は控えめ（60〜80）
- rewind_enabled: 巻き戻し演出を使うか（盛り上がり・ボケ系はtrue、静かな内容はfalse）
- freeze_enabled: フリーズ演出を使うか（決定的瞬間がある動画はtrue）
- fastforward_enabled: 早送りを使うか（前置きが長い・間延びしている場合はtrue）
- fastforward_speed: 早送り速度（1.5〜4.0倍。退屈度に応じて）
- zoom_enabled: ズーム演出を使うか（アクション・スポーツ・驚きシーンはtrue）
- monochrome_enabled: モノクロ演出を使うか（回想・感動系コンテンツはtrue）
- flip_enabled: 反転演出を使うか（コメディ・ボケ動画はtrue）
- mosaic_enabled: モザイク演出を使うか（顔隠し・センシティブ素材を含む場合はtrue）
- extend_target: 尺伸ばしのターゲット秒数（-1=無効。短すぎる動画は58〜60を設定）
- extend_method: 尺伸ばし方法（"endcard"/"loop"/"replay"/"slowmo"から選択）

注意:
- cut_sections は無音・動きのない区間・冗長なシーンのみ（短すぎる動画はカットしない）
- 【重要】すべての秒数（captions・cut_sections・各エフェクト）は、いま見せている
  動画のタイムラインそのままで答えてください。カットや早送りを引き算しないこと。
  編集後のズレはこちらで補正します。
- funny=true のシーンには、その言語らしいリアクション表現を追加
""" + "\n" + _LANG_STYLE.get(output_lang, _LANG_STYLE["ja"])

    # ── アップロード＋解析を同じキーで一括リトライ
    for attempt in range(1, 9):
        # アップロード（同じclientで）
        video_file = None
        try:
            video_file = current_client.files.upload(
                file=video_path,
                config={"mime_type": "video/mp4"}
            )
        except Exception as e:
            err = str(e)
            if "429" in err or "quota" in err.lower():
                log(f"⏳ アップロード429 → キーローリング ({attempt}/8)")
                _rotate_client(err)
                continue
            log(f"❌ アップロード失敗: {e}")
            return dict(_ANALYSIS_DEFAULT)

        # 処理待ち
        while video_file.state.name == "PROCESSING":
            log("  Gemini アップロード処理中...")
            time.sleep(3)
            video_file = current_client.files.get(name=video_file.name)

        # generate_content（アップロードと同じclientで）
        try:
            raw = _gemini_call(current_client, [video_file, prompt], log=log)
            raw = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
            try:
                data = json.loads(raw)
            except Exception:
                log("⚠️ JSON解析失敗、デフォルト値を使用")
                data = dict(_ANALYSIS_DEFAULT)
            log(f"✅ 解析完了: {data.get('title')} / カット {len(data.get('cut_sections',[]))} 箇所")
            # 解析内容の詳細をチャットに表示
            ep = data.get("edit_params", {})
            captions = data.get("captions", [])
            cuts = data.get("cut_sections", [])
            effects = [k.replace("_enabled","") for k, v in ep.items() if k.endswith("_enabled") and v]
            log(f"  📝 タイトル: {data.get('title','')}")
            log(f"  🏷 サブタイトル: {data.get('subtitle','')}")
            if data.get("narration"):
                log(f"  🎙 ナレーション: {data.get('narration','')[:40]}...")
            log(f"  ✂️ カット: {len(cuts)}箇所 / 字幕: {len(captions)}件")
            if effects:
                log(f"  🎬 エフェクト: {', '.join(effects)}")
            if ep.get("extend_target", -1) > 0:
                log(f"  ⏱ 尺伸ばし: {ep['extend_target']}秒 ({ep.get('extend_method','endcard')})")
            if data.get("layout_hint"):
                log(f"  🖼 レイアウト: {data['layout_hint'][:50]}")
            if data.get("font_style"):
                log(f"  🔤 フォント: {data['font_style']}")
            try: current_client.files.delete(name=video_file.name)
            except Exception: pass
            # 保険: 字幕が出力言語になっていなければ書き直す（逐語書き起こし対策）
            data = _fix_text_language(current_client, data, output_lang, log)
            return data
        except Exception as e:
            err = str(e)
            try: current_client.files.delete(name=video_file.name)
            except Exception: pass
            if "429" in err or "quota" in err.lower():
                log(f"🔄 generate 429 → キーローリング＆再アップロード ({attempt}/8)")
                _rotate_client(err)
                continue
            if "403" in err or "permission" in err.lower():
                log(f"🔄 403アクセス拒否 → キーローリング＆再アップロード ({attempt}/8)")
                _rotate_client(err)
                continue
            if "503" in err or "UNAVAILABLE" in err:
                import random as _rnd
                # 同時リトライの衝突(サンダリングハード)を避けるためジッターを加える
                wait = min(20 * attempt, 90) + _rnd.uniform(0, 5)
                log(f"⏳ generate 503混雑 → {wait:.0f}秒待機してリトライ ({attempt}/8)...")
                time.sleep(wait)
                continue
            log(f"❌ generate失敗: {e}")
            return dict(_ANALYSIS_DEFAULT)

    log("❌ Gemini解析 全試行失敗 → フォールバック使用")
    return dict(_ANALYSIS_DEFAULT)


# ════════════════════════════════════════════════════════
#  Step 5: 動画編集（カット + 演出）
# ════════════════════════════════════════════════════════
def edit_video(video_path: str, analysis: dict,
               out_path: str, log: LOG_CB,
               output_resolution: str = "1080p",
               encode_preset: str = "fast",
               font_size_title: int = 82,
               font_size_subtitle: int = 54,
               font_size_caption: int = 58,
               rewind_enabled: bool = True,
               freeze_enabled: bool = True,
               extend_target: float = -1,
               extend_method: str = "endcard",
               fastforward_enabled: bool = True,
               fastforward_speed: float = 2.0,
               zoom_enabled: bool = True,
               monochrome_enabled: bool = True,
               flip_enabled: bool = True,
               mosaic_enabled: bool = True,
               simple_bgm_path: str = "",
               simple_bgm_volume: float = 0.10,
               watermark: bool = False,
               blur_background: bool = True) -> bool:
    log("🎬 動画編集開始...")
    try:
        from editor import run_edit
        run_edit(
            video_path=video_path,
            analysis=analysis,
            out_path=out_path,
            log=log,
            output_resolution=output_resolution,
            encode_preset=encode_preset,
            font_size_title=font_size_title,
            font_size_subtitle=font_size_subtitle,
            font_size_caption=font_size_caption,
            rewind_enabled=rewind_enabled,
            freeze_enabled=freeze_enabled,
            extend_target=extend_target,
            extend_method=extend_method,
            fastforward_enabled=fastforward_enabled,
            fastforward_speed=fastforward_speed,
            zoom_enabled=zoom_enabled,
            monochrome_enabled=monochrome_enabled,
            flip_enabled=flip_enabled,
            mosaic_enabled=mosaic_enabled,
            simple_bgm_path=simple_bgm_path,
            simple_bgm_volume=simple_bgm_volume,
            watermark=watermark,
            blur_background=blur_background,
        )
        return True
    except Exception as e:
        log(f"❌ 編集失敗: {e}")
        import traceback; traceback.print_exc()
        return False


# ════════════════════════════════════════════════════════
#  Step 6: YouTube アップロード
# ════════════════════════════════════════════════════════
def _notify_video_created(url: str = "", title: str = ""):
    """LPの実績カウンター・証拠ギャラリーに通知（失敗しても本体処理に影響しない）"""
    try:
        import urllib.request, json as _json
        payload = _json.dumps({"url": url, "title": title[:80]}).encode("utf-8")
        req = urllib.request.Request(
            "https://tomato-shorts-license.clipflowlicense.workers.dev/video/increment",
            data=payload, headers={"Content-Type": "application/json"}, method="POST")
        urllib.request.urlopen(req, timeout=3)
    except Exception:
        pass


def upload_to_youtube(video_path: str, analysis: dict,
                      credentials_path: str, log: LOG_CB,
                      schedule_hour: int = -1) -> Optional[str]:
    """
    YouTube Data API v3 でアップロード。
    credentials_path: OAuth2 client_secrets.json のパス
    schedule_hour: -1 なら即時公開、0-23 なら翌日その時刻に予約
    戻り値: アップロードされた動画URL or None
    """
    log("📤 YouTube アップロード準備中...")
    try:
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.auth.transport.requests import Request
        import pickle

        SCOPES    = ["https://www.googleapis.com/auth/youtube.upload"]
        token_path = str(Path(credentials_path).parent / "yt_token.pickle")

        creds = None
        if Path(token_path).exists():
            with open(token_path, "rb") as f:
                creds = pickle.load(f)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow  = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
                creds = flow.run_local_server(port=0)
            with open(token_path, "wb") as f:
                pickle.dump(creds, f)

        youtube = build("youtube", "v3", credentials=creds)

        # ── Tomato Clip ブランディング（必ず付与）
        BRAND_TAG   = "MadeWithTomatoClip"
        BRAND_BLOCK = (
            "#MadeWithTomatoClip\n"
            "この動画は Tomato Clip で生成されました\n"
            "https://tomatoshorts.web.app"
        )
        description = analysis.get("description", "#海外ショート").rstrip()
        if BRAND_TAG not in description:
            description += "\n\n" + BRAND_BLOCK
        tags = list(analysis.get("tags", ["海外ショート"]))
        if BRAND_TAG not in tags:
            tags.append(BRAND_TAG)

        body = {
            "snippet": {
                "title":       analysis.get("title", "海外バズり動画")[:100],
                "description": description[:4900],
                "tags":        tags[:15],
                "categoryId":  "24",  # エンタメ
                "defaultLanguage": analysis.get("output_language", "ja")
            },
            "status": {
                "privacyStatus": "public",
                "selfDeclaredMadeForKids": False,
            }
        }

        # 予約投稿
        if schedule_hour >= 0:
            from datetime import datetime, timedelta, timezone
            jst    = timezone(timedelta(hours=9))
            now_jst = datetime.now(jst)
            sched  = now_jst.replace(hour=schedule_hour, minute=0, second=0, microsecond=0)
            if sched <= now_jst:
                sched += timedelta(days=1)
            body["status"]["privacyStatus"]  = "private"
            body["status"]["publishAt"]      = sched.isoformat()
            log(f"📅 予約投稿: {sched.strftime('%Y/%m/%d %H:%M')} JST")

        media = MediaFileUpload(video_path, mimetype="video/mp4",
                                resumable=True, chunksize=1024 * 1024 * 5)
        req   = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

        response = None
        while response is None:
            status, response = req.next_chunk()
            if status:
                pct = int(status.progress() * 100)
                log(f"  アップロード中... {pct}%")

        vid_id = response["id"]
        url    = f"https://www.youtube.com/shorts/{vid_id}"
        log(f"✅ アップロード完了！→ {url}")
        threading.Thread(target=_notify_video_created,
                          args=(url, analysis.get("title", "")), daemon=True).start()
        return url

    except ImportError:
        log("⚠️ google-api-python-client が未インストール")
        log("   pip install google-api-python-client google-auth-oauthlib")
        return None
    except Exception as e:
        log(f"❌ アップロード失敗: {e}")
        return None


# ════════════════════════════════════════════════════════
#  メインパイプライン（全工程をつなぐ）
# ════════════════════════════════════════════════════════
def analyze_trends(config: dict, log: LOG_CB) -> dict:
    """
    トレンド動画を収集し、Gemini でバズりパターンを分析してレポートを返す。
    戻り値: {
        "summary": str,           # 全体サマリー
        "genres": [...],          # バズりジャンル TOP5
        "keywords": [...],        # 共通キーワード
        "tips": [...],            # 「こういう動画を作れ」アドバイス
        "top_videos": [...],      # スコア上位動画リスト
    }
    """
    setup_rotators(config, log)
    gemini_rot  = get_rotator("gemini",  log)
    youtube_rot = get_rotator("youtube", log)
    SLEEP       = gemini_rot.cooltime

    key   = gemini_rot.next() or config.get("gemini_key", "")
    model = init_gemini(key, config.get("gemini_model") or DEFAULT_MODEL)

    log("=" * 50)
    log("📊 トレンド分析 開始")
    log("=" * 50)

    # ── Step 1: トレンド動画を収集（複数リージョン・カテゴリ）
    log("\n🔍 トレンド動画を収集中...")
    time.sleep(SLEEP)
    videos = discover_shorts(
        youtube_key       = youtube_rot.next() or config.get("youtube_key", ""),
        priority_channels = config.get("priority_channels", []),
        categories        = config.get("categories", ["24"]),
        log               = log,
        freshness_hours   = int(config.get("freshness_hours", 72)),
        search_keywords   = config.get("search_keywords", "")
    )

    if not videos:
        log("⚠️ 動画が取得できませんでした")
        return {}

    # ── Step 2: AI スコアリング
    log("\n🤖 AIスコアリング中...")
    time.sleep(SLEEP)
    videos = score_videos(model, videos, log)
    top    = videos[:15]

    # ── Step 3: Gemini でトレンド分析
    log("\n📊 Geminiがトレンドを分析中...")
    time.sleep(SLEEP)

    items_json = json.dumps([
        {
            "title":   v["title"],
            "channel": v["channel"],
            "views":   v["views"],
            "score":   v["score"],
            "reason":  v.get("reason", ""),
            "title_jp": v.get("title_jp", ""),
        }
        for v in top
    ], ensure_ascii=False)

    prompt = f"""
以下は今日の海外YouTubeショート人気動画リストです。
これを分析して、日本語解説チャンネルとして参考にすべきトレンドをレポートしてください。
JSONのみ返答（コードブロック不要）。

{{
  "summary": "今のトレンドの全体傾向（150文字以内）",
  "genres": [
    {{"name": "ジャンル名", "desc": "なぜバズってるか（50文字）", "count": 件数}}
  ],
  "keywords": ["共通キーワード1", "キーワード2", ...最大8個],
  "tips": [
    "この系統の動画を作れ！という具体的アドバイス（1文）",
    ...最大5個
  ],
  "hot_title": "今すぐ作るべき動画タイトル案（日本語・インパクト重視）"
}}

動画リスト:
{items_json}
"""

    raw = _gemini_generate_with_retry(model, prompt, log)
    if raw is None:
        log("⚠️ Gemini分析スキップ")
        result = {}
    else:
        try:
            raw = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
            result = json.loads(raw)
        except Exception as e:
            log(f"⚠️ 分析JSON解析失敗: {e}")
            result = {}

    result["top_videos"] = [
        {"title": v["title"], "title_jp": v.get("title_jp",""), "views": v["views"], "score": v["score"]}
        for v in top[:10]
    ]

    # DBにトレンドを記録（時代の流れを蓄積）
    try:
        import db as db_mod
        db_mod.save_trend(result)
        log("💾 トレンドをDBに記録しました")
    except Exception as e:
        log(f"⚠️ トレンド保存失敗: {e}")

    log("✅ トレンド分析完了！")
    return result


def _can_upload_unattended(credentials_path: str) -> bool:
    """
    無人実行（スケジュール）でアップロードして安全か判定する。
    トークンが未発行だと OAuth のブラウザ認証待ちでハングするため、
    無人時はトークン発行済みの場合のみアップロードを許可する。
    """
    token_path = Path(credentials_path).parent / "yt_token.pickle"
    return token_path.exists()


def _extract_video_id(url: str) -> str:
    """YouTube URL から video_id を抽出"""
    import re
    patterns = [
        r"(?:shorts/|v=|youtu\.be/)([A-Za-z0-9_-]{11})",
    ]
    for p in patterns:
        m = re.search(p, url)
        if m:
            return m.group(1)
    # URL 自体が11文字のIDの場合
    if re.match(r"^[A-Za-z0-9_-]{11}$", url.strip()):
        return url.strip()
    raise ValueError(f"YouTubeのURLを認識できませんでした: {url}")


def run_pipeline_from_url(url: str, config: dict, log: LOG_CB,
                          on_video_ready: Callable = None,
                          stop_event: threading.Event = None,
                          confirm_upload: Callable = None):
    """
    YouTube URL を直接指定してパイプラインを実行。
    発見・スコアリングをスキップしてDL→解析→編集→投稿。
    """
    import tempfile

    setup_rotators(config, log)
    gemini_rot = get_rotator("gemini", log)
    SLEEP      = gemini_rot.cooltime

    work_dir = Path(config.get("work_dir", tempfile.gettempdir())) / "tomato_clip"
    work_dir.mkdir(parents=True, exist_ok=True)

    key   = gemini_rot.next() or config.get("gemini_key", "")
    model = init_gemini(key, config.get("gemini_model") or DEFAULT_MODEL)

    log("=" * 50)
    log("🔗 URL指定パイプライン開始")
    log(f"   URL: {url}")
    log("=" * 50)

    try:
        video_id = _extract_video_id(url)
    except ValueError as e:
        log(f"❌ {e}"); return

    # ── 重複チェック（同じ動画の二重生成・二重投稿を防止）
    try:
        import db as _db
        prev = next((v for v in _db.get_videos(500) if v["id"] == video_id), None)
        if prev:
            log("⚠️ この動画はすでに処理済みです → 中止（重複投稿防止）")
            log(f"   前回: {prev.get('posted_at', '')[:16]}  「{prev.get('title', '')}」")
            if prev.get("yt_url"):
                log(f"   投稿済みURL: {prev['yt_url']}")
            elif prev.get("output_path"):
                log(f"   生成済みファイル: {prev['output_path']}")
            log("   もう一度作り直したい場合は DBタブ → 動画履歴 から削除してください")
            return
    except Exception:
        pass

    video = {"id": video_id, "title": url, "channel": "URL指定", "score": 100, "priority": True}

    # ── Step 1: ダウンロード
    log("\n【Step 1/4】⬇️  動画ダウンロード中...")
    seg = pick_highlight_segment(video_id, model, config, log)
    dl_path = download_video(video_id, str(work_dir), log,
                             start=seg[0] if seg else None,
                             end=seg[1] if seg else None)
    if not dl_path:
        log("❌ DL失敗"); return

    if stop_event and stop_event.is_set():
        log("⏹ 停止しました"); return

    # ── Step 2: Gemini 解析
    log("\n【Step 2/4】🔬 Gemini 動画解析中...")
    log("   （文字起こし・翻訳・カット点・字幕生成）")
    time.sleep(SLEEP)
    output_lang = config.get("output_language", "ja")
    analysis = analyze_video(model, dl_path, log,
                             chat_context=config.get("chat_context", ""),
                             output_lang=output_lang)
    analysis["output_language"] = output_lang
    if seg:
        # 区間DLのオフセット。台本編集(get_transcript)がソース字幕と
        # 出力動画の時間軸を対応付けるのに使う。
        analysis["segment_start"], analysis["segment_end"] = seg
    log(f"   ✅ タイトル: {analysis.get('title')}")
    log(f"   ✅ 字幕: {len(analysis.get('captions',[]))} 件")
    log(f"   ✅ カット: {len(analysis.get('cut_sections',[]))} 箇所")

    analysis["tmpl_config"]  = {}
    analysis["footage_path"] = None

    # Python編集（常時有効・失敗時は従来編集に自動フォールバック）
    try:
        import code_edit
        code_edit.apply_code_edit(model, dl_path, analysis, log, config)
    except Exception as e:
        log(f"⚠️ Python編集をスキップ: {str(e)[:100]}")

    if stop_event and stop_event.is_set():
        log("⏹ 停止しました"); return

    # ── Step 3: 編集
    log("\n【Step 3/4】🎬 動画編集中...")
    out_path = str(work_dir / f"output_{video_id}.mp4")
    _here2 = Path(__file__).parent

    def _resolve2(val, default_name):
        p = Path(val) if val else Path(default_name)
        return str(p if p.is_absolute() else _here2 / p)

    ep = analysis.get("edit_params", {})
    ok = edit_video(
        video_path         = dl_path,
        analysis           = analysis,
        out_path           = out_path,
        log                = log,
        output_resolution  = config.get("output_resolution", "1080p"),
        encode_preset      = config.get("encode_preset", "fast"),
        font_size_title    = int(ep.get("font_size_title",     82)),
        font_size_subtitle = int(ep.get("font_size_subtitle", 54)),
        font_size_caption  = int(ep.get("font_size_caption",  58)),
        rewind_enabled     = bool(ep.get("rewind_enabled",      True)),
        freeze_enabled     = bool(ep.get("freeze_enabled",      True)),
        extend_target      = float(ep.get("extend_target",     -1)),
        extend_method      = ep.get("extend_method",           "endcard"),
        fastforward_enabled= bool(ep.get("fastforward_enabled", True)),
        fastforward_speed  = float(ep.get("fastforward_speed",  2.0)),
        zoom_enabled       = bool(ep.get("zoom_enabled",        True)),
        monochrome_enabled = bool(ep.get("monochrome_enabled",  True)),
        flip_enabled       = bool(ep.get("flip_enabled",        True)),
        mosaic_enabled     = bool(ep.get("mosaic_enabled",      True)),
        simple_bgm_path    = config.get("simple_bgm_path", ""),
        simple_bgm_volume  = float(config.get("simple_bgm_volume", 0.10)),
        watermark          = bool(config.get("demo_mode", False)),
        blur_background    = bool(config.get("blur_background", True)),
    )
    if not ok:
        log("❌ 編集失敗"); return

    # 編集完了後、不要になった生ダウンロード(数百MB)を削除してディスクを節約する。
    # 出力は out_path に生成済み。編集失敗時(上のreturn)は残して原因調査できるようにする。
    try:
        if dl_path and Path(dl_path).exists():
            Path(dl_path).unlink()
        _mid = analysis.get("code_intermediate")
        if _mid and Path(_mid).exists():
            Path(_mid).unlink()   # Python編集の中間動画も不要
    except Exception:
        pass

    import db as db_mod
    db_mod.save_video(
        video_id=video_id, title=analysis.get("title",""),
        channel="URL指定", score=100,
        output_path=out_path, yt_url="",
        template_id="", meta=analysis
    )

    if on_video_ready:
        on_video_ready(out_path, analysis)

    if stop_event and stop_event.is_set():
        log("⏹ 停止しました（動画は生成済み・投稿はスキップ）")
        log(f"   完成動画: {out_path}")
        return

    # ── 投稿前確認（手動実行時のみ）
    cred = config.get("credentials_path", "")
    if cred and Path(cred).exists() and confirm_upload is not None:
        log("\n👀 投稿前の確認待ち... ダイアログで選択してください")
        if not confirm_upload(out_path, analysis):
            log("🚫 投稿せず保存しました")
            log(f"   完成動画: {out_path}")
            return

    # ── Step 4: アップロード
    log("\n【Step 4/4】📤 YouTube アップロード中...")
    if cred and Path(cred).exists() and confirm_upload is None and not _can_upload_unattended(cred):
        log("⚠️ 無人実行のためYouTube認証(初回)をスキップしました（ブラウザ認証待ちを回避）")
        log(f"   完成動画: {out_path}")
        log("   ソフトを開いて一度手動で認証すると、次回から自動投稿されます")
    elif cred and Path(cred).exists():
        time.sleep(SLEEP)
        yt_url = upload_to_youtube(
            video_path=out_path, analysis=analysis,
            credentials_path=cred, log=log,
            schedule_hour=config.get("schedule_hour", -1)
        )
        if yt_url:
            db_mod.save_video(
                video_id=video_id, title=analysis.get("title",""),
                channel="URL指定", score=100,
                output_path=out_path, yt_url=yt_url,
                template_id="", meta=analysis
            )
    else:
        log("⚠️ YouTube認証なし → スキップ")
        log(f"   完成動画: {out_path}")

    log("\n" + "=" * 50)
    log("🎉 URL指定パイプライン完了！")
    log("=" * 50)


def _expand_theme(model, kw: str, log: LOG_CB):
    """
    テーマ語をYouTube上の実表記に展開する（例:「アイアンマウス」→ ironmouse）。
    日本語名と原語名が違う海外の配信者・ゲーム等では、カタカナのまま検索・
    タイトル照合しても空振りし、無関係のバズ動画を採用してしまう（実際に起きた）。
    """
    prompt = (
        f"YouTubeで動画を探す準備。テーマ:「{kw}」\n"
        "対象（人物・チャンネル・ゲーム・番組など）がYouTube上で使われる代表的な表記を、"
        "原語（英語名など）・カタカナ・略称を含めて挙げてください。\n"
        'JSONのみ返答（コードブロック不要）: '
        '{"queries": ["検索クエリを2〜4個（原語表記を優先、雰囲気語は残す）"], '
        '"match_terms": ["動画タイトル/チャンネル名との照合に使う対象の表記を2〜6個（すべて小文字）"]}'
    )
    try:
        import re as _re
        raw = _gemini_call(model, prompt)
        txt = _re.sub(r"^```(?:json)?|```$", "", (raw or "").strip(), flags=_re.M).strip()
        d = json.loads(txt)
        qs = [str(q).strip() for q in d.get("queries", []) if str(q).strip()][:4]
        ts = [str(t).strip().lower() for t in d.get("match_terms", []) if str(t).strip()][:6]
        if qs and ts:
            log(f"   🌐 表記ゆれを展開: {', '.join(ts)}")
            return {"queries": qs, "match_terms": ts}
    except Exception as e:
        log(f"   ⚠️ テーマ展開に失敗（原文のまま検索します）: {str(e)[:60]}")
    return None


def run_pipeline(config: dict, log: LOG_CB,
                 on_video_ready: Callable = None,
                 stop_event: threading.Event = None,
                 confirm_upload: Callable = None):
    """
    config keys:
      gemini_key, youtube_key, credentials_path
      priority_channels, regions, categories
      skull_path, phonk_path, pexels_key
      work_dir, schedule_hour
      max_videos: 1回の実行で処理する最大本数
      active_template: テンプレートID（"auto" でAI自動選択）
    """
    import tempfile

    # キーローリング初期化
    setup_rotators(config, log)
    gemini_rot  = get_rotator("gemini",  log)
    youtube_rot = get_rotator("youtube", log)

    # クールタイム = 20 ÷ キー数
    SLEEP = gemini_rot.cooltime
    log(f"🔑 クールタイム: {SLEEP:.1f}秒 (Gemini:{gemini_rot.count()}個 / YouTube:{youtube_rot.count()}個)")

    work_dir = Path(config.get("work_dir", tempfile.gettempdir())) / "tomato_clip"
    work_dir.mkdir(parents=True, exist_ok=True)

    # Gemini モデル（ローリング）
    key   = gemini_rot.next() or config.get("gemini_key", "")
    model = init_gemini(key, config.get("gemini_model") or DEFAULT_MODEL)

    log("=" * 50)
    log("🏭 TOMATO SHORTS パイプライン開始")
    log(f"   時刻: {time.strftime('%Y/%m/%d %H:%M:%S')}")
    log("=" * 50)

    # ── Step 1: 発見（GeminiがDBを読んでクエリ生成 → 検索 → ダブりチェック）
    log("\n【Step 1/6】🔍 動画発見中...")
    force_kw = str(config.get("force_keyword", "")).strip()
    theme_terms = []
    if force_kw:
        log(f"   🎯 指定テーマで検索: {force_kw}")
        _exp = _expand_theme(model, force_kw, log)
        if _exp:
            ai_queries = [{"keyword": q, "category": "user", "note": "ユーザー指定テーマ"}
                          for q in _exp["queries"]]
            theme_terms = _exp["match_terms"]
        else:
            ai_queries = [{"keyword": force_kw, "category": "user", "note": "ユーザー指定テーマ"},
                          {"keyword": f"{force_kw} clip", "category": "user", "note": "ユーザー指定テーマ"}]
    else:
        log("   🧠 GeminiがDBを読んで検索クエリを生成します...")
        time.sleep(SLEEP)
        ai_queries = generate_search_queries(model, log, gemini_rot=gemini_rot)
    time.sleep(SLEEP)
    videos = discover_shorts(
        youtube_key       = youtube_rot.next() or config.get("youtube_key",""),
        priority_channels = config.get("priority_channels", []),
        categories        = config.get("categories", ["24"]),
        log               = log,
        freshness_hours   = int(config.get("freshness_hours", 72)) if not force_kw else 0,
        search_keywords   = config.get("search_keywords", ""),
        ai_queries        = ai_queries or None,
        source_preference = config.get("source_preference", "prefer_original"),
    )

    # 指定テーマの場合、タイトル/チャンネル名にテーマ語を含む動画だけに絞る
    # （バズっているだけの無関係動画を掴まないため）。照合語は表記ゆれ展開済みの
    # theme_terms を優先（「アイアンマウス」だけだと英題 Ironmouse に一致しない）。
    if force_kw and videos:
        import re as _re
        _STOP = {"clip", "clips", "shorts", "short", "funny", "moments", "video",
                 "切り抜き", "面白", "まとめ"}
        toks = theme_terms or [t for t in _re.split(r"[\s　]+", force_kw.lower())
                               if len(t) >= 3 and t not in _STOP]
        if toks:
            strict = [v for v in videos
                      if any(t in (v["title"] + " " + v["channel"]).lower() for t in toks)]
            if strict:
                log(f"   🎯 テーマ一致: {len(strict)}/{len(videos)} 件に絞り込み")
                videos = strict
            else:
                # 無関係のバズ動画を作るより、正直に「見つからない」と伝える
                log(f"   ⚠️ テーマ「{force_kw}」に一致する動画が見つかりませんでした")
                log("      （表記を変える・別のテーマにする等でもう一度お試しください）")
                return

    if stop_event and stop_event.is_set():
        log("⏹ 停止しました"); return

    # ── Step 2: AI スコアリング
    log("\n【Step 2/6】🤖 AI スコアリング中...")
    time.sleep(SLEEP)
    videos = score_videos(model, videos, log, gemini_rot=gemini_rot,
                          source_preference=config.get("source_preference", "prefer_original"))

    # 上位候補を予備込みで持つ。DLできない動画（国限定公開・削除・ライブ等）を
    # 引いたら次点で再挑戦する（以前は候補1本だけだったので、その1本が
    # 米国限定だと即「生成できませんでした」になっていた＝実際に起きた）。
    targets = [v for v in videos if v["score"] >= 60][:5]
    if not targets:
        log("⚠️ スコア60以上なし → 上位動画を強制採用")
        targets = videos[:5]
    if not targets:
        log("⚠️ 採用動画なし"); return
    want, made = 1, 0

    log(f"\n📋 採用候補: {len(targets)} 本（1本完成で終了・DL不可なら次点へ）")
    for v in targets:
        log(f"   • {v['title'][:35]} (スコア:{v['score']} / {'⭐優先' if v.get('priority') else '📡トレンド'})")

    for i, video in enumerate(targets):
        if made >= want:
            break
        if stop_event and stop_event.is_set():
            log("⏹ 停止しました"); return

        log(f"\n{'='*50}")
        log(f"▶ [{i+1}/{len(targets)}] {video['title'][:40]}")
        log(f"   チャンネル: {video['channel']} / スコア: {video['score']}")
        log(f"{'='*50}")

        # ── Step 3: ダウンロード
        log("\n【Step 3/6】⬇️  動画ダウンロード中...")
        time.sleep(SLEEP)
        _seg = pick_highlight_segment(video["id"], model, config, log)
        dl_path = download_video(video["id"], str(work_dir), log,
                                 start=_seg[0] if _seg else None,
                                 end=_seg[1] if _seg else None)
        if not dl_path:
            log("❌ DL失敗（国限定公開・削除・ライブ等）→ 次の候補で再挑戦します")
            continue

        if stop_event and stop_event.is_set():
            log("⏹ 停止しました"); return

        # ── Step 4: Gemini 解析
        log("\n【Step 4/6】🔬 Gemini 動画解析中...")
        log("   （文字起こし・翻訳・カット点・字幕生成）")
        time.sleep(SLEEP)
        output_lang = config.get("output_language", "ja")
        analysis = analyze_video(model, dl_path, log, gemini_rot=gemini_rot,
                                 chat_context=config.get("chat_context", ""),
                                 output_lang=output_lang)
        analysis["output_language"] = output_lang
        if _seg:
            analysis["segment_start"], analysis["segment_end"] = _seg
        if output_lang == "ja" and video.get("title_jp"):
            analysis.setdefault("title", video["title_jp"])

        log(f"   ✅ タイトル: {analysis.get('title')}")
        log(f"   ✅ 字幕: {len(analysis.get('captions',[]))} 件")
        log(f"   ✅ カット: {len(analysis.get('cut_sections',[]))} 箇所")

        analysis["tmpl_config"]  = {}
        analysis["footage_path"] = None

        # Python編集（常時有効・失敗時は従来編集に自動フォールバック）
        try:
            import code_edit
            code_edit.apply_code_edit(model, dl_path, analysis, log, config)
        except Exception as e:
            log(f"⚠️ Python編集をスキップ: {str(e)[:100]}")

        if stop_event and stop_event.is_set():
            log("⏹ 停止しました"); return

        # ── Step 5: 編集
        log("\n【Step 5/6】🎬 動画編集中...")
        log("   カット → 字幕 → 演出 → BGM → 書き出し")
        out_path = str(work_dir / f"output_{video['id']}.mp4")
        _here = Path(__file__).parent

        def _resolve(val, default_name):
            p = Path(val) if val else Path(default_name)
            return str(p if p.is_absolute() else _here / p)

        ep = analysis.get("edit_params", {})
        ok = edit_video(
            video_path         = dl_path,
            analysis           = analysis,
            out_path           = out_path,
            log                = log,
            output_resolution  = config.get("output_resolution", "1080p"),
            encode_preset      = config.get("encode_preset", "fast"),
            font_size_title    = int(ep.get("font_size_title",     82)),
            font_size_subtitle = int(ep.get("font_size_subtitle", 54)),
            font_size_caption  = int(ep.get("font_size_caption",  58)),
            rewind_enabled     = bool(ep.get("rewind_enabled",      True)),
            freeze_enabled     = bool(ep.get("freeze_enabled",      True)),
            extend_target      = float(ep.get("extend_target",     -1)),
            extend_method      = ep.get("extend_method",           "endcard"),
            fastforward_enabled= bool(ep.get("fastforward_enabled", True)),
            fastforward_speed  = float(ep.get("fastforward_speed",  2.0)),
            simple_bgm_path    = config.get("simple_bgm_path", ""),
            simple_bgm_volume  = float(config.get("simple_bgm_volume", 0.10)),
            watermark          = bool(config.get("demo_mode", False)),
            blur_background    = bool(config.get("blur_background", True)),
        )
        if not ok:
            log("❌ 編集失敗 → スキップ")
            continue

        # 編集完了後、不要になった生ダウンロード(数百MB)を削除してディスクを節約
        try:
            if dl_path and Path(dl_path).exists():
                Path(dl_path).unlink()
            _mid = analysis.get("code_intermediate")
            if _mid and Path(_mid).exists():
                Path(_mid).unlink()   # Python編集の中間動画も不要
        except Exception:
            pass

        # DB に保存
        import db as db_mod
        db_mod.save_video(
            video_id    = video["id"],
            title       = analysis.get("title",""),
            channel     = video.get("channel",""),
            score       = video.get("score", 0),
            output_path = out_path,
            yt_url      = "",
            template_id = "",
            meta        = analysis
        )

        made += 1   # 1本完成（以降の候補は予備だったので使わない）

        if on_video_ready:
            on_video_ready(out_path, analysis)

        if stop_event and stop_event.is_set():
            log("⏹ 停止しました（動画は生成済み・投稿はスキップ）")
            log(f"   完成動画: {out_path}")
            return

        # ── 投稿前確認（手動実行時のみ）
        cred = config.get("credentials_path", "")
        if cred and Path(cred).exists() and confirm_upload is not None:
            log("\n👀 投稿前の確認待ち... ダイアログで選択してください")
            if not confirm_upload(out_path, analysis):
                log("🚫 投稿せず保存しました")
                log(f"   完成動画: {out_path}")
                continue

        # ── Step 6: YouTube アップロード
        log("\n【Step 6/6】📤 YouTube アップロード中...")
        time.sleep(SLEEP)
        yt_url = None
        if cred and Path(cred).exists() and confirm_upload is None and not _can_upload_unattended(cred):
            log("⚠️ 無人実行のためYouTube認証(初回)をスキップしました（ブラウザ認証待ちを回避）")
            log(f"   完成動画: {out_path}")
            log("   ソフトを開いて一度手動で認証すると、次回から自動投稿されます")
        elif cred and Path(cred).exists():
            yt_url = upload_to_youtube(
                video_path       = out_path,
                analysis         = analysis,
                credentials_path = cred,
                log              = log,
                schedule_hour    = -1
            )
            if yt_url:
                db_mod.save_video(
                    video_id    = video["id"],
                    title       = analysis.get("title",""),
                    channel     = video.get("channel",""),
                    score       = video.get("score", 0),
                    output_path = out_path,
                    yt_url      = yt_url,
                    template_id = "",
                    meta        = analysis
                )
        else:
            log("⚠️ YouTube認証なし → スキップ")
            log(f"   完成動画: {out_path}")

        log(f"\n✅ 完了！（候補 {i+1}/{len(targets)} 本目で成功）")
        if made < want and i < len(targets) - 1:
            log(f"   次の動画まで {SLEEP}秒 待機...")
            time.sleep(SLEEP)

    log("\n" + "=" * 50)
    log("🎉 パイプライン全工程完了！")
    log("=" * 50)
