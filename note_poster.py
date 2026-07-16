"""
note_poster.py
note への自動投稿（Selenium）
+ 週次レポートの自動生成・投稿
"""

import time, json, tempfile
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Callable
import db

JST    = timezone(timedelta(hours=9))
LOG_CB = Callable[[str], None]
SLEEP  = 20


# ════════════════════════════════════════════════════════
#  Selenium で note に自動投稿
# ════════════════════════════════════════════════════════
class NotePoster:
    def __init__(self, email: str, password: str, log: LOG_CB):
        self.email    = email
        self.password = password
        self.log      = log
        self._driver  = None

    def _init_driver(self):
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
            from selenium.webdriver.chrome.service import Service
            opts = Options()
            opts.add_argument("--no-sandbox")
            opts.add_argument("--disable-dev-shm-usage")
            # opts.add_argument("--headless")  # 作業風景を見たいのでオフ
            self._driver = webdriver.Chrome(options=opts)
            self.log("🌐 Chrome 起動完了")
            return True
        except ImportError:
            self.log("⚠️ selenium 未インストール → pip install selenium")
            return False
        except Exception as e:
            self.log(f"❌ Chrome 起動失敗: {e}\n   ChromeDriver が PATH にあるか確認してください")
            return False

    def login(self) -> bool:
        """note にログイン"""
        if not self._init_driver():
            return False
        try:
            from selenium.webdriver.common.by import By
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.webdriver.support import expected_conditions as EC

            self.log("🔑 note ログイン中...")
            self._driver.get("https://note.com/login")
            time.sleep(3)

            wait = WebDriverWait(self._driver, 15)

            # メールアドレス入力
            email_el = wait.until(EC.presence_of_element_located(
                (By.CSS_SELECTOR, "input[type='email'], input[name='email']")))
            email_el.clear()
            email_el.send_keys(self.email)
            time.sleep(1)

            # パスワード入力
            pw_el = self._driver.find_element(
                By.CSS_SELECTOR, "input[type='password'], input[name='password']")
            pw_el.clear()
            pw_el.send_keys(self.password)
            time.sleep(1)

            # ログインボタン
            login_btn = self._driver.find_element(
                By.CSS_SELECTOR, "button[type='submit'], .o-loginButton")
            login_btn.click()
            time.sleep(4)

            if "login" not in self._driver.current_url:
                self.log("✅ note ログイン成功")
                return True
            else:
                self.log("❌ note ログイン失敗（メール・パスワードを確認）")
                return False
        except Exception as e:
            self.log(f"❌ ログインエラー: {e}")
            return False

    def post_article(self, title: str, body: str,
                     tags: list[str] = None, publish: bool = True) -> str | None:
        """
        note に記事を投稿する。
        戻り値: 投稿URLまたはNone
        """
        if not self._driver:
            if not self.login():
                return None

        try:
            from selenium.webdriver.common.by import By
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.webdriver.support import expected_conditions as EC
            from selenium.webdriver.common.keys import Keys

            self.log("📝 note 新規記事作成中...")
            self._driver.get("https://note.com/notes/new")
            time.sleep(SLEEP)

            wait = WebDriverWait(self._driver, 20)

            # タイトル入力
            self.log("  ✏️  タイトル入力...")
            title_el = wait.until(EC.presence_of_element_located(
                (By.CSS_SELECTOR, ".p-textInput__title, [placeholder*='タイトル'], h1[contenteditable]")))
            title_el.click()
            title_el.send_keys(title)
            time.sleep(2)

            # 本文入力
            self.log("  📄 本文入力中...")
            body_el = self._driver.find_element(
                By.CSS_SELECTOR, ".ProseMirror, [contenteditable='true'].o-noteBodyContainer, .note-editor")
            body_el.click()
            # 長文は少しずつ入力（貼り付け）
            body_el.send_keys(Keys.CONTROL, "a")
            time.sleep(0.5)
            # JavaScript で値を設定（より確実）
            self._driver.execute_script(
                "arguments[0].innerText = arguments[1];", body_el, body)
            time.sleep(2)

            # タグ追加
            if tags:
                self.log("  🏷️  タグ追加中...")
                time.sleep(SLEEP)
                try:
                    tag_input = self._driver.find_element(
                        By.CSS_SELECTOR, "[placeholder*='タグ'], .p-tagInput input")
                    for tag in tags[:5]:
                        tag_input.send_keys(tag)
                        tag_input.send_keys(Keys.ENTER)
                        time.sleep(1)
                except Exception:
                    self.log("  ⚠️  タグ入力スキップ")

            if not publish:
                self.log("  💾 下書き保存（公開しない）")
                try:
                    draft_btn = self._driver.find_element(
                        By.CSS_SELECTOR, "[aria-label*='下書き'], button.p-draft")
                    draft_btn.click()
                except Exception:
                    pass
                time.sleep(2)
                return self._driver.current_url

            # 公開ボタン
            self.log("  🚀 公開処理中...")
            time.sleep(SLEEP)
            pub_btn = wait.until(EC.element_to_be_clickable(
                (By.CSS_SELECTOR, "button.p-publishButton, [data-testid='publish-button'], .o-notePublish")))
            pub_btn.click()
            time.sleep(3)

            # 公開確認ダイアログ
            try:
                confirm = wait.until(EC.element_to_be_clickable(
                    (By.CSS_SELECTOR, "button.p-publishConfirmButton, [data-testid='confirm-publish']")))
                confirm.click()
                time.sleep(4)
            except Exception:
                pass

            url = self._driver.current_url
            self.log(f"✅ note 投稿完了！ → {url}")
            return url

        except Exception as e:
            self.log(f"❌ note 投稿失敗: {e}")
            # スクリーンショット保存
            try:
                ss_path = Path.home() / "TomatoClip_Output" / "note_error.png"
                self._driver.save_screenshot(str(ss_path))
                self.log(f"   スクリーンショット: {ss_path}")
            except Exception:
                pass
            return None

    def close(self):
        if self._driver:
            try:
                self._driver.quit()
            except Exception:
                pass


# ════════════════════════════════════════════════════════
#  週次レポートを note に自動投稿
# ════════════════════════════════════════════════════════
def auto_post_weekly_report(gemini_key: str, note_email: str, note_password: str,
                             log: LOG_CB, publish: bool = True) -> str | None:
    """
    週次レポートを生成して note に自動投稿。
    スケジューラーから毎週月曜に呼ぶ。
    戻り値: 投稿URL or None
    """
    from weekly_report import generate_weekly_report, should_run_weekly

    # 今週まだ投稿していないかチェック
    state_path = Path.home() / ".tomato_clip" / "last_report.json"
    last_url   = ""
    if state_path.exists():
        try:
            state    = json.loads(state_path.read_text())
            last_url = state.get("url", "")
            if not should_run_weekly(state.get("path", "")):
                log("📝 今週のレポートは投稿済みです")
                return last_url
        except Exception:
            pass

    # レポート生成
    log("📝 週次レポート自動生成開始...")
    report_path = generate_weekly_report(gemini_key, log)

    # レポートテキスト読み込み
    try:
        report_text = Path(report_path).read_text(encoding="utf-8")
    except Exception as e:
        log(f"❌ レポートファイル読み込み失敗: {e}")
        return None

    # タイトル生成
    now   = datetime.now(JST)
    week  = now.isocalendar()[1]
    title = f"【第{week}週】TOMATO SHORTS 実績レポート — {now.strftime('%Y/%m/%d')}"

    tags = ["YouTube自動化", "ショート動画", "海外バズり", "副業", "TOMATO_SHORTS"]

    # note に投稿
    if not note_email or not note_password:
        log("⚠️ note のメール・パスワードが未設定")
        log(f"   レポートファイル: {report_path}")
        log("   手動でコピーして投稿してください")
        return None

    poster = NotePoster(note_email, note_password, log)
    url    = poster.post_article(title, report_text, tags, publish=publish)
    poster.close()

    # 状態保存
    if url:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps({
            "url":        url,
            "path":       report_path,
            "posted_at":  now.isoformat()
        }, ensure_ascii=False))

    return url
