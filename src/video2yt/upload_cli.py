"""CLI for video2yt-upload: upload a video + thumbnail to YouTube via OAuth."""

import argparse
import json
import sys
from pathlib import Path

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from video2yt import playlists, upload, publication


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
    recovery = parser.add_mutually_exclusive_group()
    recovery.add_argument("--adopt-video-id", help="Recover a known existing video after verifying channel and title; never inserts a video.")
    recovery.add_argument("--retry-uncertain", action="store_true", help="Retry an interrupted insert ONLY after checking Studio confirms no video was created.")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Authenticate and verify channel only, no upload.",
    )
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> dict:
    if not args.metadata.is_file():
        raise FileNotFoundError(f"metadata not found: {args.metadata}")
    with publication.locked(args.metadata.parent):
        return _run_locked(args)


def _run_locked(args: argparse.Namespace) -> dict:
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

    project = args.metadata.parent
    receipt = publication.load(project)
    fingerprint = publication.file_hash(video_path)
    meta_hash = publication.metadata_hash(meta)
    if receipt:
        if receipt["channel_id"] != expected:
            raise ValueError("publication channel changed; refusing to reuse or reupload")
        if receipt.get("video_sha256") != fingerprint or receipt.get("metadata_sha256") != meta_hash:
            raise ValueError("video or metadata changed after upload attempt; use Studio for metadata edits or a new project for a different video")
    adopt = getattr(args, "adopt_video_id", None)
    if adopt:
        if not publication.VIDEO_ID_RE.fullmatch(adopt):
            raise ValueError("invalid YouTube video ID")
        if receipt and receipt.get("video_id") not in (None, adopt):
            raise ValueError("receipt already belongs to a different video")
        found = youtube.videos().list(part="snippet,status", id=adopt).execute().get("items", [])
        if len(found) != 1 or found[0]["snippet"].get("channelId") != expected:
            raise ValueError("adopted video is missing or belongs to another channel")
        if found[0]["snippet"].get("title") != meta["title"]:
            raise ValueError("adopted video title does not match metadata; verify the intended video")
        receipt = receipt or {}
        receipt.update(schema_version=1, status="uploaded", video_id=adopt,
                       channel_id=expected, video_sha256=fingerprint,
                       metadata_sha256=meta_hash,
                       uploaded_at=receipt.get("uploaded_at") or found[0]["snippet"].get("publishedAt"),
                       adopted=True, metadata_filename=args.metadata.name)
        # API snippet timestamp is retained as publication time only for public videos.
        if found[0].get("status", {}).get("privacyStatus") == "public":
            receipt["published_at"] = found[0]["snippet"].get("publishedAt")
        publication.uploaded_time(receipt)  # Reject adoption with no trustworthy chronology.
        publication.save(project, receipt)
    if not receipt or not receipt.get("video_id"):
        if receipt and not getattr(args, "retry_uncertain", False):
            raise RuntimeError("previous upload outcome is uncertain; check Studio, then use --adopt-video-id ID or --retry-uncertain only if no video exists")
        receipt = {"schema_version": 1, "status": "uploading", "channel_id": expected,
                   "video_sha256": fingerprint, "metadata_sha256": meta_hash,
                   "attempted_at": publication.now_iso(), "metadata_filename": args.metadata.name}
        publication.save(project, receipt)
        try:
            video_id = upload.upload_video(youtube, meta, video_path)
        except HttpError as e:
            raise RuntimeError(f"upload failed (outcome may be uncertain): {e}") from e
        receipt.update(video_id=video_id, status="uploaded", uploaded_at=publication.now_iso())
        publication.save(project, receipt)  # Before thumbnail, playlist, or archive work.
    video_id = receipt["video_id"]
    errors = []
    thumbnail_hash = publication.file_hash(thumbnail_path)
    if not args.skip_thumbnail:
        if receipt.get("thumbnail_sha256") != thumbnail_hash or receipt.get("thumbnail_status") != "complete":
            # Invalidate completed state before any attempt to change the remote asset.
            receipt.update(status="uploaded", thumbnail_status="pending")
            publication.save(project, receipt)
            try:
                upload.upload_thumbnail(youtube, video_id, thumbnail_path)
                receipt.update(thumbnail_status="complete", thumbnail_sha256=thumbnail_hash)
            except Exception as e:
                receipt["thumbnail_status"] = "failed"
                errors.append(f"thumbnail upload failed: {e}")
            publication.save(project, receipt)
    elif receipt.get("thumbnail_status") != "complete":
        receipt["thumbnail_status"] = "skipped"
    if receipt.get("playlist_status") != "complete":
        try:
            playlists.add_video(youtube, video_id, meta["title"], meta["season"], log=_log)
            receipt["playlist_status"] = "complete"
        except Exception as e:
            receipt["playlist_status"] = "failed"
            errors.append(f"playlist add failed: {e}")
        publication.save(project, receipt)
    receipt["status"] = "complete" if not errors else "uploaded"
    receipt["errors"] = errors
    publication.save(project, receipt)
    publication.archive(project)
    for error in errors:
        _log(f"{error}; rerun the same command to resume video {video_id}")
    url = f"https://www.youtube.com/watch?v={video_id}"
    studio_url = f"https://studio.youtube.com/video/{video_id}/edit"
    _log("DONE" if not errors else "VIDEO UPLOADED; FOLLOW-UP STEPS INCOMPLETE")
    _log(f"watch: {url}")
    _log(f"studio: {studio_url}")
    return {"video_id": video_id, "video_url": url, "studio_url": studio_url,
            "dry_run": False, "complete": not errors, "errors": errors}


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        result = run(args)
        return 0 if result.get("dry_run") or result.get("complete") else 1
    except (ValueError, OSError, RuntimeError, HttpError) as e:
        _log(f"error: {e}")
        return 1
