"""
make_dist.py
ビルド後に配布用 ZIP（Setup.exe + README.txt のみ）を自動生成するスクリプト
実行: python make_dist.py
"""
import zipfile, sys
from pathlib import Path

HERE     = Path(__file__).parent
SETUP    = HERE / "dist" / "Setup.exe"
README   = HERE / "README.txt"
OUT_ZIP  = HERE / "Tomato_Clip.zip"

def main():
    print("=" * 50)
    print("  Tomato Clip — 配布 ZIP 作成")
    print("=" * 50)

    errors = []
    if not SETUP.exists():
        errors.append(f"❌ {SETUP} が見つかりません。先に python build_exe.py --installer を実行してください。")
    if not README.exists():
        errors.append(f"❌ {README} が見つかりません。")

    if errors:
        for e in errors:
            print(e)
        sys.exit(1)

    with zipfile.ZipFile(OUT_ZIP, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(SETUP,  "Setup.exe")
        z.write(README, "README.txt")

    size_mb = OUT_ZIP.stat().st_size / 1024 / 1024
    print(f"\n✅ 配布 ZIP 完成: {OUT_ZIP}")
    print(f"   サイズ: {size_mb:.1f} MB")
    print(f"\n   内容:")
    print(f"     Setup.exe   ← インストーラー（ソースコード非公開）")
    print(f"     README.txt  ← ユーザー向け説明書")
    print(f"\n   ソースコードは含まれていません ✅")

if __name__ == "__main__":
    main()
