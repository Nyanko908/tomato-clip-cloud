# -*- coding: utf-8 -*-
"""
flag_icons.py - 国旗アイコン（PIL簡易描画）

TkinterはWindows上で国旗絵文字（Regional Indicator Symbolの合字）を正しく描画できず、
"JP" のような2文字コードのまま表示されてしまう（Tkの文字描画がUnicode合字シェーピングに
対応していないため）。そのためPILで簡易的な国旗画像を描画し、ImageTk.PhotoImageとして使う。
"""
from PIL import Image, ImageDraw, ImageTk


def get_flag_image(code: str, size=(56, 38), master=None) -> ImageTk.PhotoImage:
    """言語コードに対応する簡易国旗のImageTk.PhotoImageを返す"""
    img = _draw_flag(code, size)
    return ImageTk.PhotoImage(img, master=master)


def _draw_flag(code: str, size):
    w, h = size
    img = Image.new("RGB", (w, h), "#888888")
    d = ImageDraw.Draw(img)

    if code == "ja":
        d.rectangle([0, 0, w, h], fill="#ffffff")
        r = h * 0.3
        cx, cy = w / 2, h / 2
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill="#bc002d")
    elif code == "en":
        stripe_h = h / 7
        for i in range(7):
            color = "#b22234" if i % 2 == 0 else "#ffffff"
            d.rectangle([0, i * stripe_h, w, (i + 1) * stripe_h], fill=color)
        d.rectangle([0, 0, w * 0.4, h * 0.55], fill="#3c3b6e")
    elif code == "es":
        d.rectangle([0, 0, w, h * 0.25], fill="#aa151b")
        d.rectangle([0, h * 0.25, w, h * 0.75], fill="#f1bf00")
        d.rectangle([0, h * 0.75, w, h], fill="#aa151b")
    elif code == "pt":
        d.rectangle([0, 0, w, h], fill="#009b3a")
        cx, cy, r = w * 0.42, h / 2, h * 0.3
        d.polygon([(cx, cy - r), (cx + r, cy), (cx, cy + r), (cx - r, cy)], fill="#ffcc29")
        d.ellipse([cx - r * 0.45, cy - r * 0.45, cx + r * 0.45, cy + r * 0.45], fill="#002776")
    elif code == "de":
        d.rectangle([0, 0, w, h / 3], fill="#000000")
        d.rectangle([0, h / 3, w, h * 2 / 3], fill="#dd0000")
        d.rectangle([0, h * 2 / 3, w, h], fill="#ffce00")
    elif code == "fr":
        d.rectangle([0, 0, w / 3, h], fill="#0055a4")
        d.rectangle([w / 3, 0, w * 2 / 3, h], fill="#ffffff")
        d.rectangle([w * 2 / 3, 0, w, h], fill="#ef4135")
    elif code == "id":
        d.rectangle([0, 0, w, h / 2], fill="#ce1126")
        d.rectangle([0, h / 2, w, h], fill="#ffffff")
    elif code == "hi":
        d.rectangle([0, 0, w, h / 3], fill="#ff9933")
        d.rectangle([0, h / 3, w, h * 2 / 3], fill="#ffffff")
        d.rectangle([0, h * 2 / 3, w, h], fill="#138808")
        cx, cy, r = w / 2, h / 2, h * 0.09
        d.ellipse([cx - r, cy - r, cx + r, cy + r], outline="#000080", width=1)
    elif code == "ko":
        d.rectangle([0, 0, w, h], fill="#ffffff")
        cx, cy, r = w / 2, h / 2, h * 0.24
        d.pieslice([cx - r, cy - r, cx + r, cy + r], 0, 180, fill="#cd2e3a")
        d.pieslice([cx - r, cy - r, cx + r, cy + r], 180, 360, fill="#0047a0")
    elif code == "it":
        d.rectangle([0, 0, w / 3, h], fill="#008c45")
        d.rectangle([w / 3, 0, w * 2 / 3, h], fill="#ffffff")
        d.rectangle([w * 2 / 3, 0, w, h], fill="#cd212a")
    elif code == "tr":
        d.rectangle([0, 0, w, h], fill="#e30a17")
        cx, cy, r = w * 0.4, h / 2, h * 0.26
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill="#ffffff")
        d.ellipse([cx - r * 0.7 + r * 0.35, cy - r * 0.7, cx + r * 0.7 + r * 0.35, cy + r * 0.7], fill="#e30a17")
    elif code == "nl":
        d.rectangle([0, 0, w, h / 3], fill="#ae1c28")
        d.rectangle([0, h / 3, w, h * 2 / 3], fill="#ffffff")
        d.rectangle([0, h * 2 / 3, w, h], fill="#21468b")

    return img
