"""CLI for video2yt-upload: upload a video + thumbnail to YouTube via OAuth."""

import argparse
import json
import sys
from pathlib import Path

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from video2yt import upload


def _log(msg: str) -> None:
    print(f"[video2yt-upload] {msg}", file=sys.stderr)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="video2yt-upload",
        description=(
            "Upload a video (and thumbnail) to YouTube using the YouTube Data API v3. "
            "Reads structured metadata from a JSON file produced by the workflow. "
            "Caches OAuth tokens in --token (default youtube_token.json)."
        ),
    )
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--client-secret", type=Path, default=Path("client_secret.json"))
    parser.add_argument("--token", type=Path, default=Path("youtube_token.json"))
    parser.add_argument("--skip-thumbnail", action="store_true")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Authenticate and verify channel only, no upload.",
    )
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> dict:
    if not args.metadata.exists():
        raise FileNotFoundError(f"metadata not found: {args.metadata}")
    try:
        meta = json.loads(args.metadata.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"malformed metadata JSON {args.metadata}: {e}")
    upload.validate_meta(meta)
    video_path = Path(meta["video_path"])
    thumbnail_path = Path(meta["thumbnail_path"])

    if not video_path.exists():
        raise FileNotFoundError(f"video not found: {video_path}")
    if not thumbnail_path.exists():
        raise FileNotFoundError(f"thumbnail not found: {thumbnail_path}")

    _log(f"video: {video_path} ({video_path.stat().st_size/1024/1024:.1f} MB)")
    _log(f"thumbnail: {thumbnail_path}")
    _log(f"title: {meta['title']}")
    _log(f"privacy: {meta['privacy_status']}")
    _log(f"expected channel: {meta['expected_channel_id']}")

    creds = upload.get_credentials(args.client_secret, args.token)
    youtube = build("youtube", "v3", credentials=creds, cache_discovery=False)

    try:
        channels = upload.list_channels(youtube)
    except HttpError as e:
        raise RuntimeError(f"failed to list channels: {e}")
    if not channels:
        raise RuntimeError("no channels found for authenticated user")
    channel_ids = [c["id"] for c in channels]
    _log(f"authenticated channels: {channel_ids}")
    expected = meta["expected_channel_id"]
    if expected not in channel_ids:
        raise RuntimeError(
            f"expected channel {expected} not in authenticated channels {channel_ids}. "
            "If you have multiple YouTube channels (brand accounts), re-run OAuth and "
            "select the correct account, or delete the token file to force re-auth."
        )
    _log(f"channel {expected} verified")

    if args.dry_run:
        _log("dry-run mode, exiting before upload")
        return {"video_id": None, "video_url": None, "studio_url": None, "dry_run": True}

    try:
        video_id = upload.upload_video(youtube, meta, video_path)
    except HttpError as e:
        raise RuntimeError(f"upload failed: {e}")

    if not args.skip_thumbnail:
        try:
            upload.upload_thumbnail(youtube, video_id, thumbnail_path)
        except HttpError as e:
            _log(f"thumbnail upload failed: {e} (video itself is uploaded)")

    url = f"https://www.youtube.com/watch?v={video_id}"
    studio_url = f"https://studio.youtube.com/video/{video_id}/edit"
    _log("DONE")
    _log(f"watch: {url}")
    _log(f"studio: {studio_url}")
    return {"video_id": video_id, "video_url": url, "studio_url": studio_url, "dry_run": False}


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        run(args)
        return 0
    except (ValueError, FileNotFoundError, RuntimeError) as e:
        _log(f"error: {e}")
        return 1
