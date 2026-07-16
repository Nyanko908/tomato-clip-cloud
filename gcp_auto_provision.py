# -*- coding: utf-8 -*-
"""
gcp_auto_provision.py - 既存のOAuthクライアント(credentials_path)を使って
Gemini / YouTube Data API のAPIキーを自動作成する。

前提: credentials_path（YouTube OAuth2用に既にユーザーが用意した client_secrets.json）
は、TomatoClip共有のOAuthアプリではなく、ユーザー自身のGoogle Cloudプロジェクトに
紐づく「Bring Your Own Client」方式。そのため以下のフローはそのユーザー自身のプロジェクト
内で完結し、TomatoClip側の検証・審査は不要。

フロー:
  1. cloud-platform スコープでOAuth認可（YouTube用トークンとは別キャッシュ）
  2. client_secrets.json 内の project_id を読み取る
  3. Cloud Resource Manager API でプロジェクト番号を解決
  4. Service Usage API で対象APIを有効化
  5. API Keys API でキーを作成（Long Running Operationなのでポーリング）し、
     対象APIのみに制限する
"""
import json
import pickle
import time
from pathlib import Path

SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]
_GENAI_SERVICE    = "generativelanguage.googleapis.com"
_YOUTUBE_SERVICE  = "youtube.googleapis.com"


def _token_path(credentials_path: str) -> Path:
    return Path(credentials_path).parent / "gcp_token.pickle"


def get_gcp_credentials(credentials_path: str, log=print):
    """cloud-platform スコープのOAuth認可を行い、認証情報を返す（トークンはキャッシュする）"""
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request

    tp = _token_path(credentials_path)
    creds = None
    if tp.exists():
        with open(tp, "rb") as fh:
            creds = pickle.load(fh)

    if not creds or not creds.valid or not set(SCOPES) <= set(creds.scopes or []):
        if creds and creds.expired and creds.refresh_token and set(SCOPES) <= set(creds.scopes or []):
            creds.refresh(Request())
        else:
            log("🌐 ブラウザで認証中...")
            flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(tp, "wb") as fh:
            pickle.dump(creds, fh)
    return creds


def _get_project_id(credentials_path: str) -> str:
    with open(credentials_path, encoding="utf-8") as f:
        data = json.load(f)
    block = data.get("installed") or data.get("web") or {}
    project_id = block.get("project_id")
    if not project_id:
        raise ValueError("client_secrets.json に project_id が見つかりません")
    return project_id


def _get_project_number(creds, project_id: str) -> str:
    from googleapiclient.discovery import build
    crm = build("cloudresourcemanager", "v3", credentials=creds)
    project = crm.projects().get(name=f"projects/{project_id}").execute()
    return project["name"].split("/")[-1]


def _enable_and_create_key(creds, project_number: str, service: str,
                            display_name: str, log) -> str:
    from googleapiclient.discovery import build

    log("🔌 APIを有効化中...")
    su = build("serviceusage", "v1", credentials=creds)
    su.services().enable(
        name=f"projects/{project_number}/services/{service}"
    ).execute()

    log("🔑 キーを作成中...")
    ak = build("apikeys", "v2", credentials=creds)
    op = ak.projects().locations().keys().create(
        parent=f"projects/{project_number}/locations/global",
        body={
            "displayName": display_name,
            "restrictions": {"apiTargets": [{"service": service}]},
        },
    ).execute()

    op_name = op["name"]
    for _ in range(60):
        result = ak.operations().get(name=op_name).execute()
        if result.get("done"):
            if "error" in result:
                raise RuntimeError(result["error"].get("message", "キー作成に失敗しました"))
            return result["response"]["keyString"]
        time.sleep(1)
    raise TimeoutError("キー作成がタイムアウトしました")


def create_gemini_api_key(credentials_path: str, log=print) -> str:
    """Generative Language APIのみに制限されたAPIキー文字列を返す"""
    project_id = _get_project_id(credentials_path)
    creds = get_gcp_credentials(credentials_path, log)
    log("📁 プロジェクトを確認中...")
    project_number = _get_project_number(creds, project_id)
    return _enable_and_create_key(
        creds, project_number, _GENAI_SERVICE,
        "Tomato Clip - Gemini (auto-generated)", log)


def create_youtube_api_key(credentials_path: str, log=print) -> str:
    """YouTube Data API v3のみに制限されたAPIキー文字列を返す"""
    project_id = _get_project_id(credentials_path)
    creds = get_gcp_credentials(credentials_path, log)
    log("📁 プロジェクトを確認中...")
    project_number = _get_project_number(creds, project_id)
    return _enable_and_create_key(
        creds, project_number, _YOUTUBE_SERVICE,
        "Tomato Clip - YouTube Data API (auto-generated)", log)
