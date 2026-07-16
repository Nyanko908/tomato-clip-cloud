"""
analytics.py
・投稿動画の YouTube 統計を定期取得
・Gemini でバズりパターンを学習・次回スコアリングに反映
・伸び率グラフデータ生成
"""
import json
from datetime import datetime
from typing import Callable
import db

LOG_CB = Callable[[str], None]


# ════════════════════════════════════════════════════════
#  YouTube Analytics 統計取得
# ════════════════════════════════════════════════════════
def fetch_video_stats(youtube_key: str, video_ids: list[str], log: LOG_CB) -> dict:
    """
    YouTube Data API で複数動画の統計を一括取得。
    戻り値: {video_id: {"views":int, "likes":int, "comments":int}}
    """
    import urllib.request, urllib.parse

    if not video_ids:
        return {}

    log(f"📊 統計取得: {len(video_ids)} 件")
    ids_str = ",".join(video_ids[:50])
    params  = urllib.parse.urlencode({
        "part": "statistics", "id": ids_str, "key": youtube_key
    })
    url = f"https://www.googleapis.com/youtube/v3/videos?{params}"

    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            data = json.loads(r.read())
        result = {}
        for item in data.get("items", []):
            s = item.get("statistics", {})
            result[item["id"]] = {
                "views":    int(s.get("viewCount",    0)),
                "likes":    int(s.get("likeCount",    0)),
                "comments": int(s.get("commentCount", 0)),
            }
        return result
    except Exception as e:
        log(f"⚠️ 統計取得失敗: {e}")
        return {}


def update_all_analytics(youtube_key: str, log: LOG_CB):
    """全投稿済み動画の統計を更新してDBに保存"""
    videos = db.get_videos(limit=100)
    ids    = [v["id"] for v in videos if v.get("yt_url")]
    if not ids:
        log("📊 更新対象なし")
        return

    stats = fetch_video_stats(youtube_key, ids, log)
    for vid, s in stats.items():
        db.save_analytics(vid, s["views"], s["likes"], s["comments"])
    log(f"📊 統計更新完了: {len(stats)} 件")


# ════════════════════════════════════════════════════════
#  Gemini によるバズりパターン学習
# ════════════════════════════════════════════════════════
def learn_buzz_pattern(model, log: LOG_CB) -> dict:
    """
    過去の投稿データから Gemini にバズりパターンを分析させ、
    次回スコアリングに使うヒントを返す。
    戻り値: {"insights": [...], "boost_keywords": [...], "avoid_keywords": [...]}
    """
    summary = db.get_all_analytics_summary()
    if len(summary) < 3:
        log("📊 学習データ不足（最低3件必要）")
        return {}

    # 上位・下位の動画情報をGeminiに渡す
    top    = sorted(summary, key=lambda x: x.get("peak_views") or 0, reverse=True)[:5]
    bottom = sorted(summary, key=lambda x: x.get("peak_views") or 0)[:5]

    data_str = json.dumps({
        "top_videos":    top,
        "bottom_videos": bottom
    }, ensure_ascii=False, default=str)

    prompt = f"""
以下はYouTubeショート解説チャンネルの投稿実績データです。
上位動画と下位動画を比較して、バズる動画の特徴を分析してください。
JSONのみ返答（コードブロック不要）。

{{
  "insights":        ["バズりパターンの洞察（各50文字以内）×3件"],
  "boost_keywords":  ["タイトルに含まれるとバズりやすいキーワード×5"],
  "avoid_keywords":  ["避けるべきキーワード×3"],
  "best_template":   "最もバズったテンプレートID（不明なら null）",
  "best_channel":    "最もバズったチャンネルジャンル",
  "score_formula":   "次回スコアリングで重視すべき点（100文字以内）"
}}

データ:
{data_str}
"""
    log("🧠 Gemini でバズりパターン学習中...")
    try:
        resp = model.generate_content(prompt)
        raw  = resp.text.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        result = json.loads(raw)
        log("✅ 学習完了")
        for ins in result.get("insights", []):
            log(f"  💡 {ins}")
        return result
    except Exception as e:
        log(f"⚠️ 学習失敗: {e}")
        return {}


# ════════════════════════════════════════════════════════
#  グラフデータ生成（GUI用）
# ════════════════════════════════════════════════════════
def get_growth_data(video_id: str) -> dict:
    """
    特定動画の伸びデータを返す。
    戻り値: {"labels": [...], "views": [...], "likes": [...]}
    """
    rows = db.get_analytics(video_id)
    if not rows:
        return {"labels": [], "views": [], "likes": []}

    labels = [r["checked_at"][:10] for r in rows]
    views  = [r["views"]           for r in rows]
    likes  = [r["likes"]           for r in rows]
    return {"labels": labels, "views": views, "likes": likes}


def get_channel_ranking() -> list[dict]:
    """チャンネル別の平均再生数ランキング"""
    summary = db.get_all_analytics_summary()
    ch_data = {}
    for v in summary:
        ch = v.get("channel", "不明")
        if ch not in ch_data:
            ch_data[ch] = []
        ch_data[ch].append(v.get("peak_views") or 0)

    ranking = [
        {"channel": ch, "avg_views": int(sum(vs)/len(vs)), "count": len(vs)}
        for ch, vs in ch_data.items()
    ]
    return sorted(ranking, key=lambda x: x["avg_views"], reverse=True)
