# -*- coding: utf-8 -*-
"""youtube_stats.py — YouTube Data API v3 でチャンネル/動画の統計を取得する。

新UIの統計ダッシュボード（Studio風）用。すべて **APIキー**ベースで動く（OAuth不要）。
必要なのは config の `youtube_key` と `my_channel_id`(or `linked_channel_id`) のみ。

v3 は累積値（現在の再生数など）しか返さないため、成長推移は自前スナップショットで作る：
`~/.tomato_clip/channel_history.json` に 1日1件 {date, subs, views, video_count} を追記。

analytics.py（fetch_video_stats の urllib パターン）を踏襲。共有 db.py は触らない。
"""
import json
import urllib.request
import urllib.parse
from datetime import datetime, date
from pathlib import Path
from typing import Optional

_API = "https://www.googleapis.com/youtube/v3"
_HISTORY_PATH = Path.home() / ".tomato_clip" / "channel_history.json"


def _get(endpoint: str, params: dict) -> dict:
    url = f"{_API}/{endpoint}?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=12) as r:
        return json.loads(r.read())


def _iso_to_sec(iso: str) -> int:
    """ISO8601 duration (PT1M30S) → 秒。"""
    import re
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
    if not m:
        return 0
    h, mi, s = (int(x) if x else 0 for x in m.groups())
    return h * 3600 + mi * 60 + s


def fetch_channel(youtube_key: str, channel_id: str) -> dict:
    """チャンネルの基本情報＋統計。uploads プレイリストIDも返す。"""
    d = _get("channels", {"part": "snippet,statistics,contentDetails",
                          "id": channel_id, "key": youtube_key})
    items = d.get("items", [])
    if not items:
        return {}
    it = items[0]
    sn, st = it.get("snippet", {}), it.get("statistics", {})
    thumbs = sn.get("thumbnails", {})
    thumb = (thumbs.get("medium") or thumbs.get("default") or {}).get("url", "")
    return {
        "id": channel_id,
        "title": sn.get("title", ""),
        "thumbnail": thumb,
        "subs": int(st.get("subscriberCount", 0)),
        "views": int(st.get("views", 0) or st.get("viewCount", 0)),
        "video_count": int(st.get("videoCount", 0)),
        "uploads_playlist": it.get("contentDetails", {})
                              .get("relatedPlaylists", {}).get("uploads", ""),
    }


def fetch_all_video_ids(youtube_key: str, uploads_playlist: str, cap: int = 200) -> list:
    """uploads プレイリストから動画IDを取得（ページング, cap 上限）。空なら []。"""
    if not uploads_playlist:
        return []
    ids, token = [], None
    while len(ids) < cap:
        params = {"part": "contentDetails", "playlistId": uploads_playlist,
                  "maxResults": 50, "key": youtube_key}
        if token:
            params["pageToken"] = token
        try:
            d = _get("playlistItems", params)
        except Exception:
            break  # 空プレイリストの404など
        for x in d.get("items", []):
            vid = x.get("contentDetails", {}).get("videoId")
            if vid:
                ids.append(vid)
        token = d.get("nextPageToken")
        if not token:
            break
    return ids[:cap]


def fetch_videos(youtube_key: str, ids: list) -> list:
    """動画IDリスト → 統計付きの動画dictリスト（50件バッチ）。"""
    out = []
    for i in range(0, len(ids), 50):
        batch = ids[i:i + 50]
        try:
            d = _get("videos", {"part": "snippet,statistics,contentDetails",
                                "id": ",".join(batch), "key": youtube_key})
        except Exception:
            continue
        for it in d.get("items", []):
            sn, st = it.get("snippet", {}), it.get("statistics", {})
            thumbs = sn.get("thumbnails", {})
            thumb = (thumbs.get("medium") or thumbs.get("default") or {}).get("url", "")
            views = int(st.get("viewCount", 0))
            likes = int(st.get("likeCount", 0))
            comments = int(st.get("commentCount", 0))
            out.append({
                "id": it.get("id", ""),
                "title": sn.get("title", ""),
                "thumbnail": thumb,
                "published": sn.get("publishedAt", ""),
                "duration_sec": _iso_to_sec(it.get("contentDetails", {}).get("duration", "")),
                "views": views, "likes": likes, "comments": comments,
                "engagement": round((likes + comments) / max(views, 1), 4),
            })
    return out


def load_history() -> list:
    try:
        if _HISTORY_PATH.exists():
            return json.loads(_HISTORY_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return []


def snapshot_channel(channel: dict) -> list:
    """当日のチャンネル統計を history に1日1件で追記（同日は上書き）。"""
    hist = load_history()
    today = date.today().isoformat()
    entry = {"date": today, "subs": channel.get("subs", 0),
             "views": channel.get("views", 0), "video_count": channel.get("video_count", 0)}
    hist = [h for h in hist if h.get("date") != today]
    hist.append(entry)
    hist.sort(key=lambda h: h.get("date", ""))
    hist = hist[-365:]  # 最大1年
    try:
        _HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        _HISTORY_PATH.write_text(json.dumps(hist, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass
    return hist


def build_dashboard(config: dict) -> dict:
    """ダッシュボード表示用のデータ一式を構築して返す。

    key/channel_id 欠落やAPIエラー時は {"error": "..."} を返す（UIで案内）。
    """
    key = (config.get("youtube_key") or "").strip()
    cid = (config.get("linked_channel_id") or config.get("my_channel_id") or "").strip()
    if not key:
        return {"error": "no_key"}
    if not cid:
        return {"error": "no_channel"}

    try:
        channel = fetch_channel(key, cid)
    except Exception as e:
        return {"error": "api", "message": str(e)}
    if not channel:
        return {"error": "channel_not_found"}

    timeseries = snapshot_channel(channel)

    vids = []
    try:
        ids = fetch_all_video_ids(key, channel.get("uploads_playlist", ""))
        if ids:
            vids = fetch_videos(key, ids)
    except Exception:
        vids = []

    vids.sort(key=lambda v: v.get("views", 0), reverse=True)
    total_likes = sum(v["likes"] for v in vids)
    total_comments = sum(v["comments"] for v in vids)
    total_views_v = sum(v["views"] for v in vids)
    avg_engagement = round((total_likes + total_comments) / max(total_views_v, 1), 4) if vids else 0

    return {
        "channel": channel,
        "totals": {
            "subs": channel.get("subs", 0),
            "views": channel.get("views", 0),
            "video_count": channel.get("video_count", 0),
            "total_likes": total_likes,
            "total_comments": total_comments,
            "avg_engagement": avg_engagement,
        },
        "videos": vids,
        "top": vids[:5],
        "timeseries": [{"date": h["date"], "subs": h["subs"], "views": h["views"]}
                       for h in timeseries],
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source": "youtube_data_api_v3",
    }
