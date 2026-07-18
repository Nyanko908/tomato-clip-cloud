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

    def __init__(self, log: LOG_CB):
        from editor import TimeMap
        self._tmap = TimeMap()
        self._log = log
        self.ops = []          # [{"op":"cuts"|"speed"|"insert", ...}] 適用済み座標で記録

    def log(self, msg):
        self._log(f"  🐍 {msg}")

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


# ════════════════════════════════════════════════════════
#  実行（別スレッド + タイムアウト。凍結EXEでも動く）
# ════════════════════════════════════════════════════════
def run_edit_code(code: str, src_path: str, out_path: str, log: LOG_CB) -> dict:
    """
    検証済みコードを実行し、編集結果を out_path（中間動画・ほぼ無劣化）に書く。
    戻り: {"ok": True, "oplog": [...], "duration": float} / {"ok": False, "error": "..."}
    """
    err = validate_code(code)
    if err:
        return {"ok": False, "error": f"検証NG: {err}"}

    result = {}

    def _worker():
        clip = None
        try:
            from moviepy.editor import VideoFileClip
            tc = TC(log)
            g = {"__builtins__": _safe_builtins()}
            exec(compile(code, "<tomato_edit>", "exec"), g)   # AST検査済み
            clip = VideoFileClip(src_path)
            src_dur = float(clip.duration or 0)
            out = g["edit"](clip, tc)
            if out is None:
                raise ValueError("edit() が None を返しました（clip を return してください）")
            # 尺の整合チェック：tc.* 以外で尺を変えると字幕がズレるので警告
            expect = tc._tmap.map(src_dur)
            if abs(float(out.duration) - expect) > 1.0:
                log(f"  ⚠️ 尺がSDKの記録と{abs(float(out.duration) - expect):.1f}秒ズレています"
                    "（尺を変える操作は tc.cut / tc.fastforward 等を使ってください）")
            fps = int(round(float(getattr(out, "fps", None) or clip.fps or 30)))
            out.write_videofile(
                out_path, fps=max(24, min(60, fps)), codec="libx264",
                preset="ultrafast", audio_codec="aac", logger=None,
                ffmpeg_params=["-crf", "12"],
            )
            result.update({"ok": True, "oplog": tc.ops,
                           "duration": float(out.duration)})
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
_SDK_DOC = """
【SDK仕様】def edit(clip, tc): を定義し、編集後の clip を return すること。
時刻はすべて「元動画の秒」で指定してよい（tcが内部で換算する）。

尺が変わる操作は必ず tc を使う（字幕の自動追従のため）:
  clip = tc.cut(clip, [(12.0, 18.5), ...])       # 区間を取り除く
  clip = tc.fastforward(clip, s, e, speed=2.0)   # 早送り
  clip = tc.rewind(clip, at, dur=1.5)            # 直前を逆再生
  clip = tc.freeze(clip, at, dur=1.5)            # 静止フレーム
見た目だけの演出（尺不変）:
  clip = tc.zoom(clip, s, e, scale=1.5)
  clip = tc.monochrome(clip, s, e) / tc.flip(clip, s, e) / tc.mosaic(clip, s, e)
自由演出: moviepy を直接使ってよい（import moviepy / numpy / math / random / PIL のみ可）。
ただし尺を変えるのは禁止（変えたい時は tc を使う）。区間指定には tc.t(元秒) で現在秒に変換。
禁止: ファイル入出力・ネットワーク・os/subprocess・eval等（検査で弾かれる）。
進捗は tc.log("...") で出せる。
"""

_SAMPLES = '''
【サンプル1: 無音カット + 見せ場ズーム】
def edit(clip, tc):
    tc.log("無音区間をカット")
    clip = tc.cut(clip, [(12.0, 15.5)])
    tc.log("見せ場をズーム")
    clip = tc.zoom(clip, 24.0, 27.0, scale=1.6)
    return clip

【サンプル2: 前置き早送り + 決定的瞬間フリーズ + 色味アップ】
def edit(clip, tc):
    clip = tc.fastforward(clip, 0.0, 6.0, speed=2.5)
    clip = tc.freeze(clip, 21.0, dur=1.2)
    from moviepy.editor import vfx
    clip = clip.fx(vfx.colorx, 1.12)   # 尺不変の演出は自由
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
        res = run_edit_code(code, src_path, out_path, log)
        if res.get("ok"):
            analysis["edit_code"] = code
            analysis["code_oplog"] = res.get("oplog", [])
            analysis["code_intermediate"] = out_path
            log(f"  ✅ Python編集完了（{res.get('duration', 0):.1f}秒 / 操作{len(res.get('oplog', []))}件）")
            return True
        log(f"  ✂ 実行エラー ({attempt}/3) → 書き直します")
        feedback = f"実行時エラー:\n{res.get('error', '')[:1500]}"
    log("⚠️ Python編集: 3回失敗 → 従来の編集で続行します")
    return False
