"""Tests for explicit-season + keyword playlist routing and mutations."""

import httplib2
import pytest
from googleapiclient.errors import HttpError

from scripts import backfill_playlists
from video2yt import playlists

S13 = "英雄戰場 S13 流派教學"
S14 = "英雄戰場 S14 流派教學"
ANOMALY = "英雄戰場 異變玩法教學"
COUNTER = "英雄戰場 剋制與轉型教學"
GUO = "郭楓荷 實戰教學"


class _Request:
    def __init__(self, response):
        self._response = response

    def execute(self):
        return self._response


class _FakePlaylists:
    def __init__(self, store):
        self.store = store  # title -> {"id": ..., "videos": [...]}

    def list(self, part, mine, maxResults, pageToken=None):
        items = [
            {"id": v["id"], "snippet": {"title": title}}
            for title, v in self.store.items()
        ]
        return _Request({"items": items})

    def insert(self, part, body):
        title = body["snippet"]["title"]
        playlist_id = f"PL_{len(self.store)}"
        self.store[title] = {"id": playlist_id, "videos": []}
        return _Request({"id": playlist_id})

    def update(self, part, body):
        playlist_id = body["id"]
        old_title = next(title for title, value in self.store.items() if value["id"] == playlist_id)
        value = self.store.pop(old_title)
        self.store[body["snippet"]["title"]] = value
        return _Request({"id": playlist_id})


class _FakePlaylistItems:
    def __init__(self, store):
        self.store = store

    def _by_id(self, playlist_id):
        for v in self.store.values():
            if v["id"] == playlist_id:
                return v
        raise KeyError(playlist_id)

    def list(self, part, playlistId, maxResults, pageToken=None):
        items = [
            {
                "id": f"PLI::{playlistId}::{vid}",
                "contentDetails": {"videoId": vid},
            }
            for vid in self._by_id(playlistId)["videos"]
        ]
        return _Request({"items": items})

    def insert(self, part, body):
        playlist_id = body["snippet"]["playlistId"]
        video_id = body["snippet"]["resourceId"]["videoId"]
        self._by_id(playlist_id)["videos"].append(video_id)
        return _Request({})

    def delete(self, id):
        prefix, playlist_id, video_id = id.split("::", 2)
        assert prefix == "PLI"
        self._by_id(playlist_id)["videos"].remove(video_id)
        return _Request({})


class FakeYouTube:
    def __init__(self, store=None):
        self.store = store if store is not None else {}
        self._playlists = _FakePlaylists(self.store)
        self._items = _FakePlaylistItems(self.store)

    def playlists(self):
        return self._playlists

    def playlistItems(self):
        return self._items


def test_classify_uses_explicit_season_not_new_season_title():
    title = "新賽季抉擇野豬完整教學 | 郭楓荷"
    assert classify_names(title, 14) == [S14, GUO]
    assert classify_names(title, 13) == [S13, GUO]


def classify_names(title, season=14):
    return playlists.classify(title, season)


def test_classify_includes_exactly_one_season_playlist():
    got = classify_names("黃金箭異變完整教學 | 郭楓荷", 14)
    assert got == [S14, ANOMALY, GUO]
    assert sum(name.startswith("英雄戰場 S") for name in got) == 1


def test_classify_never_recreates_retired_catchall():
    retired = "爐石戰記：英雄戰場 流派教學全集"
    assert retired not in classify_names("任意教學", 14)


def test_backfill_targets_only_topical_playlists():
    assert backfill_playlists.targets_for_video("video", "任意教學") == []
    assert backfill_playlists.targets_for_video("video", "黃金箭異變教學") == [ANOMALY]


def test_classify_anomaly_keyword():
    got = classify_names("「爐石戰記：英雄戰場」新賽季黃金箭異變完整教學 | 郭楓荷 × Kimmy")
    assert got == [S14, ANOMALY, GUO]


def test_classify_counter_and_transform_keywords():
    assert COUNTER in classify_names("雙重縫針用法＋剋制完整教學")
    assert COUNTER in classify_names("食料惡魔完整轉型教學")
    assert COUNTER not in classify_names("死海流 四千攻完虐四萬背靠背")


def test_classify_guo_keyword():
    assert GUO in classify_names("死海流教學 | 郭楓荷 實戰")
    assert GUO not in classify_names("跳蛙野獸 | 瓦莉拉 × Kimmy 實戰")


def test_add_video_creates_playlists_and_inserts():
    yt = FakeYouTube()
    added = playlists.add_video(yt, "vid1", "異變搖旗吶喊教學 | 郭楓荷 實戰", 14)
    assert added == [S14, ANOMALY, GUO]
    assert yt.store[S14]["videos"] == ["vid1"]
    assert yt.store[ANOMALY]["videos"] == ["vid1"]
    assert yt.store[GUO]["videos"] == ["vid1"]
    assert COUNTER not in yt.store  # unmatched playlists are not created


def test_add_video_is_idempotent():
    yt = FakeYouTube()
    playlists.add_video(yt, "vid1", "跳蛙野獸教學", 14)
    added_again = playlists.add_video(yt, "vid1", "跳蛙野獸教學", 14)
    assert added_again == []
    assert yt.store[S14]["videos"] == ["vid1"]


def test_add_video_reuses_existing_playlist():
    yt = FakeYouTube({S14: {"id": "PL_existing", "videos": ["old"]}})
    playlists.add_video(yt, "vid2", "任意教學", 14)
    assert yt.store[S14]["videos"] == ["old", "vid2"]


def _http_error(status, content=b""):
    return HttpError(httplib2.Response({"status": status}), content)


class _FlakyRequest:
    """Raises 404 for the first n executes, then returns the response."""

    def __init__(self, response, failures):
        self._response = response
        self._failures = failures

    def execute(self):
        if self._failures > 0:
            self._failures -= 1
            raise _http_error(404)
        return self._response


def test_execute_retrying_404_recovers(monkeypatch):
    monkeypatch.setattr(playlists.time, "sleep", lambda s: None)
    req = _FlakyRequest({"items": []}, failures=2)
    assert playlists._execute_retrying_404(req) == {"items": []}


def test_execute_retrying_404_gives_up(monkeypatch):
    monkeypatch.setattr(playlists.time, "sleep", lambda s: None)
    req = _FlakyRequest({"items": []}, failures=10)
    with pytest.raises(HttpError):
        playlists._execute_retrying_404(req)


def test_execute_retrying_404_does_not_retry_other_errors(monkeypatch):
    calls = []
    monkeypatch.setattr(playlists.time, "sleep", lambda s: calls.append(s))

    class _Fail500:
        def execute(self):
            raise _http_error(500)

    with pytest.raises(HttpError):
        playlists._execute_retrying_404(_Fail500())
    assert calls == []  # no retry sleeps for non-404


def test_execute_retrying_404_recovers_service_unavailable_409(monkeypatch):
    monkeypatch.setattr(playlists.time, "sleep", lambda _seconds: None)

    class _Transient409:
        def __init__(self):
            self.calls = 0

        def execute(self):
            self.calls += 1
            if self.calls == 1:
                raise _http_error(
                    409,
                    b'{"error":{"errors":[{"reason":"SERVICE_UNAVAILABLE"}]}}',
                )
            return {"id": "inserted"}

    assert playlists._execute_retrying_404(_Transient409()) == {"id": "inserted"}


def test_ensure_playlist_updates_existing_map_in_place():
    yt = FakeYouTube()
    existing = {}
    pid = playlists.ensure_playlist(yt, S14, "desc", existing)
    assert existing[S14] == pid
    # second call hits the map, not the API
    assert playlists.ensure_playlist(yt, S14, "desc", existing) == pid


def test_playlist_members_map_video_to_membership_id():
    yt = FakeYouTube({S13: {"id": "PL13", "videos": ["old", "s14"]}})

    assert playlists.playlist_members(yt, "PL13") == {
        "old": "PLI::PL13::old",
        "s14": "PLI::PL13::s14",
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
