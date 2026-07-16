# -*- coding: utf-8 -*-
"""brand_migrate.py — 旧ブランド(Tomato Shorts)のユーザーデータを新ブランド(Tomato Clip)へ移行。

改名（Tomato Shorts → Tomato Clip）で設定・データの保存先が
  ~/.tomato_shorts_config.json → ~/.tomato_clip_config.json
  ~/.tomato_shorts/（license.json, credits.json, data.db） → ~/.tomato_clip/
に変わった。既存ユーザーが設定・Proライセンス・クレジット・生成履歴を失わないよう、
旧パスが在って新パスが無いときだけ**コピー**する（旧データは念のため残す＝安全側）。

各エントリポイント（main.py / web_app.py / discord_bot.py）の最初、
ライセンスや設定を読む前に一度呼ぶこと。冪等（新パスが在れば何もしない）。
"""
import shutil
from pathlib import Path


def migrate_legacy_paths(log=lambda *a: None) -> bool:
    home = Path.home()
    migrated = False

    # 1) データディレクトリ（license / credits / DB）
    old_dir = home / ".tomato_shorts"
    new_dir = home / ".tomato_clip"
    if old_dir.is_dir() and not new_dir.exists():
        try:
            shutil.copytree(old_dir, new_dir)
            migrated = True
            log(f"[migrate] {old_dir} → {new_dir}")
        except Exception as e:
            log(f"[migrate] データ移行に失敗: {e}")

    # 2) 単一ファイル（設定 / 永続メモリ）
    for old_name, new_name in [
        (".tomato_shorts_config.json", ".tomato_clip_config.json"),
        (".tomato_shorts_memory.json", ".tomato_clip_memory.json"),
    ]:
        old_p, new_p = home / old_name, home / new_name
        if old_p.is_file() and not new_p.exists():
            try:
                shutil.copy2(old_p, new_p)
                migrated = True
                log(f"[migrate] {old_p} → {new_p}")
            except Exception as e:
                log(f"[migrate] {old_name} の移行に失敗: {e}")

    # 3) BOOTH自動化のブラウザプロファイル（ログインセッションを引き継ぐ）
    old_prof = home / ".tomato_shorts_automation_profile"
    new_prof = home / ".tomato_clip_automation_profile"
    if old_prof.is_dir() and not new_prof.exists():
        try:
            shutil.copytree(old_prof, new_prof)
            migrated = True
            log(f"[migrate] {old_prof} → {new_prof}")
        except Exception as e:
            log(f"[migrate] 自動化プロファイルの移行に失敗: {e}")

    return migrated


if __name__ == "__main__":
    print("migrated" if migrate_legacy_paths(print) else "nothing to migrate")
