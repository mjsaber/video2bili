"""Tests for music_mix.py — CC0 bed build + .music_bed_meta.json cache.

Mocks the subprocess.run boundary (no real ffmpeg invoked) AND the
music_library functions (no real cache dir touched).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from video2yt import meta, music_library, music_mix, music_mix_cli, validate
from video2yt.validate import MediaInfo


# ---------- fixtures ----------

@dataclass
class _FakeTrack:
    path: Path
    duration: float


def _track(tmp_path: Path, name: str, duration: float) -> music_library.Track:
    """Return a real music_library.Track (matches scan_cache output shape)."""
    p = tmp_path / f"{name}.mp3"
    p.write_bytes(b"FAKE-AUDIO")
    return music_library.Track(name=name, path=p, duration=duration)


def _fake_probe(duration=60.0, width=1920, height=1080):
    info = MediaInfo(
        duration=duration, width=width, height=height,
        has_video=True, has_audio=True,
        vcodec="h264", acodec="aac", size_bytes=10_000_000,
    )
    return lambda path: info


def _setup_mp4(tmp_path: Path, name: str = "BV1") -> Path:
    seg = tmp_path / "seg"
    seg.mkdir()
    mp4 = seg / f"{name}.mp4"
    mp4.write_bytes(b"fake-mp4-bytes")
    return mp4


def _patch_music_library(monkeypatch, tracks: list, attribution: list[str],
                         manifest: list[dict] | None = None):
    """Replace the music_library entry points with mocks that don't touch
    disk or the network."""
    manifest = manifest or [{"name": "Track1", "url": "https://example.com/Track1.mp3",
                             "attribution": "Track1 by X — CC BY 3.0"}]
    monkeypatch.setattr("video2yt.music_mix.music_library.load_manifest",
                       lambda: manifest)
    monkeypatch.setattr("video2yt.music_mix.music_library.ensure_manifest_cached",
                       lambda m, d: None)
    monkeypatch.setattr("video2yt.music_mix.music_library.scan_cache",
                       lambda d: tracks)
    monkeypatch.setattr(
        "video2yt.music_mix.music_library.select_sequence",
        lambda pool, target_duration, crossfade, seed: tracks,
    )
    monkeypatch.setattr(
        "video2yt.music_mix.music_library.attribution_lines",
        lambda tracks, manifest: attribution,
    )


def _fake_ffmpeg(captured: list):
    def _run(cmd, **kwargs):
        captured.append(cmd)
        # Find the output path (last positional in our build_music_bed argv).
        out = Path(cmd[-1])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"PCM-BED")
        return MagicMock(returncode=0, stdout="", stderr="")
    return _run


# ---------- core behavior ----------

def test_render_first_run_builds_bed_credits_and_sidecar(tmp_path, monkeypatch):
    mp4 = _setup_mp4(tmp_path)
    monkeypatch.setattr("video2yt.music_mix.validate.probe", _fake_probe(60.0))
    tracks = [_track(tmp_path, "T1", 30.0), _track(tmp_path, "T2", 30.0)]
    _patch_music_library(monkeypatch, tracks, ["Track1 by X — CC BY 3.0"])
    ffmpeg_calls = []
    monkeypatch.setattr("video2yt.music_mix.subprocess.run",
                       _fake_ffmpeg(ffmpeg_calls))

    result = music_mix.render(mp4)
    assert result.from_cache is False
    assert result.bed_wav.exists()
    assert result.credits_txt.exists()
    assert result.meta_path.exists()
    assert result.tracks_used == 2
    # ffmpeg was invoked once for the bed build.
    assert len(ffmpeg_calls) == 1

    # Credits text contains the attribution line.
    body = result.credits_txt.read_text(encoding="utf-8")
    assert "Track1 by X — CC BY 3.0" in body
    assert "paste these lines" in body  # header preserved

    # Sidecar records the expected key.
    recorded = json.loads(result.meta_path.read_text())
    assert recorded["duration"] == 60.0
    assert recorded["width"] == 1920
    assert recorded["height"] == 1080


def test_render_warm_cache_skips_ffmpeg(tmp_path, monkeypatch):
    """All three outputs present + matching sidecar → ffmpeg NOT invoked."""
    mp4 = _setup_mp4(tmp_path)
    monkeypatch.setattr("video2yt.music_mix.validate.probe", _fake_probe(60.0))

    bed_path = mp4.with_name(mp4.stem + music_mix.BED_FILENAME_SUFFIX)
    credits_path = mp4.with_name(mp4.stem + music_mix.CREDITS_FILENAME_SUFFIX)
    meta_path = mp4.with_name(mp4.stem + music_mix.META_FILENAME_SUFFIX)
    bed_path.write_bytes(b"PCM-CACHED")
    credits_path.write_text("cached credits")
    meta.write_meta(meta_path, {"duration": 60.0, "width": 1920, "height": 1080})

    ffmpeg_calls = []
    monkeypatch.setattr("video2yt.music_mix.subprocess.run",
                       _fake_ffmpeg(ffmpeg_calls))

    result = music_mix.render(mp4)
    assert result.from_cache is True
    assert ffmpeg_calls == []


def test_render_stale_duration_rebuilds(tmp_path, monkeypatch):
    """Recorded duration off by more than the tolerance → rebuild."""
    mp4 = _setup_mp4(tmp_path)
    # Current duration is 60s but sidecar recorded 30s (way past tolerance).
    monkeypatch.setattr("video2yt.music_mix.validate.probe", _fake_probe(60.0))
    bed_path = mp4.with_name(mp4.stem + music_mix.BED_FILENAME_SUFFIX)
    credits_path = mp4.with_name(mp4.stem + music_mix.CREDITS_FILENAME_SUFFIX)
    meta_path = mp4.with_name(mp4.stem + music_mix.META_FILENAME_SUFFIX)
    bed_path.write_bytes(b"OLD")
    credits_path.write_text("old")
    meta.write_meta(meta_path, {"duration": 30.0, "width": 1920, "height": 1080})

    tracks = [_track(tmp_path, "T1", 60.0)]
    _patch_music_library(monkeypatch, tracks, [])
    ffmpeg_calls = []
    monkeypatch.setattr("video2yt.music_mix.subprocess.run",
                       _fake_ffmpeg(ffmpeg_calls))

    result = music_mix.render(mp4)
    assert result.from_cache is False
    assert len(ffmpeg_calls) == 1
    # Sidecar updated.
    recorded = json.loads(meta_path.read_text())
    assert recorded["duration"] == 60.0


def test_render_duration_drift_within_tolerance_still_cache_hits(
    tmp_path, monkeypatch,
):
    """ffprobe sometimes jitters by ~10-100ms across runs on the same file;
    that must NOT invalidate the bed."""
    mp4 = _setup_mp4(tmp_path)
    monkeypatch.setattr("video2yt.music_mix.validate.probe", _fake_probe(60.4))

    bed_path = mp4.with_name(mp4.stem + music_mix.BED_FILENAME_SUFFIX)
    credits_path = mp4.with_name(mp4.stem + music_mix.CREDITS_FILENAME_SUFFIX)
    meta_path = mp4.with_name(mp4.stem + music_mix.META_FILENAME_SUFFIX)
    bed_path.write_bytes(b"PCM")
    credits_path.write_text("c")
    meta.write_meta(meta_path, {"duration": 60.0, "width": 1920, "height": 1080})

    ffmpeg_calls = []
    monkeypatch.setattr("video2yt.music_mix.subprocess.run",
                       _fake_ffmpeg(ffmpeg_calls))

    result = music_mix.render(mp4)
    # 60.4 - 60.0 = 0.4s, within DURATION_TOLERANCE_SECONDS=0.5
    assert result.from_cache is True
    assert ffmpeg_calls == []


def test_render_width_change_invalidates_even_if_duration_matches(
    tmp_path, monkeypatch,
):
    """Same duration but different width = user re-fetched at different
    quality. Invalidate so stems-stage and music-mix stay aligned."""
    mp4 = _setup_mp4(tmp_path)
    monkeypatch.setattr("video2yt.music_mix.validate.probe",
                       _fake_probe(60.0, width=854, height=480))

    bed_path = mp4.with_name(mp4.stem + music_mix.BED_FILENAME_SUFFIX)
    credits_path = mp4.with_name(mp4.stem + music_mix.CREDITS_FILENAME_SUFFIX)
    meta_path = mp4.with_name(mp4.stem + music_mix.META_FILENAME_SUFFIX)
    bed_path.write_bytes(b"OLD")
    credits_path.write_text("old")
    meta.write_meta(meta_path, {"duration": 60.0, "width": 1920, "height": 1080})

    tracks = [_track(tmp_path, "T1", 60.0)]
    _patch_music_library(monkeypatch, tracks, [])
    ffmpeg_calls = []
    monkeypatch.setattr("video2yt.music_mix.subprocess.run",
                       _fake_ffmpeg(ffmpeg_calls))

    result = music_mix.render(mp4)
    assert result.from_cache is False
    assert len(ffmpeg_calls) == 1


def test_render_force_bypasses_cache(tmp_path, monkeypatch):
    mp4 = _setup_mp4(tmp_path)
    monkeypatch.setattr("video2yt.music_mix.validate.probe", _fake_probe(60.0))

    bed_path = mp4.with_name(mp4.stem + music_mix.BED_FILENAME_SUFFIX)
    credits_path = mp4.with_name(mp4.stem + music_mix.CREDITS_FILENAME_SUFFIX)
    meta_path = mp4.with_name(mp4.stem + music_mix.META_FILENAME_SUFFIX)
    bed_path.write_bytes(b"OLD")
    credits_path.write_text("old")
    meta.write_meta(meta_path, {"duration": 60.0, "width": 1920, "height": 1080})

    tracks = [_track(tmp_path, "T1", 60.0)]
    _patch_music_library(monkeypatch, tracks, ["A — CC BY"])
    ffmpeg_calls = []
    monkeypatch.setattr("video2yt.music_mix.subprocess.run",
                       _fake_ffmpeg(ffmpeg_calls))

    result = music_mix.render(mp4, force=True)
    assert result.from_cache is False
    assert len(ffmpeg_calls) == 1


def test_render_missing_credits_invalidates_cache(tmp_path, monkeypatch):
    """If the credits txt was manually deleted, the cache must rebuild
    (the YouTube description needs that file)."""
    mp4 = _setup_mp4(tmp_path)
    monkeypatch.setattr("video2yt.music_mix.validate.probe", _fake_probe(60.0))

    bed_path = mp4.with_name(mp4.stem + music_mix.BED_FILENAME_SUFFIX)
    meta_path = mp4.with_name(mp4.stem + music_mix.META_FILENAME_SUFFIX)
    bed_path.write_bytes(b"PCM")
    meta.write_meta(meta_path, {"duration": 60.0, "width": 1920, "height": 1080})
    # NO credits.txt

    tracks = [_track(tmp_path, "T1", 60.0)]
    _patch_music_library(monkeypatch, tracks, ["A — CC BY"])
    ffmpeg_calls = []
    monkeypatch.setattr("video2yt.music_mix.subprocess.run",
                       _fake_ffmpeg(ffmpeg_calls))

    result = music_mix.render(mp4)
    assert result.from_cache is False
    assert len(ffmpeg_calls) == 1


# ---------- credits content ----------

def test_render_credits_excludes_tracks_without_attribution(tmp_path, monkeypatch):
    """A YouTube-Audio-Library track (no manifest entry → empty attribution
    list) must not contaminate the credits with bogus lines."""
    mp4 = _setup_mp4(tmp_path)
    monkeypatch.setattr("video2yt.music_mix.validate.probe", _fake_probe(60.0))
    tracks = [_track(tmp_path, "yt_audio_lib_track", 60.0)]
    # attribution_lines returns [] because the track has no manifest entry.
    _patch_music_library(monkeypatch, tracks, attribution=[])
    monkeypatch.setattr("video2yt.music_mix.subprocess.run",
                       _fake_ffmpeg([]))

    result = music_mix.render(mp4)
    body = result.credits_txt.read_text(encoding="utf-8")
    # Header still present...
    assert "paste these lines" in body
    # ...but no attribution lines (only the header + blank lines).
    assert "CC BY" not in body


# ---------- propagation ----------

def test_render_forwards_seed_and_crossfade_to_select_sequence(
    tmp_path, monkeypatch,
):
    """--seed and --crossfade must reach music_library.select_sequence so
    deterministic seeded runs and tunable crossfades actually work."""
    mp4 = _setup_mp4(tmp_path)
    monkeypatch.setattr("video2yt.music_mix.validate.probe", _fake_probe(60.0))
    tracks = [_track(tmp_path, "T1", 60.0)]
    captured = {}
    def fake_select(pool, target_duration, crossfade, seed):
        captured["seed"] = seed
        captured["crossfade"] = crossfade
        captured["target_duration"] = target_duration
        return tracks
    monkeypatch.setattr("video2yt.music_mix.music_library.load_manifest",
                       lambda: [])
    monkeypatch.setattr("video2yt.music_mix.music_library.ensure_manifest_cached",
                       lambda m, d: None)
    monkeypatch.setattr("video2yt.music_mix.music_library.scan_cache",
                       lambda d: tracks)
    monkeypatch.setattr("video2yt.music_mix.music_library.select_sequence",
                       fake_select)
    monkeypatch.setattr("video2yt.music_mix.music_library.attribution_lines",
                       lambda t, m: [])
    monkeypatch.setattr("video2yt.music_mix.subprocess.run", _fake_ffmpeg([]))

    music_mix.render(mp4, crossfade=3.5, seed=42)
    assert captured["seed"] == 42
    assert captured["crossfade"] == 3.5
    assert captured["target_duration"] == 60.0


def test_render_forwards_crossfade_to_build_music_bed(tmp_path, monkeypatch):
    """The crossfade param must also reach the ffmpeg filtergraph (the
    acrossfade=d= duration). Otherwise --crossfade 5 wouldn't actually
    change the bed."""
    mp4 = _setup_mp4(tmp_path)
    monkeypatch.setattr("video2yt.music_mix.validate.probe", _fake_probe(60.0))
    tracks = [_track(tmp_path, "T1", 30.0), _track(tmp_path, "T2", 35.0)]
    _patch_music_library(monkeypatch, tracks, [])
    ffmpeg_calls = []
    monkeypatch.setattr("video2yt.music_mix.subprocess.run",
                       _fake_ffmpeg(ffmpeg_calls))

    music_mix.render(mp4, crossfade=4.0)
    assert len(ffmpeg_calls) == 1
    # The filter_complex string contains acrossfade=d=4.000
    fc_idx = ffmpeg_calls[0].index("-filter_complex") + 1
    fc_string = ffmpeg_calls[0][fc_idx]
    assert "acrossfade=d=4.000" in fc_string
    # And the tail afade also uses 4.000.
    assert "afade=t=out:" in fc_string
    assert "d=4.000" in fc_string


# ---------- CLI ----------

def test_parse_args_defaults():
    args = music_mix_cli.parse_args(["/tmp/BV.mp4"])
    assert args.raw_mp4 == Path("/tmp/BV.mp4")
    assert args.crossfade == 2.0
    assert args.seed is None
    assert args.force is False


def test_parse_args_overrides():
    args = music_mix_cli.parse_args([
        "/tmp/BV.mp4", "--crossfade", "3", "--seed", "42", "--force",
    ])
    assert args.crossfade == 3.0
    assert args.seed == 42
    assert args.force is True
