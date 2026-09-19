

def test_track_loudness_parses_ebur128_and_caches(tmp_path, monkeypatch):
    from unittest.mock import MagicMock
    import json
    from video2yt import music_library
    track = tmp_path / "t.mp3"
    track.write_bytes(b"fake")
    calls = []
    def _run(cmd, **kw):
        calls.append(cmd)
        return MagicMock(returncode=0, stdout="", stderr="[Parsed_ebur128_0] Summary:\n\n  Integrated loudness:\n    I:         -17.7 LUFS\n    Threshold: -28.0 LUFS\n")
    monkeypatch.setattr("video2yt.loudness.subprocess.run", _run)
    assert music_library.track_loudness(track) == -17.7
    assert music_library.track_loudness(track) == -17.7   # second call served from the sidecar
    assert len(calls) == 1
    cache = json.loads((tmp_path / music_library.LOUDNESS_SIDECAR).read_text())
    assert cache == {f"t.mp3:{track.stat().st_size}": -17.7}


def test_track_loudness_returns_none_when_ffmpeg_cannot_measure(tmp_path, monkeypatch):
    from unittest.mock import MagicMock
    from video2yt import music_library
    track = tmp_path / "bad.mp3"
    track.write_bytes(b"fake")
    monkeypatch.setattr("video2yt.loudness.subprocess.run",
                        lambda cmd, **kw: MagicMock(returncode=1, stdout="", stderr="boom"))
    assert music_library.track_loudness(track) is None
    assert not (tmp_path / music_library.LOUDNESS_SIDECAR).exists()
