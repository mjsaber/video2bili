"""Post a top-level comment on a YouTube video using the cached OAuth token.

Reuses youtube_token.json (must include the youtube.force-ssl scope, which
authorizes commentThreads.insert). Usage:

    uv run python scripts/post_comment.py --video-id <ID> --text-file <path>
    uv run python scripts/post_comment.py --video-id <ID> --text "..."
"""

import argparse
import sys
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--video-id", required=True)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--text")
    g.add_argument("--text-file", type=Path)
    ap.add_argument("--token", default="youtube_token.json")
    args = ap.parse_args()

    text = args.text if args.text else args.text_file.read_text(encoding="utf-8").strip()

    creds = Credentials.from_authorized_user_file(args.token)
    if not creds.valid and creds.refresh_token:
        creds.refresh(Request())
        Path(args.token).write_text(creds.to_json(), encoding="utf-8")

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
