"""Post a top-level comment on a YouTube video (pipeline Step 10).

Reuses the uploader's ``get_credentials`` so auth is as robust as Step 9: it
auto-recovers from the known stale-token path (OAuth apps in "Testing" status
have refresh tokens that expire after 7 days → ``RefreshError``; the helper
deletes the cached token and re-runs the OAuth flow) and from scope migrations.
The ``youtube.force-ssl`` scope (already in upload.SCOPES) authorizes
``commentThreads.insert``. Usage:

    uv run python scripts/post_comment.py --video-id <ID> --text-file <path>
    uv run python scripts/post_comment.py --video-id <ID> --text "..."
"""

import argparse
import sys
from pathlib import Path

from googleapiclient.discovery import build

from video2yt.upload import get_credentials


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--video-id", required=True)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--text")
    g.add_argument("--text-file", type=Path)
    ap.add_argument("--client-secret", type=Path, default=Path("client_secret.json"))
    ap.add_argument("--token", type=Path, default=Path("youtube_token.json"))
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

    yt = build("youtube", "v3", credentials=creds)
    resp = yt.commentThreads().insert(
        part="snippet",
        body={
            "snippet": {
                "videoId": args.video_id,
                "topLevelComment": {"snippet": {"textOriginal": text}},
            }
        },
    ).execute()

    cid = resp["snippet"]["topLevelComment"]["id"]
    print(f"[comment] posted id={cid} on video {args.video_id}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
