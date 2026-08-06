"""Channel playlist management: classify and mutate video memberships.

Each upload goes to one explicit season playlist plus any topical/streamer
playlists matched by its title. ``add_video`` is called by video2yt-upload after
a successful upload; the one-time topical backfill lives in
``scripts/backfill_playlists.py``.
"""

import time
from typing import Callable

from googleapiclient.errors import HttpError

# Ordered topical rules: (playlist title, description, title-keyword predicate).
PLAYLIST_RULES: list[tuple[str, str, Callable[[str], bool]]] = [
    (
        "英雄戰場 異變玩法教學",
        "異變（Anomaly）相關流派與玩法完整教學。#英雄戰場教學",
        lambda title: "異變" in title,
    ),
    (
        "英雄戰場 剋制與轉型教學",
        "強勢流派怎麼破、決賽怎麼轉型的決策向教學。#英雄戰場教學",
        lambda title: "剋制" in title or "轉型" in title,
    ),
    (
        "郭楓荷 實戰教學",
        "郭楓荷實戰對局完整教學合集。#英雄戰場教學",
        lambda title: "郭楓荷" in title,
    ),
]


def season_playlist_title(season: int) -> str:
    return f"英雄戰場 S{season} 流派教學"


def season_playlist_description(season: int) -> str:
    suffix = "，持續更新" if season == 14 else ""
    return f"爐石戰記：英雄戰場第 {season} 賽季流派完整教學與實戰{suffix}。#英雄戰場教學"


def classify_topic(title: str) -> list[str]:
    """Return only title-keyword topical/streamer playlist names."""
    return [name for name, _desc, match in PLAYLIST_RULES if match(title)]


def classify(title: str, season: int) -> list[str]:
    """Return one explicit season playlist followed by topical matches."""
    return [season_playlist_title(season), *classify_topic(title)]


def playlist_definitions(title: str, season: int) -> list[tuple[str, str]]:
    """Return ordered ``(title, description)`` targets for one upload."""
    matched = set(classify(title, season))
    definitions = [
        (season_playlist_title(season), season_playlist_description(season)),
        *((name, desc) for name, desc, _match in PLAYLIST_RULES),
    ]
    return [(name, desc) for name, desc in definitions if name in matched]


def _execute_retrying_404(request, attempts: int = 4, delay: float = 3.0):
    """Execute a playlistItems request, retrying known transient API failures.

    A freshly created playlist can 404 on playlistItems endpoints for a few
    seconds before it propagates (observed live 2026-07-08). YouTube can also
    abort the first insert with 409/SERVICE_UNAVAILABLE (observed 2026-08-06).
    """
    for attempt in range(attempts):
        try:
            return request.execute()
        except HttpError as e:
            transient_409 = (
                e.status_code == 409 and b'"SERVICE_UNAVAILABLE"' in e.content
            )
            if (e.status_code != 404 and not transient_409) or attempt == attempts - 1:
                raise
            time.sleep(delay)


def _list_all(request_factory):
    """Paginate a youtube list endpoint; request_factory(page_token) -> request."""
    items = []
    page_token = None
    while True:
        response = request_factory(page_token).execute()
        items.extend(response.get("items", []))
        page_token = response.get("nextPageToken")
        if not page_token:
            return items


def my_playlists_by_title(youtube) -> dict[str, str]:
    """Map playlist title -> playlist id for the authenticated channel."""
    items = _list_all(
        lambda tok: youtube.playlists().list(
            part="snippet", mine=True, maxResults=50, pageToken=tok
        )
    )
    return {i["snippet"]["title"]: i["id"] for i in items}


def ensure_playlist(youtube, title: str, description: str, existing: dict[str, str]) -> str:
    """Return the playlist id for title, creating a public playlist if missing.

    ``existing`` (title -> id, from my_playlists_by_title) is updated in place
    so repeated calls in one run don't re-query or double-create.
    """
    if title in existing:
        return existing[title]
    response = (
        youtube.playlists()
        .insert(
            part="snippet,status",
            body={
                "snippet": {"title": title, "description": description},
                "status": {"privacyStatus": "public"},
            },
        )
        .execute()
    )
    existing[title] = response["id"]
    return response["id"]


def playlist_members(youtube, playlist_id: str) -> dict[str, str]:
    """Map video ID to playlist-item ID for one playlist."""
    items = []
    page_token = None
    while True:
        response = _execute_retrying_404(
            youtube.playlistItems().list(
                part="id,contentDetails",
                playlistId=playlist_id,
                maxResults=50,
                pageToken=page_token,
            )
        )
        items.extend(response.get("items", []))
        page_token = response.get("nextPageToken")
        if not page_token:
            break
    return {item["contentDetails"]["videoId"]: item["id"] for item in items}


def playlist_video_ids(youtube, playlist_id: str) -> set[str]:
    return set(playlist_members(youtube, playlist_id))


def insert_video(youtube, playlist_id: str, video_id: str) -> None:
    _execute_retrying_404(
        youtube.playlistItems().insert(
            part="snippet",
            body={
                "snippet": {
                    "playlistId": playlist_id,
                    "resourceId": {"kind": "youtube#video", "videoId": video_id},
                }
            },
        )
    )


def remove_video(youtube, playlist_id: str, video_id: str) -> bool:
    """Remove one exact video membership, returning whether it existed."""
    membership_id = playlist_members(youtube, playlist_id).get(video_id)
    if membership_id is None:
        return False
    youtube.playlistItems().delete(id=membership_id).execute()
    return True


def rename_playlist(youtube, playlist_id: str, title: str, description: str) -> None:
    """Rename a playlist in place while preserving its ID and membership."""
    youtube.playlists().update(
        part="snippet",
        body={"id": playlist_id, "snippet": {"title": title, "description": description}},
    ).execute()


def add_video(youtube, video_id: str, title: str, season: int, log=None) -> list[str]:
    """Add a video to its season and title-matched playlists (idempotent).

    Returns the playlist titles the video was newly added to.
    """
    existing = my_playlists_by_title(youtube)
    added = []
    for name, desc in playlist_definitions(title, season):
        playlist_id = ensure_playlist(youtube, name, desc, existing)
        if video_id in playlist_video_ids(youtube, playlist_id):
            if log:
                log(f"playlist: already in 「{name}」")
            continue
        insert_video(youtube, playlist_id, video_id)
        added.append(name)
        if log:
            log(f"playlist: added to 「{name}」")
    return added
