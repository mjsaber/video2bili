"""One-time backfill for keyword-matched topical and streamer playlists.

Reuses the uploader's get_credentials (same token/scopes as video2yt-upload).
Idempotent — safe to re-run; videos already in a playlist are skipped. Videos
are inserted oldest-first so playlist order is chronological. Season playlists
are intentionally excluded because historical titles do not identify seasons
reliably; those are managed by explicit upload metadata and season migrations.

    uv run python scripts/backfill_playlists.py            # dry-run plan
    uv run python scripts/backfill_playlists.py --yes      # actually add
"""

import argparse
import sys
from pathlib import Path

from googleapiclient.discovery import build

from video2yt import playlists
from video2yt.upload import get_credentials

EXPECTED_CHANNEL_ID = "UCEgIrCo0pR6DyyrXuSn3wBg"

# Videos whose title lacks the rule keyword but that belong in a playlist anyway.
# 老虎流: anomaly-version comp (畸变版本) but no 異變 in the title.
MANUAL_EXTRAS: dict[str, list[str]] = {
    "UNQqM-Ey2HM": ["英雄戰場 異變玩法教學"],
}


def log(msg: str) -> None:
    print(f"[backfill] {msg}", file=sys.stderr)


def targets_for_video(video_id: str, title: str) -> list[str]:
    """Return topical/streamer targets without guessing a historical season."""
    return playlists.classify_topic(title) + MANUAL_EXTRAS.get(video_id, [])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--yes", action="store_true", help="actually add (default: dry-run)")
    ap.add_argument("--client-secret", type=Path, default=Path("client_secret.json"))
    ap.add_argument("--token", type=Path, default=Path("youtube_token.json"))
    args = ap.parse_args()

    creds = get_credentials(args.client_secret, args.token)
    yt = build("youtube", "v3", credentials=creds, cache_discovery=False)

    channel = yt.channels().list(part="contentDetails", mine=True).execute()["items"][0]
    if channel["id"] != EXPECTED_CHANNEL_ID:
        log(f"error: authenticated channel {channel['id']} != {EXPECTED_CHANNEL_ID}")
        return 1
    uploads_pl = channel["contentDetails"]["relatedPlaylists"]["uploads"]

    items = playlists._list_all(
        lambda tok: yt.playlistItems().list(
            part="snippet,contentDetails", playlistId=uploads_pl, maxResults=50, pageToken=tok
        )
    )
    videos = [
        (i["contentDetails"]["videoId"], i["snippet"]["title"], i["snippet"]["publishedAt"])
        for i in items
    ]
    videos.sort(key=lambda v: v[2])  # oldest first -> chronological playlist order
    log(f"{len(videos)} uploads found")

    plan: list[tuple[str, str, str]] = []  # (video_id, title, playlist)
    for video_id, title, _pub in videos:
        targets = targets_for_video(video_id, title)
        for name in targets:
            plan.append((video_id, title, name))

    if not args.yes:
        for video_id, title, name in plan:
            log(f"DRY-RUN would add {video_id} 「{title[:40]}…」 -> 「{name}」")
        log(f"{len(plan)} insertions planned; re-run with --yes to apply")
        return 0

    existing = playlists.my_playlists_by_title(yt)
    members: dict[str, set[str]] = {}
    added = skipped = 0
    for name, desc, _match in playlists.PLAYLIST_RULES:
        playlist_id = playlists.ensure_playlist(yt, name, desc, existing)
        members[name] = playlists.playlist_video_ids(yt, playlist_id)
    for video_id, title, name in plan:
        playlist_id = existing[name]
        if video_id in members[name]:
            skipped += 1
            continue
        playlists.insert_video(yt, playlist_id, video_id)
        members[name].add(video_id)
        added += 1
        log(f"added {video_id} -> 「{name}」")
    log(f"done: {added} added, {skipped} already present")
    return 0


if __name__ == "__main__":
    sys.exit(main())
