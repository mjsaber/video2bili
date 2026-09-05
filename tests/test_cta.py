"""Contextual CTAs preserve the underlying gameplay timeline and audio."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from video2yt import cta, cta_cli


@pytest.fixture
def source(tmp_path, monkeypatch):
    video = tmp_path / "game 中文 ' clip.mp4"
    video.write_bytes(b"source")
    font = tmp_path / "font's file.ttf"
    font.write_bytes(b"font")
    def probe(segments):
        for segment in segments:
            segment.duration = 10.0
    monkeypatch.setattr(cta, "validate_segments_strict", probe)
    return video, font


@pytest.mark.parametrize("at,duration", [(-1, 1), (float('nan'), 1), (0, float('inf')),
                                        (0, 0), (9, 2)])
def test_rejects_invalid_overlay_window(source, tmp_path, at, duration):
    video, font = source
    with pytest.raises(ValueError, match="time|duration|within"):
        cta.render(video, "學會這個轉型就訂閱", at, tmp_path / "out.mp4", duration=duration, font=font)


@pytest.mark.parametrize("text", ["", "two\nlines", "x" * 41, "tab\there"])
def test_rejects_empty_multiline_or_overlong_text(source, tmp_path, text):
    with pytest.raises(ValueError, match="text"):
        cta.render(source[0], text, 1, tmp_path / "out.mp4", font=source[1])


def test_refuses_same_input_and_unapproved_overwrite(source, tmp_path):
    video, font = source
    with pytest.raises(ValueError, match="input"):
        cta.render(video, "訂閱", 1, video, font=font, overwrite=True)
    output = tmp_path / "out.mp4"; output.write_bytes(b"previous")
    with pytest.raises(FileExistsError):
        cta.render(video, "訂閱", 1, output, font=font)
    assert output.read_bytes() == b"previous"


def test_command_uses_literal_text_and_copies_audio(source, tmp_path, monkeypatch):
    video, font = source
    text = "訂閱: 100% %{pts} ' \\"
    output = tmp_path / "成品 ' output.mp4"
    captured = {}
    def run(cmd, **kwargs):
        captured["cmd"] = cmd
        work = Path(kwargs["cwd"])
        assert (work / "cta.txt").read_text() == text
        assert (work / "font.ttf").read_bytes() == font.read_bytes()
        Path(cmd[-1]).write_bytes(b"rendered")
    monkeypatch.setattr(cta.subprocess, "run", run)
    assert cta.render(video, text, 2, output, font=font, position="bottom") == output
    cmd = captured["cmd"]
    assert cmd[cmd.index("-i") + 1] == str(video.resolve())
    vf = cmd[cmd.index("-vf") + 1]
    assert "textfile=cta.txt" in vf and "expansion=none" in vf
    assert text not in vf and "fontfile=font.ttf" in vf and "h-text_h" in vf
    assert cmd[cmd.index("-c:a") + 1] == "copy"
    assert "-af" not in cmd and "-shortest" not in cmd
    assert output.read_bytes() == b"rendered" and video.read_bytes() == b"source"


def test_failed_render_preserves_existing_output(source, tmp_path, monkeypatch):
    output = tmp_path / "out.mp4"; output.write_bytes(b"previous")
    def fail(*args, **kwargs):
        raise subprocess.CalledProcessError(1, "ffmpeg")
    monkeypatch.setattr(cta.subprocess, "run", fail)
    with pytest.raises(subprocess.CalledProcessError):
        cta.render(source[0], "訂閱", 1, output, font=source[1], overwrite=True)
    assert output.read_bytes() == b"previous"


def test_duration_mismatch_does_not_publish_output(source, tmp_path, monkeypatch):
    def probe(segments):
        for segment in segments:
            segment.duration = 10 if segment.path == source[0].resolve() else 9
    monkeypatch.setattr(cta, "validate_segments_strict", probe)
    monkeypatch.setattr(cta.subprocess, "run", lambda cmd, **kw: Path(cmd[-1]).write_bytes(b"short"))
    with pytest.raises(ValueError, match="duration"):
        cta.render(source[0], "訂閱", 1, tmp_path / "out.mp4", font=source[1])
    assert not (tmp_path / "out.mp4").exists()


def test_cli_defaults():
    args = cta_cli.parse_args(["--video", "a.mp4", "--text", "訂閱", "--at", "4", "-o", "b.mp4"])
    assert args.duration == 4 and args.position == "top" and args.overwrite is False


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="ffmpeg required")
def test_real_overlay_keeps_audio_frames_and_duration(tmp_path):
    video = tmp_path / "game 中文 ' source.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=blue:s=1920x1080:r=30:d=1",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=1:sample_rate=48000",
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", str(video)], check=True)
    output = tmp_path / "out.mp4"
    cta.render(video, "訂閱 100% %{pts}", 0.2, output, duration=0.4)
    def audio_hash(path):
        return subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:a:0", "-c:a", "copy", "-f", "hash", "-"],
                              check=True, capture_output=True, text=True).stdout
    assert audio_hash(video) == audio_hash(output)
    info = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(output)],
                                     check=True, capture_output=True, text=True).stdout)
    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    assert (v["width"], v["height"], v["r_frame_rate"], v["codec_name"], v["nb_frames"]) == (1920, 1080, "30/1", "h264", "30")
    assert abs(float(info["format"]["duration"]) - 1) < 0.1
    def top_frame_max(at):
        frame = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(at), "-i", str(output),
                                "-frames:v", "1", "-vf", "crop=1920:140:0:0,format=gray",
                                "-f", "rawvideo", "-"], check=True, capture_output=True).stdout
        return max(frame)
    assert top_frame_max(0.1) < 100
    assert top_frame_max(0.3) > 200  # White CTA glyphs only during the selected interval.
    assert top_frame_max(0.8) < 100


def test_cli_surfaces_invalid_request_without_output(source, tmp_path):
    assert cta_cli.main(["--video", str(source[0]), "--text", "訂閱", "--at", "nan",
                         "-o", str(tmp_path / "out.mp4")]) == 1
    assert not (tmp_path / "out.mp4").exists()


def test_refuses_hardlink_of_input_even_with_overwrite(source, tmp_path):
    import os
    alias = tmp_path / "alias.mp4"
    os.link(source[0], alias)
    with pytest.raises(ValueError, match="input"):
        cta.render(source[0], "訂閱", 1, alias, font=source[1], overwrite=True)
    assert source[0].read_bytes() == b"source"


def test_concurrent_output_is_not_overwritten(source, tmp_path, monkeypatch):
    output = tmp_path / "out.mp4"
    def race(cmd, **kwargs):
        Path(cmd[-1]).write_bytes(b"rendered")
        output.write_bytes(b"another render")
    monkeypatch.setattr(cta.subprocess, "run", race)
    with pytest.raises(FileExistsError):
        cta.render(source[0], "訂閱", 1, output, font=source[1])
    assert output.read_bytes() == b"another render"
