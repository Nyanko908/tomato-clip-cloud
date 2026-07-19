# -*- coding: utf-8 -*-
"""
code_edit.py — Python編集モード（常時有効）。

固定エフェクト＋JSONスキーマの代わりに、Gemini に編集コード（Python）を書かせて
実行する。自由度は無限だが、買い切り商品でユーザーのPC上で動かすので安全第一：

  1. サンドボックス … 実行前に AST を検査。import は許可リスト
     (moviepy/numpy/math/random/PIL) のみ、open/eval/exec/os 等は拒否、
     ダンダー属性アクセスも拒否。ビルトインも許可リストに絞る。
  2. 自己修復ループ … 生成→検証→実行。失敗したら traceback を Gemini に
     返して書き直させる（最大3回）。全滅したら従来の固定編集へフォールバック
     ＝「動画が完成しない」は絶対に起こさない。
  3. SDK … 尺が変わる操作（カット/早送り/巻き戻し/フリーズ）は editor.py の
     実証済み関数を包んだ tc.* を使わせ、TimeMap 相当のオペログを記録する。
     後段の字幕・エフェクト配置はオペログから TimeMap を再構築してズレない。
     見た目だけの演出（色調・ズーム等）は moviepy を自由に使ってよい。

パーソナライズ（プラグイン任意）：~/TomatoClip/ に TOMATOCLIP.md（ユーザーの記録）
や TC_DB/recipes/*.py（編集レシピ）が置いてあれば、コード生成プロンプトに注入する。
プラグインが無くても Python編集自体は動く。
"""
from __future__ import annotations

import ast
import json
import re
import threading
import traceback
from pathlib import Path
from typing import Callable, Optional

LOG_CB = Callable[[str], None]

# 実行タイムアウト（秒）。moviepyの中間書き出し込みなので長め。
_TIMEOUT_SEC = 600

# プラグインフォルダ（ユーザー案：全部同じフォルダ）。無くてもよい。
PLUGIN_DIR = Path.home() / "TomatoClip"


# ════════════════════════════════════════════════════════
#  サンドボックス（AST検査 + 制限ビルトイン）
# ════════════════════════════════════════════════════════
_ALLOWED_IMPORT_ROOTS = {"moviepy", "numpy", "math", "random", "PIL"}

_BANNED_NAMES = {
    "eval", "exec", "compile", "__import__", "open", "input", "breakpoint",
    "globals", "locals", "vars", "getattr", "setattr", "delattr",
    "exit", "quit", "help", "memoryview", "classmethod", "staticmethod",
}

_SAFE_BUILTIN_NAMES = [
    "abs", "all", "any", "bool", "dict", "divmod", "enumerate", "filter",
    "float", "format", "frozenset", "hasattr", "hash", "int", "isinstance",
    "issubclass", "iter", "len", "list", "map", "max", "min", "next", "pow",
    "print", "range", "repr", "reversed", "round", "set", "slice", "sorted",
    "str", "sum", "tuple", "zip",
    "Exception", "ValueError", "TypeError", "IndexError", "KeyError",
    "ZeroDivisionError", "StopIteration", "ArithmeticError", "RuntimeError",
    "True", "False", "None",
]


def validate_code(code: str) -> Optional[str]:
    """コードを検査してNGなら理由を返す（OKなら None）。"""
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return f"SyntaxError: {e}"
    has_edit = False
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = ([a.name for a in node.names] if isinstance(node, ast.Import)
                     else [node.module or ""])
            for n in names:
                root = (n or "").split(".")[0]
                if root not in _ALLOWED_IMPORT_ROOTS:
                    return f"import '{n}' は許可されていません（許可: {sorted(_ALLOWED_IMPORT_ROOTS)}）"
        elif isinstance(node, ast.Name) and node.id in _BANNED_NAMES:
            return f"'{node.id}' の使用は許可されていません"
        elif isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            return f"ダンダー属性 '{node.attr}' へのアクセスは許可されていません"
        elif isinstance(node, ast.FunctionDef) and node.name == "edit":
            has_edit = True
    if not has_edit:
        return "def edit(clip, tc): が定義されていません"
    return None


def _safe_builtins():
    import builtins as _b
    safe = {}
    for name in _SAFE_BUILTIN_NAMES:
        if hasattr(_b, name):
            safe[name] = getattr(_b, name)

    def _guarded_import(name, *args, **kwargs):
        if name.split(".")[0] not in _ALLOWED_IMPORT_ROOTS:
            raise ImportError(f"import '{name}' は許可されていません")
        return __import__(name, *args, **kwargs)

    safe["__import__"] = _guarded_import
    return safe


# ════════════════════════════════════════════════════════
#  SDK — 尺が変わる操作は editor.py の実証済み関数＋オペログ記録
# ════════════════════════════════════════════════════════
class TC:
    """
    生成コードに渡す編集SDK。時刻はすべて「元クリップの秒」で指定してよい。
    内部の TimeMap が現在の時間軸へ変換し、同じ内容をオペログに記録する。
    後段（字幕・レイアウト）はオペログから TimeMap を再構築して追従する。
    """

    def __init__(self, log: LOG_CB, captions=None):
        from editor import TimeMap
        self._tmap = TimeMap()
        self._log = log
        self.ops = []          # [{"op":"cuts"|"speed"|"insert", ...}] 適用済み座標で記録
        self.captions = list(captions or [])   # 解析結果の字幕（text/start/end/funny）
        self.handled_captions = False          # True=字幕はコードが描いた（既定字幕を置かない）
        self.reported = []                     # tc.report()による自己申告（自由コード用）
        self.used_assets = []                  # tc.asset()で使った素材（クレジット表示用）

    def asset(self, name: str) -> str:
        """
        TC_DB の素材のファイルパスを返す（ImageClip / AudioFileClip にそのまま渡せる）。
        使った素材は記録され、クレジットが必要なものは動画の引用元表示に自動で載る。
        """
        import tc_db
        meta = tc_db.find_asset(str(name))
        if not meta:
            names = [m["name"] for m in tc_db.list_assets()][:10]
            raise ValueError(f"素材 '{name}' はTC_DBにありません。使える素材: {names}")
        if not any(u.get("name") == meta["name"] for u in self.used_assets):
            self.used_assets.append(meta)
        self.log(f"素材を使用: {meta['name']}（{meta['license']}）")
        return meta["path"]

    def report(self, edit_report: dict):
        """
        自由コードで尺を変えた時の自己申告（「制限」ではなく「記録・検証」方式）。
        {"cuts":[{"start","end"}], "speeds":[{"start","end","factor"}],
         "inserts":[{"at","dur"}]} を元動画の秒で申告する。
        実行後にシステムが「申告から計算した尺」と「実際の尺」を突き合わせ、
        合わなければその試行は失敗として書き直しになる。
        """
        if isinstance(edit_report, dict):
            self.reported.append(edit_report)

    def log(self, msg):
        self._log(f"  🐍 {msg}")

    # ── 字幕の自作サポート ──
    def take_captions(self):
        """字幕を自分のコードで描くと宣言する。既定レンダラーは字幕を配置しなくなる。"""
        self.handled_captions = True
        self.log("字幕はコード側で描画します")

    def font(self, size=58, style=None):
        """同梱フォント（日本語対応）の PIL ImageFont を返す。
        moviepyのTextClipはImageMagick必須で使えないため、文字はPILで描く。"""
        from editor import _font
        return _font(int(size), style)

    def text_image(self, text, size=58, color="#FFFFFF", stroke="#000000", style=None):
        """縁取り付きテキストの RGBA PIL Image を返す（字幕・テロップの自作素材）。"""
        from PIL import Image, ImageDraw
        f = self.font(size, style)
        dummy = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
        w = max(2, int(dummy.textlength(text, font=f)))
        img = Image.new("RGBA", (w + 28, int(size) + 28), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.text((16, 10), text, font=f, fill=stroke)
        d.text((14, 8), text, font=f, fill=color)
        return img

    # ── 尺が変わる操作（必ずこれを使う） ──
    def cut(self, clip, ranges):
        """ranges: [(start, end), ...] を取り除く。"""
        from editor import apply_cuts
        mapped = []
        for s, e in ranges:
            ms, me = self._tmap.map(s), self._tmap.map(e)
            if me > ms:
                mapped.append((ms, me))
        if not mapped:
            return clip
        clip = apply_cuts(clip, [{"start": s, "end": e} for s, e in mapped], self._log)
        self._tmap.add_cuts([{"start": s, "end": e} for s, e in mapped])
        self.ops.append({"op": "cuts", "ranges": [[s, e] for s, e in mapped]})
        return clip

    def fastforward(self, clip, start, end, speed=2.0):
        from editor import apply_fastforward
        s, e = self._tmap.map(start), self._tmap.map(end)
        if e <= s or speed <= 0:
            return clip
        clip = apply_fastforward(clip, s, e, speed, log=self._log)
        self._tmap.add_speed(s, e, speed)
        self.ops.append({"op": "speed", "s": s, "e": e, "f": speed})
        return clip

    def rewind(self, clip, at, dur=1.5):
        from editor import apply_rewind
        t = self._tmap.map(at)
        clip = apply_rewind(clip, t, dur, log=self._log)
        self._tmap.add_insert(t - dur, dur)
        self.ops.append({"op": "insert", "at": t - dur, "dur": dur})
        return clip

    def freeze(self, clip, at, dur=1.5):
        from editor import apply_freeze
        t = self._tmap.map(at)
        clip = apply_freeze(clip, t, dur, log=self._log)
        self._tmap.add_insert(t, dur)
        self.ops.append({"op": "insert", "at": t, "dur": dur})
        return clip

    # ── 見た目だけの演出（尺は変わらない） ──
    def zoom(self, clip, start, end, scale=1.5):
        from editor import apply_zoom
        return apply_zoom(clip, self._tmap.map(start), self._tmap.map(end), scale, log=self._log)

    def monochrome(self, clip, start, end):
        from editor import apply_monochrome
        return apply_monochrome(clip, self._tmap.map(start), self._tmap.map(end), log=self._log)

    def flip(self, clip, start, end):
        from editor import apply_flip
        return apply_flip(clip, self._tmap.map(start), self._tmap.map(end), log=self._log)

    def mosaic(self, clip, start, end, block=20):
        from editor import apply_mosaic
        return apply_mosaic(clip, self._tmap.map(start), self._tmap.map(end), block, log=self._log)

    # 現在の時間軸に変換（自由コードで区間演出したい時用）
    def t(self, src_sec):
        return self._tmap.map(src_sec)


def _apply_report(tmap, ops, rep):
    """自己申告（元動画の秒）を TimeMap／オペログへ合成する。tc と同じ写像規則。"""
    for c in rep.get("cuts") or []:
        try:
            s, e = tmap.map(float(c["start"])), tmap.map(float(c["end"]))
        except (TypeError, ValueError, KeyError):
            continue
        if e > s:
            tmap.add_cuts([{"start": s, "end": e}])
            ops.append({"op": "cuts", "ranges": [[s, e]]})
    for sp in rep.get("speeds") or []:
        try:
            s, e = tmap.map(float(sp["start"])), tmap.map(float(sp["end"]))
            f = float(sp.get("factor", 2.0))
        except (TypeError, ValueError, KeyError):
            continue
        if e > s and f > 0:
            tmap.add_speed(s, e, f)
            ops.append({"op": "speed", "s": s, "e": e, "f": f})
    for ins in rep.get("inserts") or []:
        try:
            at, d = tmap.map(float(ins["at"])), float(ins["dur"])
        except (TypeError, ValueError, KeyError):
            continue
        if d > 0:
            tmap.add_insert(at, d)
            ops.append({"op": "insert", "at": at, "dur": d})


# ════════════════════════════════════════════════════════
#  実行（別スレッド + タイムアウト。凍結EXEでも動く）
# ════════════════════════════════════════════════════════
def run_edit_code(code: str, src_path: str, out_path: str, log: LOG_CB,
                  captions=None) -> dict:
    """
    検証済みコードを実行し、編集結果を out_path（中間動画・ほぼ無劣化）に書く。
    戻り: {"ok": True, "oplog": [...], "duration": float, "handled_captions": bool}
          / {"ok": False, "error": "..."}
    """
    err = validate_code(code)
    if err:
        return {"ok": False, "error": f"検証NG: {err}"}

    result = {}

    def _worker():
        clip = None
        try:
            from moviepy.editor import VideoFileClip
            tc = TC(log, captions=captions)
            g = {"__builtins__": _safe_builtins()}
            exec(compile(code, "<tomato_edit>", "exec"), g)   # AST検査済み
            clip = VideoFileClip(src_path)
            src_dur = float(clip.duration or 0)
            out = g["edit"](clip, tc)
            if out is None:
                raise ValueError("edit() が None を返しました（clip を return してください）")
            # 自己申告（tc.report / モジュール変数 edit_report）をオペログへ合成
            reports = list(tc.reported)
            if isinstance(g.get("edit_report"), dict):
                reports.append(g["edit_report"])
            for rep in reports:
                _apply_report(tc._tmap, tc.ops, rep)
            # 検証：「編集操作を制限する」のではなく「編集結果を記録・検証する」。
            # 記録＋申告から計算した尺と実際の尺が合わなければ、この試行は失敗にして
            # 書き直させる（以前は警告のみで通していた＝字幕がズレたまま採用される穴）。
            expect = tc._tmap.map(src_dur)
            drift = abs(float(out.duration) - expect)
            if drift > 1.0:
                raise ValueError(
                    f"尺の検証NG: 記録・申告から期待される長さは {expect:.1f}s ですが"
                    f"実際は {float(out.duration):.1f}s（{drift:.1f}s 不一致）。"
                    "尺を変える操作は tc関数を使うか、edit_report/tc.report で正しく申告してください")
            fps = int(round(float(getattr(out, "fps", None) or clip.fps or 30)))
            out.write_videofile(
                out_path, fps=max(24, min(60, fps)), codec="libx264",
                preset="ultrafast", audio_codec="aac", logger=None,
                ffmpeg_params=["-crf", "12"],
            )
            result.update({"ok": True, "oplog": tc.ops,
                           "duration": float(out.duration),
                           "handled_captions": bool(tc.handled_captions),
                           "used_assets": list(tc.used_assets)})
        except Exception:
            result.update({"ok": False, "error": traceback.format_exc(limit=6)})
        finally:
            try:
                if clip is not None:
                    clip.close()
            except Exception:
                pass

    th = threading.Thread(target=_worker, daemon=True)
    th.start()
    th.join(_TIMEOUT_SEC)
    if th.is_alive():
        return {"ok": False, "error": f"タイムアウト（{_TIMEOUT_SEC}秒）"}
    return result if result else {"ok": False, "error": "結果なし"}


def rebuild_timemap(oplog: list):
    """オペログから TimeMap を再構築する（editor.run_edit の後段が使う）。"""
    from editor import TimeMap
    tmap = TimeMap()
    for op in oplog or []:
        try:
            if op.get("op") == "cuts":
                tmap.add_cuts([{"start": s, "end": e} for s, e in op.get("ranges", [])])
            elif op.get("op") == "speed":
                tmap.add_speed(float(op["s"]), float(op["e"]), float(op["f"]))
            elif op.get("op") == "insert":
                tmap.add_insert(float(op["at"]), float(op["dur"]))
        except Exception:
            pass
    return tmap


# ════════════════════════════════════════════════════════
#  コード生成（自己修復ループ）＋ プラグイン注入
# ════════════════════════════════════════════════════════
# ルールは最小限にし、書き方はサンプルで見せる（サンプル主体の方が直感的に書ける）。
_SDK_DOC = """
【書き方】def edit(clip, tc): を定義し、編集後の clip を return する。ルールは2つだけ:
1. 尺（長さ）が変わる編集は、どちらかの方法で「記録」する（後工程の字幕がこれで追従する）:
   a) tc関数を使う（自動記録・確実）… tc.cut([(s,e),..]) / tc.fastforward(s,e,speed)
      / tc.rewind(at,dur) / tc.freeze(at,dur)
   b) moviepy で自由に書き、edit_report で申告する（サンプル5）。実行後にシステムが
      申告と実際の尺を突き合わせて検証し、合わないと書き直しになる。
2. 尺が変わらない演出は moviepy で自由に書いてよい（import可: moviepy/numpy/math/random/PIL。
   ファイル入出力・ネットワーク・os等は禁止＝自動検査で弾かれる）。
時刻は「元動画の秒」で書く。自由演出で区間を切り出す時は tc.t(元秒) で現在秒に変換。
進捗コメントは tc.log("...")。tc.zoom/monochrome/flip/mosaic も使える（尺不変の定番）。
字幕を独自スタイルで描きたい時は tc.take_captions() を呼び、tc.captions（解析結果）と
tc.text_image(text, size, color)（日本語対応フォントのPIL画像）で自分で描く（サンプル4）。
呼ばなければ後工程が既定スタイルで字幕を配置する。
素材一覧が渡されていれば tc.asset("名前") でファイルパスを取得し、ImageClip や
AudioFileClip でオーバーレイ・効果音として使える（ライセンスは確認済み・クレジットは自動）。
"""

_SAMPLES = '''
【サンプル1: 無音カット + 見せ場ズーム】
def edit(clip, tc):
    tc.log("無音区間をカットしてテンポアップ")
    clip = tc.cut(clip, [(12.0, 15.5)])
    tc.log("見せ場を強調")
    clip = tc.zoom(clip, 24.0, 27.0, scale=1.6)
    return clip

【サンプル2: 前置き早送り + 決定的瞬間フリーズ + 色味アップ】
def edit(clip, tc):
    clip = tc.fastforward(clip, 0.0, 6.0, speed=2.5)
    clip = tc.freeze(clip, 21.0, dur=1.2)
    from moviepy.editor import vfx
    clip = clip.fx(vfx.colorx, 1.12)   # 尺不変の演出は自由
    return clip

【サンプル3: 座標を指定した自由演出（リアクションに寄るクロップ）】
def edit(clip, tc):
    from moviepy.editor import vfx, concatenate_videoclips
    w, h = clip.size
    s, e = tc.t(30.0), tc.t(33.0)       # 元動画の30〜33秒を現在秒に変換
    part = (clip.subclip(s, e)
                .fx(vfx.crop, x1=w*0.2, y1=h*0.1, x2=w*0.8, y2=h*0.7)  # 顔のあたりを切り出し
                .resize((w, h)))         # 同じ画面サイズに戻す＝実質ズーム
    clip = concatenate_videoclips([clip.subclip(0, s), part, clip.subclip(e)])
    return clip                          # 尺は変わっていないのでOK

【サンプル4: 字幕を自作する（1文字ずつ出るタイピング演出）。
 既定の字幕スタイルが動画に合わない時は tc.take_captions() で自分で描いてよい】
def edit(clip, tc):
    tc.take_captions()                   # 既定レンダラーの字幕を止めて自分で描く宣言
    from moviepy.editor import CompositeVideoClip, ImageClip
    import numpy, random
    w, h = clip.size
    layers = [clip]
    for cap in tc.captions:              # 解析結果の字幕 [{"text","start","end","funny"}]
        s, e = tc.t(cap["start"]), tc.t(cap["end"])
        text, step = cap["text"], 0.05
        for i in range(1, len(text) + 1):        # 1文字ずつ増やす＝タイピング
            img = tc.text_image(text[:i], size=64, color="#FFF000" if cap.get("funny") else "#FFFFFF")
            t0 = s + (i - 1) * step
            # 次の文字が出たら前の状態は消す（最後だけ end まで表示）。重ねると文字が濁る
            d = step if i < len(text) else max(0.1, e - t0)
            jitter = random.randint(-3, 3)       # 少し揺らすと勢いが出る
            layers.append(ImageClip(numpy.array(img)).set_start(t0)
                          .set_duration(d)
                          .set_position(("center", int(h * 0.82) + jitter)))
    return CompositeVideoClip(layers)    # 尺は変わっていないのでOK

【サンプル5: moviepyで自由に尺を変える + edit_report で申告（tc関数を使わない書き方）】
def edit(clip, tc):
    from moviepy.editor import concatenate_videoclips
    cut_start, cut_end = 10.0, 15.0      # この区間が冗長なので取り除く
    clip = concatenate_videoclips([clip.subclip(0, cut_start), clip.subclip(cut_end)])
    tc.report({"cuts": [{"start": cut_start, "end": cut_end}]})   # 申告（元動画の秒）
    # 早送りなら {"speeds":[{"start":s,"end":e,"factor":2.0}]}、
    # 静止・挿入なら {"inserts":[{"at":t,"dur":1.5}]} を申告する
    return clip
'''


def _plugin_context(log: LOG_CB) -> str:
    """~/TomatoClip/ のプラグイン（任意）を読み、プロンプト追記分を返す。"""
    parts = []
    try:
        md = PLUGIN_DIR / "TOMATOCLIP.md"
        if md.exists():
            txt = md.read_text(encoding="utf-8", errors="ignore")[:4000]
            if txt.strip():
                parts.append("【ユーザーについて（TOMATOCLIP.md）】\n" + txt)
                log("  🧩 TOMATOCLIP.md を反映")
        rec_dir = PLUGIN_DIR / "TC_DB" / "recipes"
        if rec_dir.is_dir():
            recipes = sorted(rec_dir.glob("*.py"))[:3]
            for p in recipes:
                txt = p.read_text(encoding="utf-8", errors="ignore")[:2000]
                if txt.strip():
                    parts.append(f"【ユーザーの編集レシピ: {p.name}】\n{txt}")
            if recipes:
                log(f"  🧩 編集レシピ {len(recipes)}件を反映")
        # TC_DB の素材INDEX（Web検索で取得済み・ライセンス確認済みのもの）
        import tc_db
        idx = tc_db.asset_index_text()
        if idx:
            parts.append(idx)
            log(f"  🧩 素材 {len(tc_db.list_assets())}件を提示")
    except Exception:
        pass
    return ("\n".join(parts) + "\n") if parts else ""


def _build_prompt(analysis: dict, duration: float, lang: str, feedback: str, log: LOG_CB) -> str:
    brief = {
        "title": analysis.get("title", ""),
        "duration_sec": round(duration, 1),
        "cut_sections": analysis.get("cut_sections", []),
        "rewind_at": analysis.get("rewind_at"),
        "freeze_at": analysis.get("freeze_at"),
        "fastforward": [analysis.get("fastforward_at"), analysis.get("fastforward_end")],
        "zoom": [analysis.get("zoom_at"), analysis.get("zoom_end")],
        "captions_sec": [[c.get("start"), c.get("end")] for c in analysis.get("captions", [])[:20]],
    }
    fb = f"\n【前回の失敗】この原因を直すこと:\n{feedback}\n" if feedback else ""
    return f"""あなたはショート動画の編集者です。以下の解析結果をもとに、この動画を
最も面白く仕上げる Python の編集コードを書いてください。

{_SDK_DOC}
{_SAMPLES}
{_plugin_context(log)}
【この動画の解析結果】（時刻は元動画の秒）
{json.dumps(brief, ensure_ascii=False)}

注意:
- 解析結果のカット候補・演出候補は参考。より良い判断があれば変えてよい。
- 字幕は captions_sec の時刻に後工程で自動配置される。カット等は tc を使えばズレない。
- コメントは{('日本語' if lang == 'ja' else lang)}で、何を狙った編集か書くこと（編集履歴に表示される）。
{fb}
返答は Python コードのみ（コードブロック記号 ``` は不要）。
"""


def apply_code_edit(client, src_path: str, analysis: dict, log: LOG_CB,
                    config: dict = None) -> bool:
    """
    コード生成→検証→実行の自己修復ループ（最大3回）。
    成功したら analysis に edit_code / code_oplog / code_intermediate を設定して True。
    失敗しても False を返すだけ（呼び出し側は従来編集へフォールバック）。
    """
    if config is not None and not config.get("python_edit", True):
        return False
    try:
        from moviepy.editor import VideoFileClip
        probe = VideoFileClip(src_path)
        duration = float(probe.duration or 0)
        probe.close()
    except Exception as e:
        log(f"⚠️ Python編集: 素材を読めません（従来編集で続行）: {e}")
        return False
    if duration <= 0:
        return False

    from pipeline import _gemini_call
    lang = (analysis.get("output_language") or "ja")
    out_path = str(Path(src_path).with_name(Path(src_path).stem + "_pyedit.mp4"))

    log("🐍 Python編集: AIが編集コードを書いています...")
    feedback = ""
    for attempt in range(1, 4):
        try:
            raw = _gemini_call(client, _build_prompt(analysis, duration, lang, feedback, log))
        except Exception as e:
            log(f"⚠️ Python編集: コード生成に失敗（従来編集で続行）: {str(e)[:100]}")
            return False
        code = re.sub(r"^```(?:python)?|```$", "", (raw or "").strip(), flags=re.M).strip()
        err = validate_code(code)
        if err:
            log(f"  🔎 検証NG ({attempt}/3): {err}")
            feedback = f"コード検証エラー: {err}"
            continue
        log(f"  ▶ 実行中 ({attempt}/3)...")
        res = run_edit_code(code, src_path, out_path, log,
                            captions=analysis.get("captions"))
        if res.get("ok"):
            analysis["edit_code"] = code
            analysis["code_oplog"] = res.get("oplog", [])
            analysis["code_intermediate"] = out_path
            analysis["code_handled_captions"] = bool(res.get("handled_captions"))
            # 使った素材：記録＋クレジット必要なものは引用元表示に自動で載せる
            used = res.get("used_assets") or []
            if used:
                analysis["used_assets"] = [u["name"] for u in used]
                srcs = analysis.setdefault("sources", [])
                for u in used:
                    if u.get("attribution_required") and u.get("credit"):
                        if not any(u["credit"] in str(s) for s in srcs):
                            srcs.append(u["credit"])
            log(f"  ✅ Python編集完了（{res.get('duration', 0):.1f}秒 / 操作{len(res.get('oplog', []))}件"
                + ("・字幕はコード描画" if res.get("handled_captions") else "") + "）")
            return True
        log(f"  ✂ 実行エラー ({attempt}/3) → 書き直します")
        feedback = f"実行時エラー:\n{res.get('error', '')[:1500]}"
    log("⚠️ Python編集: 3回失敗 → 従来の編集で続行します")
    return False
