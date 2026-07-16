"""
template_engine.py
企画テンプレートエンジン
  - テンプレート = 動画の"企画タイプ"（解説・ランキング・Phonk×ドクロ・ミニマル）
  - Gemini が動画の"温度"を読んで最適テンプレを自動選択
  - Pexels フリー素材を AI が判断して自動挿入
  - 全 API 呼び出しに 20 秒インターバル
"""

import json, time, tempfile, urllib.request, urllib.parse, os
from pathlib import Path
from typing import Callable

LOG_CB = Callable[[str], None]
SLEEP  = 20   # API 呼び出し間隔（秒）

USER_TEMPLATES_PATH = Path.home() / ".tomato_clip_user_templates.json"

# ════════════════════════════════════════════════════════
#  企画テンプレート定義
# ════════════════════════════════════════════════════════
PLAN_TEMPLATES = {

    "calm_explain": {
        "name":        "🎙️ 落ち着き解説",
        "description": "ナレーション中心・静かな BGM・フリー素材を背景に使う",
        "suitable_for": "教育・料理・科学・ドキュメント・静かな内容",
        "temperature": "low",   # low / medium / high
        "config": {
            "title_color":       "#FFFFFF",
            "subtitle_color":    "#AAAAAA",
            "caption_color":     "#FFFFFF",
            "caption_bg":        "#000000",
            "caption_bg_alpha":  150,
            "font_size":         52,
            "title_font_size":   66,
            "skull_enabled":     False,
            "phonk_enabled":     False,
            "narration_enabled": True,
            "mono_on_skull":     False,
            "free_footage":      True,
            "free_footage_mode": "background",  # background / transition / ai_decide
            "ranking_overlay":   False,
        }
    },

    "ranking_hype": {
        "name":        "🏆 ランキング演出",
        "description": "1動画内でランキング形式の字幕演出・カウントダウン・Phonk",
        "suitable_for": "TOP系・比較・驚き・バズり動画",
        "temperature": "medium",
        "config": {
            "title_color":       "#FFE000",
            "subtitle_color":    "#FF6600",
            "caption_color":     "#FFFFFF",
            "caption_bg":        "#111111",
            "caption_bg_alpha":  200,
            "font_size":         60,
            "title_font_size":   74,
            "skull_enabled":     False,
            "phonk_enabled":     True,
            "phonk_volume":      0.18,
            "phonk_chorus_vol":  0.40,
            "narration_enabled": True,
            "mono_on_skull":     False,
            "free_footage":      True,
            "free_footage_mode": "transition",
            "ranking_overlay":   True,   # ランキング演出フラグ
            "ranking_style":     "countdown",  # countdown / reveal
        }
    },

    "phonk_skull": {
        "name":        "💀 Phonk × ドクロ",
        "description": "テンション高め・Phonk爆音・ドクロ演出・モノクロ",
        "suitable_for": "衝撃・ドッキリ・爆笑・やばい系・スポーツ神プレー",
        "temperature": "high",
        "config": {
            "title_color":       "#FFE000",
            "subtitle_color":    "#FF3B30",
            "caption_color":     "#00FF5A",
            "caption_bg":        "#000000",
            "caption_bg_alpha":  170,
            "font_size":         58,
            "title_font_size":   72,
            "skull_enabled":     True,
            "skull_size_ratio":  0.55,
            "skull_duration":    2.5,
            "phonk_enabled":     True,
            "phonk_volume":      0.22,
            "phonk_chorus_vol":  0.60,
            "narration_enabled": True,
            "mono_on_skull":     True,
            "free_footage":      False,
            "free_footage_mode": "ai_decide",
            "ranking_overlay":   False,
        }
    },

    "neon_vibe": {
        "name":        "💜 ネオン Vibe",
        "description": "おしゃれ・ネオン字幕・Lo-fi系BGM・都会的",
        "suitable_for": "ファッション・音楽・アート・ライフスタイル",
        "temperature": "medium",
        "config": {
            "title_color":       "#CC44FF",
            "subtitle_color":    "#00FFEE",
            "caption_color":     "#CC44FF",
            "caption_bg":        "#0a0014",
            "caption_bg_alpha":  190,
            "font_size":         56,
            "title_font_size":   70,
            "skull_enabled":     False,
            "phonk_enabled":     True,
            "phonk_volume":      0.15,
            "phonk_chorus_vol":  0.35,
            "narration_enabled": True,
            "mono_on_skull":     False,
            "free_footage":      True,
            "free_footage_mode": "background",
            "ranking_overlay":   False,
        }
    },
}


# ════════════════════════════════════════════════════════
#  ユーザー定義テンプレート（永続化）
# ════════════════════════════════════════════════════════
def load_user_templates() -> dict:
    if USER_TEMPLATES_PATH.exists():
        try:
            return json.loads(USER_TEMPLATES_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_user_template(tid: str, template: dict):
    templates = load_user_templates()
    templates[tid] = template
    USER_TEMPLATES_PATH.write_text(
        json.dumps(templates, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    PLAN_TEMPLATES[tid] = template


def delete_user_template(tid: str):
    templates = load_user_templates()
    templates.pop(tid, None)
    USER_TEMPLATES_PATH.write_text(
        json.dumps(templates, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    PLAN_TEMPLATES.pop(tid, None)


def _merge_user_templates():
    """起動時にユーザーテンプレートをPLAN_TEMPLATESに統合"""
    PLAN_TEMPLATES.update(load_user_templates())


_merge_user_templates()


def ai_generate_template(prompt_text: str, model) -> dict:
    """
    ユーザーの説明文からGeminiがテンプレートconfigを生成。
    戻り値: テンプレートdict or None
    """
    from channel_learner import build_learning_prompt_context
    learning_ctx = build_learning_prompt_context()

    schema_example = json.dumps(list(PLAN_TEMPLATES.values())[0], ensure_ascii=False, indent=2)
    prompt = f"""
あなたは動画編集テンプレートを設計するAIです。
以下のユーザーの説明に合ったテンプレートをJSON形式で1つ生成してください。
{learning_ctx}

【ユーザーの説明】
{prompt_text}

【出力フォーマット】（以下のJSONのみ返答、コードブロック不要）
{{
  "name": "テンプレート名（絵文字あり）",
  "description": "説明文",
  "suitable_for": "向いているコンテンツの種類",
  "temperature": "low / medium / high のいずれか",
  "config": {{
    "title_color": "#HEX色",
    "subtitle_color": "#HEX色",
    "caption_color": "#HEX色",
    "caption_bg": "#HEX色",
    "caption_bg_alpha": 0-255の整数,
    "font_size": 整数,
    "title_font_size": 整数,
    "skull_enabled": true/false,
    "phonk_enabled": true/false,
    "phonk_volume": 0.0-1.0,
    "phonk_chorus_vol": 0.0-1.0,
    "narration_enabled": true/false,
    "mono_on_skull": true/false,
    "free_footage": true/false,
    "free_footage_mode": "background / transition / ai_decide",
    "ranking_overlay": true/false
  }}
}}

参考にする既存テンプレートの形式:
{schema_example}
"""
    try:
        resp = model.models.generate_content(model=model._model_name, contents=prompt)
        raw  = resp.text.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        return json.loads(raw)
    except Exception as e:
        raise RuntimeError(f"テンプレート生成失敗: {e}")


# ════════════════════════════════════════════════════════
#  AI テンプレート自動選択
# ════════════════════════════════════════════════════════
def ai_select_template(model, video_title: str, video_description: str,
                        analysis: dict, log: LOG_CB, gemini_rot=None) -> str:
    """
    Gemini が動画の"温度"を読んで最適テンプレIDを返す
    戻り値: テンプレートID ("calm_explain" / "ranking_hype" / "phonk_skull" / "neon_vibe")
    """
    log("🤖 [AI] テンプレート自動選択中...")

    templates_desc = "\n".join(
        f'- "{tid}": {t["name"]} / 向いてる内容: {t["suitable_for"]}'
        for tid, t in PLAN_TEMPLATES.items()
    )

    captions_sample = " ".join(
        c.get("text", "") for c in (analysis.get("captions") or [])[:5]
    )

    prompt = f"""
以下の YouTube Shorts 動画に最も適したテンプレートIDを1つだけ返してください。
JSONも説明も不要。テンプレートIDの文字列のみ返答。

【選択肢】
{templates_desc}

【動画情報】
タイトル: {video_title}
説明: {video_description[:200]}
字幕サンプル: {captions_sample[:300]}
Gemini分析タイトル: {analysis.get('title', '')}

判断基準:
- 衝撃・やばい・爆笑・スポーツ神プレー → phonk_skull
- TOP・ランキング・比較・驚き系 → ranking_hype
- 教育・料理・科学・静かな内容 → calm_explain
- ファッション・音楽・アート → neon_vibe
"""

    time.sleep(SLEEP)
    current_model = model
    for attempt in range(1, 5):
        try:
            resp = current_model.models.generate_content(
                model=current_model._model_name, contents=prompt
            )
            tid = resp.text.strip().strip('"').strip("'")
            if tid in PLAN_TEMPLATES:
                log(f"✅ [AI] テンプレート選択: {PLAN_TEMPLATES[tid]['name']}")
                return tid
            break
        except Exception as e:
            err = str(e)
            if ("429" in err or "quota" in err.lower()) and gemini_rot and gemini_rot.count() > 1:
                try:
                    from pipeline import init_gemini
                    new_key = gemini_rot.next()
                    if new_key:
                        current_model = init_gemini(new_key, current_model._model_name)
                        log(f"🔄 テンプレ選択 429 → キーローリング ({attempt}/4)")
                        continue
                except Exception:
                    pass
            log(f"⚠️ テンプレ選択失敗: {e}")
            break

    # フォールバック: タイトルキーワードで判定
    title_lower = (video_title + analysis.get("title","")).lower()
    if any(w in title_lower for w in ["やばい","衝撃","爆笑","神","すごい","草"]):
        return "phonk_skull"
    if any(w in title_lower for w in ["top","ランキング","1位","best","worst"]):
        return "ranking_hype"
    if any(w in title_lower for w in ["解説","説明","学","科学","料理","how"]):
        return "calm_explain"
    return "phonk_skull"   # デフォルト


# ════════════════════════════════════════════════════════
#  Pexels フリー素材取得
# ════════════════════════════════════════════════════════
def fetch_free_footage(query: str, pexels_key: str, log: LOG_CB,
                       out_dir: str = None) -> str | None:
    """
    Pexels API で動画素材を検索・ダウンロード。
    戻り値: ダウンロードしたファイルパス or None
    """
    if not pexels_key:
        log("⚠️ Pexels API キーなし → フリー素材スキップ")
        return None

    log(f"🎥 [Pexels] 素材検索: {query}")
    time.sleep(SLEEP)

    try:
        params  = urllib.parse.urlencode({"query": query, "per_page": 5, "orientation": "portrait"})
        req     = urllib.request.Request(
            f"https://api.pexels.com/videos/search?{params}",
            headers={"Authorization": pexels_key}
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())

        videos = data.get("videos", [])
        if not videos:
            log(f"⚠️ Pexels: '{query}' の素材なし")
            return None

        # 縦型優先・短め優先で選ぶ
        best = None
        for v in videos:
            for vf in v.get("video_files", []):
                if vf.get("height", 0) > vf.get("width", 1):  # 縦型
                    if best is None or v.get("duration", 999) < best[1]:
                        best = (vf["link"], v.get("duration", 0))
        if not best:
            best = (videos[0]["video_files"][0]["link"], 0)

        dl_url = best[0]
        out    = out_dir or tempfile.gettempdir()
        fname  = Path(out) / f"pexels_{query[:20].replace(' ','_')}.mp4"
        log(f"⬇️  [Pexels] ダウンロード中...")
        urllib.request.urlretrieve(dl_url, str(fname))
        log(f"✅ [Pexels] 取得完了: {fname.name}")
        return str(fname)

    except Exception as e:
        log(f"⚠️ Pexels 取得失敗: {e}")
        return None


def ai_decide_footage_query(model, analysis: dict, log: LOG_CB) -> str:
    """AI が動画内容から Pexels 検索クエリ（英語）を決める"""
    log("🤖 [AI] フリー素材キーワード決定中...")
    time.sleep(SLEEP)

    prompt = f"""
以下の動画タイトルと字幕を見て、Pexels で検索する英語キーワードを1〜3語で返してください。
縦型動画用の背景・トランジション素材として使います。
キーワードのみ返答（説明不要）。

タイトル: {analysis.get('title','')}
字幕: {' '.join(c.get('text','') for c in (analysis.get('captions') or [])[:3])}
"""
    try:
        resp = model.models.generate_content(model=model._model_name, contents=prompt)
        q    = resp.text.strip().split("\n")[0][:50]
        log(f"✅ [AI] 素材キーワード: {q}")
        return q
    except Exception:
        return "abstract background"


# ════════════════════════════════════════════════════════
#  ランキング演出オーバーレイ
# ════════════════════════════════════════════════════════
def build_ranking_overlays(captions: list, video_w: int, video_h: int,
                            style: str = "countdown"):
    """
    字幕リストからランキング演出クリップを生成する。
    funny=True の字幕を自動的にランキング対象として扱う。
    戻り値: ImageClip リスト
    """
    from moviepy.editor import ImageClip
    from PIL import Image, ImageDraw, ImageFont
    import numpy as np

    FONT_PATH = "NotoSansJP-Bold.ttf"
    def _font(size):
        try:    return ImageFont.truetype(FONT_PATH, size)
        except: return ImageFont.load_default()

    funny_caps = [c for c in captions if c.get("funny")]
    if not funny_caps:
        return []

    clips = []
    total = len(funny_caps)

    for i, cap in enumerate(funny_caps):
        rank  = total - i  # カウントダウン（最後が1位）
        start = float(cap.get("start", 0))
        end   = float(cap.get("end",   start + 2))
        dur   = max(end - start, 0.5)

        # バッジ画像生成
        badge_size = 90
        img   = Image.new("RGBA", (badge_size, badge_size), (0,0,0,0))
        draw  = ImageDraw.Draw(img)

        # 丸背景
        color = (255, 60, 60, 230) if rank == 1 else \
                (255, 160, 0, 220) if rank == 2 else \
                (100, 200, 255, 210)
        draw.ellipse([0,0,badge_size-1,badge_size-1], fill=color)

        # ランク数字
        fnt  = _font(42)
        txt  = f"#{rank}"
        tw   = int(draw.textlength(txt, font=fnt))
        draw.text(((badge_size-tw)//2, 18), txt, font=fnt, fill="#FFFFFF")

        arr = np.array(img)
        clip = (ImageClip(arr)
                .set_start(start)
                .set_duration(dur)
                .set_position((video_w - badge_size - 16, 80))
                .crossfadein(0.15))
        clips.append(clip)

    return clips


# ════════════════════════════════════════════════════════
#  フリー素材を動画に合成
# ════════════════════════════════════════════════════════
def apply_free_footage(base_clip, footage_path: str, mode: str,
                       video_w: int, video_h: int, log: LOG_CB):
    """
    フリー素材を base_clip に合成する。
    mode: "background" / "transition" / "ai_decide"
    戻り値: CompositeVideoClip
    """
    from moviepy.editor import VideoFileClip, CompositeVideoClip, concatenate_videoclips
    import numpy as np

    if not footage_path or not Path(footage_path).exists():
        return base_clip

    try:
        log(f"🎥 フリー素材合成中 (mode={mode})...")
        footage = VideoFileClip(footage_path)

        if mode == "background":
            # 冒頭3秒だけ背景として使う（半透明オーバーレイ）
            dur  = min(3.0, footage.duration, base_clip.duration)
            bg   = (footage.subclip(0, dur)
                    .resize((video_w, video_h))
                    .set_opacity(0.35)
                    .set_start(0))
            result = CompositeVideoClip([base_clip, bg], size=(video_w, video_h))
            log("✅ フリー素材: 背景オーバーレイ合成")
            return result

        elif mode == "transition":
            # シーン切り替わり風に中間に挿入（1秒）
            mid    = base_clip.duration / 2
            clip_a = base_clip.subclip(0, mid)
            trans  = (footage.subclip(0, min(1.0, footage.duration))
                      .resize((video_w, video_h)))
            clip_b = base_clip.subclip(mid)
            result = concatenate_videoclips([clip_a, trans, clip_b], method="compose")
            log("✅ フリー素材: トランジション挿入")
            return result

        else:
            # ai_decide → background として扱う
            return apply_free_footage(base_clip, footage_path, "background",
                                      video_w, video_h, log)

    except Exception as e:
        log(f"⚠️ フリー素材合成失敗: {e}")
        return base_clip


# ════════════════════════════════════════════════════════
#  テンプレートを DB に保存・取得（PLAN_TEMPLATES を db に同期）
# ════════════════════════════════════════════════════════
def sync_plan_templates_to_db():
    """PLAN_TEMPLATES を DB に同期（起動時に呼ぶ）"""
    import db, base64
    from io import BytesIO
    from PIL import Image, ImageDraw

    existing = {t["id"] for t in db.get_templates()}
    for tid, t in PLAN_TEMPLATES.items():
        if tid not in existing:
            # シンプルなプレビュー生成
            img  = Image.new("RGB", (270, 480), "#0a0a12")
            draw = ImageDraw.Draw(img)
            tc   = t["config"].get("title_color", "#fff")
            try:
                r = int(tc[1:3],16); g = int(tc[3:5],16); b = int(tc[5:7],16)
            except:
                r,g,b = 255,255,255
            draw.rectangle([20,180,250,300], fill=(r//3,g//3,b//3))
            draw.text((30,200), t["name"][:12], fill=(r,g,b))
            buf = BytesIO()
            img.save(buf, format="PNG")
            preview = base64.b64encode(buf.getvalue()).decode()
            db.save_template(tid, t["name"], t["config"], preview)


def get_plan_template(tid: str) -> dict:
    """テンプレートIDからconfig取得（DB優先、なければデフォルト）"""
    import db, json
    templates = db.get_templates()
    for t in templates:
        if t["id"] == tid:
            cfg = t.get("config_json", "{}")
            return json.loads(cfg) if isinstance(cfg, str) else cfg
    return PLAN_TEMPLATES.get(tid, PLAN_TEMPLATES["phonk_skull"])["config"]
