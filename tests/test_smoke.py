import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from video2yt import validate
from video2yt.validate import MediaInfo


def _make_ffprobe_output(duration=60.0, width=1920, height=1080, vcodec="h264", acodec="aac"):
    streams = []
    if vcodec:
        streams.append({"codec_type": "video", "codec_name": vcodec, "width": width, "height": height})
    if acodec:
        streams.append({"codec_type": "audio", "codec_name": acodec})
    return json.dumps({"streams": streams, "format": {"duration": str(duration)}})


def test_probe_parses_ffprobe_output(tmp_path, monkeypatch):
    fake_file = tmp_path / "test.mp4"
    fake_file.write_bytes(b"x" * 1000)

    def fake_run(cmd, **kwargs):
        assert cmd[0] == "ffprobe"
        assert str(fake_file) in cmd
        result = MagicMock()
        result.stdout = _make_ffprobe_output()
        result.returncode = 0
        return result

    monkeypatch.setattr("video2yt.validate.subprocess.run", fake_run)
    info = validate.probe(fake_file)

    assert info.duration == 60.0
    assert info.width == 1920
    assert info.height == 1080
    assert info.has_video is True
    assert info.has_audio is True
    assert info.vcodec == "h264"
    assert info.acodec == "aac"
    assert info.size_bytes == 1000


def test_probe_raises_on_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        validate.probe(tmp_path / "does_not_exist.mp4")


def _mk_info(**kw):
    defaults = dict(
        duration=60.0, width=1920, height=1080,
        has_video=True, has_audio=True,
        vcodec="h264", acodec="aac",
        size_bytes=10_000_000,
    )
    defaults.update(kw)
    return MediaInfo(**defaults)


def test_check_source_raises_without_video_stream():
    info = _mk_info(has_video=False, width=0, height=0, vcodec="")
    with pytest.raises(ValueError, match="no video stream"):
        validate.check_source(info, 1080)


def test_check_source_raises_on_zero_duration():
    info = _mk_info(duration=0)
    with pytest.raises(ValueError, match="duration"):
        validate.check_source(info, 1080)


def test_check_source_warns_on_missing_audio():
    info = _mk_info(has_audio=False, acodec=None)
    warnings = validate.check_source(info, 1080)
    assert any("audio" in w.lower() for w in warnings)


def test_check_source_warns_on_low_resolution():
    info = _mk_info(width=1280, height=720)
    warnings = validate.check_source(info, 1080)
    assert any("resolution" in w.lower() or "720" in w for w in warnings)


def test_check_source_no_warnings_for_exact_match():
    info = _mk_info()
    warnings = validate.check_source(info, 1080)
    assert warnings == []


def test_check_ass_raises_on_missing_file(tmp_path):
    with pytest.raises(ValueError, match="not found"):
        validate.check_ass(tmp_path / "missing.ass")


def test_check_ass_raises_without_events_section(tmp_path):
    f = tmp_path / "no_events.ass"
    f.write_text("[Script Info]\nTitle: foo\n", encoding="utf-8")
    with pytest.raises(ValueError, match=r"\[Events\]"):
        validate.check_ass(f)


def test_check_ass_raises_on_zero_dialogue(tmp_path):
    f = tmp_path / "empty.ass"
    f.write_text(
        "[Script Info]\n\n[Events]\nFormat: Layer, Start, End, Style, Text\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Dialogue|danmaku"):
        validate.check_ass(f)


def test_check_ass_returns_dialogue_count(tmp_path):
    f = tmp_path / "ok.ass"
    f.write_text(
        "[Script Info]\n\n[Events]\n"
        "Format: Layer, Start, End, Style, Text\n"
        "Dialogue: 0,0:00:01.00,0:00:05.00,Default,hello\n"
        "Dialogue: 0,0:00:02.00,0:00:06.00,Default,world\n"
        "Dialogue: 0,0:00:03.00,0:00:07.00,Default,foo\n",
        encoding="utf-8",
    )
    assert validate.check_ass(f) == 3


def test_check_output_raises_on_empty_file():
    source = _mk_info()
    output = _mk_info(size_bytes=0)
    with pytest.raises(ValueError, match="empty"):
        validate.check_output(source, output)


def test_check_output_raises_on_missing_video_stream():
    source = _mk_info()
    output = _mk_info(has_video=False, vcodec="")
    with pytest.raises(ValueError, match="video stream"):
        validate.check_output(source, output)


def test_check_output_raises_when_audio_lost():
    source = _mk_info(has_audio=True)
    output = _mk_info(has_audio=False, acodec=None)
    with pytest.raises(ValueError, match="audio"):
        validate.check_output(source, output)


def test_check_output_raises_on_wrong_vcodec():
    source = _mk_info()
    output = _mk_info(vcodec="hevc")
    with pytest.raises(ValueError, match="vcodec|h264"):
        validate.check_output(source, output)


def test_check_output_raises_on_duration_mismatch():
    source = _mk_info(duration=60.0)
    output = _mk_info(duration=58.5)
    with pytest.raises(ValueError, match="duration"):
        validate.check_output(source, output)


def test_check_output_allows_small_duration_drift():
    source = _mk_info(duration=60.0)
    output = _mk_info(duration=60.3)
    warnings = validate.check_output(source, output)
    assert warnings == []


def test_check_output_raises_on_resolution_mismatch():
    source = _mk_info(width=1920, height=1080)
    output = _mk_info(width=1280, height=720)
    with pytest.raises(ValueError, match="resolution"):
        validate.check_output(source, output)


def test_check_output_warns_on_tiny_output():
    source = _mk_info(size_bytes=10_000_000)
    output = _mk_info(size_bytes=100_000)  # 0.01x
    warnings = validate.check_output(source, output)
    assert any("size" in w.lower() for w in warnings)


def test_check_output_warns_on_huge_output():
    source = _mk_info(size_bytes=10_000_000)
    output = _mk_info(size_bytes=100_000_000)  # 10x
    warnings = validate.check_output(source, output)
    assert any("size" in w.lower() for w in warnings)
