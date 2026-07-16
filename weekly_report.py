"""
weekly_report.py
毎週月曜に自動でnote用レポートを生成する
  - 先週の再生数・伸び・バズった動画を集計
  - Gemini で note 記事文章を生成
  - テキストファイルとして書き出し（貼るだけで完成）
  - スケジューラーから呼び出し可能
"""

import json, os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable
import db

JST    = timezone(timedelta(hours=9))
LOG_CB = Callable[[str], None]

REPORT_DIR = Path.home() / "TomatoClip_Output" / "weekly_reports"


# ════════════════════════════════════════════════════════
#  集計
# ════════════════════════════════════════════════════════
def _collect_weekly_stats(days: int = 7) -> dict:
    """先週分のデータを集計して返す"""
    now       = datetime.now(JST)
    week_ago  = now - timedelta(days=days)
    all_vids  = db.get_videos(limit=200)

    # 先週投稿した動画
    week_vids = [
        v for v in all_vids
        if v.get("posted_at") and
        datetime.fromisoformat(v["posted_at"]).replace(tzinfo=JST) >= week_ago
    ]

    # アナリティクス集計
    total_views = 0
    total_likes = 0
    video_stats = []
    for v in week_vids:
        rows = db.get_analytics(v["id"])
        peak_views = max((r["views"] for r in rows), default=0)
        peak_likes = max((r["likes"] for r in rows), default=0)

        # 伸び率（最初→最後）
        growth = 0
        if len(rows) >= 2:
            first = rows[0]["views"] or 1
            last  = rows[-1]["views"]
            growth = round((last - first) / first * 100, 1)

        total_views += peak_views
        total_likes += peak_likes
        video_stats.append({
            "title":      v.get("title", "不明"),
            "channel":    v.get("channel", "不明"),
            "views":      peak_views,
            "likes":      peak_likes,
            "growth":     growth,
            "template":   v.get("template_id", "default"),
            "posted_at":  v.get("posted_at", "")[:10],
            "yt_url":     v.get("yt_url", ""),
            "score":      v.get("score", 0),
        })

    video_stats.sort(key=lambda x: x["views"], reverse=True)

    # 全期間の累計
    all_summary = db.get_all_analytics_summary()
    total_all_views = sum(v.get("peak_views") or 0 for v in all_summary)

    # チャンネル別ランキング（先週）
    ch_map = {}
    for v in video_stats:
        ch = v["channel"]
        ch_map.setdefault(ch, 0)
        ch_map[ch] += v["views"]
    ch_ranking = sorted(ch_map.items(), key=lambda x: x[1], reverse=True)

    # テンプレート別
    tmpl_map = {}
    for v in video_stats:
        t = v["template"]
        tmpl_map.setdefault(t, {"count": 0, "views": 0})
        tmpl_map[t]["count"] += 1
        tmpl_map[t]["views"] += v["views"]

    # 前週比（簡易: 2週間前のデータと比較）
    two_weeks_ago = now - timedelta(days=days * 2)
    prev_vids = [
        v for v in all_vids
        if v.get("posted_at") and
        two_weeks_ago <= datetime.fromisoformat(v["posted_at"]).replace(tzinfo=JST) < week_ago
    ]
    prev_views = 0
    for v in prev_vids:
        rows = db.get_analytics(v["id"])
        prev_views += max((r["views"] for r in rows), default=0)

    wow_rate = 0.0
    if prev_views > 0:
        wow_rate = round((total_views - prev_views) / prev_views * 100, 1)

    week_num = now.isocalendar()[1]

    return {
        "week_num":       week_num,
        "period":         f"{week_ago.strftime('%Y/%m/%d')} 〜 {now.strftime('%Y/%m/%d')}",
        "posted_count":   len(week_vids),
        "total_views":    total_views,
        "total_likes":    total_likes,
        "wow_rate":       wow_rate,
        "total_all_views":total_all_views,
        "video_stats":    video_stats,
        "top3":           video_stats[:3],
        "ch_ranking":     ch_ranking[:5],
        "tmpl_map":       tmpl_map,
        "generated_at":   now.strftime("%Y/%m/%d %H:%M JST"),
    }


# ════════════════════════════════════════════════════════
#  Gemini で記事本文を生成
# ════════════════════════════════════════════════════════
def _generate_article(model, stats: dict, log: LOG_CB) -> str:
    log("📝 Gemini で記事生成中...")

    top3_str = "\n".join(
        f"  {i+1}. 『{v['title']}』({v['channel']}) — {v['views']:,}再生 / +{v['growth']}%伸び"
        for i, v in enumerate(stats["top3"])
    ) or "  データなし"

    ch_str = "\n".join(
        f"  {i+1}. {ch} — {views:,}再生"
        for i, (ch, views) in enumerate(stats["ch_ranking"])
    ) or "  データなし"

    prompt = f"""
あなたは「TOMATO SHORTS」というYouTube自動化ツールを開発・運用しているクリエイターです。
noteで週次実績レポートを発信しています。読者はツールに興味があるクリエイターです。

以下のデータを元に、**noteの記事本文**をMarkdown形式で書いてください。

【制約】
- 文体: テンション高め・正直・ユーモアあり・データ根拠あり
- 長さ: 800〜1200文字
- 構成: 見出し(##)を使う、数字を積極的に使う
- 最後: ツールへの興味喚起（押しつけがましくなく）
- NG: 嘘の数字・誇張しすぎ・「完璧でした」みたいな嘘くさい表現

【今週のデータ】
- 集計期間: {stats['period']}
- 投稿本数: {stats['posted_count']} 本
- 総再生数: {stats['total_views']:,}
- 総いいね: {stats['total_likes']:,}
- 前週比: {'+' if stats['wow_rate'] >= 0 else ''}{stats['wow_rate']}%
- 累計総再生数: {stats['total_all_views']:,}

【今週のTOP3動画】
{top3_str}

【チャンネル別再生数ランキング】
{ch_str}

記事本文のみ返答してください（タイトルは不要、本文から始める）。
"""

    try:
        resp = model.generate_content(prompt)
        return resp.text.strip()
    except Exception as e:
        log(f"⚠️ Gemini 生成失敗: {e}")
        return _fallback_article(stats)


def _fallback_article(stats: dict) -> str:
    """Gemini 失敗時のフォールバックテンプレ"""
    top = stats["top3"][0] if stats["top3"] else {}
    return f"""
## 今週の実績（第{stats['week_num']}週）

集計期間: {stats['period']}

今週は **{stats['posted_count']}本** の動画を自動投稿しました。

総再生数は **{stats['total_views']:,}** で、前週比 **{stats['wow_rate']:+}%** でした。

{'最もバズった動画は「' + top.get('title','—') + '」で ' + f"{top.get('views',0):,}" + '再生でした。' if top else ''}

引き続きデータを積み上げていきます！
""".strip()


# ════════════════════════════════════════════════════════
#  テキストファイル書き出し
# ════════════════════════════════════════════════════════
def _build_full_report(stats: dict, body: str) -> str:
    """note に貼り付ける完全な記事テキストを組み立てる"""
    top3_block = ""
    for i, v in enumerate(stats["top3"], 1):
        url_part = f"\n   URL: {v['yt_url']}" if v.get("yt_url") else ""
        top3_block += (
            f"\n{i}. 【{v['views']:,}再生】{v['title']}\n"
            f"   チャンネル: {v['channel']} / いいね: {v['likes']:,} / 伸び率: {v['growth']:+}%{url_part}\n"
        )

    tmpl_block = ""
    for tid, d in stats["tmpl_map"].items():
        avg = d["views"] // d["count"] if d["count"] else 0
        tmpl_block += f"  - {tid}: {d['count']}本 / 平均{avg:,}再生\n"

    header = f"""---
■ TOMATO SHORTS 週次レポート — 第{stats['week_num']}週
■ 集計期間: {stats['period']}
■ 生成日時: {stats['generated_at']}
---

"""
    data_block = f"""
---
## 📊 今週の数字まとめ

| 項目 | 数値 |
|---|---|
| 投稿本数 | {stats['posted_count']} 本 |
| 総再生数 | {stats['total_views']:,} |
| 総いいね数 | {stats['total_likes']:,} |
| 前週比 | {stats['wow_rate']:+}% |
| 累計総再生数 | {stats['total_all_views']:,} |

## 🏆 今週のTOP3
{top3_block}
## 🎨 テンプレート別パフォーマンス
{tmpl_block if tmpl_block else '  データなし\n'}
---
※ このレポートは TOMATO SHORTS の analytics モジュールが自動生成しました
"""
    return header + body + data_block


# ════════════════════════════════════════════════════════
#  メイン: レポート生成エントリポイント
# ════════════════════════════════════════════════════════
def generate_weekly_report(gemini_key: str, log: LOG_CB,
                            days: int = 7) -> str:
    """
    週次レポートを生成してファイルパスを返す。
    スケジューラーや GUI から呼び出す。
    """
    log("=" * 45)
    log("📝 週次レポート生成開始")
    log("=" * 45)

    # 集計
    log("📊 データ集計中...")
    stats = _collect_weekly_stats(days=days)
    log(f"  投稿: {stats['posted_count']}本 / 再生: {stats['total_views']:,} / 前週比: {stats['wow_rate']:+}%")

    # Gemini で記事生成
    body = ""
    if gemini_key:
        try:
            import google.generativeai as genai
            genai.configure(api_key=gemini_key)
            model = genai.GenerativeModel("gemini-2.0-flash")
            body  = _generate_article(model, stats, log)
        except Exception as e:
            log(f"⚠️ Gemini 初期化失敗: {e}")
            body = _fallback_article(stats)
    else:
        body = _fallback_article(stats)

    # ファイル書き出し
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    now      = datetime.now(JST)
    filename = f"weekly_report_week{stats['week_num']}_{now.strftime('%Y%m%d')}.txt"
    filepath = REPORT_DIR / filename

    full_text = _build_full_report(stats, body)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(full_text)

    log(f"✅ レポート生成完了 → {filepath}")
    log(f"   noteに貼り付けるだけで完成です！")
    return str(filepath)


# ════════════════════════════════════════════════════════
#  スケジューラー用: 毎週月曜チェック
# ════════════════════════════════════════════════════════
def should_run_weekly(last_report_path: str = "") -> bool:
    """今日が月曜かつ今週まだ生成していないなら True"""
    now = datetime.now(JST)
    if now.weekday() != 0:   # 0 = Monday
        return False
    if last_report_path and Path(last_report_path).exists():
        mtime = datetime.fromtimestamp(
            Path(last_report_path).stat().st_mtime, tz=JST)
        if (now - mtime).days < 6:
            return False
    return True
