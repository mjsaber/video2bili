"""Upload a video to YouTube using YouTube Data API v3 + OAuth.

Exposes 4 building-block functions used by the CLI:
  - get_credentials: load (or mint) OAuth credentials, auto-recovering from
    expired/revoked refresh tokens.
  - list_channels: returns the authenticated user's channels.
  - upload_video: resumable insert + chunk-progress logging.
  - upload_thumbnail: thumbnails().set after the video exists.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.http import MediaFileUpload

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]

REQUIRED_META_FIELDS = (
    "video_path", "thumbnail_path", "title", "description", "tags",
    "category_id", "default_language", "default_audio_language",
    "privacy_status", "expected_channel_id",
)


def validate_meta(meta: dict) -> None:
    """Raise `ValueError` if `meta` is missing any required key.

    A clear up-front check avoids letting a hand-written metadata.json crash
    deep inside upload_video with an unhelpful KeyError.
    """
    if not isinstance(meta, dict):
        raise ValueError(f"metadata must be a JSON object, got {type(meta).__name__}")
    missing = [k for k in REQUIRED_META_FIELDS if k not in meta]
    if missing:
        raise ValueError(f"metadata missing required keys: {missing}")


def _covers_scopes(creds: Credentials) -> bool:
    """True unless the creds positively lack one of the required ``SCOPES``.

    A token minted before a scope was added to ``SCOPES`` (e.g. ``force-ssl``)
    stays ``valid`` but is missing the new grant, so later API calls 403. Loaded
    tokens carry their granted scopes in ``creds.scopes``; when that is present we
    require it to cover ``SCOPES``. If it is absent/unknown we don't force a
    re-auth (avoids false positives on minimal credential objects).
    """
    granted = getattr(creds, "scopes", None)
    if not granted:
        return True
    return set(SCOPES).issubset(set(granted))


def get_credentials(secret_path: Path, token_path: Path) -> Credentials:
    """Load (or mint) OAuth credentials. Auto-recovers from expired/revoked refresh tokens.

    OAuth apps in "Testing" status have refresh tokens that expire after 7 days. The old
    behavior crashed with `RefreshError: invalid_grant: Token has been expired or revoked.`
    and required `rm youtube_token.json` by hand. We now catch that and fall through to
    a fresh OAuth flow. We also re-auth when a cached token is missing a scope that was
    added to SCOPES since it was minted (otherwise it stays valid but 403s on the new API).
    """
    creds: Credentials | None = None
    if token_path.exists():
        # NOTE: do NOT pass SCOPES here. from_authorized_user_file overwrites
        # creds.scopes with whatever is passed in, masking the token's real
        # granted scopes and defeating the _covers_scopes migration check.
        # Loading without scopes preserves the "scopes" recorded in the file.
        creds = Credentials.from_authorized_user_file(str(token_path))

    if creds and not _covers_scopes(creds):
        # Don't delete the cached token here: it is still usable (just missing a
        # newer scope), so discarding it before a *successful* re-auth would lose
        # working credentials if the OAuth flow fails. Drop the in-memory creds
        # only; the success path overwrites the file via write_text below.
        print(
            "[yt] cached token is missing a required scope (SCOPES changed since it "
            "was minted). Re-running OAuth flow; existing token kept until it succeeds.",
            file=sys.stderr,
        )
        creds = None

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except RefreshError as e:
            print(
                f"[yt] cached refresh token rejected ({e}). "
                "Common cause: OAuth app in Testing status — refresh tokens expire after 7 days. "
                "Deleting cached token and re-running OAuth flow.",
                file=sys.stderr,
            )
            token_path.unlink(missing_ok=True)
            creds = None

    if not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file(str(secret_path), SCOPES)
        try:
            creds = flow.run_local_server(port=0, prompt="consent")
        except Exception as e:
            raise RuntimeError(
                f"OAuth flow failed: {e}. Common causes: closed browser, "
                "port conflict, no network, or denied consent."
            ) from e

    token_path.write_text(creds.to_json())
    print(f"[yt] token saved to {token_path}", file=sys.stderr)
    return creds


def list_channels(youtube) -> list[dict]:
    resp = youtube.channels().list(part="id,snippet", mine=True).execute()
    return resp.get("items", [])


def upload_video(youtube, meta: dict[str, Any], video_path: Path) -> str:
    body = {
        "snippet": {
            "title": meta["title"],
            "description": meta["description"],
            "tags": meta["tags"],
            "categoryId": meta["category_id"],
            "defaultLanguage": meta["default_language"],
            "defaultAudioLanguage": meta["default_audio_language"],
        },
        "status": {
            "privacyStatus": meta["privacy_status"],
            "selfDeclaredMadeForKids": meta.get("made_for_kids", False),
            "embeddable": True,
        },
    }
    media = MediaFileUpload(
        str(video_path), mimetype="video/mp4", chunksize=8 * 1024 * 1024, resumable=True,
    )
    request = youtube.videos().insert(
        part=",".join(body.keys()), body=body, media_body=media,
    )

    response = None
    last_pct = -1
    start = time.time()
    while response is None:
        status, response = request.next_chunk()
        if status:
            pct = int(status.progress() * 100)
            if pct >= last_pct + 5:
                elapsed = time.time() - start
                print(f"[yt] upload {pct}%  elapsed={elapsed:.0f}s", file=sys.stderr)
                last_pct = pct
    video_id = response["id"]
    print(f"[yt] upload complete: video_id={video_id}", file=sys.stderr)
    return video_id


def upload_thumbnail(youtube, video_id: str, thumbnail_path: Path) -> None:
    media = MediaFileUpload(str(thumbnail_path), mimetype="image/png")
    youtube.thumbnails().set(videoId=video_id, media_body=media).execute()
    print(f"[yt] thumbnail uploaded for {video_id}", file=sys.stderr)
