"""Dry-run-first migration that separates S14 uploads from the S13 playlist.

    uv run python scripts/migrate_season_playlists.py
    uv run python scripts/migrate_season_playlists.py --yes
"""

import argparse
import sys
import time
from pathlib import Path
from typing import Callable

from googleapiclient.discovery import build

from video2yt import playlists
from video2yt.upload import get_credentials

EXPECTED_CHANNEL_ID = "UCEgIrCo0pR6DyyrXuSn3wBg"
OLD_TITLE = "爐石戰記：英雄戰場 流派教學全集"
S13_TITLE = "英雄戰場 S13 流派教學"
S14_TITLE = "英雄戰場 S14 流派教學"
S13_DESCRIPTION = playlists.season_playlist_description(13)
S14_DESCRIPTION = playlists.season_playlist_description(14)
S14_VIDEO_IDS = ("hZiEib2tzAs", "KXlycy1Kb1A")


def log(message: str) -> None:
    print(f"[season-playlists] {message}", file=sys.stderr)


def _wait_for_postconditions(
    youtube,
    s13_id: str,
    s14_id: str,
    *,
    attempts: int = 6,
    delay: float = 3.0,
) -> None:
    """Poll until YouTube's eventually consistent membership reads converge."""
    final_s13: dict[str, str] = {}
    final_s14: dict[str, str] = {}
    for attempt in range(attempts):
        final_s13 = playlists.playlist_members(youtube, s13_id)
        final_s14 = playlists.playlist_members(youtube, s14_id)
        removed_from_s13 = all(video_id not in final_s13 for video_id in S14_VIDEO_IDS)
        present_in_s14 = all(video_id in final_s14 for video_id in S14_VIDEO_IDS)
        if removed_from_s13 and present_in_s14:
            return
        if attempt < attempts - 1:
            time.sleep(delay)
    if any(video_id in final_s13 for video_id in S14_VIDEO_IDS):
        raise RuntimeError("postcondition failed: S14 video remains in S13")
    raise RuntimeError("postcondition failed: S14 video missing from S14")


def migrate(youtube, apply: bool, log: Callable[[str], None]) -> list[str]:
    """Plan or apply the exact S13/S14 migration, returning needed actions."""
    existing = playlists.my_playlists_by_title(youtube)
    has_old = OLD_TITLE in existing
    has_s13 = S13_TITLE in existing
    if has_old and has_s13:
        raise RuntimeError("both old and renamed S13 playlists exist")
    if not has_old and not has_s13:
        raise RuntimeError("neither old nor renamed S13 playlist exists")

    s13_id = existing[OLD_TITLE if has_old else S13_TITLE]
    s13_members = playlists.playlist_members(youtube, s13_id)
    s14_id = existing.get(S14_TITLE)
    s14_members = playlists.playlist_members(youtube, s14_id) if s14_id else {}

    actions: list[str] = []
    if has_old:
        actions.append(f"rename {OLD_TITLE} -> {S13_TITLE}")
    if s14_id is None:
        actions.append(f"create {S14_TITLE}")
    for video_id in S14_VIDEO_IDS:
        if video_id not in s14_members:
            actions.append(f"add {video_id} -> {S14_TITLE}")
    for video_id in S14_VIDEO_IDS:
        if video_id in s13_members:
            actions.append(f"remove {video_id} <- {S13_TITLE}")

    for action in actions:
        log(("APPLY " if apply else "DRY-RUN ") + action)
    if not apply:
        return actions

    if has_old:
        playlists.rename_playlist(youtube, s13_id, S13_TITLE, S13_DESCRIPTION)
        del existing[OLD_TITLE]
        existing[S13_TITLE] = s13_id
    if s14_id is None:
        s14_id = playlists.ensure_playlist(youtube, S14_TITLE, S14_DESCRIPTION, existing)
    for video_id in S14_VIDEO_IDS:
        if video_id not in s14_members:
            playlists.insert_video(youtube, s14_id, video_id)
    for video_id in S14_VIDEO_IDS:
        if video_id in s13_members:
            playlists.remove_video(youtube, s13_id, video_id)

    _wait_for_postconditions(youtube, s13_id, s14_id)
    return actions


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--yes", action="store_true", help="apply migration")
    parser.add_argument("--client-secret", type=Path, default=Path("client_secret.json"))
    parser.add_argument("--token", type=Path, default=Path("youtube_token.json"))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    credentials = get_credentials(args.client_secret, args.token)
    youtube = build("youtube", "v3", credentials=credentials, cache_discovery=False)
    channels = youtube.channels().list(part="id", mine=True).execute().get("items", [])
    channel_ids = [item["id"] for item in channels]
    if EXPECTED_CHANNEL_ID not in channel_ids:
        log(f"error: expected channel {EXPECTED_CHANNEL_ID}, authenticated {channel_ids}")
        return 1
    try:
        migrate(youtube, apply=args.yes, log=log)
    except RuntimeError as error:
        log(f"error: {error}")
        return 1
    if not args.yes:
        log("dry-run only; rerun with --yes to apply")
    return 0


if __name__ == "__main__":
    sys.exit(main())
