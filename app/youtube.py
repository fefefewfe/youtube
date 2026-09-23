"""Subida a YouTube con la YouTube Data API v3 (OAuth 2.0 de aplicación web)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from .config import PUBLIC_BASE_URL, YOUTUBE_CLIENT_SECRETS, YOUTUBE_TOKEN_FILE

SCOPES = ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube.readonly"]
REDIRECT_URI = f"{PUBLIC_BASE_URL}/api/youtube/callback"
_pending_flows: dict[str, object] = {}


class YouTubeError(RuntimeError):
    pass


def _flow():
    try:
        from google_auth_oauthlib.flow import Flow
    except ImportError as e:
        raise YouTubeError("Instala google-api-python-client y google-auth-oauthlib") from e
    if not YOUTUBE_CLIENT_SECRETS.exists():
        raise YouTubeError(f"Falta {YOUTUBE_CLIENT_SECRETS.name} en la carpeta data/ (ver README)")
    return Flow.from_client_secrets_file(str(YOUTUBE_CLIENT_SECRETS), scopes=SCOPES, redirect_uri=REDIRECT_URI)


def status() -> dict:
    return {
        "configured": YOUTUBE_CLIENT_SECRETS.exists(),
        "connected": YOUTUBE_TOKEN_FILE.exists(),
        "redirect_uri": REDIRECT_URI,
    }


def auth_url() -> str:
    flow = _flow()
    url, state = flow.authorization_url(access_type="offline", prompt="consent", include_granted_scopes="true")
    _pending_flows[state] = flow
    return url


def finish_auth(state: str, full_url: str) -> None:
    flow = _pending_flows.pop(state, None) or _flow()
    import os

    if full_url.startswith("http://"):
        os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")  # localhost
    flow.fetch_token(authorization_response=full_url)
    YOUTUBE_TOKEN_FILE.write_text(flow.credentials.to_json())


def disconnect() -> None:
    YOUTUBE_TOKEN_FILE.unlink(missing_ok=True)


def _service():
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
    except ImportError as e:
        raise YouTubeError("Instala google-api-python-client y google-auth-oauthlib") from e
    if not YOUTUBE_TOKEN_FILE.exists():
        raise YouTubeError("Conecta tu cuenta de YouTube primero")
    creds = Credentials.from_authorized_user_info(json.loads(YOUTUBE_TOKEN_FILE.read_text()), SCOPES)
    if not creds.valid and creds.refresh_token:
        creds.refresh(Request())
        YOUTUBE_TOKEN_FILE.write_text(creds.to_json())
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def channel_name() -> str | None:
    try:
        r = _service().channels().list(part="snippet", mine=True).execute()
        items = r.get("items", [])
        return items[0]["snippet"]["title"] if items else None
    except Exception:
        return None


def upload(video: Path, title: str, description: str, tags: list[str], privacy: str,
           thumbnail: Path | None, language: str, progress: Callable[[float, str], None]) -> str:
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaFileUpload

    yt = _service()
    body = {
        "snippet": {
            "title": title[:100], "description": description[:5000], "tags": tags[:30],
            "categoryId": "27",  # Educación
            "defaultLanguage": language, "defaultAudioLanguage": language,
        },
        "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False},
    }
    media = MediaFileUpload(str(video), mimetype="video/mp4", chunksize=8 * 1024 * 1024, resumable=True)
    req = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    resp = None
    try:
        while resp is None:
            st, resp = req.next_chunk()
            if st:
                progress(0.05 + 0.85 * st.progress(), f"Subiendo a YouTube {int(st.progress() * 100)}%")
    except HttpError as e:
        raise YouTubeError(f"YouTube rechazó la subida: {e}") from e
    vid = resp["id"]
    if thumbnail and thumbnail.exists():
        try:
            yt.thumbnails().set(videoId=vid, media_body=MediaFileUpload(str(thumbnail))).execute()
        except HttpError:
            pass  # las miniaturas personalizadas requieren canal verificado
    progress(1.0, "¡Subido a YouTube!")
    return vid
