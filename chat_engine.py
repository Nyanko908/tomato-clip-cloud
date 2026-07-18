# -*- coding: utf-8 -*-
"""
chat_engine.py — Tomato Clip のチャット頭脳（Tkinter非依存）。

app.py の _chat_send / _chat_dispatch_exec のロジックを、Tkinter I/O から切り離して
コールバック方式に置き換えたもの。pywebview 版 UI（web_app.py）から使う。
中身の生成は pipeline.py（run_pipeline / run_pipeline_from_url / analyze_trends）を流用。

コールバック（callbacks dict、UIへの出力）:
  on_text(text)                    … AIのテキストを表示
  on_progress_start(pid, title)    … 進捗カードを開始
  on_progress(pid, step_text)      … 進捗カードのステップ更新
  on_progress_done(pid, title)     … 進捗カード完了
  on_video(dict{path,title,subtitle}) … 完成動画カード
  on_error(text)                   … エラー表示
  on_done()                        … 1ターン完了（UIの送信ロック解除）
"""
import json, time, threading, hmac, hashlib
from pathlib import Path
from datetime import datetime
from typing import Optional

# ── クレジット（app.py から流用・純粋ロジック） ──────────────────
CREDIT_FILE = Path.home() / ".tomato_clip" / "credits.json"
CREDIT_MAX, CREDIT_INIT, COST_VIDEO, COST_TREND = 20, 20, 15, 3


def _credit_sig(credits: int, last: float) -> str:
    try:
        from license import _get_machine_id
        mid = _get_machine_id()
    except Exception:
        mid = "fallback"
    key = f"ts-credit-v1:{mid}".encode()
    msg = f"{credits}|{last:.3f}".encode()
    return hmac.new(key, msg, hashlib.sha256).hexdigest()


def credits_load() -> int:
    import math
    try:
        if CREDIT_FILE.exists():
            d = json.loads(CREDIT_FILE.read_text(encoding="utf-8"))
            cur = int(d.get("credits", 0)); last = float(d.get("last_recovery", time.time()))
            if not hmac.compare_digest(d.get("sig", ""), _credit_sig(cur, last)):
                credits_save(CREDIT_INIT); return CREDIT_INIT
            earned = math.floor((time.time() - last) / 3600)
            if earned > 0:
                if cur < CREDIT_MAX:
                    cur = min(CREDIT_MAX, cur + earned)
                credits_save(cur, last + earned * 3600)
            return cur
    except Exception:
        pass
    credits_save(CREDIT_INIT); return CREDIT_INIT


def credits_save(amount: int, last_recovery: float = None):
    if last_recovery is None:
        last_recovery = time.time()
    CREDIT_FILE.parent.mkdir(parents=True, exist_ok=True)
    CREDIT_FILE.write_text(json.dumps(
        {"credits": amount, "last_recovery": last_recovery,
         "sig": _credit_sig(amount, last_recovery)}), encoding="utf-8")


def credits_add(amount: int) -> int:
    cur = credits_load()
    try:
        d = json.loads(CREDIT_FILE.read_text(encoding="utf-8")); last = float(d.get("last_recovery", time.time()))
    except Exception:
        last = time.time()
    new = cur + amount
    credits_save(new, last)
    return new


# ── システムプロンプト ───────────────────────────────────────
_SYSTEM = (
    "あなたはYouTube Shorts自動生成ツール「Tomato Clip」のAIアシスタントです。"
    "ユーザーが操作・実行を指示した場合は必ず適切なツールを呼び出してください。\n"
    "「動画作って」「一本作って」「生成して」など動画生成の指示があれば、"
    "URLが明示されていない限り必ずstart_pipelineを呼んでください。URLを聞き返してはいけません。"
    "start_from_urlはユーザーがURLを明示的に提示したときだけ使用してください。"
    "「〇〇をテーマに」「〇〇の動画」のように具体テーマがあればstart_with_keywordを使ってください。\n"
    "「覚えて」「記録して」はsave_memory、「履歴見せて」「過去の動画は？」はdb_read_history、"
    "「〇〇の切り抜きしたい」「〇〇を検索して」はdb_add_search_intent（category は vtuber/gaming/funny 等）。\n"
    "「トレンド分析して」「今何が伸びてる？」はanalyze_trends。\n"
    "普通の質問・相談・会話はテキストで簡潔に日本語で答えてください。"
    "検索やURL読解が必要でも、分かる範囲で知識をもとに答えてください。"
)


def _tools():
    """function_declarations のみ（ビルトインツールは併用不可＝2026-07の仕様。混ぜると400）。"""
    from google.genai import types as gt
    S = lambda **p: {"type": "OBJECT", "properties": p, "required": [k for k in p]}
    return [gt.Tool(function_declarations=[
        gt.FunctionDeclaration(name="start_pipeline",
            description="トレンドから自動でYouTube Shortsを検索・編集・生成する",
            parameters={"type": "OBJECT", "properties": {}, "required": []}),
        gt.FunctionDeclaration(name="start_from_url",
            description="指定したYouTubeのURLをベースに動画を生成する",
            parameters={"type": "OBJECT", "properties": {"url": {"type": "STRING", "description": "YouTubeのURL"}}, "required": ["url"]}),
        gt.FunctionDeclaration(name="start_with_keyword",
            description="特定のテーマ・キーワードで動画を生成する",
            parameters={"type": "OBJECT", "properties": {"keyword": {"type": "STRING"}}, "required": ["keyword"]}),
        gt.FunctionDeclaration(name="analyze_trends",
            description="今のYouTubeトレンドを分析する",
            parameters={"type": "OBJECT", "properties": {}, "required": []}),
        gt.FunctionDeclaration(name="db_read_history",
            description="過去に生成した動画の履歴を表示する",
            parameters={"type": "OBJECT", "properties": {}, "required": []}),
        gt.FunctionDeclaration(name="db_add_search_intent",
            description="検索したいジャンル/対象（VTuber・ゲーム等）をDBに登録する",
            parameters={"type": "OBJECT", "properties": {"category": {"type": "STRING"}, "value": {"type": "STRING"}}, "required": ["value"]}),
        gt.FunctionDeclaration(name="save_memory",
            description="ユーザーが覚えてほしいことを長期記憶に保存する",
            parameters={"type": "OBJECT", "properties": {"content": {"type": "STRING"}}, "required": ["content"]}),
        gt.FunctionDeclaration(name="stop_process",
            description="実行中の生成を停止する",
            parameters={"type": "OBJECT", "properties": {}, "required": []}),
    ])]


class ChatEngine:
    def __init__(self, config: dict, get_license, callbacks: dict):
        self.config = config
        self.get_license = get_license          # callable -> license or None
        self.cb = callbacks or {}
        self.history = []
        self.stop_event = None
        self.running = False

    def _emit(self, name, *args):
        fn = self.cb.get(name)
        if fn:
            try:
                fn(*args)
            except Exception:
                pass

    # ── 1ターン処理（web_app からスレッドで呼ばれる） ──
    def send(self, text: str):
        try:
            self._handle(text)
        except Exception as e:
            import traceback; traceback.print_exc()
            self._emit("on_error", f"エラーが発生しました: {e}")
        finally:
            self._emit("on_done")

    def _handle(self, text: str):
        from pipeline import init_gemini, DEFAULT_MODEL as _DEFAULT_MODEL
        from google.genai import types as gt

        key = self.config.get("gemini_key", "")
        if not key:
            self._emit("on_text", "❌ Gemini APIキーが設定されていません。設定から登録してください。")
            return

        client = init_gemini(key, self.config.get("gemini_model") or _DEFAULT_MODEL)
        self.history.append({"role": "user", "parts": [text]})
        system = _SYSTEM + f"\n現在時刻: {datetime.now().strftime('%Y-%m-%d %H:%M')}"

        contents = [
            gt.Content(role=h["role"], parts=[gt.Part(text=h["parts"][0])])
            for h in self.history
        ]
        for attempt in range(4):
            try:
                resp = client.models.generate_content(
                    model=client._model_name, contents=contents,
                    config=gt.GenerateContentConfig(system_instruction=system, tools=_tools()))
                break
            except Exception as e:
                es = str(e)
                if ("503" in es or "UNAVAILABLE" in es) and attempt < 3:
                    time.sleep(6 * (2 ** attempt)); continue
                raise

        fcs, txt = [], []
        try:
            for part in resp.candidates[0].content.parts:
                if getattr(part, "function_call", None):
                    fcs.append(part.function_call)
                elif getattr(part, "text", None):
                    txt.append(part.text)
        except Exception:
            pass

        lead = "\n".join(t.strip() for t in txt if t and t.strip())
        if lead:
            self._emit("on_text", lead)

        if fcs:
            for fc in fcs:
                self.history.append({"role": "model", "parts": [f"[ツール実行: {fc.name}]"]})
                self._dispatch(fc.name, dict(fc.args) if fc.args else {})
        elif lead:
            self.history.append({"role": "model", "parts": [lead]})
        elif not lead:
            self._emit("on_text", "(応答がありませんでした。もう一度お試しください)")

    # ── ツールディスパッチ ──
    def _dispatch(self, name: str, args: dict):
        if name in ("start_pipeline", "start_with_keyword", "start_from_url"):
            self._run_generation(name, args)
        elif name == "analyze_trends":
            self._run_trends()
        elif name == "db_read_history":
            self._read_history()
        elif name == "db_add_search_intent":
            self._add_intent(args)
        elif name == "save_memory":
            self._save_memory(args)
        elif name == "stop_process":
            if self.stop_event:
                self.stop_event.set()
                self._emit("on_text", "⏹ 停止をリクエストしました。")
            else:
                self._emit("on_text", "実行中の処理はありません。")
        else:
            self._emit("on_text", f"（「{name}」はこのバージョンでは未対応です）")

    # ── 生成（core） ──
    def _run_generation(self, name: str, args: dict):
        if self.running:
            self._emit("on_text", "⚠️ すでに生成を実行中です。完了までお待ちください。")
            return
        lic = None
        try:
            lic = self.get_license() if callable(self.get_license) else self.get_license
        except Exception:
            lic = None
        is_demo = (lic is None or getattr(lic, "is_demo", True))

        if is_demo and credits_load() < COST_VIDEO:
            self._emit("on_text",
                       f"クレジットが不足しています（動画生成には {COST_VIDEO} 必要 / 現在 {credits_load()}）。"
                       "毎時1回復、または設定のプロモコードで追加できます。")
            return
        if is_demo:
            credits_save(credits_load() - COST_VIDEO)

        url = (args.get("url") or "").strip()
        if name == "start_from_url" and not url:
            if is_demo:
                credits_add(COST_VIDEO)
            self._emit("on_text", "URLが取得できませんでした。もう一度URLを教えてください。")
            return

        self.running = True
        self.stop_event = threading.Event()
        pid = "prog_" + str(int(time.time() * 1000))
        self._emit("on_progress_start", pid, "動画をつくっています")

        from pipeline import run_pipeline, run_pipeline_from_url
        config = {**self.config,
                  "work_dir": str(Path.home() / "TomatoClip_Output"),
                  "demo_mode": is_demo}
        if name == "start_with_keyword":
            kw = (args.get("keyword") or "").strip()
            config["search_keywords"] = kw
            config["force_keyword"] = kw

        produced = {"n": 0, "last": None}

        def log(msg):
            self._emit("on_progress", pid, str(msg))

        def on_ready(path, analysis=None, *a, **k):
            produced["n"] += 1
            produced["last"] = (path, analysis or {})

        try:
            if name == "start_from_url":
                run_pipeline_from_url(url=url, config=config, log=log,
                                      on_video_ready=on_ready, stop_event=self.stop_event,
                                      confirm_upload=lambda *a, **k: False)
            else:
                run_pipeline(config=config, log=log, on_video_ready=on_ready,
                             stop_event=self.stop_event, confirm_upload=lambda *a, **k: False)
        except Exception as e:
            import traceback; traceback.print_exc()
            log(f"❌ エラー: {e}")
        finally:
            self.running = False
            if produced["n"] == 0:
                if is_demo:
                    credits_add(COST_VIDEO)
                self._emit("on_progress_done", pid, "完成しませんでした")
                self._emit("on_text",
                           "動画が生成できませんでした（対象が見つからない・途中でエラー等）。"
                           + ("消費したクレジットは返却しました。" if is_demo else ""))
            else:
                self._emit("on_progress_done", pid, "完成しました 🎉")
                path, analysis = produced["last"]
                # id = 出力ファイル名 output_<YouTube動画ID>.mp4 から復元。
                # エディタの台本タブ(get_transcript)が字幕取得に使う。
                _stem = Path(path or "").stem
                self._emit("on_video", {
                    "path": path,
                    "id": _stem[7:] if _stem.startswith("output_") else "",
                    "title": analysis.get("title", "完成した動画"),
                    "subtitle": analysis.get("subtitle", ""),
                })

    # ── トレンド分析 ──
    def _run_trends(self):
        lic = None
        try:
            lic = self.get_license() if callable(self.get_license) else self.get_license
        except Exception:
            lic = None
        is_demo = (lic is None or getattr(lic, "is_demo", True))
        if is_demo and credits_load() < COST_TREND:
            self._emit("on_text", f"クレジットが不足しています（トレンド分析には {COST_TREND} 必要）。")
            return
        if not self.config.get("youtube_key"):
            self._emit("on_text", "トレンド分析には YouTube Data API キーが必要です。設定から登録してください。")
            return
        if is_demo:
            credits_save(credits_load() - COST_TREND)
        pid = "trend_" + str(int(time.time() * 1000))
        self._emit("on_progress_start", pid, "トレンドを分析中")
        try:
            from pipeline import analyze_trends
            config = {**self.config, "work_dir": str(Path.home() / "TomatoClip_Output")}
            result = analyze_trends(config, lambda m: self._emit("on_progress", pid, str(m)))
            self._emit("on_progress_done", pid, "分析完了 📊")
            summary = (result or {}).get("summary") or "トレンド分析が完了しました。"
            self._emit("on_text", summary)
        except Exception as e:
            if is_demo:
                credits_add(COST_TREND)
            self._emit("on_error", f"トレンド分析に失敗しました: {e}")

    # ── DB ──
    def _read_history(self):
        try:
            import db
            vids = db.get_videos(20)
            if not vids:
                self._emit("on_text", "まだ生成した動画はありません。")
                return
            lines = ["これまでに生成した動画です："]
            for v in vids:
                lines.append(f"・{v.get('title','(無題)')}")
            self._emit("on_text", "\n".join(lines))
        except Exception as e:
            self._emit("on_error", f"履歴の取得に失敗しました: {e}")

    def _add_intent(self, args):
        try:
            import db
            val = (args.get("value") or "").strip()
            cat = (args.get("category") or "custom").strip()
            if not val:
                self._emit("on_text", "検索対象が取得できませんでした。")
                return
            db.add_search_intent(category=cat, value=val)
            self._emit("on_text", f"✅ 「{val}」を検索対象に登録しました。次の生成から反映されます。")
        except Exception as e:
            self._emit("on_error", f"登録に失敗しました: {e}")

    def _save_memory(self, args):
        content = (args.get("content") or "").strip()
        if not content:
            self._emit("on_text", "覚える内容が取得できませんでした。")
            return
        try:
            import memory_engine
            if hasattr(memory_engine, "save_memory"):
                memory_engine.save_memory(content)
            elif hasattr(memory_engine, "add_memory"):
                memory_engine.add_memory(content)
        except Exception:
            pass
        self._emit("on_text", f"✅ 覚えました：{content}")
