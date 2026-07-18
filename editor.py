"""
editor.py
動画編集モジュール
  - 無音/冗長シーンの自動カット
  - 縦型リサイズ
  - タイトル/字幕オーバーレイ
  - タイプ音
  - ドクロ演出（ラスト・全画面・モノクロ）
  - Phonk BGM（librosa サビ同期）
  - 冒頭ナレーション
"""

import os, random, tempfile, textwrap, time
from pathlib import Path
from typing import Callable

import numpy as np
from PIL import Image, ImageDraw, ImageFont

# Pillow 10+ で削除された旧定数を復元（moviepy 1.x の resize が参照する）
if not hasattr(Image, "ANTIALIAS"):
    Image.ANTIALIAS = Image.LANCZOS

LOG_CB = Callable[[str], None]

VIDEO_SIZE       = (1080, 1920)
TITLE_COLOR      = "#FFE000"
SUBTITLE_COLOR   = "#FF3B30"
CAPTION_COLOR    = "#00FF5A"
FONT_PATH        = "NotoSansJP-Bold.ttf"
CAPTION_ZONE_H   = 320
TITLE_SHOW_SEC   = 4.5   # タイトル/サブタイトルを冒頭に出す秒数（全編出しっぱなし対策）


# ════════════════════════════════════════════════════════
#  フォント取得
# ════════════════════════════════════════════════════════
# ════════════════════════════════════════════════════════
#  フォントカタログ（GeminiがAI解析時に font_style で選択する）
#  ファイルは ~/.tomato_clip/fonts/ に配置（全て SIL OFL・商用利用可）
# ════════════════════════════════════════════════════════
FONTS_DIR = Path.home() / ".tomato_clip" / "fonts"

FONT_CATALOG = {
    "standard":    {"file": None,
                    "desc": "標準の太角ゴシック。万能・読みやすい。迷ったらこれ"},
    "impact":      {"file": "DelaGothicOne-Regular.ttf",
                    "desc": "超極太ゴシック（Dela Gothic One）。インパクト最強・バズ系・衝撃系"},
    "pop":         {"file": "MochiyPopOne-Regular.ttf",
                    "desc": "丸いポップ体（Mochiy Pop One）。かわいい・ゆるい・ほのぼの系"},
    "rounded":     {"file": "MPLUSRounded1c-Black.ttf",
                    "desc": "極太丸ゴシック（M PLUS Rounded 1c）。親しみやすい・優しい・日常系"},
    "energetic":   {"file": "RocknRollOne-Regular.ttf",
                    "desc": "勢いのあるポップ体（RocknRoll One）。テンション高い・音楽・ノリ系"},
    "shout":       {"file": "ReggaeOne-Regular.ttf",
                    "desc": "叫び系の極太書体（Reggae One）。ツッコミ・バラエティ・絶叫系"},
    "comic":       {"file": "RampartOne-Regular.ttf",
                    "desc": "立体アウトライン（Rampart One）。ふざけ・シュール・ネタ系"},
    "handwritten": {"file": "YuseiMagic-Regular.ttf",
                    "desc": "マジックペン手書き風（Yusei Magic）。実況コメント・ラフ・友達感"},
    "cute":        {"file": "HachiMaruPop-Regular.ttf",
                    "desc": "ゆるかわ手書き（Hachi Maru Pop）。女子系・ペット・癒し系"},
    "retro":       {"file": "DotGothic16-Regular.ttf",
                    "desc": "8bitドット文字（DotGothic16）。ゲーム・レトロ・ネット文化系"},
    "serif":       {"file": "ShipporiMinchoB1-Bold.ttf",
                    "desc": "太明朝（しっぽり明朝）。シリアス・回想・感動・ドラマチック系"},
}


_HIRAGINO_CACHE = "unset"


def _hiragino_font_file():
    """ヒラギノ角ゴがインストールされていればファイルパスを返す（太字優先・キャッシュ）"""
    global _HIRAGINO_CACHE
    if _HIRAGINO_CACHE != "unset":
        return _HIRAGINO_CACHE
    import glob
    dirs = [
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Windows\Fonts"),
        r"C:\Windows\Fonts",
    ]
    patterns = ["*ヒラギノ角ゴ*W6*", "*Hira*W6*", "*ヒラギノ角ゴ*W3*", "*Hira*W3*",
                "*ヒラギノ*", "*Hiragino*"]
    for d in dirs:
        for pat in patterns:
            hits = sorted(glob.glob(os.path.join(d, pat)))
            for h in hits:
                if h.lower().endswith((".ttf", ".ttc", ".otf")):
                    _HIRAGINO_CACHE = h
                    return h
    _HIRAGINO_CACHE = None
    return None


def _font(size: int, style: str = None):
    """
    style: FONT_CATALOG のキー（Geminiが動画の雰囲気に合わせて選択）。
    None / "standard" / 未知の値 / ファイル欠損時は標準チェーンにフォールバック。
    """
    if style and style != "standard":
        info = FONT_CATALOG.get(style)
        if info and info.get("file"):
            p = FONTS_DIR / info["file"]
            if p.exists():
                try:
                    return ImageFont.truetype(str(p), size)
                except Exception:
                    pass

    candidates = [
        _hiragino_font_file(),  # ヒラギノ角ゴ（あれば最優先）
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Windows\Fonts\NotoSansCJKjp-Bold.otf"),
        FONT_PATH,
        r"C:\Windows\Fonts\BIZ-UDGothicB.ttc",
        r"C:\Windows\Fonts\meiryo.ttc",
        r"C:\Windows\Fonts\YuGothB.ttc",
        r"C:\Windows\Fonts\GOTHICB.TTF",
    ]
    for path in candidates:
        if not path:
            continue
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


# ════════════════════════════════════════════════════════
#  自動カット
# ════════════════════════════════════════════════════════
class TimeMap:
    """
    「元動画の時刻」→「編集後の時刻」の対応表。

    なぜ要るか: カット・早送り・巻き戻し・フリーズは、どれも動画の長さを変える。
    Gemini が返す秒数はすべて *元動画* を見て決めた値なので、それを
    変換後のクリップにそのまま渡すと、2つ目以降のエフェクトは必ず別の場所に当たる。
    （カットで30秒削れば、ズームは30秒ズレる。字幕も同じだけズレる。）
    変換を1つ適用するたびにここへ登録し、以降の秒数は map() を通してから使う。
    """

    def __init__(self):
        self._ops = []

    def add_cuts(self, cuts: list):
        """[{start,end}] を取り除いた。カット中の時刻はカット開始点に寄せる。"""
        rs = sorted(((float(c["start"]), float(c["end"])) for c in cuts
                     if float(c["end"]) > float(c["start"])), key=lambda x: x[0])
        if not rs:
            return

        def op(t):
            shift = 0.0
            for s, e in rs:
                if t >= e:
                    shift += e - s          # まるごと手前で消えた分
                elif t > s:
                    return s - shift        # カットされた区間の中 → その入口へ
            return t - shift
        self._ops.append(op)

    def add_speed(self, s: float, e: float, speed: float):
        """[s,e] を speed 倍速にした（この s,e は変換前の時刻）。"""
        if e <= s or speed <= 0:
            return
        span = e - s

        def op(t):
            if t <= s:
                return t
            if t >= e:
                return t - span + span / speed
            return s + (t - s) / speed
        self._ops.append(op)

    def add_insert(self, at: float, dur: float):
        """at に dur 秒ぶん挿入した（巻き戻し・フリーズ）。"""
        if dur <= 0:
            return

        def op(t):
            return t + dur if t > at else t
        self._ops.append(op)

    def map(self, t) -> float:
        """元動画の秒数 → 現在のクリップ上の秒数。"""
        t = float(t)
        for op in self._ops:
            t = op(t)
        return max(0.0, t)


def apply_cuts(video, cut_sections: list, log: LOG_CB):
    """
    cut_sections: [{"start": float, "end": float}]
    カット区間を除いた VideoFileClip を返す。
    """
    from moviepy.editor import concatenate_videoclips

    if not cut_sections:
        return video

    dur = video.duration
    # カット区間をソート・クリップ
    cuts = sorted(cut_sections, key=lambda x: x["start"])
    keep = []
    prev = 0.0
    for c in cuts:
        s = max(0.0, min(float(c["start"]), dur))
        e = max(0.0, min(float(c["end"]),   dur))
        if s > prev + 0.1:
            keep.append((prev, s))
        prev = e
    if prev < dur - 0.1:
        keep.append((prev, dur))

    if not keep:
        log("⚠️ カット後に映像なし → カットをスキップ")
        return video

    log(f"✂️  カット: {len(cut_sections)}箇所 → {len(keep)}区間を結合")
    clips = [video.subclip(s, e) for s, e in keep]
    return concatenate_videoclips(clips, method="chain")


# ════════════════════════════════════════════════════════
#  タイプ音
# ════════════════════════════════════════════════════════
def _typewriter_sound(duration_sec: float, fps: int = 44100) -> np.ndarray:
    samples        = int(duration_sec * fps)
    audio          = np.zeros(samples)
    click_interval = int(0.07 * fps)
    click_dur      = int(0.012 * fps)
    for pos in range(0, samples - click_dur, click_interval):
        freq  = random.uniform(800, 1400)
        t     = np.linspace(0, click_dur / fps, click_dur)
        click = 0.15 * np.sin(2 * np.pi * freq * t) * np.exp(-t * 80)
        audio[pos:pos + click_dur] += click
    return np.column_stack([audio, audio]).astype(np.float32)


# ════════════════════════════════════════════════════════
#  字幕クリップ
# ════════════════════════════════════════════════════════
def _caption_clip(text: str, start: float, end: float,
                  is_funny: bool, tw: int, th: int, font_size: int = 58):
    from moviepy.editor import ImageClip
    padding   = 20
    font      = _font(font_size)
    wrap_w    = max(6, int(14 * 58 / font_size))
    wrapped   = textwrap.fill(text, width=wrap_w)
    lines     = wrapped.split("\n")
    dummy     = Image.new("RGBA", (1, 1))
    draw      = ImageDraw.Draw(dummy)
    line_h    = font_size + 8
    text_w    = max((draw.textlength(l, font=font) for l in lines), default=200)
    bg_w      = int(text_w) + padding * 2
    bg_h      = int(line_h * len(lines)) + padding * 2

    img  = Image.new("RGBA", (bg_w, bg_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    if is_funny:
        draw.rounded_rectangle([0, 0, bg_w, bg_h], radius=12, fill=(255, 220, 0, 210))
        tc = "#111111"
    else:
        draw.rounded_rectangle([0, 0, bg_w, bg_h], radius=12, fill=(0, 0, 0, 170))
        tc = CAPTION_COLOR

    for i, line in enumerate(lines):
        lw = draw.textlength(line, font=font)
        x  = (bg_w - lw) / 2
        y  = padding + i * line_h
        draw.text((x + 2, y + 2), line, font=font, fill="#000000")
        draw.text((x, y),         line, font=font, fill=tc)

    return (ImageClip(np.array(img))
            .set_duration(end - start)
            .set_start(start)
            .set_position(("center", th - CAPTION_ZONE_H + (CAPTION_ZONE_H - bg_h) // 2)))


# ════════════════════════════════════════════════════════
#  タイトルクリップ
# ════════════════════════════════════════════════════════
def _title_clips(title: str, subtitle: str, tw: int, th: int, dur: float):
    from moviepy.editor import ImageClip

    def _img(text, color, font_size, y_pos):
        text  = text.replace("\n", " ").strip()
        font  = _font(font_size)
        dummy = Image.new("RGBA", (1, 1))
        draw  = ImageDraw.Draw(dummy)
        w     = int(draw.textlength(text, font=font))
        img   = Image.new("RGBA", (w + 20, font_size + 18), (0, 0, 0, 0))
        draw  = ImageDraw.Draw(img)
        draw.text((12, 5), text, font=font, fill="#000000")
        draw.text((10, 4), text, font=font, fill=color)
        return (ImageClip(np.array(img))
                .set_duration(dur)
                .set_position(("center", y_pos)))

    return [_img(title, TITLE_COLOR, 72, 80), _img(subtitle, SUBTITLE_COLOR, 50, 165)]




# ════════════════════════════════════════════════════════
#  早送り
# ════════════════════════════════════════════════════════
def apply_fastforward(clip, ff_start: float, ff_end: float,
                      speed: float = 2.0, log=print):
    """
    ff_start〜ff_end 区間を speed 倍速にする。
    音声は無音化（高速再生の音声は不自然なので）。
    """
    from moviepy.editor import concatenate_videoclips
    from moviepy.video.fx.speedx import speedx as vfx_speedx

    try:
        ff_start = max(0.0, ff_start)
        ff_end   = min(ff_end, clip.duration)
        if ff_end - ff_start < 0.5 or speed <= 1.0:
            return clip

        before = clip.subclip(0, ff_start) if ff_start > 0.05 else None
        fast   = (clip.subclip(ff_start, ff_end)
                  .fx(vfx_speedx, speed)
                  .without_audio())
        after  = clip.subclip(ff_end) if ff_end < clip.duration - 0.05 else None

        parts = [p for p in [before, fast, after] if p is not None]
        new_dur = sum(p.duration for p in parts)
        log(f"⏩ 早送り: {ff_start:.1f}s〜{ff_end:.1f}s × {speed}倍 "
            f"({ff_end - ff_start:.1f}s → {(ff_end - ff_start) / speed:.1f}s)")
        return concatenate_videoclips(parts, method="chain")
    except Exception as e:
        log(f"⚠️ 早送り失敗: {e}")
        return clip


# ════════════════════════════════════════════════════════
#  巻き戻し・フリーズエフェクト
# ════════════════════════════════════════════════════════
def apply_rewind(clip, rewind_at: float, rewind_dur: float = 1.5, log=print):
    """
    rewind_at 秒の直前を rewind_dur 秒逆再生してから続ける。
    例: rewind_at=5.0, dur=1.5 → [0→3.5] + [3.5→5逆] + [3.5→end]
    """
    from moviepy.editor import concatenate_videoclips
    try:
        t_start = max(0.0, rewind_at - rewind_dur)
        t_end   = min(rewind_at, clip.duration)
        if t_end - t_start < 0.3:
            return clip
        before   = clip.subclip(0, t_start) if t_start > 0 else None
        segment  = clip.subclip(t_start, t_end)
        reversed_seg = segment.fl_time(lambda t: segment.duration - t,
                                       apply_to=["mask", "video"]).set_duration(segment.duration)
        after    = clip.subclip(t_start)
        parts    = [p for p in [before, reversed_seg, after] if p is not None]
        log(f"⏪ 巻き戻しエフェクト: {t_start:.1f}s〜{t_end:.1f}s")
        return concatenate_videoclips(parts, method="chain")
    except Exception as e:
        log(f"⚠️ 巻き戻し失敗: {e}")
        return clip


def apply_freeze(clip, freeze_at: float, freeze_dur: float = 1.5, log=print):
    """
    freeze_at 秒のフレームを freeze_dur 秒静止させてから続ける。
    """
    from moviepy.editor import ImageClip, concatenate_videoclips
    try:
        t = min(max(freeze_at, 0.0), clip.duration - 0.1)
        frame        = clip.get_frame(t)
        freeze_clip  = (ImageClip(frame)
                        .set_duration(freeze_dur)
                        .set_fps(clip.fps or 30))
        before = clip.subclip(0, t)
        after  = clip.subclip(t)
        log(f"⏸ フリーズフレーム: {t:.1f}s × {freeze_dur:.1f}秒")
        return concatenate_videoclips([before, freeze_clip, after], method="chain")
    except Exception as e:
        log(f"⚠️ フリーズ失敗: {e}")
        return clip


# ════════════════════════════════════════════════════════
#  ズーム・モノクロ・反転・モザイク
# ════════════════════════════════════════════════════════
def apply_zoom(clip, zoom_at: float, zoom_end: float,
               scale: float = 1.5, log=print):
    """zoom_at〜zoom_end 区間を中央クロップでズームイン"""
    from moviepy.editor import concatenate_videoclips
    try:
        zoom_at  = max(0.0, zoom_at)
        zoom_end = min(zoom_end, clip.duration)
        if zoom_end - zoom_at < 0.2 or scale <= 1.0:
            return clip
        before  = clip.subclip(0, zoom_at)  if zoom_at  > 0.05 else None
        after   = clip.subclip(zoom_end)    if zoom_end < clip.duration - 0.05 else None
        seg     = clip.subclip(zoom_at, zoom_end)
        w, h    = seg.size
        cw, ch  = int(w / scale), int(h / scale)
        x1, y1  = (w - cw) // 2, (h - ch) // 2
        zoomed  = seg.crop(x1=x1, y1=y1, x2=x1 + cw, y2=y1 + ch).resize((w, h))
        parts   = [p for p in [before, zoomed, after] if p is not None]
        log(f"🔍 ズーム: {zoom_at:.1f}s〜{zoom_end:.1f}s × {scale}倍")
        return concatenate_videoclips(parts, method="chain")
    except Exception as e:
        log(f"⚠️ ズーム失敗: {e}")
        return clip


def apply_monochrome(clip, mono_at: float, mono_end: float, log=print):
    """mono_at〜mono_end 区間をモノクロ化"""
    from moviepy.editor import concatenate_videoclips
    try:
        mono_at  = max(0.0, mono_at)
        mono_end = min(mono_end, clip.duration)
        if mono_end - mono_at < 0.2:
            return clip

        def _to_gray(frame):
            gray = np.dot(frame[..., :3], [0.299, 0.587, 0.114])
            return np.stack([gray, gray, gray], axis=-1).astype(np.uint8)

        before  = clip.subclip(0, mono_at)  if mono_at  > 0.05 else None
        after   = clip.subclip(mono_end)    if mono_end < clip.duration - 0.05 else None
        seg     = clip.subclip(mono_at, mono_end).fl_image(_to_gray)
        parts   = [p for p in [before, seg, after] if p is not None]
        log(f"🎞 モノクロ: {mono_at:.1f}s〜{mono_end:.1f}s")
        return concatenate_videoclips(parts, method="chain")
    except Exception as e:
        log(f"⚠️ モノクロ失敗: {e}")
        return clip


def apply_flip(clip, flip_at: float, flip_end: float, log=print):
    """flip_at〜flip_end 区間を左右反転（ミラー）"""
    from moviepy.editor import concatenate_videoclips
    from moviepy.video.fx.mirror_x import mirror_x
    try:
        flip_at  = max(0.0, flip_at)
        flip_end = min(flip_end, clip.duration)
        if flip_end - flip_at < 0.2:
            return clip
        before  = clip.subclip(0, flip_at)  if flip_at  > 0.05 else None
        after   = clip.subclip(flip_end)    if flip_end < clip.duration - 0.05 else None
        seg     = clip.subclip(flip_at, flip_end).fx(mirror_x)
        parts   = [p for p in [before, seg, after] if p is not None]
        log(f"↔️ 左右反転: {flip_at:.1f}s〜{flip_end:.1f}s")
        return concatenate_videoclips(parts, method="chain")
    except Exception as e:
        log(f"⚠️ 反転失敗: {e}")
        return clip


def apply_mosaic(clip, mosaic_at: float, mosaic_end: float,
                 block_size: int = 20, log=print):
    """mosaic_at〜mosaic_end 区間をモザイク（ピクセル化）"""
    from moviepy.editor import concatenate_videoclips
    try:
        mosaic_at  = max(0.0, mosaic_at)
        mosaic_end = min(mosaic_end, clip.duration)
        if mosaic_end - mosaic_at < 0.2:
            return clip

        def _pixelate(frame):
            h, w = frame.shape[:2]
            small = Image.fromarray(frame.astype(np.uint8)).resize(
                (max(1, w // block_size), max(1, h // block_size)), Image.NEAREST)
            return np.array(small.resize((w, h), Image.NEAREST))

        before  = clip.subclip(0, mosaic_at)  if mosaic_at  > 0.05 else None
        after   = clip.subclip(mosaic_end)    if mosaic_end < clip.duration - 0.05 else None
        seg     = clip.subclip(mosaic_at, mosaic_end).fl_image(_pixelate)
        parts   = [p for p in [before, seg, after] if p is not None]
        log(f"🟫 モザイク: {mosaic_at:.1f}s〜{mosaic_end:.1f}s (ブロック{block_size}px)")
        return concatenate_videoclips(parts, method="chain")
    except Exception as e:
        log(f"⚠️ モザイク失敗: {e}")
        return clip


# ════════════════════════════════════════════════════════
#  尺伸ばし
# ════════════════════════════════════════════════════════
def apply_duration_extend(clip, target_dur: float, method: str, log=print):
    """
    clip が target_dur 秒に満たない場合に尺を伸ばす。
    method: "loop" / "slowmo" / "replay" / "endcard"
    """
    from moviepy.editor import concatenate_videoclips, ImageClip

    if target_dur <= 0 or clip.duration >= target_dur:
        return clip

    needed = target_dur - clip.duration
    log(f"📏 尺伸ばし: {clip.duration:.1f}s → {target_dur:.1f}s ({method} +{needed:.1f}s)")

    try:
        if method == "loop":
            parts = [clip]
            total = clip.duration
            while total < target_dur:
                remain = target_dur - total
                if remain >= clip.duration:
                    parts.append(clip)
                    total += clip.duration
                else:
                    parts.append(clip.subclip(0, remain))
                    total += remain
            return concatenate_videoclips(parts, method="chain")

        elif method == "slowmo":
            slow_src  = max(0.0, clip.duration - min(needed * 2, clip.duration * 0.4))
            normal    = clip.subclip(0, slow_src) if slow_src > 0 else None
            slow_clip = (clip.subclip(slow_src)
                         .fl_time(lambda t: t * 0.5)
                         .set_duration((clip.duration - slow_src) * 2))
            parts = [p for p in [normal, slow_clip] if p is not None]
            result = concatenate_videoclips(parts, method="chain")
            return result.subclip(0, target_dur) if result.duration > target_dur else result

        elif method == "replay":
            hi_start = max(0.0, clip.duration * 0.3)
            hi_end   = min(hi_start + needed, clip.duration)
            replay   = clip.subclip(hi_start, hi_end)
            return concatenate_videoclips([clip, replay], method="chain")

        elif method == "endcard":
            try:
                frame = clip.get_frame(max(0, clip.duration - 0.1))
            except Exception:
                frame = clip.get_frame(0)
            endcard = ImageClip(frame).set_duration(needed).set_fps(clip.fps or 30)
            return concatenate_videoclips([clip, endcard], method="chain")

    except Exception as e:
        log(f"⚠️ 尺伸ばし失敗: {e}")

    return clip


# ════════════════════════════════════════════════════════
#  Phonk BGM（サビをドクロに同期）
# ════════════════════════════════════════════════════════
def _build_simple_bgm(bgm_path: str, video_dur: float,
                      volume: float, log=print):
    """BGMファイルをループして動画全体に敷く（フェードイン/アウト付き）"""
    from moviepy.audio.AudioClip import AudioArrayClip
    import librosa

    if not bgm_path or not Path(bgm_path).exists():
        log("⚠️ シンプルBGMなし → スキップ")
        return None

    log(f"🎵 シンプルBGM: {Path(bgm_path).name} (音量:{volume:.2f})")
    y, sr = librosa.load(bgm_path, sr=44100, mono=False)
    if y.ndim == 1:
        y = np.vstack([y, y])

    total   = int(video_dur * sr) + sr
    src_len = y.shape[1]
    looped  = np.zeros((2, total), dtype=np.float32)
    pos = 0
    while pos < total:
        chunk = min(src_len, total - pos)
        looped[:, pos:pos + chunk] = y[:, :chunk]
        pos += chunk

    # フェードイン2秒・フェードアウト2秒
    fi = int(2.0 * sr)
    fo = int(2.0 * sr)
    looped[:, :fi]          *= np.linspace(0, 1, fi)
    looped[:, total - fo:]  *= np.linspace(1, 0, fo)
    looped *= volume

    stereo = looped[:, :total].T.astype(np.float32)
    return AudioArrayClip(stereo, fps=sr).set_duration(video_dur)




# ════════════════════════════════════════════════════════
#  引用元クリップ（最後3秒に表示）
# ════════════════════════════════════════════════════════
def _make_source_clip(sources: list, tw: int, th: int, dur: float):
    """sources リストを最後3秒に小さく表示するクリップを返す"""
    from moviepy.editor import ImageClip

    if not sources:
        return None

    SHOW_DURATION = min(3.0, dur)
    start = max(0.0, dur - SHOW_DURATION)

    font_size = 22
    padding   = 10
    font      = _font(font_size)
    line_h    = font_size + 4

    lines = ["📎 出典:"]
    for s in sources[:5]:
        text    = s if isinstance(s, str) else str(s)
        wrapped = textwrap.fill(text, width=45)
        lines.extend(wrapped.split("\n"))

    dummy = Image.new("RGBA", (1, 1))
    draw  = ImageDraw.Draw(dummy)
    max_w = max((int(draw.textlength(l, font=font)) for l in lines), default=200)
    bg_w  = min(max_w + padding * 2, tw - 40)
    bg_h  = line_h * len(lines) + padding * 2

    img  = Image.new("RGBA", (bg_w, bg_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([0, 0, bg_w, bg_h], radius=6, fill=(0, 0, 0, 160))

    for i, line in enumerate(lines):
        color = "#FFFFFF" if i == 0 else "#AAAAAA"
        draw.text((padding, padding + i * line_h), line, font=font, fill=color)

    y_pos = th - CAPTION_ZONE_H - bg_h - 20

    try:
        return (ImageClip(np.array(img))
                .set_duration(SHOW_DURATION)
                .set_start(start)
                .set_position(("center", y_pos))
                .crossfadein(0.3))
    except Exception:
        return None


_DEFAULT_NARRATION = {
    "ja": "ご覧ください。", "en": "Take a look.", "es": "Mira esto.",
    "pt": "Olha isso.", "de": "Schau dir das an.", "fr": "Regarde ça.",
    "id": "Lihat ini.", "hi": "इसे देखो।", "ko": "이거 봐봐.",
    "it": "Guarda questo.", "tr": "Şuna bak.", "nl": "Kijk hier eens naar.",
}


# ════════════════════════════════════════════════════════
#  メイン編集関数
# ════════════════════════════════════════════════════════
def run_edit(video_path: str, analysis: dict,
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
             watermark: bool = False):

    from moviepy.editor import (
        VideoFileClip, ColorClip, CompositeVideoClip, CompositeAudioClip,
        AudioFileClip, ImageClip, concatenate_videoclips
    )
    from moviepy.audio.AudioClip import AudioArrayClip
    from voicevox import synthesize as vv_synthesize, try_launch as vv_launch

    tw, th = (720, 1280) if output_resolution == "720p" else (1080, 1920)
    _scale = tw / 1080
    fs_title    = max(20, int(font_size_title    * _scale))
    fs_subtitle = max(16, int(font_size_subtitle * _scale))
    fs_caption  = max(14, int(font_size_caption  * _scale))

    log("[1/7] 動画読み込み...")
    raw = VideoFileClip(video_path)

    # 出力fpsは素材に合わせる（従来は30固定で60fps素材の滑らかさが半減していた）。
    # 可変fps等で異常値が来ても壊れないよう 24〜60 に収める。
    try:
        out_fps = int(round(float(raw.fps or 30)))
    except Exception:
        out_fps = 30
    out_fps = max(24, min(60, out_fps))
    if out_fps != 30:
        log(f"  🎞 出力fps: {out_fps}（素材に追従）")

    # analysis の秒数はすべて「元動画」基準。各変換で尺が変わるので、
    # 使う直前に tmap.map() で現在のクリップ上の秒数へ直す。
    tmap = TimeMap()

    code_mid = analysis.get("code_intermediate")
    code_used = bool(code_mid and Path(code_mid).exists())
    if code_used:
        # ── Python編集モード：AIが書いたコードの実行結果（中間動画）を採用。
        #    尺を変えた操作はオペログに記録済み → TimeMap を再構築して
        #    以降の字幕・タイトル配置が自動追従する（固定エフェクトは適用しない）。
        log("[2/7] Python編集の結果を使用...")
        raw.close()
        cut = VideoFileClip(code_mid)
        from code_edit import rebuild_timemap
        tmap = rebuild_timemap(analysis.get("code_oplog"))
        if extend_target > 0:
            cut = apply_duration_extend(cut, extend_target, extend_method, log=log)
    else:
        # カット
        log("[2/7] 自動カット...")
        cuts = analysis.get("cut_sections", [])
        cut = apply_cuts(raw, cuts, log)
        tmap.add_cuts(cuts)

        # 巻き戻し・フリーズエフェクト
        rewind_at = analysis.get("rewind_at")
        freeze_at = analysis.get("freeze_at")
        freeze_dur = float(analysis.get("freeze_duration", 1.5))
        ff_at  = analysis.get("fastforward_at")
        ff_end = analysis.get("fastforward_end")
        if fastforward_enabled and ff_at is not None and ff_end is not None:
            s, e = tmap.map(ff_at), tmap.map(ff_end)
            cut = apply_fastforward(cut, s, e, fastforward_speed, log=log)
            tmap.add_speed(s, e, fastforward_speed)
        if rewind_enabled and rewind_at is not None:
            t = tmap.map(rewind_at)
            cut = apply_rewind(cut, t, log=log)
            tmap.add_insert(t - 1.5, 1.5)      # apply_rewind の既定 rewind_dur
        if freeze_enabled and freeze_at is not None:
            t = tmap.map(freeze_at)
            cut = apply_freeze(cut, t, freeze_dur, log=log)
            tmap.add_insert(t, freeze_dur)

        # 以下は尺を変えないので、写像に足す必要はない（時刻の変換だけ）
        zoom_at    = analysis.get("zoom_at")
        zoom_end   = analysis.get("zoom_end")
        zoom_scale = float(analysis.get("zoom_scale", 1.5))
        if zoom_enabled and zoom_at is not None and zoom_end is not None:
            cut = apply_zoom(cut, tmap.map(zoom_at), tmap.map(zoom_end), zoom_scale, log=log)

        mono_at  = analysis.get("monochrome_at")
        mono_end = analysis.get("monochrome_end")
        if monochrome_enabled and mono_at is not None and mono_end is not None:
            cut = apply_monochrome(cut, tmap.map(mono_at), tmap.map(mono_end), log=log)

        flip_at  = analysis.get("flip_at")
        flip_end = analysis.get("flip_end")
        if flip_enabled and flip_at is not None and flip_end is not None:
            cut = apply_flip(cut, tmap.map(flip_at), tmap.map(flip_end), log=log)

        mosaic_at  = analysis.get("mosaic_at")
        mosaic_end = analysis.get("mosaic_end")
        if mosaic_enabled and mosaic_at is not None and mosaic_end is not None:
            cut = apply_mosaic(cut, tmap.map(mosaic_at), tmap.map(mosaic_end), log=log)

        if extend_target > 0:
            cut = apply_duration_extend(cut, extend_target, extend_method, log=log)

    # 縦型レイアウト生成
    log("[3/7] 縦型レイアウト生成...")

    # ── ゾーン定義（上:タイトル / 中:動画 / 下:字幕）
    TITLE_ZONE_H   = 320   # 上部タイトルエリア高さ
    VIDEO_ZONE_H   = th - TITLE_ZONE_H - CAPTION_ZONE_H   # 1280px

    # 動画を VIDEO_ZONE_H に収まるようリサイズ（偶数寸法に丸める）
    vw, vh = cut.size
    scale  = min(tw / vw, VIDEO_ZONE_H / vh)
    rw     = max(2, int(vw * scale) // 2 * 2)
    rh     = max(2, int(vh * scale) // 2 * 2)
    vx     = (tw - rw) // 2
    vy     = TITLE_ZONE_H + (VIDEO_ZONE_H - rh) // 2   # タイトルゾーンの下から中央
    dur    = cut.duration

    # ── オーバーレイ画像を準備 [(PIL画像, x, y, start, end)]  x は "center" か整数
    log("[4/7] タイトル・字幕生成...")
    overlays = []

    # Geminiが選んだフォントスタイル
    font_style = analysis.get("font_style")
    if font_style not in FONT_CATALOG:
        font_style = None
    if font_style and font_style != "standard":
        log(f"  🔤 フォント: {font_style}（{FONT_CATALOG[font_style]['desc'][:22]}...）")

    title    = analysis.get("title",    "海外バズり")
    subtitle = analysis.get("subtitle", "今週の注目")
    # タイトルは冒頭のフック。全編出しっぱなしだと映像に被り続けるので
    # 最初の数秒だけ表示する（短い動画は尺の半分まで）。
    title_end = min(dur, max(TITLE_SHOW_SEC, 0.5) if dur > TITLE_SHOW_SEC * 2 else dur / 2)
    for text, color, fsize, y in [
        (title,    TITLE_COLOR,    fs_title,    100),
        (subtitle, SUBTITLE_COLOR, fs_subtitle, 200),
    ]:
        text  = text.replace("\n", " ").strip()
        font  = _font(fsize, font_style)
        dummy = Image.new("RGBA", (1, 1))
        draw  = ImageDraw.Draw(dummy)
        w     = int(draw.textlength(text, font=font))
        img   = Image.new("RGBA", (min(w + 20, tw - 40), fsize + 20), (0, 0, 0, 0))
        draw  = ImageDraw.Draw(img)
        draw.text((12, 6), text, font=font, fill="#000000AA")
        draw.text((10, 4), text, font=font, fill=color)
        overlays.append((img, "center", y, 0.0, title_end))

    # 字幕（Python編集コードが tc.take_captions() で自作した場合は置かない）
    caption_times = []
    caps = [] if analysis.get("code_handled_captions") else analysis.get("captions", [])
    if analysis.get("code_handled_captions"):
        log("  💬 字幕はPython編集コードが描画済み → 既定字幕はスキップ")
    for cap in caps:
        t = cap.get("text", "")
        fny = cap.get("funny", False)
        if not t or float(cap.get("end", 0)) <= float(cap.get("start", 0)):
            continue
        # 字幕の秒数も元動画基準。カット・早送り等でズレた分をここで吸収する
        # （以前は生の値をそのまま置いていたので、カットした分だけ字幕がズレていた）
        s = tmap.map(cap.get("start", 0))
        e = tmap.map(cap.get("end", 0))
        if e <= s:
            continue
        s = min(s, max(0.0, dur - 0.1))
        e = min(e, dur)
        img = _caption_image(t, fny, fs_caption, style=font_style)
        # 位置：AIが x/y（0〜1の比率）を指定したら尊重、無指定は従来の下部ゾーン中央
        x = "center"
        try:
            if cap.get("y") is not None:
                y = int(min(max(float(cap["y"]), 0.0), 1.0) * (th - img.height))
            else:
                y = th - CAPTION_ZONE_H + (CAPTION_ZONE_H - img.height) // 2
            if cap.get("x") is not None:
                x = int(min(max(float(cap["x"]), 0.0), 1.0) * (tw - img.width))
        except (TypeError, ValueError):
            y = th - CAPTION_ZONE_H + (CAPTION_ZONE_H - img.height) // 2
            x = "center"
        overlays.append((img, x, y, s, e))
        caption_times.append((s, e))

    # 引用元（最後3秒に表示）
    sources = analysis.get("sources", [])
    if sources:
        log(f"  📎 引用元 {len(sources)}件 表示...")
        img = _source_image(sources, tw)
        if img is not None:
            y = th - CAPTION_ZONE_H - img.height - 20
            overlays.append((img, "center", y, max(0.0, dur - 3.0), dur))

    # デモ用ウォーターマーク
    if watermark:
        try:
            wm_text = "Tomato Clip Demo"
            wm_font = _font(max(20, int(32 * _scale)))
            dummy   = Image.new("RGBA", (1, 1))
            d       = ImageDraw.Draw(dummy)
            wm_w    = int(d.textlength(wm_text, font=wm_font))
            pad     = 12
            wm_img  = Image.new("RGBA", (wm_w + pad * 2, wm_font.size + pad * 2), (0, 0, 0, 0))
            d       = ImageDraw.Draw(wm_img)
            d.rounded_rectangle([0, 0, wm_img.width, wm_img.height],
                                radius=8, fill=(0, 0, 0, 64))
            d.text((pad + 2, pad + 2), wm_text, font=wm_font, fill=(0, 0, 0, 150))
            d.text((pad, pad),         wm_text, font=wm_font, fill=(255, 255, 255, 140))
            overlays.append((wm_img, "center", th - wm_img.height - 60, 0.0, dur))
        except Exception as e:
            log(f"  ⚠️ ウォーターマーク失敗（続行）: {e}")

    # ── ナレーション（日本語はVOICEVOX、それ以外はgTTS）
    log("[5/7] ナレーション生成...")
    narr_path = None
    try:
        narr_lang  = analysis.get("output_language", "ja")
        tmpl_cfg   = analysis.get("tmpl_config", {})
        speaker_id = tmpl_cfg.get("voicevox_speaker",
                     analysis.get("voicevox_speaker", 3))
        speed      = tmpl_cfg.get("voicevox_speed",
                     analysis.get("voicevox_speed", 1.1))
        pitch      = tmpl_cfg.get("voicevox_pitch",
                     analysis.get("voicevox_pitch", 0.0))
        vv_path    = tmpl_cfg.get("voicevox_path",
                     analysis.get("voicevox_path", ""))
        if narr_lang == "ja":
            vv_launch(vv_path, log)
        default_narration = _DEFAULT_NARRATION.get(narr_lang, _DEFAULT_NARRATION["en"])
        narr_path = vv_synthesize(
            text       = analysis.get("narration", default_narration),
            speaker_id = speaker_id,
            speed      = speed,
            pitch      = pitch,
            log        = log,
            lang       = narr_lang
        )
        if narr_path:
            log(f"🎙️ ナレーション完了（言語: {narr_lang}）")
    except Exception as e:
        log(f"⚠️ ナレーション失敗: {e}")
        narr_path = None

    # ── 書き出し: 高速(ffmpeg合成) → 失敗時は従来(moviepy合成)にフォールバック
    tmpl_cfg     = analysis.get("tmpl_config", {})
    use_template = bool(tmpl_cfg.get("ranking_overlay") or analysis.get("footage_path"))

    done = False
    if not use_template:
        try:
            _export_fast(
                # Python編集時は中間動画が既にエフェクト適用済み＝直接合成に使える
                cut=cut,
                src_path=(code_mid if code_used else video_path),
                unmodified=(cut is raw) or (code_used and extend_target <= 0),
                overlays=overlays, caption_times=caption_times,
                narr_path=narr_path,
                bgm_path=simple_bgm_path, bgm_volume=simple_bgm_volume,
                tw=tw, th=th, rw=rw, rh=rh, vx=vx, vy=vy, dur=dur,
                out_path=out_path, preset=encode_preset, log=log,
                out_fps=out_fps,
            )
            done = True
        except Exception as e:
            log(f"⚠️ 高速書き出し失敗 → 従来方式にフォールバック: {e}")

    if not done:
        _export_moviepy(
            cut=cut, overlays=overlays, caption_times=caption_times,
            analysis=analysis, narr_path=narr_path,
            bgm_path=simple_bgm_path, bgm_volume=simple_bgm_volume,
            tw=tw, th=th, scale=scale, vx=vx, vy=vy, dur=dur,
            out_path=out_path, preset=encode_preset, log=log,
            out_fps=out_fps,
        )

    log(f"✅ 編集完了: {Path(out_path).name}")

    if narr_path:
        try:
            os.remove(narr_path)
        except Exception:
            pass


# ════════════════════════════════════════════════════════
#  オーバーレイ画像ヘルパー
# ════════════════════════════════════════════════════════
def _caption_image(text: str, is_funny: bool, font_size: int = 58,
                   style: str = None) -> Image.Image:
    """字幕のRGBA画像を返す（_caption_clip と同じ描画）"""
    padding = 20
    font    = _font(font_size, style)
    wrap_w  = max(6, int(14 * 58 / font_size))
    wrapped = textwrap.fill(text, width=wrap_w)
    lines   = wrapped.split("\n")
    dummy   = Image.new("RGBA", (1, 1))
    draw    = ImageDraw.Draw(dummy)
    line_h  = font_size + 8
    text_w  = max((draw.textlength(l, font=font) for l in lines), default=200)
    bg_w    = int(text_w) + padding * 2
    bg_h    = int(line_h * len(lines)) + padding * 2

    img  = Image.new("RGBA", (bg_w, bg_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    if is_funny:
        draw.rounded_rectangle([0, 0, bg_w, bg_h], radius=12, fill=(255, 220, 0, 210))
        tc = "#111111"
    else:
        draw.rounded_rectangle([0, 0, bg_w, bg_h], radius=12, fill=(0, 0, 0, 170))
        tc = CAPTION_COLOR
    for i, line in enumerate(lines):
        lw = draw.textlength(line, font=font)
        x  = (bg_w - lw) / 2
        y  = padding + i * line_h
        draw.text((x + 2, y + 2), line, font=font, fill="#000000")
        draw.text((x, y),         line, font=font, fill=tc)
    return img


def _source_image(sources: list, tw: int) -> Image.Image | None:
    """引用元表示のRGBA画像を返す（_make_source_clip と同じ描画）"""
    if not sources:
        return None
    font_size = 22
    padding   = 10
    font      = _font(font_size)
    line_h    = font_size + 4
    lines = ["📎 出典:"]
    for s in sources[:5]:
        if isinstance(s, dict):
            text = f"{s.get('account', '')}  {s.get('url', '')}".strip()
        else:
            text = str(s)
        if not text:
            continue
        wrapped = textwrap.fill(text, width=45)
        lines.extend(wrapped.split("\n"))
    dummy = Image.new("RGBA", (1, 1))
    draw  = ImageDraw.Draw(dummy)
    max_w = max((int(draw.textlength(l, font=font)) for l in lines), default=200)
    bg_w  = min(max_w + padding * 2, tw - 40)
    bg_h  = line_h * len(lines) + padding * 2
    img  = Image.new("RGBA", (bg_w, bg_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([0, 0, bg_w, bg_h], radius=6, fill=(0, 0, 0, 160))
    for i, line in enumerate(lines):
        color = "#FFFFFF" if i == 0 else "#AAAAAA"
        draw.text((padding, padding + i * line_h), line, font=font, fill=color)
    return img


# ════════════════════════════════════════════════════════
#  高速書き出し（映像: moviepy 前処理 → 合成/エンコード: ffmpeg）
# ════════════════════════════════════════════════════════
def _read_audio_stereo(path, sr=44100) -> np.ndarray:
    """音声ファイルを (N, 2) float32 で読む"""
    import librosa
    y, _ = librosa.load(str(path), sr=sr, mono=False)
    if y.ndim == 1:
        y = np.vstack([y, y])
    return y.T.astype(np.float32)


def _bgm_array(bgm_path: str, video_dur: float, volume: float, log) -> np.ndarray | None:
    """BGMをループ+フェードした (N, 2) float32 配列を返す"""
    if not bgm_path or not Path(bgm_path).exists():
        return None
    import librosa
    log(f"🎵 シンプルBGM: {Path(bgm_path).name} (音量:{volume:.2f})")
    y, _ = librosa.load(bgm_path, sr=44100, mono=False)
    if y.ndim == 1:
        y = np.vstack([y, y])
    total   = int(video_dur * 44100)
    src_len = y.shape[1]
    if src_len == 0 or total == 0:
        return None
    reps   = total // src_len + 1
    looped = np.tile(y, reps)[:, :total].copy()
    fi = min(int(2.0 * 44100), total)
    looped[:, :fi]        *= np.linspace(0, 1, fi)
    looped[:, total - fi:] *= np.linspace(1, 0, fi)
    return (looped * volume).T.astype(np.float32)


def _export_fast(cut, src_path, unmodified, overlays, caption_times,
                 narr_path, bgm_path, bgm_volume,
                 tw, th, rw, rh, vx, vy, dur,
                 out_path, preset, log, out_fps=30):
    """
    合成とエンコードを ffmpeg のフィルターグラフで一括実行する高速パス。
    映像エフェクト適用済みの cut を低解像度のまま中間ファイルへ書き、
    スケール・黒背景配置・全オーバーレイ・音声ミックスを ffmpeg 1回で行う。
    """
    import tempfile, subprocess, wave, shutil
    import imageio_ffmpeg

    t0     = time.time()
    tmpdir = Path(tempfile.mkdtemp(prefix="ts_edit_"))
    try:
        # ── 映像パス（エフェクトなしなら元ファイルを直接使う）
        if unmodified:
            stage1 = str(src_path)
            log("[6/7] 前処理不要 → 元動画を直接合成します")
        else:
            log("[6/7] 映像前処理（エフェクト適用）...")
            stage1 = str(tmpdir / "stage1.mp4")
            # 中間ファイルは後段で必ず再エンコードされる。既定crf(23)のままだと
            # 「劣化した素材の再圧縮」になるので、crf12=ほぼ無劣化で書く
            # （ultrafast維持＝速度はそのまま、一時ファイルが太るだけ）。
            cut.write_videofile(
                stage1, fps=out_fps, codec="libx264", preset="ultrafast",
                audio=False, threads=os.cpu_count() or 4, logger=None,
                ffmpeg_params=["-crf", "12"],
            )

        # ── 音声ミックス（numpy）
        sr  = 44100
        n   = int(dur * sr) + 1
        mix = np.zeros((n, 2), dtype=np.float32)

        def _add(arr, start=0.0, vol=1.0):
            i0 = int(start * sr)
            if i0 >= n:
                return
            m = min(len(arr), n - i0)
            if m > 0:
                mix[i0:i0 + m] += arr[:m] * vol

        if cut.audio is not None:
            base_wav = tmpdir / "base.wav"
            cut.audio.write_audiofile(str(base_wav), fps=sr, nbytes=2, logger=None)
            _add(_read_audio_stereo(base_wav))
        for s, e in caption_times:
            _add(_typewriter_sound(e - s), s, 0.4)
        if narr_path:
            _add(_read_audio_stereo(narr_path))
        bgm = _bgm_array(bgm_path, dur, bgm_volume, log)
        if bgm is not None:
            _add(bgm)
        np.clip(mix, -0.99, 0.99, out=mix)

        wav_path = tmpdir / "mix.wav"
        with wave.open(str(wav_path), "wb") as wf:
            wf.setnchannels(2)
            wf.setsampwidth(2)
            wf.setframerate(sr)
            wf.writeframes((mix * 32767).astype(np.int16).tobytes())

        # ── オーバーレイPNG
        png_paths = []
        for i, (img, x, y, s, e) in enumerate(overlays):
            p = tmpdir / f"ov{i}.png"
            img.save(p)
            png_paths.append(str(p))

        # ── ffmpeg 一括合成
        log("[7/7] 書き出し中（ffmpeg高速合成）...")
        ff  = imageio_ffmpeg.get_ffmpeg_exe()
        cmd = [ff, "-y", "-i", stage1, "-i", str(wav_path)]
        for p in png_paths:
            cmd += ["-i", p]

        parts = [
            f"color=black:size={tw}x{th}:duration={dur:.3f}:rate={out_fps}[bg]",
            f"[0:v]scale={rw}:{rh}[v0]",
            f"[bg][v0]overlay={vx}:{vy}:eof_action=repeat[m0]",
        ]
        cur = "m0"
        for i, (img, x, y, s, e) in enumerate(overlays):
            xo = "(W-w)/2" if x == "center" else str(int(x))
            en = "" if (s <= 0.01 and e >= dur - 0.01) \
                 else f":enable='between(t,{s:.3f},{e:.3f})'"
            parts.append(
                f"[{cur}][{i + 2}:v]overlay={xo}:{int(y)}:eof_action=repeat{en}[m{i + 1}]")
            cur = f"m{i + 1}"

        cmd += [
            "-filter_complex", ";".join(parts),
            "-map", f"[{cur}]", "-map", "1:a",
            "-c:v", "libx264", "-preset", preset, "-crf", "20",
            "-pix_fmt", "yuv420p", "-r", str(out_fps),
            "-c:a", "aac", "-b:a", "192k",
            "-t", f"{dur:.3f}", str(out_path),
        ]
        r = subprocess.run(cmd, capture_output=True)
        if r.returncode != 0:
            raise RuntimeError("ffmpeg失敗: " + r.stderr.decode(errors="ignore")[-300:])
        log(f"  ⚡ 高速書き出し完了 ({time.time() - t0:.0f}秒)")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _export_moviepy(cut, overlays, caption_times, analysis, narr_path,
                    bgm_path, bgm_volume,
                    tw, th, scale, vx, vy, dur,
                    out_path, preset, log, out_fps=30):
    """従来方式（moviepy全合成）。テンプレート演出や高速パス失敗時に使用"""
    from moviepy.editor import (
        ColorClip, CompositeVideoClip, CompositeAudioClip,
        AudioFileClip, ImageClip
    )
    from moviepy.audio.AudioClip import AudioArrayClip

    log("[6/7] 従来方式で合成中...")
    resized = cut.resize(scale)
    bg   = ColorClip(size=(tw, th), color=[0, 0, 0]).set_duration(dur)
    base = CompositeVideoClip([bg, resized.set_position((vx, vy))], size=(tw, th))
    all_clips = [base]

    tmpl_cfg = analysis.get("tmpl_config", {})
    if tmpl_cfg.get("ranking_overlay"):
        log("  🏆 ランキング演出...")
        try:
            from template_engine import build_ranking_overlays
            all_clips.extend(build_ranking_overlays(
                analysis.get("captions", []), tw, th,
                style=tmpl_cfg.get("ranking_style", "countdown")))
        except Exception as e:
            log(f"  ⚠️ ランキング演出失敗: {e}")

    footage_path = analysis.get("footage_path")
    if footage_path:
        log("  🎥 フリー素材合成...")
        try:
            from template_engine import apply_free_footage
            all_clips[0] = apply_free_footage(
                base, footage_path, analysis.get("footage_mode", "ai_decide"),
                tw, th, log)
        except Exception as e:
            log(f"  ⚠️ フリー素材合成失敗: {e}")

    for img, x, y, s, e in overlays:
        all_clips.append(
            ImageClip(np.array(img))
            .set_start(s).set_duration(e - s)
            .set_position(("center" if x == "center" else int(x), int(y)))
        )

    type_sounds = [
        AudioArrayClip(_typewriter_sound(e - s), fps=44100).set_start(s).volumex(0.4)
        for s, e in caption_times
    ]
    narr_audio       = AudioFileClip(narr_path).set_start(0) if narr_path else None
    simple_bgm_audio = _build_simple_bgm(bgm_path, dur, bgm_volume, log)

    audio_tracks = []
    if simple_bgm_audio:
        audio_tracks.append(simple_bgm_audio)
    if base.audio:
        audio_tracks.append(base.audio)
    if narr_audio:
        audio_tracks.append(narr_audio)
    audio_tracks.extend(type_sounds)

    log("[7/7] 書き出し中（少しかかります）...")
    final = CompositeVideoClip(all_clips, size=(tw, th))
    if audio_tracks:
        final = final.set_audio(CompositeAudioClip(audio_tracks))
    final.write_videofile(
        out_path, fps=out_fps, codec="libx264",
        audio_codec="aac", preset=preset, threads=4, logger=None
    )


