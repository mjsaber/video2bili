"""Upload a video to YouTube using YouTube Data API v3 + OAuth.

Reads structured metadata from a JSON file, performs OAuth (cached token),
verifies the authenticated user owns the expected channel, and uploads the
video with a thumbnail.

Usage:
    uv run python scripts/youtube_upload.py \\
        --metadata output/back2back/youtube_metadata.json \\
        --client-secret client_secret.json \\
        --token youtube_token.json
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
]


def get_credentials(secret_path: Path, token_path: Path) -> Credentials:
    creds: Credentials | None = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(secret_path), SCOPES)
            creds = flow.run_local_server(port=0, prompt="consent")
        token_path.write_text(creds.to_json())
        print(f"[yt] token saved to {token_path}", file=sys.stderr)
    return creds


def list_channels(youtube) -> list[dict]:
    resp = youtube.channels().list(part="id,snippet", mine=True).execute()
    return resp.get("items", [])


def upload_video(youtube, meta: dict, video_path: Path) -> str:
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--client-secret", type=Path, default=Path("client_secret.json"))
    parser.add_argument("--token", type=Path, default=Path("youtube_token.json"))
    parser.add_argument("--skip-thumbnail", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="Auth + verify channel only, no upload")
    args = parser.parse_args()

    meta = json.loads(args.metadata.read_text(encoding="utf-8"))
    video_path = Path(meta["video_path"])
    thumbnail_path = Path(meta["thumbnail_path"])

    if not video_path.exists():
        print(f"video not found: {video_path}", file=sys.stderr)
        return 2
    if not thumbnail_path.exists():
        print(f"thumbnail not found: {thumbnail_path}", file=sys.stderr)
        return 2

    print(f"[yt] video: {video_path} ({video_path.stat().st_size/1024/1024:.1f} MB)", file=sys.stderr)
    print(f"[yt] thumbnail: {thumbnail_path}", file=sys.stderr)
    print(f"[yt] title: {meta['title']}", file=sys.stderr)
    print(f"[yt] privacy: {meta['privacy_status']}", file=sys.stderr)
    print(f"[yt] expected channel: {meta['expected_channel_id']}", file=sys.stderr)

    creds = get_credentials(args.client_secret, args.token)
    youtube = build("youtube", "v3", credentials=creds, cache_discovery=False)

    channels = list_channels(youtube)
    if not channels:
        print("[yt] no channels found for authenticated user", file=sys.stderr)
        return 3
    channel_ids = [c["id"] for c in channels]
    print(f"[yt] authenticated channels: {channel_ids}", file=sys.stderr)
    expected = meta["expected_channel_id"]
    if expected not in channel_ids:
        print(
            f"[yt] ERROR: expected channel {expected} not in authenticated channels {channel_ids}.\n"
            "If you have multiple YouTube channels (brand accounts), re-run OAuth and select "
            "the correct account in the browser, or delete youtube_token.json to force re-auth.",
            file=sys.stderr,
        )
        return 4
    print(f"[yt] channel {expected} verified", file=sys.stderr)

    if args.dry_run:
        print("[yt] dry-run mode, exiting before upload", file=sys.stderr)
        return 0

    try:
        video_id = upload_video(youtube, meta, video_path)
    except HttpError as e:
        print(f"[yt] upload failed: {e}", file=sys.stderr)
        return 5

    if not args.skip_thumbnail:
        try:
            upload_thumbnail(youtube, video_id, thumbnail_path)
        except HttpError as e:
            print(f"[yt] thumbnail upload failed: {e} (video itself is uploaded)", file=sys.stderr)

    url = f"https://www.youtube.com/watch?v={video_id}"
    studio_url = f"https://studio.youtube.com/video/{video_id}/edit"
    print(f"\n[yt] DONE", file=sys.stderr)
    print(f"watch: {url}", file=sys.stderr)
    print(f"studio: {studio_url}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
