"""
channel_learner.py
自分のチャンネルを分析してバズりパターンを学習する。
学習結果は ~/.tomato_clip_learnings.json に保存し、
pipeline.py のプロンプトに自動注入される。
"""

import json, time
from pathlib import Path
from typing import Callable

LOG_CB = Callable[[str], None]
LEARNINGS_PATH = Path.home() / ".tomato_clip_learnings.json"


def load_learnings() -> dict:
    if LEARNINGS_PATH.exists():
        try:
            with open(LEARNINGS_PATH, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_learnings(data: dict):
    with open(LEARNINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def resolve_channel_id(youtube_key: str, handle_or_id: str, log: LOG_CB) -> str:
    """@ハンドル または チャンネルID を受け取り、チャンネルID（UCxxx）を返す"""
    import urllib.request, urllib.parse

    # すでにIDの場合はそのまま返す
    if handle_or_id.startswith("UC") and len(handle_or_id) > 10:
        return handle_or_id

    handle = handle_or_id.lstrip("@")
    log(f"🔍 @{handle} のチャンネルIDを検索中...")
    p = urllib.parse.urlencode({"part": "id", "forHandle": handle, "key": youtube_key})
    try:
        with urllib.request.urlopen(
            f"https://www.googleapis.com/youtube/v3/channels?{p}", timeout=10
        ) as r:
            data = json.loads(r.read())
        items = data.get("items", [])
        if not items:
            raise ValueError(f"@{handle} が見つかりません")
        ch_id = items[0]["id"]
        log(f"✅ チャンネルID: {ch_id}")
        return ch_id
    except Exception as e:
        raise ValueError(f"チャンネルID取得失敗: {e}")


def fetch_channel_videos(youtube_key: str, channel_id: str,
                         log: LOG_CB, max_results: int = 30) -> list[dict]:
    """YouTube Data API でチャンネルの動画一覧と統計を取得"""
    import urllib.request, urllib.parse

    log(f"📺 チャンネル動画を取得中: {channel_id}")

    def api_get(url):
        with urllib.request.urlopen(url, timeout=10) as r:
            return json.loads(r.read())

    # 動画ID一覧を取得
    p = urllib.parse.urlencode({
        "part": "snippet", "channelId": channel_id,
        "type": "video", "order": "date",
        "maxResults": max_results, "key": youtube_key
    })
    try:
        data = api_get(f"https://www.googleapis.com/youtube/v3/search?{p}")
    except Exception as e:
        log(f"❌ チャンネル取得失敗: {e}")
        return []

    video_ids = [item["id"].get("videoId") for item in data.get("items", [])
                 if item["id"].get("videoId")]
    if not video_ids:
        log("⚠️ 動画が見つかりません")
        return []

    # 統計を一括取得
    p2 = urllib.parse.urlencode({
        "part": "snippet,statistics", "id": ",".join(video_ids), "key": youtube_key
    })
    try:
        data2 = api_get(f"https://www.googleapis.com/youtube/v3/videos?{p2}")
    except Exception as e:
        log(f"❌ 統計取得失敗: {e}")
        return []

    videos = []
    for item in data2.get("items", []):
        stats = item.get("statistics", {})
        videos.append({
            "id":       item["id"],
            "title":    item["snippet"]["title"],
            "views":    int(stats.get("viewCount", 0)),
            "likes":    int(stats.get("likeCount", 0)),
            "comments": int(stats.get("commentCount", 0)),
            "published": item["snippet"]["publishedAt"],
        })

    videos.sort(key=lambda x: x["views"], reverse=True)
    log(f"✅ {len(videos)}本取得 / トップ: {videos[0]['title'][:30]} ({videos[0]['views']:,}回)")
    return videos


def analyze_channel(youtube_key: str, channel_id: str,
                    model, log: LOG_CB, gemini_rot=None,
                    save: bool = True) -> dict:
    """
    チャンネル動画を分析してバズりパターンを学習する。
    戻り値: 学習結果 dict（~/.tomato_clip_learnings.json に保存）
    """
    from pipeline import _gemini_generate_with_retry
    import db as db_mod

    # ── 1. チャンネル動画取得
    channel_id = resolve_channel_id(youtube_key, channel_id, log)
    ch_videos = fetch_channel_videos(youtube_key, channel_id, log)
    if not ch_videos:
        return {}

    # ── 2. 自プロジェクトのDB履歴も参照
    db_videos = db_mod.get_videos(limit=50)

    # ── 3. Geminiで分析
    log("🤖 Geminiがチャンネルパターンを分析中...")

    ch_json = json.dumps(ch_videos[:20], ensure_ascii=False)
    db_json = json.dumps([
        {"title": v["title"], "template": v.get("template_id",""),
         "score": v.get("score", 0)}
        for v in db_videos[:20]
    ], ensure_ascii=False)

    prompt = f"""
あなたはYouTubeショート動画の専門アナリストです。
以下のチャンネル動画データを分析して、バズりパターンを日本語で教えてください。
JSONのみ返答（コードブロック不要）。

{{
  "summary": "このチャンネルの全体的な傾向（100文字）",
  "best_title_patterns": ["バズるタイトルのパターン1", "パターン2", ...最大5個"],
  "best_categories": ["バズりやすいジャンル/カテゴリ1", ...最大3個],
  "best_keywords": ["効果的なキーワード1", ...最大8個],
  "avoid_patterns": ["避けるべきパターン1", ...最大3個],
  "caption_style": "字幕・実況のスタイルのアドバイス（50文字）",
  "recommended_template": "このチャンネルに最適なテンプレートID（例: hype, calm, explain）",
  "tips": ["次の動画に活かすべきアドバイス1", ...最大5個"]
}}

チャンネル動画（再生数順）:
{ch_json}

過去の制作動画:
{db_json}
"""

    raw = _gemini_generate_with_retry(model, prompt, log, gemini_rot=gemini_rot)
    if not raw:
        log("⚠️ 分析失敗")
        return {}

    try:
        raw = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        learnings = json.loads(raw)
    except Exception as e:
        log(f"⚠️ JSON解析失敗: {e}")
        return {}

    learnings["analyzed_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    learnings["channel_id"]  = channel_id
    learnings["top_views"]   = ch_videos[0]["views"] if ch_videos else 0

    if save:
        save_learnings(learnings)
    log(f"✅ 学習完了 → {LEARNINGS_PATH}")
    log(f"   サマリー: {learnings.get('summary','')}")
    return learnings


def build_learning_prompt_context() -> str:
    """
    学習結果をGeminiプロンプトに注入するテキストを生成する。
    学習データがなければ空文字を返す。
    """
    data = load_learnings()
    if not data:
        return ""

    lines = [
        "\n【チャンネル学習データ】",
        f"分析日: {data.get('analyzed_at','')}",
        f"概要: {data.get('summary','')}",
    ]
    if data.get("best_title_patterns"):
        lines.append("バズるタイトルパターン: " + " / ".join(data["best_title_patterns"]))
    if data.get("best_keywords"):
        lines.append("効果的キーワード: " + ", ".join(data["best_keywords"]))
    if data.get("caption_style"):
        lines.append(f"字幕スタイル: {data['caption_style']}")
    if data.get("avoid_patterns"):
        lines.append("避けるパターン: " + " / ".join(data["avoid_patterns"]))
    if data.get("tips"):
        lines.append("アドバイス: " + " / ".join(data["tips"][:3]))
    lines.append("上記のパターンを参考にして、このチャンネルに合ったコンテンツを生成してください。")
    return "\n".join(lines)
