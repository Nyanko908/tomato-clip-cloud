"""
scheduler.py - 自動スケジューラー
・4時間おき（設定可）でパイプラインを自動実行
・YouTube 予約投稿と連動（次の投稿枠を自動計算）
・次回実行時刻をDBに保存・GUI に反映
"""
import threading, time
from datetime import datetime, timedelta, timezone
from typing import Callable
import db

JST = timezone(timedelta(hours=9))
LOG_CB = Callable[[str], None]


class Scheduler:
    def __init__(self, log: LOG_CB):
        self.log        = log
        self._thread    = None
        self._stop      = threading.Event()
        self._run_cb    = None   # パイプライン実行コールバック

    def set_run_callback(self, cb: Callable):
        """パイプライン実行関数を登録"""
        self._run_cb = cb

    # ── 開始 / 停止
    def start(self):
        sched = db.get_schedule()
        if not sched.get("enabled"):
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        self.log("📅 スケジューラー開始")

    def stop(self):
        self._stop.set()
        self.log("📅 スケジューラー停止")

    def restart(self):
        self.stop()
        time.sleep(0.5)
        self.start()

    # ── メインループ
    def _loop(self):
        while not self._stop.is_set():
            sched = db.get_schedule()
            if not sched.get("enabled"):
                self.log("📅 スケジューラー無効化 → 停止")
                break

            next_run_str = sched.get("next_run")
            now          = datetime.now(JST)

            # 次回実行時刻が未設定 → すぐ実行
            if not next_run_str:
                self._execute(sched)
            else:
                try:
                    next_run = datetime.fromisoformat(next_run_str)
                    if next_run.tzinfo is None:
                        next_run = next_run.replace(tzinfo=JST)
                except Exception:
                    next_run = now

                wait_sec = (next_run - now).total_seconds()
                if wait_sec <= 0:
                    self._execute(sched)
                else:
                    mins = int(wait_sec // 60)
                    self.log(f"📅 次回実行まで {mins} 分")
                    # 1分ごとにチェック
                    for _ in range(min(int(wait_sec), 60)):
                        if self._stop.is_set():
                            return
                        time.sleep(1)
                    continue

            # 次回実行時刻を設定
            interval = sched.get("interval_hrs", 4)
            next_dt  = datetime.now(JST) + timedelta(hours=interval)
            db.update_schedule(
                next_run  = next_dt.isoformat(),
                last_run  = datetime.now(JST).isoformat(),
                run_count = sched.get("run_count", 0) + 1
            )
            self.log(f"📅 次回: {next_dt.strftime('%m/%d %H:%M')} JST")

            # インターバル待機（1分刻み）
            wait_total = interval * 3600
            for _ in range(wait_total // 60):
                if self._stop.is_set():
                    return
                time.sleep(60)

    def _execute(self, sched: dict):
        self.log(f"📅 スケジュール実行開始 (#{sched.get('run_count',0)+1})")
        if self._run_cb:
            try:
                self._run_cb()
            except Exception as e:
                self.log(f"❌ スケジュール実行エラー: {e}")

    # ── YouTube 投稿枠を計算（4時間おき、JST）
    @staticmethod
    def next_upload_slots(count: int = 5, interval_hrs: int = 4) -> list[str]:
        """
        次の投稿予約時刻リストを返す（JST）
        例: ["2024/01/15 18:00", "2024/01/15 22:00", ...]
        """
        now   = datetime.now(JST)
        slots = []
        # 直近の投稿枠（6時, 10時, 14時, 18時, 22時 など）に合わせる
        base_hours = list(range(0, 24, interval_hrs))
        # 今から最初の枠を探す
        next_hour = None
        for h in base_hours:
            candidate = now.replace(hour=h, minute=0, second=0, microsecond=0)
            if candidate > now + timedelta(minutes=30):
                next_hour = candidate
                break
        if next_hour is None:
            next_hour = (now + timedelta(days=1)).replace(
                hour=base_hours[0], minute=0, second=0, microsecond=0)

        for i in range(count):
            slot = next_hour + timedelta(hours=interval_hrs * i)
            slots.append(slot.strftime("%Y/%m/%d %H:%M JST"))
        return slots
