"""
voicevox.py
VOICEVOX API 連携モジュール
  - VOICEVOX エンジンをローカルで起動・管理
  - キャラクター（スピーカー）一覧取得・選択
  - テキスト → 音声ファイル生成
  - gTTS のフォールバックあり（VOICEVOX 未起動時）
  - GUI キャラ選択ウィジェット

VOICEVOX のインストール:
  https://voicevox.hiroshiba.jp/ からダウンロード
  起動するだけで localhost:50021 で API が動く
"""

import json, time, tempfile, subprocess, threading
from pathlib import Path
from typing import Callable
import urllib.request
import urllib.parse
from i18n import T

LOG_CB        = Callable[[str], None]
VOICEVOX_URL  = "http://localhost:50021"
DEFAULT_SPEAKER = 3   # ずんだもん（あまあま）

# よく使われるキャラクター一覧（起動前でも表示できるよう固定リスト）
PRESET_SPEAKERS = [
    {"id": 1,  "name": "四国めたん",     "style": "ノーマル"},
    {"id": 2,  "name": "四国めたん",     "style": "あまあま"},
    {"id": 3,  "name": "ずんだもん",     "style": "あまあま"},
    {"id": 4,  "name": "ずんだもん",     "style": "ノーマル"},
    {"id": 5,  "name": "ずんだもん",     "style": "セクシー"},
    {"id": 6,  "name": "ずんだもん",     "style": "ツンツン"},
    {"id": 8,  "name": "春日部つむぎ",   "style": "ノーマル"},
    {"id": 10, "name": "雨晴はう",       "style": "ノーマル"},
    {"id": 11, "name": "波音リツ",       "style": "ノーマル"},
    {"id": 13, "name": "玄野武宏",       "style": "ノーマル"},
    {"id": 14, "name": "白上虎太郎",     "style": "ふつう"},
    {"id": 16, "name": "青山龍星",       "style": "ノーマル"},
    {"id": 20, "name": "冥鳴ひまり",     "style": "ノーマル"},
    {"id": 23, "name": "もち子さん",     "style": "ノーマル"},
    {"id": 29, "name": "No.7",           "style": "ノーマル"},
    {"id": 42, "name": "スタイルベリー", "style": "ノーマル"},
]


# ════════════════════════════════════════════════════════
#  VOICEVOX エンジン管理
# ════════════════════════════════════════════════════════
def is_running() -> bool:
    """VOICEVOX エンジンが起動中か確認"""
    try:
        with urllib.request.urlopen(f"{VOICEVOX_URL}/version", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def try_launch(voicevox_exe_path: str = "", log: LOG_CB = print) -> bool:
    """
    VOICEVOX エンジンを自動起動する。
    voicevox_exe_path: VOICEVOX.exe のフルパス
    """
    if is_running():
        return True

    # よくあるインストール場所を自動探索
    candidates = [
        voicevox_exe_path,
        r"C:\Program Files\VOICEVOX\VOICEVOX.exe",
        r"C:\Users\Public\VOICEVOX\VOICEVOX.exe",
        str(Path.home() / "AppData" / "Local" / "Programs" / "VOICEVOX" / "VOICEVOX.exe"),
        str(Path.home() / "Desktop" / "VOICEVOX" / "VOICEVOX.exe"),
    ]

    for path in candidates:
        if path and Path(path).exists():
            log(f"🎙️ VOICEVOX を起動中: {path}")
            subprocess.Popen([path], creationflags=subprocess.CREATE_NO_WINDOW
                             if hasattr(subprocess, "CREATE_NO_WINDOW") else 0)
            # 起動待ち（最大15秒）
            for _ in range(15):
                time.sleep(1)
                if is_running():
                    log("✅ VOICEVOX 起動完了")
                    return True
            log("⚠️ VOICEVOX 起動タイムアウト")
            return False

    log("⚠️ VOICEVOX が見つかりません → gTTS にフォールバック")
    return False


def get_speakers() -> list[dict]:
    """
    VOICEVOX から利用可能なスピーカー一覧を取得。
    未起動時はプリセット一覧を返す。
    """
    try:
        with urllib.request.urlopen(f"{VOICEVOX_URL}/speakers", timeout=3) as r:
            data  = json.loads(r.read())
            result = []
            for speaker in data:
                for style in speaker.get("styles", []):
                    result.append({
                        "id":    style["id"],
                        "name":  speaker["name"],
                        "style": style["name"],
                    })
            return result
    except Exception:
        return PRESET_SPEAKERS


# ════════════════════════════════════════════════════════
#  音声生成
# ════════════════════════════════════════════════════════
def synthesize(text: str, speaker_id: int = DEFAULT_SPEAKER,
               speed: float = 1.1, pitch: float = 0.0,
               log: LOG_CB = print, lang: str = "ja") -> str | None:
    """
    VOICEVOX でテキストを音声合成してファイルパスを返す。
    失敗時は gTTS にフォールバック。
    lang != "ja" の場合、VOICEVOXは日本語しか話せないため最初からgTTSを使う。
    """
    if not text.strip():
        return None

    # VOICEVOX（日本語のみ対応）
    if lang == "ja" and is_running():
        try:
            return _voicevox_synthesize(text, speaker_id, speed, pitch)
        except Exception as e:
            log(f"⚠️ VOICEVOX 合成失敗: {e} → gTTS にフォールバック")

    # gTTS フォールバック（多言語対応）
    return _gtts_fallback(text, log, lang)


def _voicevox_synthesize(text: str, speaker_id: int,
                          speed: float, pitch: float) -> str:
    """VOICEVOX API で音声合成"""
    # Step 1: audio_query（テキスト → クエリ生成）
    params = urllib.parse.urlencode({"text": text, "speaker": speaker_id})
    req    = urllib.request.Request(
        f"{VOICEVOX_URL}/audio_query?{params}",
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        query = json.loads(r.read())

    # パラメータ調整
    query["speedScale"] = speed
    query["pitchScale"] = pitch
    query["intonationScale"] = 1.1
    query["volumeScale"]     = 1.0

    # Step 2: synthesis（クエリ → WAV）
    params2 = urllib.parse.urlencode({"speaker": speaker_id})
    body    = json.dumps(query).encode("utf-8")
    req2    = urllib.request.Request(
        f"{VOICEVOX_URL}/synthesis?{params2}",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req2, timeout=30) as r:
        wav_data = r.read()

    # WAV を一時ファイルに保存
    out = tempfile.mktemp(suffix=".wav")
    with open(out, "wb") as f:
        f.write(wav_data)
    return out


_GTTS_TLD = {"pt": "com.br"}  # ポルトガル語はブラジル訛りの音声を使う（他は既定の "com"）


def _gtts_fallback(text: str, log: LOG_CB = print, lang: str = "ja") -> str | None:
    """gTTS フォールバック"""
    try:
        from gtts import gTTS
        out = tempfile.mktemp(suffix=".mp3")
        gTTS(text=text, lang=lang, tld=_GTTS_TLD.get(lang, "com"), slow=False).save(out)
        log(f"🔊 gTTS でナレーション生成（{lang}）")
        return out
    except Exception as e:
        log(f"❌ gTTS も失敗: {e}")
        return None


# ════════════════════════════════════════════════════════
#  GUI キャラ選択ウィジェット（設定タブ用）
# ════════════════════════════════════════════════════════
def build_voicevox_settings(parent, config: dict, on_change: Callable = None):
    """
    VOICEVOX 設定UIを構築。
    config に "voicevox_speaker" / "voicevox_speed" / "voicevox_path" を保存。
    """
    import tkinter as tk
    from tkinter import ttk, filedialog

    BG     = "#0a0a12"
    PANEL  = "#12121e"
    PANEL2 = "#1a1a2e"
    ACCENT = "#6c63ff"
    TEXT   = "#e0e0f0"
    MUTED  = "#55556a"
    GREEN  = "#4cffb0"
    WARN   = "#ffcc44"
    FN     = ("Segoe UI", 10)
    FNB    = ("Segoe UI", 10, "bold")

    # ── ステータス
    status_var = tk.StringVar()
    def _check_status():
        if is_running():
            status_var.set("🟢 VOICEVOX 起動中")
        else:
            status_var.set("🔴 VOICEVOX 未起動")

    _check_status()

    card = tk.Frame(parent, bg=PANEL, padx=16, pady=14)
    card.pack(fill="x", pady=(0, 10))

    tk.Label(card, textvariable=status_var, bg=PANEL,
             fg=GREEN, font=FNB).pack(anchor="w")
    tk.Label(card, text=T("VOICEVOX を別途インストール・起動してください"),
             bg=PANEL, fg=MUTED, font=FN).pack(anchor="w")

    row_btn = tk.Frame(card, bg=PANEL); row_btn.pack(anchor="w", pady=(8,0))
    tk.Button(row_btn, text=T("🔄 状態を更新"), command=_check_status,
              bg=PANEL2, fg=TEXT, relief="flat", font=FN, padx=10).pack(side="left")
    tk.Button(row_btn, text=T("🌐 公式サイト"),
              command=lambda: __import__("webbrowser").open("https://voicevox.hiroshiba.jp/"),
              bg=PANEL2, fg=ACCENT, relief="flat", font=FN, padx=10).pack(side="left", padx=6)

    # ── VOICEVOX.exe パス
    tk.Label(parent, text=T("VOICEVOX.exe のパス（自動起動用・任意）"),
             bg=BG, fg=MUTED, font=FN).pack(anchor="w", pady=(10, 2))
    path_var = tk.StringVar(value=config.get("voicevox_path", ""))
    row_p = tk.Frame(parent, bg=BG); row_p.pack(fill="x")
    tk.Entry(row_p, textvariable=path_var, bg=PANEL2, fg=TEXT,
             insertbackground=TEXT, relief="flat", font=FN).pack(
        side="left", fill="x", expand=True, ipady=6)
    tk.Button(row_p, text=T("参照"),
              command=lambda: path_var.set(
                  filedialog.askopenfilename(filetypes=[("exe","*.exe"),("all","*.*")])),
              bg=ACCENT, fg="white", relief="flat", font=FN, padx=8).pack(side="left", padx=4)

    # ── キャラ選択
    tk.Label(parent, text=T("🎭 キャラクター（スピーカー）"),
             bg=BG, fg=TEXT, font=FNB).pack(anchor="w", pady=(14, 4))

    speakers   = get_speakers()
    spk_names  = [f"{s['name']} — {s['style']}  (ID:{s['id']})" for s in speakers]
    current_id = config.get("voicevox_speaker", DEFAULT_SPEAKER)
    current_idx = next((i for i, s in enumerate(speakers) if s["id"] == current_id), 0)

    spk_var = tk.StringVar()
    spk_box = ttk.Combobox(parent, textvariable=spk_var,
                            values=spk_names, state="readonly", width=44)
    spk_box.pack(anchor="w", pady=(0, 4))
    if spk_names:
        spk_box.current(current_idx)

    def _on_spk_change(*_):
        idx = spk_box.current()
        if 0 <= idx < len(speakers):
            config["voicevox_speaker"] = speakers[idx]["id"]
            if on_change: on_change()
    spk_box.bind("<<ComboboxSelected>>", _on_spk_change)

    # キャラ一覧を再取得ボタン
    def _reload_speakers():
        nonlocal speakers, spk_names
        speakers  = get_speakers()
        spk_names = [f"{s['name']} — {s['style']}  (ID:{s['id']})" for s in speakers]
        spk_box["values"] = spk_names
        _check_status()

    tk.Button(parent, text=T("🔄 キャラ一覧を再取得"),
              command=_reload_speakers,
              bg=PANEL2, fg=TEXT, relief="flat", font=FN, padx=10).pack(anchor="w")

    # ── 話速・ピッチ
    tk.Label(parent, text=T("🎚 話速"), bg=BG, fg=MUTED, font=FN).pack(anchor="w", pady=(12,2))
    speed_var = tk.DoubleVar(value=config.get("voicevox_speed", 1.1))
    speed_row = tk.Frame(parent, bg=BG); speed_row.pack(anchor="w", fill="x")
    tk.Scale(speed_row, from_=0.5, to=2.0, resolution=0.05,
             variable=speed_var, orient="horizontal",
             bg=BG, fg=TEXT, highlightthickness=0,
             troughcolor=PANEL, length=260).pack(side="left")
    tk.Label(speed_row, textvariable=speed_var, bg=BG, fg=TEXT, font=FN, width=4).pack(side="left")

    tk.Label(parent, text=T("🎚 ピッチ"), bg=BG, fg=MUTED, font=FN).pack(anchor="w", pady=(8,2))
    pitch_var = tk.DoubleVar(value=config.get("voicevox_pitch", 0.0))
    pitch_row = tk.Frame(parent, bg=BG); pitch_row.pack(anchor="w", fill="x")
    tk.Scale(pitch_row, from_=-0.15, to=0.15, resolution=0.01,
             variable=pitch_var, orient="horizontal",
             bg=BG, fg=TEXT, highlightthickness=0,
             troughcolor=PANEL, length=260).pack(side="left")
    tk.Label(pitch_row, textvariable=pitch_var, bg=BG, fg=TEXT, font=FN, width=5).pack(side="left")

    # ── 試聴ボタン
    def _preview():
        spk_id = config.get("voicevox_speaker", DEFAULT_SPEAKER)
        speed  = speed_var.get()
        pitch  = pitch_var.get()
        config["voicevox_speed"] = speed
        config["voicevox_pitch"] = pitch
        config["voicevox_path"]  = path_var.get()
        if on_change: on_change()

        def _play():
            path = synthesize("こんにちは！Tomato Clipのナレーションです！",
                               speaker_id=spk_id, speed=speed, pitch=pitch)
            if path:
                try:
                    if __import__("sys").platform == "win32":
                        import winsound
                        winsound.PlaySound(path, winsound.SND_FILENAME)
                    else:
                        __import__("os").system(f"afplay '{path}' &")
                except Exception:
                    pass
        __import__("threading").Thread(target=_play, daemon=True).start()

    tk.Button(parent, text=T("▶ 試聴"), command=_preview,
              bg=ACCENT, fg="white", relief="flat",
              font=FNB, padx=20, pady=6).pack(anchor="w", pady=10)

    # ── 保存
    def _save():
        config["voicevox_speaker"] = speakers[spk_box.current()]["id"] if speakers else DEFAULT_SPEAKER
        config["voicevox_speed"]   = speed_var.get()
        config["voicevox_pitch"]   = pitch_var.get()
        config["voicevox_path"]    = path_var.get()
        if on_change: on_change()
    spk_box.bind("<<ComboboxSelected>>", lambda e: (_on_spk_change(), _save()))
    speed_var.trace_add("write", lambda *_: _save())
    pitch_var.trace_add("write", lambda *_: _save())
    path_var.trace_add("write",  lambda *_: _save())
