"""
templates.py
字幕スタイル・演出テンプレートの管理
・作成・編集・プレビュー生成・保存
"""
import uuid, base64, json
from io import BytesIO
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import db

PREVIEW_SIZE = (270, 480)   # 9:16 縮小プレビュー
FONT_PATH    = "NotoSansJP-Bold.ttf"

# ── デフォルトテンプレート定義
DEFAULT_TEMPLATES = [
    {
        "id":   "default",
        "name": "🟢 スタンダード（緑字幕）",
        "config": {
            "title_color":      "#FFE000",
            "subtitle_color":   "#FF3B30",
            "caption_color":    "#00FF5A",
            "caption_bg":       "#000000",
            "caption_bg_alpha": 170,
            "font_size":        58,
            "title_font_size":  72,
            "funny_bg":         "#FFE000",
            "skull_enabled":    True,
            "skull_size_ratio": 0.55,
            "skull_duration":   2.5,
            "phonk_enabled":    True,
            "phonk_volume":     0.20,
            "phonk_chorus_vol": 0.55,
            "narration_enabled":True,
            "mono_on_skull":    True,
        }
    },
    {
        "id":   "fire",
        "name": "🔥 ファイア（赤×オレンジ）",
        "config": {
            "title_color":      "#FF4400",
            "subtitle_color":   "#FF8800",
            "caption_color":    "#FFDD00",
            "caption_bg":       "#1a0000",
            "caption_bg_alpha": 200,
            "font_size":        60,
            "title_font_size":  76,
            "funny_bg":         "#FF4400",
            "skull_enabled":    True,
            "skull_size_ratio": 0.60,
            "skull_duration":   3.0,
            "phonk_enabled":    True,
            "phonk_volume":     0.25,
            "phonk_chorus_vol": 0.65,
            "narration_enabled":True,
            "mono_on_skull":    True,
        }
    },
    {
        "id":   "neon",
        "name": "💜 ネオン（紫×シアン）",
        "config": {
            "title_color":      "#CC44FF",
            "subtitle_color":   "#00FFEE",
            "caption_color":    "#CC44FF",
            "caption_bg":       "#0a0014",
            "caption_bg_alpha": 190,
            "font_size":        56,
            "title_font_size":  70,
            "funny_bg":         "#CC44FF",
            "skull_enabled":    True,
            "skull_size_ratio": 0.50,
            "skull_duration":   2.0,
            "phonk_enabled":    True,
            "phonk_volume":     0.18,
            "phonk_chorus_vol": 0.50,
            "narration_enabled":True,
            "mono_on_skull":    False,
        }
    },
    {
        "id":   "minimal",
        "name": "⚪ ミニマル（白・演出なし）",
        "config": {
            "title_color":      "#FFFFFF",
            "subtitle_color":   "#AAAAAA",
            "caption_color":    "#FFFFFF",
            "caption_bg":       "#000000",
            "caption_bg_alpha": 140,
            "font_size":        54,
            "title_font_size":  68,
            "funny_bg":         "#FFFFFF",
            "skull_enabled":    False,
            "skull_size_ratio": 0.50,
            "skull_duration":   2.0,
            "phonk_enabled":    False,
            "phonk_volume":     0.10,
            "phonk_chorus_vol": 0.30,
            "narration_enabled":False,
            "mono_on_skull":    False,
        }
    },
]


def ensure_defaults():
    """デフォルトテンプレートをDBに登録（未登録のみ）"""
    existing = {t["id"] for t in db.get_templates()}
    for t in DEFAULT_TEMPLATES:
        if t["id"] not in existing:
            preview = generate_preview(t["config"], t["name"])
            db.save_template(t["id"], t["name"], t["config"], preview)


def generate_preview(config: dict, title: str = "サンプル動画") -> str:
    """
    テンプレートのプレビュー画像を生成してbase64で返す
    """
    W, H = PREVIEW_SIZE
    img  = Image.new("RGB", (W, H), "#0a0a12")
    draw = ImageDraw.Draw(img)

    def _font(size):
        try:
            return ImageFont.truetype(FONT_PATH, size)
        except Exception:
            return ImageFont.load_default()

    # 背景グラデーション風
    for y in range(H):
        alpha = int(40 * (1 - y / H))
        draw.line([(0, y), (W, y)], fill=(alpha, alpha, alpha + 20))

    # タイトル
    tf   = _font(int(config.get("title_font_size", 72) * W / 1080))
    tc   = config.get("title_color", "#FFE000")
    draw.text((W//2, 18), title[:8], font=tf, fill=tc, anchor="mt")

    # サブタイトル
    sf   = _font(int(config.get("title_font_size", 72) * 0.65 * W / 1080))
    sc   = config.get("subtitle_color", "#FF3B30")
    draw.text((W//2, 48), "2024年のバズり動画", font=sf, fill=sc, anchor="mt")

    # ダミー字幕ボックス
    cf   = _font(int(config.get("font_size", 58) * W / 1080))
    cc   = config.get("caption_color", "#00FF5A")
    bg_c = config.get("caption_bg", "#000000")
    bg_a = config.get("caption_bg_alpha", 170)
    try:
        r, g, b = int(bg_c[1:3],16), int(bg_c[3:5],16), int(bg_c[5:7],16)
    except Exception:
        r, g, b = 0, 0, 0
    overlay = Image.new("RGBA", (W, H), (0,0,0,0))
    od      = ImageDraw.Draw(overlay)
    od.rounded_rectangle([10, H-80, W-10, H-24], radius=8, fill=(r,g,b,bg_a))
    img     = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
    draw    = ImageDraw.Draw(img)
    draw.text((W//2, H-56), "（実況）やばい！", font=cf, fill=cc, anchor="mm")

    # ドクロ有効表示
    if config.get("skull_enabled"):
        draw.text((W-8, 8), "💀", font=_font(18), fill="#FFE000", anchor="rt")

    # base64 エンコード
    buf = BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def create_template(name: str, config: dict) -> str:
    """新規テンプレート作成・保存"""
    tid     = str(uuid.uuid4())[:8]
    preview = generate_preview(config, name)
    db.save_template(tid, name, config, preview)
    return tid


def get_template_config(tid: str) -> dict:
    """テンプレートのconfig取得"""
    templates = db.get_templates()
    for t in templates:
        if t["id"] == tid:
            cfg = t.get("config_json", "{}")
            if isinstance(cfg, str):
                return json.loads(cfg)
            return cfg
    # フォールバック
    return DEFAULT_TEMPLATES[0]["config"]
