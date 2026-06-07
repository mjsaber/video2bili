"""Post a top-level comment on a YouTube video (pipeline Step 10).

Reuses the uploader's ``get_credentials`` so auth is as robust as Step 9: it
auto-recovers from the known stale-token path (OAuth apps in "Testing" status
have refresh tokens that expire after 7 days → ``RefreshError``; the helper
deletes the cached token and re-runs the OAuth flow) and from scope migrations.
The ``youtube.force-ssl`` scope (already in upload.SCOPES) authorizes
``commentThreads.insert``.

Because ``get_credentials`` may re-run the OAuth flow (any Google account can be
picked), this script verifies the authenticated channel matches the expected
channel BEFORE posting — mirroring the uploader's guard — so a wrong-account
re-auth can never post the comment from the wrong channel. Usage:

    uv run python scripts/post_comment.py --video-id <ID> --text-file <path>
    uv run python scripts/post_comment.py --video-id <ID> --text "..."
"""

import argparse
import sys
from pathlib import Path

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from video2yt.upload import get_credentials, list_channels

# All uploads/comments from this repo go to this channel (same constant the
# uploader verifies via youtube_metadata.json's expected_channel_id).
DEFAULT_CHANNEL_ID = "UCEgIrCo0pR6DyyrXuSn3wBg"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--video-id", required=True)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--text")
    g.add_argument("--text-file", type=Path)
    ap.add_argument("--client-secret", type=Path, default=Path("client_secret.json"))
    ap.add_argument("--token", type=Path, default=Path("youtube_token.json"))
    ap.add_argument(
        "--expected-channel-id", default=DEFAULT_CHANNEL_ID,
        help="Abort unless the authenticated account owns this channel.",
    )
    args = ap.parse_args()

    text = (
        args.text
        if args.text is not None
        else args.text_file.read_text(encoding="utf-8").strip()
    )
    if not text:
        print("[comment] error: empty comment text", file=sys.stderr)
        return 2

    creds = get_credentials(args.client_secret, args.token)
    yt = build("youtube", "v3", credentials=creds, cache_discovery=False)

    # Guard: get_credentials may have re-run the OAuth flow (any account can be
    # picked). Never post from the wrong channel.
    try:
        channels = list_channels(yt)
    except HttpError as e:
        print(f"[comment] error: failed to list channels: {e}", file=sys.stderr)
        return 1
    channel_ids = [c["id"] for c in channels]
    if args.expected_channel_id not in channel_ids:
        print(
            f"[comment] error: expected channel {args.expected_channel_id} not in "
            f"authenticated channels {channel_ids}. Re-run OAuth and select the "
            "correct account, or delete the token file to force re-auth.",
            file=sys.stderr,
        )
        return 1

    try:
        resp = yt.commentThreads().insert(
            part="snippet",
            body={
                "snippet": {
                    "videoId": args.video_id,
                    "topLevelComment": {"snippet": {"textOriginal": text}},
                }
            },
        ).execute()
    except HttpError as e:
        print(f"[comment] error: comment insert failed: {e}", file=sys.stderr)
        return 1

    cid = resp["snippet"]["topLevelComment"]["id"]
    print(f"[comment] posted id={cid} on video {args.video_id}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
