"""Tests for the one-time S13/S14 YouTube playlist migration."""

import copy
import importlib.util

import pytest

from scripts import migrate_season_playlists as migration
from tests.test_playlists import FakeYouTube


def test_migration_command_module_exists():
    assert importlib.util.find_spec("scripts.migrate_season_playlists") is not None


def channel_with_old_playlist():
    return FakeYouTube({
        migration.OLD_TITLE: {
            "id": "PL13",
            "videos": ["s13-video", *migration.S14_VIDEO_IDS],
        }
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


def test_apply_resumes_partially_migrated_state():
    first, second = migration.S14_VIDEO_IDS
    yt = FakeYouTube({
        migration.S13_TITLE: {"id": "PL13", "videos": ["s13-video", second]},
        migration.S14_TITLE: {"id": "PL14", "videos": [first]},
    })

    migration.migrate(yt, apply=True, log=lambda _msg: None)

    assert yt.store[migration.S13_TITLE]["videos"] == ["s13-video"]
    assert yt.store[migration.S14_TITLE]["videos"] == [first, second]


def test_refuses_ambiguous_duplicate_s13_playlists():
    yt = FakeYouTube({
        migration.OLD_TITLE: {"id": "PL_OLD", "videos": []},
        migration.S13_TITLE: {"id": "PL13", "videos": []},
    })

    with pytest.raises(RuntimeError, match="both old and renamed"):
        migration.migrate(yt, apply=False, log=lambda _msg: None)


def test_refuses_missing_s13_source_playlist():
    with pytest.raises(RuntimeError, match="neither old nor renamed"):
        migration.migrate(FakeYouTube(), apply=False, log=lambda _msg: None)


def test_wait_for_postconditions_polls_until_memberships_converge(monkeypatch):
    first, second = migration.S14_VIDEO_IDS
    responses = {
        "PL13": iter([{first: "stale-membership"}, {}]),
        "PL14": iter([
            {first: "one", second: "two"},
            {first: "one", second: "two"},
        ]),
    }
    sleeps = []
    monkeypatch.setattr(
        migration.playlists,
        "playlist_members",
        lambda _youtube, playlist_id: next(responses[playlist_id]),
    )
    monkeypatch.setattr(migration.time, "sleep", lambda seconds: sleeps.append(seconds))

    migration._wait_for_postconditions(object(), "PL13", "PL14", attempts=2, delay=3.0)

    assert sleeps == [3.0]
