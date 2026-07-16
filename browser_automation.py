# -*- coding: utf-8 -*-
"""
browser_automation.py
Google Cloud Console の「OAuthクライアントID(デスクトップアプリ)を作成する」手順を
ユーザー自身のPCにインストール済みのChrome/Edgeを使って自動操作する。

設計上の注意:
- Playwrightで新規にブラウザを起動する(chromium.launch())のではなく、
  --remote-debugging-port 付きでサブプロセス起動し、あとから connect_over_cdp()
  で接続する。これは Google が Selenium/Playwright の自動起動ブラウザ
  (--enable-automation フラグ)を検知してログインをブロックする既知の問題を
  避けるための対策。
- 専用の新規プロファイル(PROFILE_DIR)を使う。普段使いの本物のプロファイルは
  使わない。現在のChrome/Edgeは既定/実プロファイルに対する
  --remote-debugging-port を無視しCDPポートを一切listenしない(実機で確認済みの
  セキュリティ制限)ため、実プロファイルでは自動化そのものが機能しない。
  専用プロファイルは普段使いのブラウザとは別のuser-data-dirになるため同時起動
  でき、既存ブラウザを終了する必要もない。初回はGoogleログインが必要になるが、
  run_step_flow のログイン待機ロジック(login_url_markers/login_wait_label)が
  その状況を想定して実装されている。
- ここで自動化する操作は「新しい認証情報を作る」ことだけであり、既存の設定を
  変更・削除する操作は一切行わない。
"""

import os
import socket
import subprocess
import time
import urllib.request
from pathlib import Path
from typing import Callable, Optional

from gcp_console_steps import (
    BLOCK_SIGNATURES as _GCP_BLOCK_SIGNATURES,
    LOGIN_WAIT_LABEL as _GCP_LOGIN_WAIT_LABEL,
)

_GCP_LOGIN_URL_MARKERS = ["accounts.google.com"]

PROFILE_DIR = Path.home() / ".tomato_clip_automation_profile"

_CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
]


def find_installed_browser() -> Optional[str]:
    """PCにインストール済みのChrome/Edgeの実行ファイルパスを探す。見つからなければNone"""
    for path in _CHROME_CANDIDATES:
        if Path(path).exists():
            return path
    local_appdata = os.environ.get("LOCALAPPDATA", "")
    if local_appdata:
        candidate = Path(local_appdata) / "Google" / "Chrome" / "Application" / "chrome.exe"
        if candidate.exists():
            return str(candidate)
    return None


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def launch_debuggable_browser(port: int, profile_dir: Optional[Path] = None) -> Optional[subprocess.Popen]:
    """検出したブラウザを、リモートデバッグ有効で起動する。
    profile_dir未指定なら専用の新規プロファイル(PROFILE_DIR)を使う。

    【重要】以前は普段使いの本物のプロファイル(find_default_profile_dir)を優先して
    使っていたが、現在のChrome/Edgeは既定/実プロファイルに対する
    --remote-debugging-port を無視しセキュリティ上ブロックする(CDPポートが
    一切listenされない)ため、実プロファイルではこの自動化が機能しない。
    専用の新規プロファイルであれば --remote-debugging-port が正しく機能することを
    実機で確認済み。初回はGoogleログインが必要になるが、run_step_flow側の
    ログイン待機ロジック(login_url_markers/login_wait_label)が既にその状況を
    想定して実装されているため、追加対応は不要。"""
    exe = find_installed_browser()
    if not exe:
        return None
    if profile_dir is None:
        profile_dir = PROFILE_DIR
    profile_dir.mkdir(parents=True, exist_ok=True)
    return subprocess.Popen([
        exe,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
    ])


def _wait_for_cdp_ready(port: int, timeout_sec: float = 35.0) -> bool:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1)
            return True
        except Exception:
            time.sleep(0.5)
    return False


def run_step_flow(
    steps: list,
    lang: str,
    on_progress: Callable[[str], None] = lambda msg: None,
    on_need_manual_fallback: Callable[[str], None] = lambda reason: None,
    block_signatures: Optional[list] = None,
    login_url_markers: Optional[list] = None,
    login_wait_label: Optional[dict] = None,
) -> Optional[str]:
    """
    与えられたステップ定義(gcp_console_steps.py / booth_console_steps.py 等)に沿って
    ブラウザ自動操作を実行する汎用エンジン。
    戻り値: 最後にダウンロードされたファイルのパス。失敗/フォールバック時はNone
    (失敗理由は on_need_manual_fallback(reason) に文字列で渡される)

    block_signatures/login_url_markers/login_wait_label 未指定時は
    Google Cloud Console向けのデフォルト(後方互換)を使う
    """
    block_signatures = block_signatures if block_signatures is not None else _GCP_BLOCK_SIGNATURES
    login_url_markers = login_url_markers if login_url_markers is not None else _GCP_LOGIN_URL_MARKERS
    login_wait_label = login_wait_label if login_wait_label is not None else _GCP_LOGIN_WAIT_LABEL
    exe = find_installed_browser()
    if not exe:
        on_need_manual_fallback("no_browser")
        return None

    # 専用の新規プロファイル(PROFILE_DIR)を使うため、普段使いのブラウザとは
    # user-data-dirが別になり同時起動できる。既存ブラウザを終了する必要はない
    port = _free_port()
    proc = launch_debuggable_browser(port)
    if proc is None:
        on_need_manual_fallback("no_browser")
        return None

    try:
        if not _wait_for_cdp_ready(port):
            on_need_manual_fallback("browser_not_ready")
            return None

        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
            context = browser.contexts[0] if browser.contexts else browser.new_context()
            page = context.new_page()

            downloaded_path = None

            for step in steps:
                action = step["action"]
                label = step.get("label", {}).get(lang) or step.get("label", {}).get("en", "")
                if label:
                    on_progress(label)

                if action == "goto":
                    url = step["url"]
                    page.goto(url, timeout=30000)
                    page.wait_for_load_state("domcontentloaded", timeout=30000)

                    if any(marker in page.url for marker in login_url_markers):
                        on_progress(login_wait_label.get(lang, login_wait_label["en"]))
                        logged_in = False
                        for _ in range(300):  # 最大5分、ユーザーのログインを待つ
                            time.sleep(1)
                            if not any(marker in page.url for marker in login_url_markers):
                                logged_in = True
                                break
                        if not logged_in:
                            on_need_manual_fallback("login_timeout")
                            return None

                    page.wait_for_load_state("networkidle", timeout=30000)

                elif action == "click":
                    name = step.get("name", {}).get(lang) or step.get("name", {}).get("en")
                    page.get_by_role(step["role"], name=name).click(timeout=15000)

                elif action == "check":
                    # roleベースのget_by_roleでは検出できないチェックボックス向け
                    # (カスタムCSSで見た目上は隠れており、role=checkboxとしても
                    # 公開されない実装がある)。CSSセレクタで直接指定し、関連する
                    # <label for="..."> をクリックする(実ユーザーと同じ操作。
                    # JSでchecked=trueを直接設定してもフレームワークの状態と
                    # 同期せず反映されないことがあるため不可)
                    cb_id = page.locator(step["selector"]).get_attribute("id")
                    page.locator(f'label[for="{cb_id}"]').click(timeout=15000)

                elif action == "click_if_present":
                    # 状態によって出たり出なかったりする要素向け(例: 既に処理中のため
                    # ボタンがスキップされ別ページへ直接遷移するケース)。
                    # 見つからなくても失敗扱いにせず、そのまま次のステップに進む
                    name = step.get("name", {}).get(lang) or step.get("name", {}).get("en")
                    try:
                        loc = page.get_by_role(step["role"], name=name)
                        if loc.count() > 0 and loc.first.is_visible():
                            loc.first.click(timeout=step.get("timeout_ms", 5000))
                    except Exception:
                        pass

                elif action == "select_option":
                    name = step.get("name", {}).get(lang) or step.get("name", {}).get("en")
                    page.get_by_role(step["role"], name=name).click(timeout=15000)

                elif action == "fill":
                    page.get_by_role(step["role"]).first.fill(step["value"], timeout=15000)

                elif action == "click_and_download":
                    name = step.get("name", {}).get(lang) or step.get("name", {}).get("en")
                    with page.expect_download(timeout=30000) as dl_info:
                        page.get_by_role(step["role"], name=name).click(timeout=15000)
                    download = dl_info.value
                    dest = Path.home() / "Downloads" / download.suggested_filename
                    download.save_as(str(dest))
                    downloaded_path = str(dest)

                elif action == "wait_for_download_ready":
                    # 一覧ページを定期的に再読込し、ダウンロード可能なリンク(role=link, name指定)が
                    # 現れるまで待つ(CSV生成には時間がかかるため)。見つかったらそのままクリック&DL
                    name = step.get("name", {}).get(lang) or step.get("name", {}).get("en")
                    max_wait_sec = step.get("max_wait_sec", 120)
                    poll_sec = step.get("poll_sec", 5)
                    deadline = time.time() + max_wait_sec
                    found = False
                    while time.time() < deadline:
                        try:
                            locator = page.get_by_role(step["role"], name=name).first
                            if locator.count() > 0:
                                found = True
                                break
                        except Exception:
                            pass
                        time.sleep(poll_sec)
                        page.reload(timeout=30000)
                        page.wait_for_load_state("networkidle", timeout=30000)
                    if not found:
                        on_need_manual_fallback("download_not_ready")
                        return None
                    with page.expect_download(timeout=30000) as dl_info:
                        page.get_by_role(step["role"], name=name).first.click(timeout=15000)
                    download = dl_info.value
                    dest = Path.home() / "Downloads" / download.suggested_filename
                    download.save_as(str(dest))
                    downloaded_path = str(dest)

                time.sleep(0.5)
                try:
                    content = page.content()
                except Exception:
                    content = ""
                if any(sig in content for sig in block_signatures):
                    on_need_manual_fallback("blocked")
                    return None

            return downloaded_path

    except Exception as e:
        on_need_manual_fallback(f"error: {e}")
        return None
    finally:
        try:
            proc.terminate()
        except Exception:
            pass
