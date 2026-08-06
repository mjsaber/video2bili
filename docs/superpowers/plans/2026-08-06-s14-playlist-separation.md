# S14 Playlist Separation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the channel's S13 and S14 teaching playlists, migrate the two confirmed S14 uploads, and route every future upload by an explicit season metadata field.

**Architecture:** Keep season selection separate from title-keyword topical playlists. Validate `season` before upload, generate exactly one `英雄戰場 S{season} 流派教學` target, and use a dry-run-first migration command for the live rename/add/remove operation. Preserve the existing playlist ID for S13 and use exact playlist-item IDs for removals.

**Tech Stack:** Python 3.12, YouTube Data API v3, google-api-python-client, pytest, uv

---

## File structure

- Modify `src/video2yt/upload.py`: require and validate a positive integer `season` field.
- Modify `src/video2yt/upload_cli.py`: pass validated season metadata into playlist routing.
- Modify `src/video2yt/playlists.py`: generate season targets, keep topical rules separate, and add exact membership/rename/remove helpers.
- Modify `scripts/backfill_playlists.py`: backfill topical playlists only and never recreate the retired catch-all.
- Create `scripts/migrate_season_playlists.py`: dry-run-first, restart-safe S13/S14 live migration.
- Modify `tests/test_playlists.py`: cover season routing, idempotence, rename, and exact membership removal.
- Create `tests/test_upload_metadata.py`: cover season metadata validation without touching the already-dirty smoke-test file.
- Create `tests/test_season_playlist_migration.py`: cover dry-run, first application, rerun, and ambiguous-state refusal.
- Modify `output/choice_quilboar_s14/youtube_metadata.json`: record `"season": 14` in the retained shipped-project metadata.

### Task 1: Validate explicit upload season

**Files:**
- Modify: `src/video2yt/upload.py:29-50`
- Create: `tests/test_upload_metadata.py`

- [ ] **Step 1: Write failing metadata tests**

Create a complete valid metadata factory and tests that require a non-boolean positive integer:

```python
import pytest

from video2yt import upload


def valid_meta() -> dict:
    return {
        "video_path": "video.mp4",
        "thumbnail_path": "thumbnail.png",
        "title": "title",
        "description": "description",
        "tags": [],
        "category_id": "20",
        "default_language": "zh-Hant",
        "default_audio_language": "zh-Hant",
        "privacy_status": "public",
        "expected_channel_id": "channel",
        "season": 14,
    }


def test_validate_meta_accepts_positive_integer_season():
    upload.validate_meta(valid_meta())


def test_validate_meta_requires_season():
    meta = valid_meta()
    del meta["season"]
    with pytest.raises(ValueError, match="season"):
        upload.validate_meta(meta)


@pytest.mark.parametrize("season", [True, False, 0, -1, "14", 14.0, None])
def test_validate_meta_rejects_invalid_season(season):
    meta = valid_meta()
    meta["season"] = season
    with pytest.raises(ValueError, match="positive integer"):
        upload.validate_meta(meta)
```

- [ ] **Step 2: Run the tests and confirm RED**

Run: `uv run --extra dev pytest tests/test_upload_metadata.py -q`

Expected: missing season is accepted or an invalid season is accepted, so at least one test fails.

- [ ] **Step 3: Implement minimal validation**

Add `season` to `REQUIRED_META_FIELDS`, then append this validation after the missing-key check:

```python
    if missing:
        raise ValueError(f"metadata missing required keys: {missing}")
    season = meta["season"]
    if isinstance(season, bool) or not isinstance(season, int) or season < 1:
        raise ValueError("metadata season must be a positive integer")
```

- [ ] **Step 4: Run the metadata tests and confirm GREEN**

Run: `uv run --extra dev pytest tests/test_upload_metadata.py -q`

Expected: all tests pass.

### Task 2: Separate season routing from topical routing

**Files:**
- Modify: `src/video2yt/playlists.py:1-156`
- Modify: `src/video2yt/upload_cli.py:95-98`
- Modify: `tests/test_playlists.py:1-104`

- [ ] **Step 1: Replace catch-all expectations with failing season-routing tests**

Use these constants and expectations:

```python
S13 = "英雄戰場 S13 流派教學"
S14 = "英雄戰場 S14 流派教學"
ANOMALY = "英雄戰場 異變玩法教學"
COUNTER = "英雄戰場 剋制與轉型教學"
GUO = "郭楓荷 實戰教學"


def test_classify_uses_explicit_season_not_new_season_title():
    title = "新賽季抉擇野豬完整教學 | 郭楓荷"
    assert playlists.classify(title, 14) == [S14, GUO]
    assert playlists.classify(title, 13) == [S13, GUO]


def test_classify_includes_exactly_one_season_playlist():
    got = playlists.classify("黃金箭異變完整教學 | 郭楓荷", 14)
    assert got == [S14, ANOMALY, GUO]
    assert sum(name.startswith("英雄戰場 S") for name in got) == 1


def test_classify_never_recreates_retired_catchall():
    assert "爐石戰記：英雄戰場 流派教學全集" not in playlists.classify("任意教學", 14)
```

Update every existing test call from `playlists.add_video(yt, "vid", title)` to `playlists.add_video(yt, "vid", title, 14)` and expect `S14` in place of the retired catch-all.

- [ ] **Step 2: Run focused tests and confirm RED**

Run: `uv run --extra dev pytest tests/test_playlists.py -q`

Expected: `classify()` rejects the season argument and old catch-all assertions fail.

- [ ] **Step 3: Implement season targets and topical-only rules**

Remove the always-true catch-all entry from `PLAYLIST_RULES` and add:

```python
def season_playlist_title(season: int) -> str:
    return f"英雄戰場 S{season} 流派教學"


def season_playlist_description(season: int) -> str:
    suffix = "，持續更新" if season == 14 else ""
    return f"爐石戰記：英雄戰場第 {season} 賽季流派完整教學與實戰{suffix}。#英雄戰場教學"


def classify_topic(title: str) -> list[str]:
    return [name for name, _desc, match in PLAYLIST_RULES if match(title)]


def classify(title: str, season: int) -> list[str]:
    return [season_playlist_title(season), *classify_topic(title)]


def playlist_definitions(title: str, season: int) -> list[tuple[str, str]]:
    matched = set(classify(title, season))
    definitions = [
        (season_playlist_title(season), season_playlist_description(season)),
        *((name, desc) for name, desc, _match in PLAYLIST_RULES),
    ]
    return [(name, desc) for name, desc in definitions if name in matched]
```

Change `add_video` to accept `season: int`, iterate over `playlist_definitions(title, season)`, and retain its existing idempotent behavior. Change the upload call to:

```python
playlists.add_video(youtube, video_id, meta["title"], meta["season"], log=_log)
```

- [ ] **Step 4: Run playlist and metadata tests and confirm GREEN**

Run: `uv run --extra dev pytest tests/test_playlists.py tests/test_upload_metadata.py -q`

Expected: all tests pass.

### Task 3: Add exact playlist mutation helpers

**Files:**
- Modify: `src/video2yt/playlists.py`
- Modify: `tests/test_playlists.py`

- [ ] **Step 1: Extend the fake API and write failing helper tests**

Make fake playlist items include stable membership IDs and support deletion. Add these tests:

```python
def test_playlist_members_map_video_to_membership_id():
    yt = FakeYouTube({S13: {"id": "PL13", "videos": ["old", "s14"]}})
    assert playlists.playlist_members(yt, "PL13") == {
        "old": "PLI_PL13_old",
        "s14": "PLI_PL13_s14",
    }


def test_remove_video_deletes_only_exact_membership():
    yt = FakeYouTube({S13: {"id": "PL13", "videos": ["old", "s14", "other"]}})
    assert playlists.remove_video(yt, "PL13", "s14") is True
    assert yt.store[S13]["videos"] == ["old", "other"]
    assert playlists.remove_video(yt, "PL13", "missing") is False


def test_rename_playlist_preserves_id_and_members():
    yt = FakeYouTube({"old title": {"id": "PL13", "videos": ["one"]}})
    playlists.rename_playlist(yt, "PL13", "new title", "new description")
    assert yt.store["new title"] == {"id": "PL13", "videos": ["one"]}
```

- [ ] **Step 2: Run helper tests and confirm RED**

Run: `uv run --extra dev pytest tests/test_playlists.py -q`

Expected: helper attributes are missing.

- [ ] **Step 3: Implement paginated membership lookup, exact removal, and rename**

Add these functions:

```python
def playlist_members(youtube, playlist_id: str) -> dict[str, str]:
    items = _list_all(
        lambda tok: youtube.playlistItems().list(
            part="id,contentDetails",
            playlistId=playlist_id,
            maxResults=50,
            pageToken=tok,
        )
    )
    return {item["contentDetails"]["videoId"]: item["id"] for item in items}


def remove_video(youtube, playlist_id: str, video_id: str) -> bool:
    membership_id = playlist_members(youtube, playlist_id).get(video_id)
    if membership_id is None:
        return False
    youtube.playlistItems().delete(id=membership_id).execute()
    return True


def rename_playlist(youtube, playlist_id: str, title: str, description: str) -> None:
    youtube.playlists().update(
        part="snippet",
        body={"id": playlist_id, "snippet": {"title": title, "description": description}},
    ).execute()
```

Make `playlist_video_ids(youtube, playlist_id)` return `set(playlist_members(youtube, playlist_id))` so there is one membership listing implementation.

- [ ] **Step 4: Run helper tests and confirm GREEN**

Run: `uv run --extra dev pytest tests/test_playlists.py -q`

Expected: all tests pass.

### Task 4: Build a restart-safe dry-run migration command

**Files:**
- Create: `scripts/migrate_season_playlists.py`
- Create: `tests/test_season_playlist_migration.py`

- [ ] **Step 1: Write failing migration tests**

Import the script and fake YouTube implementation, define the two fixtures, and add these tests:

```python
import copy

import pytest

from scripts import migrate_season_playlists as migration
from test_playlists import FakeYouTube


def channel_with_old_playlist():
    return FakeYouTube({
        migration.OLD_TITLE: {
            "id": "PL13",
            "videos": ["s13-video", *migration.S14_VIDEO_IDS],
        }
    })


def channel_with_old_and_renamed_playlists():
    return FakeYouTube({
        migration.OLD_TITLE: {"id": "PL_OLD", "videos": []},
        migration.S13_TITLE: {"id": "PL13", "videos": []},
    })


def test_dry_run_makes_no_writes():
    yt = channel_with_old_playlist()
    before = copy.deepcopy(yt.store)
    actions = migration.migrate(yt, apply=False, log=lambda _msg: None)
    assert yt.store == before
    assert actions == [
        "rename 爐石戰記：英雄戰場 流派教學全集 -> 英雄戰場 S13 流派教學",
        "create 英雄戰場 S14 流派教學",
        "add hZiEib2tzAs -> 英雄戰場 S14 流派教學",
        "add KXlycy1Kb1A -> 英雄戰場 S14 流派教學",
        "remove hZiEib2tzAs <- 英雄戰場 S13 流派教學",
        "remove KXlycy1Kb1A <- 英雄戰場 S13 流派教學",
    ]


def test_apply_and_rerun_are_idempotent():
    yt = channel_with_old_playlist()
    migration.migrate(yt, apply=True, log=lambda _msg: None)
    assert yt.store[migration.S13_TITLE]["videos"] == ["s13-video"]
    assert yt.store[migration.S14_TITLE]["videos"] == list(migration.S14_VIDEO_IDS)
    snapshot = copy.deepcopy(yt.store)
    assert migration.migrate(yt, apply=True, log=lambda _msg: None) == []
    assert yt.store == snapshot


def test_refuses_ambiguous_duplicate_s13_playlists():
    yt = channel_with_old_and_renamed_playlists()
    with pytest.raises(RuntimeError, match="both old and renamed"):
        migration.migrate(yt, apply=False, log=lambda _msg: None)
```

- [ ] **Step 2: Run migration tests and confirm RED**

Run: `uv run --extra dev pytest tests/test_season_playlist_migration.py -q`

Expected: import fails because the migration script does not exist.

- [ ] **Step 3: Implement migration planning and application**

Define exact constants:

```python
EXPECTED_CHANNEL_ID = "UCEgIrCo0pR6DyyrXuSn3wBg"
OLD_TITLE = "爐石戰記：英雄戰場 流派教學全集"
S13_TITLE = "英雄戰場 S13 流派教學"
S14_TITLE = "英雄戰場 S14 流派教學"
S14_VIDEO_IDS = ("hZiEib2tzAs", "KXlycy1Kb1A")
```

Implement `migrate(youtube, apply: bool, log: Callable[[str], None]) -> list[str]` as follows:

```python
def migrate(youtube, apply: bool, log: Callable[[str], None]) -> list[str]:
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
        s14_id = playlists.ensure_playlist(
            youtube, S14_TITLE, S14_DESCRIPTION, existing
        )
    for video_id in S14_VIDEO_IDS:
        if video_id not in s14_members:
            playlists.insert_video(youtube, s14_id, video_id)
    for video_id in S14_VIDEO_IDS:
        if video_id in s13_members:
            playlists.remove_video(youtube, s13_id, video_id)

    final_s13 = playlists.playlist_members(youtube, s13_id)
    final_s14 = playlists.playlist_members(youtube, s14_id)
    if any(video_id in final_s13 for video_id in S14_VIDEO_IDS):
        raise RuntimeError("postcondition failed: S14 video remains in S13")
    if any(video_id not in final_s14 for video_id in S14_VIDEO_IDS):
        raise RuntimeError("postcondition failed: S14 video missing from S14")
    return actions
```

Implement the CLI entry point:

```python
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
    if channel_ids != [EXPECTED_CHANNEL_ID]:
        log(f"error: authenticated channels {channel_ids} != [{EXPECTED_CHANNEL_ID}]")
        return 1
    migrate(youtube, apply=args.yes, log=log)
    if not args.yes:
        log("dry-run only; rerun with --yes to apply")
    return 0
```

- [ ] **Step 4: Run migration tests and confirm GREEN**

Run: `uv run --extra dev pytest tests/test_season_playlist_migration.py tests/test_playlists.py -q`

Expected: all tests pass.

### Task 5: Retire catch-all backfill and record current metadata

**Files:**
- Modify: `scripts/backfill_playlists.py:1-88`
- Modify: `output/choice_quilboar_s14/youtube_metadata.json`

- [ ] **Step 1: Update the backfill contract**

Change its module docstring to state that it backfills keyword-matched topical/streamer playlists only. Keep `targets = playlists.classify_topic(title) + MANUAL_EXTRAS.get(video_id, [])`, where `classify_topic()` returns only names from `PLAYLIST_RULES`. This prevents a future rerun from recreating the retired catch-all and avoids guessing historical seasons.

- [ ] **Step 2: Add season to the retained S14 metadata**

Insert this top-level field beside the title:

```json
"season": 14,
```

- [ ] **Step 3: Run the focused suite and diff checks**

Run:

```bash
uv run --extra dev pytest tests/test_upload_metadata.py tests/test_playlists.py tests/test_season_playlist_migration.py -q
git diff --check -- src/video2yt/upload.py src/video2yt/upload_cli.py src/video2yt/playlists.py scripts/backfill_playlists.py scripts/migrate_season_playlists.py tests/test_upload_metadata.py tests/test_playlists.py tests/test_season_playlist_migration.py
```

Expected: all tests pass and `git diff --check` emits no output.

### Task 6: Regression verification and code commit

**Files:**
- Verify all modified implementation and test files.

- [ ] **Step 1: Run playlist/upload regression tests**

Run:

```bash
uv run --extra dev pytest tests/test_upload_metadata.py tests/test_playlists.py tests/test_season_playlist_migration.py tests/test_smoke.py -q
```

Expected: all selected tests pass.

- [ ] **Step 2: Review the exact diff and preserve unrelated work**

Run:

```bash
git diff -- src/video2yt/upload.py src/video2yt/upload_cli.py src/video2yt/playlists.py scripts/backfill_playlists.py scripts/migrate_season_playlists.py tests/test_upload_metadata.py tests/test_playlists.py tests/test_season_playlist_migration.py
git status --short
```

Expected: only playlist/season changes appear in the scoped diff; unrelated dirty files remain untouched.

- [ ] **Step 3: Commit implementation files only**

Run:

```bash
git add src/video2yt/upload.py src/video2yt/upload_cli.py src/video2yt/playlists.py scripts/backfill_playlists.py scripts/migrate_season_playlists.py tests/test_upload_metadata.py tests/test_playlists.py tests/test_season_playlist_migration.py
git commit -m "feat: separate playlists by Battlegrounds season"
```

Expected: one feature commit; unrelated working-tree changes remain unstaged.

### Task 7: Dry-run, apply, and verify the live YouTube migration

**Files:**
- Execute: `scripts/migrate_season_playlists.py`

- [ ] **Step 1: Run the read-only migration preview**

Run: `uv run python scripts/migrate_season_playlists.py`

Expected: exactly one rename, one create, two S14 additions, and two S13 removals; no YouTube state changes.

- [ ] **Step 2: Compare dry-run state with exact live IDs**

Confirm the S13 source playlist ID remains `PLUjHFTzDRBtI`, the migration targets only `hZiEib2tzAs` and `KXlycy1Kb1A`, and `-FK8EETGaDc` is not in any removal action.

- [ ] **Step 3: Apply the migration**

Run: `uv run python scripts/migrate_season_playlists.py --yes`

Expected: rename/create/add/remove operations complete and postcondition verification passes.

- [ ] **Step 4: Rerun the migration to prove idempotence**

Run: `uv run python scripts/migrate_season_playlists.py --yes`

Expected: no planned actions and verification still passes.

- [ ] **Step 5: Independently query final playlist state**

Use the authenticated YouTube Data API to list public playlists and memberships. Verify:

```text
英雄戰場 S13 流派教學: does not contain hZiEib2tzAs or KXlycy1Kb1A
英雄戰場 S14 流派教學: contains hZiEib2tzAs, KXlycy1Kb1A in that order
郭楓荷 實戰教學: still contains hZiEib2tzAs and KXlycy1Kb1A
爐石戰記：英雄戰場 流派教學全集: absent
```

- [ ] **Step 6: Report playlist URLs and verification evidence**

Return the final S13 and S14 YouTube playlist URLs, code commit, test count, and independently queried membership result.
