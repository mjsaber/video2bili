"""Tests for video2yt-prefetch (serial Stage 1 cache pre-download).

All external work is mocked at the video2yt.fetch.fetch_and_build seam —
no network, no real subprocess.
"""
from video2yt import fetch, prefetch_cli, validate
from video2yt.download import TruncatedDownloadError


def _make_result(tmp_path, bv="BV1", width=1920, height=1080,
                 from_cache=False, write_files=False):
    """Build a FetchResult pointing at files under a per-segment subdir.

    write_files=True actually creates the mp4 + xml on disk so quarantine
    behavior can be asserted.
    """
    sub = tmp_path / "uploader：title"
    sub.mkdir(parents=True, exist_ok=True)
    mp4 = sub / f"{bv}.mp4"
    xml = sub / f"{bv}.danmaku.xml"
    if write_files:
        mp4.write_bytes(b"v")
        xml.write_bytes(b"<i></i>")
    return fetch.FetchResult(
        bv_id=bv, raw_video=mp4, danmaku_xml=xml,
        danmaku_ass=sub / f"{bv}.danmaku.ass",
        metadata={"title": "some title"},
        info=validate.MediaInfo(
            duration=100.0, width=width, height=height,
            has_video=True, has_audio=True, vcodec="h264",
            acodec="aac", size_bytes=1,
        ),
        from_cache=from_cache, n_danmaku=3, temp_subdir=sub, elapsed=1.0,
    )


def test_parse_args_accepts_multiple_urls():
    args = prefetch_cli.parse_args(["u/BV1", "u/BV2", "-o", "/tmp/x", "-q", "720"])
    assert args.urls == ["u/BV1", "u/BV2"]
    assert args.quality == 720
    assert str(args.temp_dir) == "/tmp/x"


def test_single_url_success(tmp_path, monkeypatch):
    monkeypatch.setattr("video2yt.prefetch_cli.preflight", lambda: None)
    monkeypatch.setattr(
        "video2yt.fetch.fetch_and_build",
        lambda **kw: _make_result(tmp_path),
    )
    rc = prefetch_cli.main(["https://x/video/BV1", "-o", str(tmp_path)])
    assert rc == 0


def test_cache_hit_reported(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("video2yt.prefetch_cli.preflight", lambda: None)
    monkeypatch.setattr(
        "video2yt.fetch.fetch_and_build",
        lambda **kw: _make_result(tmp_path, from_cache=True),
    )
    rc = prefetch_cli.main(["https://x/video/BV1", "-o", str(tmp_path)])
    assert rc == 0
    assert "cached" in capsys.readouterr().err


def test_truncation_retries_then_succeeds(tmp_path, monkeypatch):
    calls = {"n": 0}

    def fab(**kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise TruncatedDownloadError("truncated audio")
        return _make_result(tmp_path)

    monkeypatch.setattr("video2yt.prefetch_cli.preflight", lambda: None)
    monkeypatch.setattr("video2yt.fetch.fetch_and_build", fab)
    rc = prefetch_cli.main(["https://x/video/BV1", "-o", str(tmp_path)])
    assert rc == 0
    assert calls["n"] == 2  # one retry


def test_truncation_exhausts_retries_fail_fast(tmp_path, monkeypatch, capsys):
    calls = {"n": 0}

    def fab(**kw):
        calls["n"] += 1
        raise TruncatedDownloadError("truncated audio")

    monkeypatch.setattr("video2yt.prefetch_cli.preflight", lambda: None)
    monkeypatch.setattr("video2yt.fetch.fetch_and_build", fab)
    rc = prefetch_cli.main(["https://x/video/BV1", "-o", str(tmp_path)])
    assert rc == 1
    assert calls["n"] == prefetch_cli.MAX_ATTEMPTS  # 3 attempts, no more
    assert "truncated" in capsys.readouterr().err.lower()


def test_low_resolution_fails_fast(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("video2yt.prefetch_cli.preflight", lambda: None)
    monkeypatch.setattr(
        "video2yt.fetch.fetch_and_build",
        lambda **kw: _make_result(tmp_path, width=854, height=480, write_files=True),
    )
    rc = prefetch_cli.main(["https://x/video/BV1", "-o", str(tmp_path), "-q", "1080"])
    assert rc == 1
    assert "480" in capsys.readouterr().err


def test_low_resolution_quarantines_cache(tmp_path, monkeypatch):
    """The bad low-res files must be renamed past download.fetch's cache
    probe globs so a later Step 6 run re-downloads instead of cache-hitting."""
    result = _make_result(tmp_path, bv="BV1", width=854, height=480, write_files=True)
    monkeypatch.setattr("video2yt.prefetch_cli.preflight", lambda: None)
    monkeypatch.setattr("video2yt.fetch.fetch_and_build", lambda **kw: result)

    rc = prefetch_cli.main(["https://x/video/BV1", "-o", str(tmp_path), "-q", "1080"])
    assert rc == 1
    # original cache files gone, quarantined copies present
    assert not result.raw_video.exists()
    assert (result.temp_subdir / "BV1.mp4.lowres").exists()
    assert not result.danmaku_xml.exists()
    assert (result.temp_subdir / "BV1.danmaku.xml.lowres").exists()


def test_multi_url_fail_fast_stops_remaining(tmp_path, monkeypatch):
    """A failure on URL 2 must stop the batch — URL 3 is never attempted."""
    seen = []

    def fab(*, url, **kw):
        seen.append(url)
        if url.endswith("BV2"):
            raise FileNotFoundError("yt-dlp produced no video file")
        return _make_result(tmp_path, bv="BV1")

    monkeypatch.setattr("video2yt.prefetch_cli.preflight", lambda: None)
    monkeypatch.setattr("video2yt.fetch.fetch_and_build", fab)
    rc = prefetch_cli.main(["u/BV1", "u/BV2", "u/BV3", "-o", str(tmp_path)])
    assert rc == 1
    assert seen == ["u/BV1", "u/BV2"]  # BV3 never attempted
