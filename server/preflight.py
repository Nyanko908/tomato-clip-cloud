# -*- coding: utf-8 -*-
"""server/preflight.py — クラウド版のデプロイ後 自己診断。

デプロイ先のサーバーで `python -m server.preflight` を実行すると、
設定・鍵・ffmpeg・バンドル復号などが揃っているかを一覧で確認できる。
"""
import os
import sys
import shutil

from server import config as cloudcfg


def _mark(ok):
    return "\033[92m✓\033[0m" if ok else "\033[91m✕\033[0m"


def main():
    print("\n🍅 Tomato Clip — クラウド 自己診断 (preflight)\n" + "─" * 44)

    # バンドルの有無・復号
    has_bundle = bool(os.environ.get("TOMATO_BUNDLE") and os.environ.get("TOMATO_BUNDLE_KEY"))
    if os.environ.get("TOMATO_BUNDLE"):
        if os.environ.get("TOMATO_BUNDLE_KEY"):
            try:
                import cloud_bundle
                cloud_bundle.open_bundle(os.environ["TOMATO_BUNDLE"], os.environ["TOMATO_BUNDLE_KEY"])
                print(f"{_mark(True)} 設定バンドル（TOMATO_BUNDLE）: 復号OK")
            except Exception as e:
                print(f"{_mark(False)} 設定バンドルの復号に失敗: {e}")
        else:
            print(f"{_mark(False)} TOMATO_BUNDLE はあるが TOMATO_BUNDLE_KEY が未設定")
    else:
        print(f"{_mark(False)} 設定バンドルなし（個別 env で設定）")

    cfg = cloudcfg.load_config()

    checks = [
        ("Gemini APIキー", bool(cfg.get("gemini_key")), True),
        ("YouTube APIキー（統計/検索）", bool(cfg.get("youtube_key")), False),
        ("YouTube 投稿クレデンシャル", bool(cfg.get("credentials_path")), False),
        ("Discord ボットトークン", bool(cfg.get("discord_bot_token")
                                or os.environ.get("DISCORD_BOT_TOKEN")), False),
        ("チャンネルID", bool(cfg.get("my_channel_id")), False),
    ]
    print()
    all_required_ok = True
    for label, ok, required in checks:
        req = "（必須）" if required else "（任意）"
        print(f"{_mark(ok or not required)} {label} {req}: {'あり' if ok else '—'}")
        if required and not ok:
            all_required_ok = False

    # yt_token（無人投稿の可否）
    try:
        from pathlib import Path
        cp = cfg.get("credentials_path", "")
        tok = bool(cp and (Path(cp).parent / "yt_token.pickle").exists())
        print(f"{_mark(True)} YouTube 無人投稿トークン: {'あり（自動投稿可）' if tok else '—（投稿はスキップ）'}")
    except Exception:
        pass

    # ffmpeg
    ff = shutil.which("ffmpeg")
    try:
        import imageio_ffmpeg
        ff = ff or imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass
    print(f"{_mark(bool(ff))} ffmpeg: {ff or '見つかりません（動画編集に必要）'}")

    # HOME 書込み
    home = os.environ.get("HOME", "")
    writable = False
    try:
        from pathlib import Path
        p = Path(home or ".") / ".tomato_write_test"
        p.write_text("x"); p.unlink(); writable = True
    except Exception:
        pass
    print(f"{_mark(writable)} 書込み可能ディレクトリ (HOME={home or '?'}): {'OK' if writable else 'NG'}")

    print("─" * 44)
    if all_required_ok and ff:
        print("\033[92m準備OK！ `python -m server.app` で起動できます 🍅\033[0m\n")
        sys.exit(0)
    else:
        print("\033[93m未設定の必須項目があります。上の ✕ を確認してください。\033[0m\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
