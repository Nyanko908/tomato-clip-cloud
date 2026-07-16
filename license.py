"""
license.py - ライセンス管理

検証フロー:
  1. ローカル: Ed25519 署名 + 有効期限 → オフラインでも動く
  2. サーバー: 週1で revoke / machine_id 整合チェック
  3. オフライン猶予: last_check から14日以内は revoked でなければOK
"""

import json, time, base64, hashlib, uuid, platform, threading
from pathlib import Path
from typing import Optional

# ── 公開鍵（key_gen.py --init で生成した値を貼る）
_PUBLIC_KEY_B64 = "ExszWZuBCKxvMfZ0u-ffjXbCNvcshDuXOEqvsBiOhBw"

# ── Cloudflare Worker URL（デプロイ後に更新）
_WORKER_URL = "https://tomato-shorts-license.clipflowlicense.workers.dev"

_LICENSE_PATH  = Path.home() / ".tomato_clip" / "license.json"
_CHECK_INTERVAL = 7 * 24 * 3600   # 7日ごとにサーバー確認
_OFFLINE_GRACE  = 14 * 24 * 3600  # 14日間はオフラインでも動く


# ────────────────────────────────────────────
#  ユーティリティ
# ────────────────────────────────────────────

def _get_machine_id() -> str:
    raw = f"{uuid.getnode()}:{platform.node()}:{platform.machine()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def _verify_signature(key: str) -> Optional[dict]:
    """Ed25519署名を検証してペイロード dict を返す。失敗時 None"""
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

        parts = key.strip().split(".")
        if len(parts) != 2:
            return None
        payload_b64, sig_b64 = parts

        # padding を補完
        def _b64d(s):
            return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))

        pub_bytes = _b64d(_PUBLIC_KEY_B64)
        pub_key   = Ed25519PublicKey.from_public_bytes(pub_bytes)
        pub_key.verify(_b64d(sig_b64), payload_b64.encode())

        payload = json.loads(_b64d(payload_b64))
        if payload.get("exp", 0) < time.time():
            return None  # 期限切れ
        return payload

    except Exception:
        return None


def _post(endpoint: str, data: dict, timeout: int = 8) -> Optional[dict]:
    try:
        import urllib.request
        body = json.dumps(data).encode()
        req  = urllib.request.Request(
            f"{_WORKER_URL}{endpoint}",
            data=body,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "TomatoClip/1.0",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


# ────────────────────────────────────────────
#  LicenseManager
# ────────────────────────────────────────────

class LicenseManager:
    def __init__(self):
        self._state: dict = self._load()
        self._lock = threading.Lock()

    # ── 永続化 ──────────────────────────────

    def _load(self) -> dict:
        try:
            if _LICENSE_PATH.exists():
                return json.loads(_LICENSE_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
        return {}

    def _save(self):
        _LICENSE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _LICENSE_PATH.write_text(
            json.dumps(self._state, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # ── 状態参照 ────────────────────────────

    @property
    def is_pro(self) -> bool:
        with self._lock:
            if not self._state.get("key"):
                return False
            if not _verify_signature(self._state["key"]):
                return False  # 署名無効 or 期限切れ
            # ライセンスファイルを別PCへコピーしても無効
            if self._state.get("machine_id") != _get_machine_id():
                return False
            if self._state.get("check_result") in ("revoked", "machine_mismatch", "not_activated"):
                return False
            # オフライン猶予: 最後にサーバー確認が成功してから14日を超えたら
            # （通信ブロックによる無効化回避を防ぐため）デモに戻す
            elapsed = time.time() - self._state.get("last_check", 0)
            if elapsed > _OFFLINE_GRACE:
                return False
            return True

    @property
    def is_demo(self) -> bool:
        return not self.is_pro

    @property
    def uid(self) -> str:
        return self._state.get("payload", {}).get("uid", "demo")

    @property
    def tier(self) -> str:
        return self._state.get("payload", {}).get("tier", "demo")

    # ── アクティベーション ───────────────────

    def activate(self, key: str) -> tuple[bool, str]:
        """
        プロダクトキーを認証する。
        Returns: (成功フラグ, メッセージ)
        """
        payload = _verify_signature(key)
        if not payload:
            return False, "❌ キーが無効または期限切れです"

        machine_id = _get_machine_id()
        result = _post("/activate", {"key": key, "machine_id": machine_id})

        if result is None:
            # サーバー不達 → ローカル検証OKなら一時許可（後で週次チェックで確定）
            pass
        elif result.get("status") == "revoked":
            return False, "❌ このキーは無効化されています"
        elif result.get("status") in ("already_bound", "already_activated"):
            return False, "❌ このキーはすでに別のPCで使用されています"
        elif result.get("status") not in ("ok", None):
            return False, f"❌ 認証エラー: {result.get('status')}"

        with self._lock:
            self._state = {
                "key":          key,
                "payload":      payload,
                "machine_id":   machine_id,
                "activated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "last_check":   time.time(),
                "check_result": result.get("status", "ok") if result else "ok",
            }
            self._save()

        exp_str = time.strftime(
            "%Y/%m/%d", time.localtime(payload.get("exp", time.time()))
        )
        return True, f"✅ 認証完了！  ({payload.get('uid','')} / 有効期限 {exp_str})"

    def deactivate(self):
        """ライセンスを削除してデモモードに戻す（PC買い替え用にサーバー側の端末紐付けも解除する）"""
        with self._lock:
            key = self._state.get("key")
            self._state = {}
            self._save()
        if key:
            threading.Thread(target=lambda: _post("/deactivate", {"key": key}), daemon=True).start()

    # ── 週次バックグラウンドチェック ────────

    def check_online_async(self):
        """起動時にバックグラウンドで呼ぶ（週1のみ実際に通信）"""
        threading.Thread(target=self._check_online, daemon=True).start()

    def _check_online(self):
        with self._lock:
            key        = self._state.get("key")
            last_check = self._state.get("last_check", 0)
        if not key:
            return
        if time.time() - last_check < _CHECK_INTERVAL:
            return  # まだ1週間経っていない

        machine_id = _get_machine_id()
        result = _post("/check", {"key": key, "machine_id": machine_id})
        if result is None:
            return  # オフライン → 猶予期間で継続

        with self._lock:
            self._state["check_result"] = result.get("status", "ok")
            self._state["last_check"]   = time.time()
            self._save()


# ── シングルトン ─────────────────────────────

_manager: Optional[LicenseManager] = None

def get_license() -> LicenseManager:
    global _manager
    if _manager is None:
        _manager = LicenseManager()
    return _manager
