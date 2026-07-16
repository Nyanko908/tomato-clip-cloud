# -*- coding: utf-8 -*-
"""cloud_setup.py — Tomato Clip クラウド版 セットアップ（矢印キー＋Enter の対話TUI）。

アプリの「☁ クラウド」タブの「今すぐセットアップ」から起動される。新しいコンソール画面で
矢印キーと Enter だけで進められる。まず「ようこそ」＋説明ページ（Enter で次へ）を表示し、
そのあとデスクトップ設定を同期してクラウド用の設定バンドルを発行する。

言語はアプリの表示言語に追従する（--lang ja / en …。無指定なら ~/.tomato_clip_config.json の ui_lang）。

単体でも実行可:  python cloud_setup.py --lang ja
"""
import os
import sys
import json
from pathlib import Path

CONFIG_PATH = Path.home() / ".tomato_clip_config.json"


# ─────────────────────────── 端末制御 ───────────────────────────
def enable_ansi():
    """Windows コンソールで ANSI エスケープを有効化。"""
    if os.name == "nt":
        try:
            import ctypes
            k = ctypes.windll.kernel32
            h = k.GetStdHandle(-11)
            mode = ctypes.c_uint()
            k.GetConsoleMode(h, ctypes.byref(mode))
            k.SetConsoleMode(h, mode.value | 0x0004)  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
        except Exception:
            pass


class A:  # ANSI
    CLR = "\033[2J\033[3J\033[H"
    HIDE = "\033[?25l"; SHOW = "\033[?25h"
    R = "\033[0m"; B = "\033[1m"; DIM = "\033[2m"
    TOM = "\033[38;5;203m"; GRN = "\033[92m"; CYN = "\033[96m"; YEL = "\033[93m"; RED = "\033[91m"
    BG = "\033[48;5;236m"
    BTN = "\033[48;5;203m\033[97m"  # トマト背景＋白文字（ボタン風）


def read_key():
    """1キー読み取り。'up'/'down'/'left'/'right'/'enter'/'esc'/'q'/文字 を返す。"""
    if os.name == "nt":
        import msvcrt
        ch = msvcrt.getch()
        if ch in (b"\x00", b"\xe0"):
            code = msvcrt.getch()
            return {b"H": "up", b"P": "down", b"K": "left", b"M": "right"}.get(code, "")
        if ch in (b"\r", b"\n"):
            return "enter"
        if ch == b"\x1b":
            return "esc"
        if ch == b"\x03":
            raise KeyboardInterrupt
        try:
            return ch.decode("utf-8", "ignore").lower()
        except Exception:
            return ""
    else:
        import termios, tty
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            c = sys.stdin.read(1)
            if c == "\x1b":
                seq = sys.stdin.read(2)
                return {"[A": "up", "[B": "down", "[C": "right", "[D": "left"}.get(seq, "esc")
            if c in ("\r", "\n"):
                return "enter"
            if c == "\x03":
                raise KeyboardInterrupt
            return c.lower()
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)


def clear():
    sys.stdout.write(A.CLR); sys.stdout.flush()


# ─────────────────────────── 多言語 ───────────────────────────
# 説明ページ等。ja/en を用意し、他言語は en にフォールバック。
STRINGS = {
    "ja": {
        "title": "Tomato Clip Cloud セットアップ",
        "hint_next": "Enter で次へ  ·  Esc で終了",
        "hint_select": "↑↓ で選択  ·  Enter で決定  ·  Esc で戻る",
        "page_dot": "ページ",
        "next_btn": "次へ  ▶",
        "welcome_title": "Tomato Clip Cloud セットアップへようこそ！",
        "welcome_lines": [
            "これから、あなた専用のクラウドをセットアップします。",
            "PCを閉じても、動画生成と Discord ボットが 24 時間動くようになります。",
            "",
            "・スマホや外出先からでも動画を作れます。",
            "・Discord の @TomatoClip に話しかけるだけで生成 → YouTube に投稿。",
            "・あなたのサーバーで動くので、料金も設定もぜんぶあなたのもの。",
            "",
            "用意するもの：デプロイ先のアカウント（Render / Railway / Fly / Replit）。",
            "所要時間は約5分。このPCのアプリ設定は自動で読み込みます。",
            "",
            "操作は Enter で次へ進むだけ。むずかしい設定はありません。",
        ],
        "agree_title": "同意しますか？",
        "agree_lines": [
            "このセットアップは、あなたの APIキー・YouTube/Discord のトークンを",
            "暗号化して、あなた自身のサーバーへ移送します。",
            "",
            "・合言葉（暗号化キー）と設定はあなたの責任で管理してください。",
            "・生成・投稿・API利用の費用は、あなたのサーバー／アカウントの負担です。",
            "・他人のコンテンツの取り扱いは各サービスの規約に従ってください。",
        ],
        "agree_q": "上記に同意して続けますか？",
        "sync_title": "このPCの設定を読み込みました",
        "have": "あり", "none": "—",
        "s_gemini": "Gemini APIキー", "s_youtube": "YouTube APIキー",
        "s_token": "YouTube 自動投稿トークン", "s_discord": "Discord ボットトークン",
        "s_channel": "チャンネルID",
        "no_gemini_warn": "⚠ Gemini APIキーが未設定です。先にアプリで設定してください。",
        "ask_continue": "続けますか？",
        "yes": "はい", "no": "いいえ",
        "packaging": "設定をパッケージ化しています…",
        "done_title": "セットアップの準備ができました！",
        "your_secrets": "この 2 つをサーバーの環境変数（Secrets）に貼ってください：",
        "saved_to": "控えを保存しました",
        "deploy_steps_title": "デプロイ手順",
        "deploy_steps": [
            "デプロイ先（Render/Railway/Fly/Replit）にこのフォルダを接続",
            "Secrets に TOMATO_BUNDLE と TOMATO_BUNDLE_KEY を登録",
            "デプロイ（Dockerfile が自動で使われます）",
            "URL/healthz が {\"ok\":true} を返せば成功",
            "アプリの「☁ クラウド」タブに URL を入れて接続確認",
        ],
        "warn_secret": "この 2 つはパスワードと同じです。他人に渡さないでください。",
        "acc_saving": "設定をあなたのアカウントに保存しています…",
        "acc_done": "設定をあなたのアカウントに保存しました！",
        "acc_key_label": "サーバーに貼る鍵（これ1つだけ）",
        "acc_key_desc": "この1つをサーバーの環境変数に貼るだけ。設定は自動で引き継がれます。",
        "acc_not_login": "先にアプリで Google ログインしてください（左下のアカウント → ログイン）。",
        "acc_steps": [
            "デプロイ先（Render/Railway/Fly/Replit）にこのフォルダを接続",
            "Secrets に TOMATO_ACCOUNT_TOKEN を登録（上の鍵を貼る）",
            "デプロイ（Dockerfile が自動で使われます）",
            "URL/healthz が {\"ok\":true} を返せば成功。設定はアカウントから自動取得されます",
        ],
        "bye": "完了！ よいクラウド生活を 🍅  （このウィンドウは閉じてOKです）",
        "quit": "セットアップを中止しました。",
    },
    "en": {
        "title": "Tomato Clip Cloud Setup",
        "hint_next": "Enter to continue  ·  Esc to quit",
        "hint_select": "↑↓ to move  ·  Enter to select  ·  Esc to go back",
        "page_dot": "Page",
        "next_btn": "Next  ▶",
        "welcome_title": "Welcome to Tomato Clip Cloud Setup!",
        "welcome_lines": [
            "We'll set up your own private cloud.",
            "Your video generation and Discord bot will run 24/7, even with your PC off.",
            "",
            "- Make videos from your phone or on the go.",
            "- Just talk to @TomatoClip on Discord -> generate -> post to YouTube.",
            "- It runs on your server, so cost and settings are entirely yours.",
            "",
            "What you need: an account on a host (Render / Railway / Fly / Replit).",
            "About 5 minutes. Your app settings are loaded automatically.",
            "",
            "Just press Enter to continue. No hard configuration.",
        ],
        "agree_title": "Do you agree?",
        "agree_lines": [
            "This setup encrypts your API keys and YouTube/Discord tokens",
            "and transfers them to your own server.",
            "",
            "- You are responsible for keeping the passphrase and settings safe.",
            "- Generation, posting and API costs are on your own server/accounts.",
            "- Follow each service's terms for handling others' content.",
        ],
        "agree_q": "Do you agree and want to continue?",
        "sync_title": "Loaded settings from this PC",
        "have": "yes", "none": "-",
        "s_gemini": "Gemini API key", "s_youtube": "YouTube API key",
        "s_token": "YouTube upload token", "s_discord": "Discord bot token",
        "s_channel": "Channel ID",
        "no_gemini_warn": "! Gemini API key is not set. Please set it in the app first.",
        "ask_continue": "Continue?",
        "yes": "Yes", "no": "No",
        "packaging": "Packaging your settings...",
        "done_title": "Your setup is ready!",
        "your_secrets": "Paste these 2 into your server's environment variables (Secrets):",
        "saved_to": "A copy was saved to",
        "deploy_steps_title": "Deploy steps",
        "deploy_steps": [
            "Connect this folder to your host (Render/Railway/Fly/Replit)",
            "Add TOMATO_BUNDLE and TOMATO_BUNDLE_KEY to Secrets",
            "Deploy (the Dockerfile is used automatically)",
            "If URL/healthz returns {\"ok\":true}, you're set",
            "Enter the URL in the app's Cloud tab and test the connection",
        ],
        "warn_secret": "These 2 are like passwords. Never share them.",
        "acc_saving": "Saving your settings to your account…",
        "acc_done": "Your settings are saved to your account!",
        "acc_key_label": "The key to paste on your server (just this one)",
        "acc_key_desc": "Paste this one value into your server's env. Settings are pulled automatically.",
        "acc_not_login": "Please sign in with Google in the app first (bottom-left account -> Log in).",
        "acc_steps": [
            "Connect this folder to your host (Render/Railway/Fly/Replit)",
            "Add TOMATO_ACCOUNT_TOKEN to Secrets (paste the key above)",
            "Deploy (the Dockerfile is used automatically)",
            "If URL/healthz returns {\"ok\":true}, you're set. Settings load from your account.",
        ],
        "bye": "Done! Enjoy your cloud 🍅  (You can close this window.)",
        "quit": "Setup cancelled.",
    },
}


def get_lang():
    lang = ""
    if "--lang" in sys.argv:
        i = sys.argv.index("--lang")
        if i + 1 < len(sys.argv):
            lang = sys.argv[i + 1]
    lang = lang or os.environ.get("TOMATO_UI_LANG", "")
    if not lang:
        try:
            lang = json.loads(CONFIG_PATH.read_text(encoding="utf-8")).get("ui_lang", "en")
        except Exception:
            lang = "en"
    return lang if lang in STRINGS else "en"


# ─────────────────────────── 描画 ───────────────────────────
def header(S):
    w = 52
    print(A.TOM + A.B + "  ╭" + "─" * w + "╮")
    t = "🍅  " + S["title"]
    print("  │ " + t + " " * (w - len(t) + 1) + "│")
    print("  ╰" + "─" * w + "╯" + A.R + "\n")


def render_page(S, title, lines, hint, button=None):
    clear()
    header(S)
    print("  " + A.B + A.TOM + title + A.R + "\n")
    for ln in lines:
        print("    " + ln)
    if button:
        print("\n\n  " + A.BTN + "  " + button + "  " + A.R)
    print(("\n" if not button else "\n") + "  " + A.DIM + hint + A.R)


def welcome_flow(S):
    """ようこそ＋説明を1画面（Enterで次へ）→「同意しますか？」（はい/いいえ）。"""
    # 1) ようこそ＋説明
    while True:
        render_page(S, S["welcome_title"], S["welcome_lines"], S["hint_next"], button=S["next_btn"])
        k = read_key()
        if k in ("enter", "right", "down"):
            break
        if k in ("esc", "q"):
            return False
    # 2) 同意
    return agree_flow(S)


def agree_flow(S):
    """同意画面。説明を表示し、はい/いいえを ↑↓/Enter で選ぶ。"""
    sel = 0  # 0=はい
    opts = [S["yes"], S["no"]]
    while True:
        clear(); header(S)
        print("  " + A.B + A.TOM + S["agree_title"] + A.R + "\n")
        for ln in S["agree_lines"]:
            print("    " + ln)
        print("\n  " + A.B + S["agree_q"] + A.R + "\n")
        for i, o in enumerate(opts):
            if i == sel:
                print("    " + A.TOM + A.B + "❯ " + o + A.R)
            else:
                print("      " + A.DIM + o + A.R)
        print("\n  " + A.DIM + S["hint_select"] + A.R)
        k = read_key()
        if k in ("up", "down", "left", "right"):
            sel = 1 - sel
        elif k == "enter":
            return sel == 0
        elif k in ("esc", "q"):
            return False


def menu_yesno(S, question, default_yes=True):
    """↑↓/←→ で はい/いいえ を選び Enter。"""
    sel = 0 if default_yes else 1
    opts = [S["yes"], S["no"]]
    while True:
        clear(); header(S)
        print("  " + A.B + question + A.R + "\n")
        for i, o in enumerate(opts):
            if i == sel:
                print("    " + A.TOM + A.B + "❯ " + o + A.R)
            else:
                print("      " + A.DIM + o + A.R)
        print("\n  " + A.DIM + S["hint_select"] + A.R)
        k = read_key()
        if k in ("up", "down", "left", "right"):
            sel = 1 - sel
        elif k == "enter":
            return sel == 0
        elif k in ("esc", "q"):
            return default_yes


# ─────────────────────────── 本体 ───────────────────────────
def load_desktop_config() -> dict:
    try:
        if CONFIG_PATH.exists():
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def run_setup(S, cfg):
    """ようこその後の実処理：同期表示 → パッケージ化 → 結果表示。"""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    cred = cfg.get("credentials_path", "")
    yt_token = bool(cred and (Path(cred).parent / "yt_token.pickle").exists())

    # 同期内容の表示
    clear(); header(S)
    print("  " + A.B + A.GRN + S["sync_title"] + A.R + "\n")
    rows = [
        (S["s_gemini"], bool(cfg.get("gemini_key"))),
        (S["s_youtube"], bool(cfg.get("youtube_key"))),
        (S["s_token"], yt_token),
        (S["s_discord"], bool(cfg.get("discord_bot_token"))),
        (S["s_channel"], bool(cfg.get("my_channel_id"))),
    ]
    for label, ok in rows:
        mk = (A.GRN + "✓" + A.R) if ok else (A.DIM + "–" + A.R)
        val = (A.GRN + S["have"] + A.R) if ok else (A.DIM + S["none"] + A.R)
        print(f"    {mk}  {label:<28} {val}")
    if not cfg.get("gemini_key"):
        print("\n  " + A.YEL + S["no_gemini_warn"] + A.R)
    print("\n  " + A.DIM + S["hint_next"] + A.R)
    if read_key() in ("esc", "q"):
        return False

    # アカウント方式（推奨）：ログイン済みなら設定をアカウントに保存し、鍵1つを表示する
    try:
        import account
        logged_in = account.is_logged_in()
    except Exception:
        account = None
        logged_in = False

    if logged_in:
        clear(); header(S)
        print("  " + A.CYN + S["acc_saving"] + A.R + "\n")
        ok = False
        try:
            ok = account.push_settings(cfg)
            token = account.get_refresh_token()
        except Exception as e:
            print("  " + A.RED + f"Error: {e}" + A.R); read_key(); return False
        clear(); header(S)
        print("  " + A.B + A.GRN + S["acc_done"] + A.R + "\n")
        print("  " + S["acc_key_desc"] + "\n")
        print("  " + A.B + S["acc_key_label"] + A.R + "  " + A.DIM + "(TOMATO_ACCOUNT_TOKEN)" + A.R)
        print("  " + A.CYN + token + A.R + "\n")
        print("  " + A.YEL + S["warn_secret"] + A.R)
        print("\n  " + A.B + S["deploy_steps_title"] + A.R)
        for i, s in enumerate(S["acc_steps"], 1):
            print(f"    {A.TOM}{i}.{A.R} {s}")
        print("\n  " + A.DIM + S["hint_next"] + A.R)
        read_key()
        return True

    # 未ログイン → バンドル方式にフォールバック（手動 env 2個）
    clear(); header(S)
    print("  " + A.YEL + S["acc_not_login"] + A.R + "\n")
    print("  " + A.DIM + S["packaging"] + A.R + "\n")
    try:
        import cloud_bundle, secrets
        pw = secrets.token_urlsafe(12)
        bundle = cloud_bundle.make_bundle(cfg, pw,
                                          include_youtube_token=yt_token,
                                          include_discord=bool(cfg.get("discord_bot_token")))
    except Exception as e:
        print("  " + A.RED + f"Error: {e}" + A.R)
        read_key(); return False

    out = Path.home() / ".tomato_clip_cloud_bundle.txt"
    try:
        out.write_text(f"TOMATO_BUNDLE={bundle}\nTOMATO_BUNDLE_KEY={pw}\n", encoding="utf-8")
    except Exception:
        pass

    print("  " + A.B + "TOMATO_BUNDLE_KEY" + A.R + "  " + A.CYN + pw + A.R)
    print("  " + A.B + "TOMATO_BUNDLE" + A.R + "  " + A.DIM + bundle[:80] + " …(" + str(len(bundle)) + ")" + A.R)
    print("  " + A.DIM + f"{S['saved_to']}: {out}" + A.R)
    print("\n  " + A.B + S["deploy_steps_title"] + A.R)
    for i, s in enumerate(S["deploy_steps"], 1):
        print(f"    {A.TOM}{i}.{A.R} {s}")
    print("\n  " + A.DIM + S["hint_next"] + A.R)
    read_key()
    return True


def main():
    enable_ansi()
    S = STRINGS[get_lang()]
    sys.stdout.write(A.HIDE)
    try:
        cfg = load_desktop_config()
        if not welcome_flow(S):
            clear(); print("\n  " + S["quit"] + "\n"); return
        if not run_setup(S, cfg):
            clear(); print("\n  " + S["quit"] + "\n"); return
        clear()
        header(S)
        print("\n  " + A.GRN + A.B + S["bye"] + A.R + "\n")
    except KeyboardInterrupt:
        clear(); print("\n  " + S["quit"] + "\n")
    finally:
        sys.stdout.write(A.SHOW); sys.stdout.flush()


if __name__ == "__main__":
    main()
