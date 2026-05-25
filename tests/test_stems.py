"""Tests for stems.py and stems_cli — song-remover subprocess wrapper +
.stems_source_meta.json cache invalidation.

Mocks at the ``subprocess.run`` boundary (no real song-remover invoked) plus
``validate.probe`` (no real ffprobe). The cache-key sha256 is computed against
the actual file bytes on disk via meta.compute_first_1mb_sha256 — we don't
mock that so we can prove the invalidation chain.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from video2yt import meta, stems, stems_cli, validate
from video2yt.validate import MediaInfo


def _fake_probe(height=1080, width=1920, duration=60.0):
    info = MediaInfo(
        duration=duration, width=width, height=height,
        has_video=True, has_audio=True,
        vcodec="h264", acodec="aac", size_bytes=10_000_000,
    )
    return lambda path: info


def _setup_mp4(tmp_path: Path, content: bytes = b"fake-mp4-bytes") -> Path:
    """Create a fake <bv>.mp4 under tmp_path/<dir>/."""
    seg = tmp_path / "Up：Title"
    seg.mkdir()
    mp4 = seg / "BV1.mp4"
    mp4.write_bytes(content)
    return mp4


def _fake_song_remover(mp4_dir: Path, bv_id: str = "BV1",
                      with_gain_txt: bool = False):
    """Return a subprocess.run replacement that emulates song-remover's
    on-disk layout: ``<mp4_dir>/<bv>/<speech,music,sfx,no_music>.wav``."""
    def _run(cmd, **kwargs):
        # song-remover is invoked with cwd=mp4_dir, so output goes there.
        bv_dir = kwargs["cwd"] / bv_id
        bv_dir.mkdir(exist_ok=True)
        for name in ("speech", "music", "sfx", "no_music"):
            (bv_dir / f"{name}.wav").write_bytes(b"PCM" + name.encode())
        if with_gain_txt:
            (bv_dir / "no_music_gain.txt").write_text("1.234")
        result = MagicMock()
        result.returncode = 0
        result.stdout = ""
        result.stderr = ""
        return result
    return _run


# ---------- separate() core behavior ----------

def test_separate_first_run_invokes_song_remover_and_writes_sidecar(tmp_path, monkeypatch):
    mp4 = _setup_mp4(tmp_path)
    monkeypatch.setattr("video2yt.stems.validate.probe", _fake_probe(height=1080))
    monkeypatch.setattr("video2yt.stems.subprocess.run",
                        _fake_song_remover(mp4.parent))

    result = stems.separate(mp4, device="cpu", chunk_min=None)
    assert result.from_cache is False
    assert result.speech_wav.exists()
    assert result.music_wav.exists()
    assert result.sfx_wav.exists()
    assert result.no_music_wav.exists()
    # Sidecar present and contains the expected meta.
    sidecar = mp4.parent / "BV1" / ".stems_source_meta.json"
    assert sidecar.exists()
    recorded = json.loads(sidecar.read_text())
    assert recorded["sha256"] == meta.compute_first_1mb_sha256(mp4)
    assert recorded["duration"] == 60.0
    assert recorded["quality_label"] == "1080p"


def test_separate_warm_cache_skips_song_remover(tmp_path, monkeypatch):
    """Second invocation with matching speech.wav + matching sidecar: no
    subprocess call. from_cache is True."""
    mp4 = _setup_mp4(tmp_path)
    monkeypatch.setattr("video2yt.stems.validate.probe", _fake_probe(height=1080))

    # Pre-populate as if song-remover had already run.
    bv_dir = mp4.parent / "BV1"
    bv_dir.mkdir()
    (bv_dir / "speech.wav").write_bytes(b"PCMspeech")
    meta.write_meta(
        bv_dir / ".stems_source_meta.json",
        {
            "sha256": meta.compute_first_1mb_sha256(mp4),
            "duration": 60.0,
            "width": 1920,
            "height": 1080,
            "quality_label": "1080p",
        },
    )

    run_calls = []
    def fake_run(cmd, **kwargs):
        run_calls.append(cmd)
        return MagicMock(returncode=0, stdout="", stderr="")
    monkeypatch.setattr("video2yt.stems.subprocess.run", fake_run)

    result = stems.separate(mp4, device="cpu", chunk_min=None)
    assert result.from_cache is True
    assert run_calls == []  # song-remover NOT invoked


def test_separate_stale_sidecar_invalidates_and_rebuilds(tmp_path, monkeypatch):
    """If the recorded sha256 doesn't match the current mp4 (because the
    user re-fetched at a different quality), stems are regenerated."""
    mp4 = _setup_mp4(tmp_path, content=b"NEW-mp4-content-after-requalify")
    monkeypatch.setattr("video2yt.stems.validate.probe", _fake_probe(height=1080))

    # Pre-populate with a sidecar that DOESN'T match the current mp4.
    bv_dir = mp4.parent / "BV1"
    bv_dir.mkdir()
    (bv_dir / "speech.wav").write_bytes(b"OLD-speech-from-previous-mp4")
    meta.write_meta(
        bv_dir / ".stems_source_meta.json",
        {"sha256": "deadbeef" * 8, "duration": 60.0, "quality_label": "480p"},
    )

    monkeypatch.setattr("video2yt.stems.subprocess.run",
                        _fake_song_remover(mp4.parent))

    result = stems.separate(mp4, device="cpu", chunk_min=None)
    assert result.from_cache is False
    # Speech.wav has been overwritten by the fake song-remover.
    assert result.speech_wav.read_bytes() == b"PCMspeech"
    # Sidecar now records the current mp4's sha256.
    recorded = json.loads((bv_dir / ".stems_source_meta.json").read_text())
    assert recorded["sha256"] == meta.compute_first_1mb_sha256(mp4)


def test_separate_force_bypasses_cache_even_when_meta_matches(tmp_path, monkeypatch):
    mp4 = _setup_mp4(tmp_path)
    monkeypatch.setattr("video2yt.stems.validate.probe", _fake_probe(height=1080))

    bv_dir = mp4.parent / "BV1"
    bv_dir.mkdir()
    (bv_dir / "speech.wav").write_bytes(b"OLD")
    meta.write_meta(
        bv_dir / ".stems_source_meta.json",
        {
            "sha256": meta.compute_first_1mb_sha256(mp4),
            "duration": 60.0,
            "width": 1920,
            "height": 1080,
            "quality_label": "1080p",
        },
    )

    run_calls = []
    fake = _fake_song_remover(mp4.parent)
    def wrapped(cmd, **kwargs):
        run_calls.append(cmd)
        return fake(cmd, **kwargs)
    monkeypatch.setattr("video2yt.stems.subprocess.run", wrapped)

    result = stems.separate(mp4, device="cpu", chunk_min=None, force=True)
    assert result.from_cache is False
    assert len(run_calls) == 1


def test_separate_raises_when_song_remover_produces_no_speech(tmp_path, monkeypatch):
    mp4 = _setup_mp4(tmp_path)
    monkeypatch.setattr("video2yt.stems.validate.probe", _fake_probe(height=1080))

    def fake_run(cmd, **kwargs):
        # song-remover "succeeds" but produces nothing.
        return MagicMock(returncode=0, stdout="", stderr="")
    monkeypatch.setattr("video2yt.stems.subprocess.run", fake_run)

    with pytest.raises(RuntimeError, match="did not produce"):
        stems.separate(mp4, device="cpu", chunk_min=None)


def test_separate_preserves_no_music_gain_txt_when_present(tmp_path, monkeypatch):
    mp4 = _setup_mp4(tmp_path)
    monkeypatch.setattr("video2yt.stems.validate.probe", _fake_probe(height=1080))
    monkeypatch.setattr("video2yt.stems.subprocess.run",
                        _fake_song_remover(mp4.parent, with_gain_txt=True))

    result = stems.separate(mp4, device="cpu", chunk_min=None)
    assert result.no_music_gain_txt is not None
    assert result.no_music_gain_txt.exists()


def test_separate_no_gain_txt_when_song_remover_skipped_normalization(tmp_path, monkeypatch):
    mp4 = _setup_mp4(tmp_path)
    monkeypatch.setattr("video2yt.stems.validate.probe", _fake_probe(height=1080))
    monkeypatch.setattr("video2yt.stems.subprocess.run",
                        _fake_song_remover(mp4.parent, with_gain_txt=False))

    result = stems.separate(mp4, device="cpu", chunk_min=None)
    assert result.no_music_gain_txt is None


# ---------- argv composition ----------

def test_argv_for_remote_device_uses_remote_flag_not_device_remote(tmp_path, monkeypatch):
    """song-remover's --device accepts only {auto, mps, cuda, cpu}; remote is
    a separate --remote bool flag (verified against ~/code/song-remover/cli.py
    commit f3380d1). Passing --device remote crashes song-remover."""
    mp4 = _setup_mp4(tmp_path)
    monkeypatch.setattr("video2yt.stems.validate.probe", _fake_probe(height=1080))

    captured = {}
    def capturing_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["cwd"] = kwargs["cwd"]
        return _fake_song_remover(mp4.parent)(cmd, **kwargs)
    monkeypatch.setattr("video2yt.stems.subprocess.run", capturing_run)

    stems.separate(mp4, device="remote", chunk_min=3)
    cmd = captured["cmd"]
    assert cmd[0] == "song-remover"
    assert cmd[1] == "BV1.mp4"
    assert "--remote" in cmd
    # --device gets "auto" (placeholder) under --remote; never "remote".
    device_idx = cmd.index("--device")
    assert cmd[device_idx + 1] == "auto"
    assert "remote" not in cmd[cmd.index("--device") + 1:cmd.index("--device") + 2]
    assert "--chunk-min" in cmd and "3" in cmd
    assert "--force" in cmd
    assert captured["cwd"] == mp4.parent


def test_argv_for_cpu_device_no_remote_no_chunk_min(tmp_path, monkeypatch):
    mp4 = _setup_mp4(tmp_path)
    monkeypatch.setattr("video2yt.stems.validate.probe", _fake_probe(height=1080))

    captured = {}
    def capturing_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return _fake_song_remover(mp4.parent)(cmd, **kwargs)
    monkeypatch.setattr("video2yt.stems.subprocess.run", capturing_run)

    stems.separate(mp4, device="cpu", chunk_min=5)
    cmd = captured["cmd"]
    assert "--remote" not in cmd
    assert "--chunk-min" not in cmd
    device_idx = cmd.index("--device")
    assert cmd[device_idx + 1] == "cpu"


def test_argv_for_mps_device(tmp_path, monkeypatch):
    mp4 = _setup_mp4(tmp_path)
    monkeypatch.setattr("video2yt.stems.validate.probe", _fake_probe(height=1080))

    captured = {}
    def capturing_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return _fake_song_remover(mp4.parent)(cmd, **kwargs)
    monkeypatch.setattr("video2yt.stems.subprocess.run", capturing_run)

    stems.separate(mp4, device="mps", chunk_min=None)
    cmd = captured["cmd"]
    assert "--remote" not in cmd
    device_idx = cmd.index("--device")
    assert cmd[device_idx + 1] == "mps"


def test_argv_rejects_unknown_device(tmp_path, monkeypatch):
    mp4 = _setup_mp4(tmp_path)
    monkeypatch.setattr("video2yt.stems.validate.probe", _fake_probe(height=1080))
    monkeypatch.setattr("video2yt.stems.subprocess.run",
                        _fake_song_remover(mp4.parent))
    with pytest.raises(ValueError, match="unknown device"):
        stems.separate(mp4, device="cuda", chunk_min=None)


# ---------- quality_label mapping ----------

@pytest.mark.parametrize("height,expected", [
    (1080, "1080p"),
    (1440, "1080p"),  # higher than 1080 still maps to "1080p" (our cap)
    (720, "720p"),
    (852, "720p"),    # in the 720-1079 band
    (480, "480p"),
    (360, "360p"),    # below 480 → raw "<h>p"
])
def test_quality_label_buckets(height, expected):
    assert stems._quality_label(height) == expected


# ---------- CLI preflight + arg parsing ----------

def test_preflight_passes_cpu_when_song_remover_on_path(monkeypatch):
    monkeypatch.setattr("video2yt.stems_cli.stems.song_remover_on_path",
                       lambda: True)
    stems_cli.preflight(device="cpu")  # should not raise; cpu skips Modal check


def test_preflight_raises_when_song_remover_missing(monkeypatch):
    monkeypatch.setattr("video2yt.stems_cli.stems.song_remover_on_path",
                       lambda: False)
    with pytest.raises(RuntimeError, match="song-remover not found"):
        stems_cli.preflight(device="cpu")


def test_preflight_remote_requires_modal_token(tmp_path, monkeypatch):
    """When --device remote is selected but ~/.modal.toml is missing, the
    user would otherwise hit a confusing Modal-internal error mid-pipeline."""
    monkeypatch.setattr("video2yt.stems_cli.stems.song_remover_on_path",
                       lambda: True)
    # Redirect HOME to an empty tmpdir so .modal.toml definitely isn't there.
    monkeypatch.setenv("HOME", str(tmp_path))
    with pytest.raises(RuntimeError, match="Modal token not found"):
        stems_cli.preflight(device="remote")


def test_preflight_remote_passes_when_modal_token_present(tmp_path, monkeypatch):
    monkeypatch.setattr("video2yt.stems_cli.stems.song_remover_on_path",
                       lambda: True)
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".modal.toml").write_text('[default]\ntoken = "fake"\n')
    stems_cli.preflight(device="remote")  # should not raise


def test_parse_args_defaults():
    args = stems_cli.parse_args(["/tmp/BV.mp4"])
    assert args.raw_mp4 == Path("/tmp/BV.mp4")
    assert args.device == "remote"
    assert args.chunk_min == 5
    assert args.force is False


def test_parse_args_overrides():
    args = stems_cli.parse_args([
        "/tmp/BV.mp4", "--device", "cpu", "--chunk-min", "3", "--force",
    ])
    assert args.device == "cpu"
    assert args.chunk_min == 3
    assert args.force is True
