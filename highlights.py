# -*- coding: utf-8 -*-
"""
highlights.py — 長尺動画から「盛り上がり」を見つける。

長尺（配信アーカイブ等）をそのまま Gemini に見せることはできない。
2時間 = 7200秒 x 300トークン/秒 = 216万トークンで、コンテキスト上限を超える。
そこで「どこを見るか」を先に決める。使う材料は2つ:

  heatmap … YouTube の「最も再生された部分」。視聴者が実際に見返した場所。
            トークン0・待ち時間0。ただし *映像* の見せ場しか映らない
            （黙って動くシーンは拾えるが、面白い会話は拾えない）。
  字幕   … 時刻つきの発話。約8千トークン・1.5秒。*会話* の見せ場が分かる。
            （実測: 20分の動画でフレーム解析の47分の1）

この2つは競合しない。実測では heatmap は「揺れるのを見返す」場面を、
字幕は「下ネタ談義」を選んだ。どちらも正解で、見ているものが違う。
両方を Gemini に渡し、最終判断だけさせる。

片方しか無くても動く（新しい動画に heatmap は無い／字幕の無い動画もある）。
"""
from __future__ import annotations

import json
import re
from typing import Callable, Optional

LOG_CB = Callable[[str], None]

# heatmap の冒頭は必ず高く出る（全員が通るため）。実測で最初の60秒は
# 全体平均の約1.5倍だった。ここを切り抜きに選ぶと事故るので割り引く。
_INTRO_SEC = 60
_INTRO_PENALTY = 0.6


def fetch_video_meta(url: str, log: LOG_CB = print) -> dict:
    """yt-dlp で heatmap・字幕・尺などを取る（動画本体はDLしない）。"""
    import yt_dlp
    opts = {"quiet": True, "no_warnings": True, "skip_download": True}
    import os
    ck = os.environ.get("YTDLP_COOKIEFILE", "")
    if ck:
        opts["cookiefile"] = ck
    px = os.environ.get("YTDLP_PROXY", "")
    if px:
        opts["proxy"] = px
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            return ydl.extract_info(url, download=False) or {}
    except Exception as e:
        log(f"⚠️ 動画情報の取得に失敗: {e}")
        return {}


def heatmap_peaks(info: dict, top: int = 6) -> list[dict]:
    """
    heatmap から盛り上がり候補を返す。[{start, end, value}]
    冒頭バイアスを補正してから強い順に並べる。
    """
    hm = info.get("heatmap") or []
    if not hm:
        return []
    out = []
    for h in hm:
        try:
            s = float(h.get("start_time", 0))
            v = float(h.get("value", 0))
        except (TypeError, ValueError):
            continue
        if s < _INTRO_SEC:
            v *= _INTRO_PENALTY      # 冒頭は誰でも通る＝盛り上がりではない
        out.append({"start": s, "end": float(h.get("end_time", s + 10)), "value": v})
    out.sort(key=lambda x: -x["value"])
    return out[:top]


def _pick_caption_url(info: dict) -> Optional[str]:
    """
    字幕(json3)の直URLを1つ選ぶ。手動字幕を優先し、無ければ自動字幕。
    元の言語を優先する（自動翻訳された157言語ぶんを漁らない）。
    """
    for store in (info.get("subtitles") or {}, info.get("automatic_captions") or {}):
        if not store:
            continue
        # 元言語 → 英語 → 日本語 → 残り、の順で最初に見つかったもの
        orig = (info.get("language") or "").split("-")[0]
        order = [k for k in (orig, "en", "ja") if k and k in store]
        order += [k for k in store.keys() if k not in order]
        for k in order:
            for f in store.get(k) or []:
                if f.get("ext") == "json3" and f.get("url"):
                    return f["url"]
    return None


def fetch_transcript(info: dict, log: LOG_CB = print) -> list[tuple[float, str]]:
    """
    字幕を [(秒, テキスト), ...] で返す。

    fetch_video_meta が取ってきた info に字幕の直URLが入っているので、
    それを1回だけ取得する。yt-dlp の字幕DL機構は指定した言語ぶん
    リクエストを撃つので、YouTube に 429 を返されやすい（実測で踏んだ）。
    取れなければ空リスト＝呼び出し側は heatmap だけで続行できる。
    """
    import os
    import urllib.request

    u = _pick_caption_url(info)
    if not u:
        return []
    try:
        req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"})
        px = os.environ.get("YTDLP_PROXY", "")
        if px:
            req.set_proxy(px.split("://")[-1], px.split("://")[0] if "://" in px else "http")
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read().decode("utf-8", "ignore"))
    except Exception as e:
        log(f"⚠️ 字幕の取得に失敗（映像データのみで続行）: {str(e)[:80]}")
        return []

    lines = []
    for ev in data.get("events", []):
        segs = ev.get("segs")
        if not segs:
            continue
        t = ev.get("tStartMs", 0) / 1000.0
        txt = "".join(s.get("utf8", "") for s in segs).replace("\n", " ").strip()
        if not txt or txt == "[Music]":
            continue
        lines.append((t, txt))
    return lines


def transcript_digest(lines: list[tuple[float, str]], bucket: int = 10) -> str:
    """
    字幕を bucket 秒ごとにまとめた "[MM:SS] 発話" 形式にする。
    自動字幕は同じ語を何度も繰り返すので、まとめるとトークンが大きく減る
    （実測: 896イベント → 112行 / 25,001文字 ≒ 8,333トークン）。
    """
    if not lines:
        return ""
    merged, cur, buf = [], lines[0][0], []
    for t, txt in lines:
        if buf and t - cur >= bucket:
            merged.append((cur, " ".join(buf)))
            buf, cur = [], t
        if not buf:
            cur = t
        buf.append(txt)
    if buf:
        merged.append((cur, " ".join(buf)))
    return "\n".join(
        f"[{int(t)//60:02d}:{int(t)%60:02d}] {tx}" for t, tx in merged)


def _fmt(sec: float) -> str:
    return f"{int(sec)//60:02d}:{int(sec)%60:02d}"


def _parse_time(v) -> Optional[float]:
    """
    "MM:SS" / "H:MM:SS" を秒に直す。数値ならそのまま秒とみなす。

    秒への換算は必ずここで行う。モデルに換算させると、字幕に [03:10] と
    書いてあっても start_sec:1344 のような値を返してくることがある（実測）。
    見えている表記を書き写させて、計算はコードが持つ。
    """
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    m = re.match(r"^\s*(?:(\d+):)?(\d{1,2}):(\d{1,2})(?:\.(\d+))?\s*$", str(v))
    if not m:
        return None
    h = int(m.group(1) or 0)
    return h * 3600 + int(m.group(2)) * 60 + int(m.group(3)) + float("0." + (m.group(4) or "0"))


def find_highlights(url: str, client, log: LOG_CB = print,
                    want: int = 3, clip_sec: int = 60,
                    lang: str = "ja") -> list[dict]:
    """
    盛り上がり区間を返す: [{start, end, why, source}]
    client は pipeline.init_gemini() で作った Gemini クライアント。

    heatmap も字幕も無い場合は空を返す（呼び出し側で従来動作にフォールバック）。
    """
    info = fetch_video_meta(url, log)
    dur = float(info.get("duration") or 0)
    if not dur:
        return []

    peaks = heatmap_peaks(info)
    if peaks:
        log(f"📈 視聴者の再生データから {len(peaks)} 箇所の候補（冒頭補正済み）")
    tr_lines = fetch_transcript(info, log)
    digest = transcript_digest(tr_lines)
    if digest:
        log(f"📝 字幕 {len(tr_lines)} 行を取得（約{len(digest)//3}トークン）")

    if not peaks and not digest:
        log("⚠️ 再生データも字幕も無い動画のため、盛り上がり検出をスキップします")
        return []

    # ── 材料を並べて Gemini に最終判断だけさせる
    blocks = []
    if peaks:
        blocks.append(
            "【視聴者が実際に見返した箇所】(強度が高いほど何度も見返された。映像の見せ場)\n" +
            "\n".join(f"- {_fmt(p['start'])} 強度{p['value']:.2f}" for p in peaks))
    if digest:
        blocks.append("【字幕（時刻つき発話）】(会話の見せ場を探す材料)\n" + digest)

    prompt = f"""あなたは切り抜き動画の編集者です。長さ{_fmt(dur)}の動画から、
ショート動画にすると最も伸びる箇所を{want}個選んでください。

材料は2種類あります:
- 「視聴者が実際に見返した箇所」は映像の見せ場を示します（何かが起きて、見返す価値があった）
- 「字幕」は会話の見せ場を示します（面白い発言・掛け合い）
両方を突き合わせ、映像と会話の両面から最も強い箇所を選んでください。
片方にしか出てこない箇所でも、十分に強ければ選んで構いません。

盛り上がりの少し手前から始めて、文脈が分かるようにしてください。
冒頭（最初の1分）は誰もが通るだけなので、そこに特別な出来事が無い限り選ばないでください。

time には、上の材料に書かれている時刻表記（MM:SS）を**そのまま書き写して**ください。
秒数に換算しないでください（換算はこちらで行います）。

JSONのみ返答（コードブロック不要）:
[{{"time": "MM:SS", "why": "選んだ理由(30文字以内)", "source": "映像/会話/両方"}}]

{chr(10).join(blocks)}
"""
    from pipeline import _gemini_call
    try:
        raw = _gemini_call(client, prompt, log=log)
    except Exception as e:
        log(f"⚠️ 盛り上がり検出に失敗: {e}")
        return []

    txt = re.sub(r"^```(?:json)?|```$", "", (raw or "").strip(), flags=re.M).strip()
    try:
        items = json.loads(txt)
    except Exception:
        m = re.search(r"\[.*\]", txt, re.S)
        if not m:
            log(f"⚠️ 盛り上がり検出の応答を解釈できませんでした: {txt[:80]!r}")
            return []
        try:
            items = json.loads(m.group(0))
        except Exception as e:
            log(f"⚠️ 盛り上がり検出の応答を解釈できませんでした: {e}")
            return []

    out = []
    for it in items if isinstance(items, list) else []:
        s = _parse_time(it.get("time"))
        if s is None:
            # 秒数で返してきた場合の保険（モデルの MM:SS→秒 の暗算は当てにならない）
            try:
                s = float(it.get("start_sec"))
            except (TypeError, ValueError):
                continue
        if not (0 <= s < dur):
            log(f"  ⚠️ 範囲外の時刻を無視: {it.get('time') or s}（尺 {_fmt(dur)}）")
            continue
        # 少し手前から始めて文脈を残す。終わりは尺で頭打ち。
        start = max(0.0, s - 5)
        end = min(dur, start + clip_sec)
        out.append({"start": start, "end": end,
                    "why": str(it.get("why", ""))[:60],
                    "source": str(it.get("source", ""))[:8]})
    for h in out:
        log(f"  ⭐ {_fmt(h['start'])}–{_fmt(h['end'])} [{h['source']}] {h['why']}")
    return out[:want]
