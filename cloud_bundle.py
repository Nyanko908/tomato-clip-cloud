# -*- coding: utf-8 -*-
"""cloud_bundle.py — クラウド版への「設定移送バンドル」暗号化。

BYO-deploy（ユーザーが自前サーバーにデプロイ）で、デスクトップの設定丸ごと
（APIキー / チャンネル / YouTube OAuth トークン / Discord トークン等）を
**1つの暗号文字列**にまとめる。ユーザーはそれと合言葉を自前サーバーの環境変数
`TOMATO_BUNDLE` / `TOMATO_BUNDLE_KEY` に貼るだけでよい（env を10個並べなくて済む）。

方式：合言葉から PBKDF2HMAC-SHA256（salt 16B・200k回）で 32B 鍵を導出し Fernet で暗号化。
出力は `TCB1.<salt_b64url>.<fernet_token>` のコンパクト文字列。生きた worker 不要・完全オフライン。

デスクトップ（web_app）とサーバー（server/config）で共有する。stdlib + cryptography のみ。
"""
import os
import json
import base64
from pathlib import Path

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

_PREFIX = "TCB1"
_ITER = 200_000

# 移送する設定キー（config から拾う。無いキーは入れない）
_TRANSFER_KEYS = [
    "gemini_key", "youtube_key", "gemini_model", "output_language", "ui_lang",
    "my_channel_id", "search_keywords", "voicevox_url", "discord_bot_token",
    "output_resolution", "encode_preset", "freshness_hours",
]


def _derive_key(passphrase: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=_ITER)
    return base64.urlsafe_b64encode(kdf.derive(passphrase.encode("utf-8")))


def _b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode("ascii").rstrip("=")


def _b64u_dec(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def collect_payload(config: dict, include_youtube_token: bool = True,
                    include_discord: bool = True) -> dict:
    """config から移送対象を集めた dict を返す（暗号化前の中身）。

    - 通常の設定キー（_TRANSFER_KEYS）
    - credentials_path があれば client_secrets.json の中身（credentials_json）
    - include_youtube_token かつ yt_token.pickle があれば b64（yt_token_b64）
    - include_discord=False なら discord_bot_token を除外
    """
    payload = {}
    for k in _TRANSFER_KEYS:
        v = config.get(k)
        if v not in (None, "", []):
            payload[k] = v
    if not include_discord:
        payload.pop("discord_bot_token", None)

    cred_path = config.get("credentials_path", "")
    if cred_path:
        try:
            p = Path(cred_path)
            if p.exists():
                payload["credentials_json"] = p.read_text(encoding="utf-8")
                if include_youtube_token:
                    tok = p.parent / "yt_token.pickle"
                    if tok.exists():
                        payload["yt_token_b64"] = base64.b64encode(tok.read_bytes()).decode("ascii")
        except Exception:
            pass
    return payload


def make_bundle(config: dict, passphrase: str,
                include_youtube_token: bool = True, include_discord: bool = True) -> str:
    """config を暗号バンドル文字列にして返す。"""
    payload = collect_payload(config, include_youtube_token, include_discord)
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    salt = os.urandom(16)
    token = Fernet(_derive_key(passphrase, salt)).encrypt(raw)
    return f"{_PREFIX}.{_b64u(salt)}.{token.decode('ascii')}"


def open_bundle(bundle_str: str, passphrase: str) -> dict:
    """暗号バンドルを復号して payload dict を返す。失敗時は例外。"""
    parts = (bundle_str or "").strip().split(".", 2)
    if len(parts) != 3 or parts[0] != _PREFIX:
        raise ValueError("bundle format invalid")
    salt = _b64u_dec(parts[1])
    token = parts[2].encode("ascii")
    raw = Fernet(_derive_key(passphrase, salt)).decrypt(token)
    return json.loads(raw.decode("utf-8"))


def bundle_summary(config: dict, include_youtube_token: bool = True,
                   include_discord: bool = True) -> dict:
    """バンドルに何が含まれるかの要約（UI 表示用。暗号化しない）。"""
    p = collect_payload(config, include_youtube_token, include_discord)
    return {
        "gemini": bool(p.get("gemini_key")),
        "youtube": bool(p.get("youtube_key")),
        "channel": bool(p.get("my_channel_id")),
        "google_token": bool(p.get("yt_token_b64")),
        "credentials": bool(p.get("credentials_json")),
        "discord": bool(p.get("discord_bot_token")),
        "keys": len(p),
    }


if __name__ == "__main__":  # 簡易セルフテスト
    cfg = {"gemini_key": "AIzaTEST", "youtube_key": "YTKEY", "my_channel_id": "UC123",
           "output_language": "ja"}
    b = make_bundle(cfg, "hunter2")
    print("bundle len:", len(b), "prefix:", b[:5])
    back = open_bundle(b, "hunter2")
    assert back["gemini_key"] == "AIzaTEST", back
    print("roundtrip OK:", back)
    try:
        open_bundle(b, "wrong")
        print("ERROR: wrong passphrase did not fail")
    except Exception as e:
        print("wrong passphrase correctly failed:", type(e).__name__)
