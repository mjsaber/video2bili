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


from video2yt import download


def test_fetch_builds_correct_yt_dlp_command(tmp_path, monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        # Simulate yt-dlp producing the output files
        (tmp_path / "BV191DpBmE2t.mp4").write_bytes(b"fake video")
        (tmp_path / "BV191DpBmE2t.danmaku.ass").write_text(
            "[Events]\nDialogue: 0,0:00:01.00,0:00:05.00,Default,hi\n",
            encoding="utf-8",
        )
        return MagicMock(returncode=0)

    monkeypatch.setattr("video2yt.download.subprocess.run", fake_run)

    video, ass = download.fetch(
        url="https://www.bilibili.com/video/BV191DpBmE2t/?spm_id_from=x",
        temp_dir=tmp_path,
        quality=1080,
        browser="chrome",
        bv_id="BV191DpBmE2t",
    )

    cmd = captured["cmd"]
    assert cmd[0] == "yt-dlp"
    # cookies
    assert "--cookies-from-browser" in cmd
    assert "chrome" in cmd
    # format with quality
    fmt_idx = cmd.index("-f")
    assert "height<=1080" in cmd[fmt_idx + 1]
    assert cmd[fmt_idx + 1].endswith("/b")  # fallback sentinel
    # danmaku postprocessor
    assert "--use-postprocessor" in cmd
    pp_idx = cmd.index("--use-postprocessor")
    assert cmd[pp_idx + 1] == "danmaku"
    # write-subs present
    assert "--write-subs" in cmd
    # output template contains BV id and %(ext)s
    out_idx = cmd.index("--output")
    assert "BV191DpBmE2t" in cmd[out_idx + 1]
    assert "%(ext)s" in cmd[out_idx + 1]
    # URL at end
    assert cmd[-1] == "https://www.bilibili.com/video/BV191DpBmE2t/?spm_id_from=x"

    assert video == tmp_path / "BV191DpBmE2t.mp4"
    assert ass == tmp_path / "BV191DpBmE2t.danmaku.ass"


def test_fetch_uses_quality_720(tmp_path, monkeypatch):
    def fake_run(cmd, **kwargs):
        fmt_idx = cmd.index("-f")
        assert "height<=720" in cmd[fmt_idx + 1]
        (tmp_path / "BV.mp4").write_bytes(b"v")
        (tmp_path / "BV.danmaku.ass").write_text(
            "[Events]\nDialogue: 0,0,0,D,x\n", encoding="utf-8",
        )
        return MagicMock(returncode=0)

    monkeypatch.setattr("video2yt.download.subprocess.run", fake_run)
    download.fetch("https://x/video/BV", tmp_path, 720, "chrome", "BV")


def test_fetch_raises_when_video_file_missing(tmp_path, monkeypatch):
    def fake_run(cmd, **kwargs):
        # Only create the ASS file, skip the video
        (tmp_path / "BV.danmaku.ass").write_text(
            "[Events]\nDialogue: x\n", encoding="utf-8",
        )
        return MagicMock(returncode=0)

    monkeypatch.setattr("video2yt.download.subprocess.run", fake_run)
    with pytest.raises(FileNotFoundError, match="video"):
        download.fetch("https://x/video/BV", tmp_path, 1080, "chrome", "BV")


def test_fetch_raises_when_ass_file_missing(tmp_path, monkeypatch):
    def fake_run(cmd, **kwargs):
        (tmp_path / "BV.mp4").write_bytes(b"v")
        return MagicMock(returncode=0)

    monkeypatch.setattr("video2yt.download.subprocess.run", fake_run)
    with pytest.raises(FileNotFoundError, match="ASS|ass"):
        download.fetch("https://x/video/BV", tmp_path, 1080, "chrome", "BV")


from video2yt import burn


def test_render_uses_cwd_and_relative_paths(tmp_path, monkeypatch):
    temp_dir = tmp_path / "temp"
    temp_dir.mkdir()
    video = temp_dir / "BV.mp4"
    video.write_bytes(b"video data")
    ass = temp_dir / "BV.danmaku.ass"
    ass.write_text("data", encoding="utf-8")
    output_dir = tmp_path / "output"
    output = output_dir / "BV_with_danmaku.mp4"

    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["cwd"] = kwargs.get("cwd")
        # Simulate ffmpeg writing the output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"burned video")
        return MagicMock(returncode=0)

    monkeypatch.setattr("video2yt.burn.subprocess.run", fake_run)

    result = burn.render(video, ass, output)

    assert result == output
    # cwd is the temp_dir containing video + ass
    assert captured["cwd"] == temp_dir
    cmd = captured["cmd"]
    assert cmd[0] == "ffmpeg"
    assert "-y" in cmd
    # -i uses basename (relative to cwd)
    i_idx = cmd.index("-i")
    assert cmd[i_idx + 1] == "BV.mp4"
    # -vf subtitles= uses basename
    vf_idx = cmd.index("-vf")
    assert cmd[vf_idx + 1] == "subtitles=BV.danmaku.ass"
    # libx264 preset medium crf 20
    assert "libx264" in cmd
    crf_idx = cmd.index("-crf")
    assert cmd[crf_idx + 1] == "20"
    preset_idx = cmd.index("-preset")
    assert cmd[preset_idx + 1] == "medium"
    # audio copied
    ca_idx = cmd.index("-c:a")
    assert cmd[ca_idx + 1] == "copy"
    # output is absolute path, NOT relative
    output_arg = cmd[-1]
    assert Path(output_arg).is_absolute()
    assert Path(output_arg) == output.resolve()


def test_render_raises_if_video_and_ass_in_different_dirs(tmp_path):
    video = tmp_path / "a" / "v.mp4"
    video.parent.mkdir()
    video.write_bytes(b"v")
    ass = tmp_path / "b" / "v.ass"
    ass.parent.mkdir()
    ass.write_text("data", encoding="utf-8")
    output = tmp_path / "out.mp4"
    with pytest.raises(ValueError, match="same directory"):
        burn.render(video, ass, output)


from video2yt import cli


def test_extract_bv_from_full_url_with_query():
    url = "https://www.bilibili.com/video/BV191DpBmE2t/?spm_id_from=333.337&vd_source=xxx"
    assert cli.extract_bv_id(url) == "BV191DpBmE2t"


def test_extract_bv_from_plain_url():
    assert cli.extract_bv_id("https://www.bilibili.com/video/BV1Sm4y1N78J") == "BV1Sm4y1N78J"


def test_extract_bv_from_url_with_trailing_slash():
    assert cli.extract_bv_id("https://www.bilibili.com/video/BV1Sm4y1N78J/") == "BV1Sm4y1N78J"


def test_extract_bv_raises_on_non_bilibili_url():
    with pytest.raises(ValueError, match="BV"):
        cli.extract_bv_id("https://www.youtube.com/watch?v=abc123")


def test_extract_bv_raises_on_empty_string():
    with pytest.raises(ValueError, match="BV"):
        cli.extract_bv_id("")


def test_preflight_passes_when_everything_present(monkeypatch):
    monkeypatch.setattr("video2yt.cli.shutil.which", lambda name: f"/usr/local/bin/{name}")
    # biliass already installed in dev env; import should succeed
    cli.preflight()  # should not raise


def test_preflight_fails_without_ffmpeg(monkeypatch):
    def fake_which(name):
        return None if name == "ffmpeg" else f"/usr/local/bin/{name}"
    monkeypatch.setattr("video2yt.cli.shutil.which", fake_which)
    with pytest.raises(RuntimeError, match="ffmpeg"):
        cli.preflight()


def test_preflight_fails_without_ffprobe(monkeypatch):
    def fake_which(name):
        return None if name == "ffprobe" else f"/usr/local/bin/{name}"
    monkeypatch.setattr("video2yt.cli.shutil.which", fake_which)
    with pytest.raises(RuntimeError, match="ffprobe"):
        cli.preflight()


def test_preflight_fails_without_biliass(monkeypatch):
    monkeypatch.setattr("video2yt.cli.shutil.which", lambda name: f"/usr/local/bin/{name}")
    import sys
    # Force biliass import to fail by injecting a sentinel into sys.modules
    monkeypatch.setitem(sys.modules, "biliass", None)
    with pytest.raises(RuntimeError, match="yt-dlp-danmaku|biliass"):
        cli.preflight()


def test_parse_args_defaults():
    args = cli.parse_args(["https://www.bilibili.com/video/BV1"])
    assert args.url == "https://www.bilibili.com/video/BV1"
    assert args.output_dir == Path("./output")
    assert args.temp_dir == Path("./temp")
    assert args.quality == 1080
    assert args.browser == "chrome"
    assert args.keep_temp is False


def test_parse_args_custom():
    args = cli.parse_args([
        "https://www.bilibili.com/video/BV1",
        "-o", "/tmp/out",
        "-t", "/tmp/tmp",
        "-q", "720",
        "-b", "firefox",
        "--keep-temp",
    ])
    assert args.output_dir == Path("/tmp/out")
    assert args.temp_dir == Path("/tmp/tmp")
    assert args.quality == 720
    assert args.browser == "firefox"
    assert args.keep_temp is True


def test_parse_args_rejects_bad_quality():
    with pytest.raises(SystemExit):
        cli.parse_args(["https://x", "-q", "4320"])


def test_run_orchestrates_full_pipeline(tmp_path, monkeypatch):
    """Full pipeline with all subprocess boundaries mocked; verifies call order."""
    call_log = []

    # Skip dep preflight
    monkeypatch.setattr("video2yt.cli.preflight", lambda: call_log.append("preflight"))

    def fake_fetch(url, temp_dir, quality, browser, bv_id):
        call_log.append(f"fetch:{bv_id}:{quality}:{browser}")
        v = temp_dir / f"{bv_id}.mp4"
        v.write_bytes(b"fakevideo")
        a = temp_dir / f"{bv_id}.danmaku.ass"
        a.write_text(
            "[Events]\n"
            "Format: Layer, Start, End, Style, Text\n"
            "Dialogue: 0,0:00:01.00,0:00:05.00,Default,hi\n",
            encoding="utf-8",
        )
        return v, a

    monkeypatch.setattr("video2yt.cli.download.fetch", fake_fetch)

    probe_calls = []
    source_info = MediaInfo(
        duration=60.0, width=1920, height=1080,
        has_video=True, has_audio=True,
        vcodec="h264", acodec="aac", size_bytes=10_000_000,
    )
    output_info = MediaInfo(
        duration=60.0, width=1920, height=1080,
        has_video=True, has_audio=True,
        vcodec="h264", acodec="aac", size_bytes=11_000_000,
    )

    def fake_probe(path):
        probe_calls.append(path)
        # First call = source, second call = output
        return source_info if len(probe_calls) == 1 else output_info

    monkeypatch.setattr("video2yt.cli.validate.probe", fake_probe)

    def fake_render(video_path, ass_path, output_path):
        call_log.append(f"render:{output_path.name}")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"burnedoutput")
        return output_path

    monkeypatch.setattr("video2yt.cli.burn.render", fake_render)

    args = cli.parse_args([
        "https://www.bilibili.com/video/BV191DpBmE2t/",
        "-o", str(tmp_path / "output"),
        "-t", str(tmp_path / "temp"),
    ])
    result = cli.run(args)

    assert result == tmp_path / "output" / "BV191DpBmE2t_with_danmaku.mp4"
    assert result.exists()
    # Verify call order
    assert call_log[0] == "preflight"
    assert call_log[1] == "fetch:BV191DpBmE2t:1080:chrome"
    assert call_log[2] == "render:BV191DpBmE2t_with_danmaku.mp4"
    # Probe called twice: source then output
    assert len(probe_calls) == 2


def test_run_deletes_temp_files_on_success(tmp_path, monkeypatch):
    monkeypatch.setattr("video2yt.cli.preflight", lambda: None)

    def fake_fetch(url, temp_dir, quality, browser, bv_id):
        v = temp_dir / f"{bv_id}.mp4"
        v.write_bytes(b"v")
        a = temp_dir / f"{bv_id}.danmaku.ass"
        a.write_text("[Events]\nDialogue: 0,0,0,D,x\n", encoding="utf-8")
        return v, a

    monkeypatch.setattr("video2yt.cli.download.fetch", fake_fetch)
    monkeypatch.setattr(
        "video2yt.cli.validate.probe",
        lambda p: MediaInfo(
            duration=60.0, width=1920, height=1080,
            has_video=True, has_audio=True,
            vcodec="h264", acodec="aac", size_bytes=1000,
        ),
    )

    def fake_render(v, a, o):
        o.parent.mkdir(parents=True, exist_ok=True)
        o.write_bytes(b"x")
        return o

    monkeypatch.setattr("video2yt.cli.burn.render", fake_render)

    args = cli.parse_args([
        "https://x/video/BV1",
        "-o", str(tmp_path / "out"),
        "-t", str(tmp_path / "tmp"),
    ])
    cli.run(args)

    # Temp files gone
    assert not (tmp_path / "tmp" / "BV1.mp4").exists()
    assert not (tmp_path / "tmp" / "BV1.danmaku.ass").exists()


def test_run_keeps_temp_when_flag_set(tmp_path, monkeypatch):
    monkeypatch.setattr("video2yt.cli.preflight", lambda: None)

    def fake_fetch(url, temp_dir, quality, browser, bv_id):
        v = temp_dir / f"{bv_id}.mp4"
        v.write_bytes(b"v")
        a = temp_dir / f"{bv_id}.danmaku.ass"
        a.write_text("[Events]\nDialogue: 0,0,0,D,x\n", encoding="utf-8")
        return v, a

    monkeypatch.setattr("video2yt.cli.download.fetch", fake_fetch)
    monkeypatch.setattr(
        "video2yt.cli.validate.probe",
        lambda p: MediaInfo(
            duration=60.0, width=1920, height=1080,
            has_video=True, has_audio=True,
            vcodec="h264", acodec="aac", size_bytes=1000,
        ),
    )
    monkeypatch.setattr(
        "video2yt.cli.burn.render",
        lambda v, a, o: (o.parent.mkdir(parents=True, exist_ok=True), o.write_bytes(b"x"), o)[-1],
    )

    args = cli.parse_args([
        "https://x/video/BV1",
        "-o", str(tmp_path / "out"),
        "-t", str(tmp_path / "tmp"),
        "--keep-temp",
    ])
    cli.run(args)
    assert (tmp_path / "tmp" / "BV1.mp4").exists()
    assert (tmp_path / "tmp" / "BV1.danmaku.ass").exists()


def test_main_returns_1_on_value_error(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("video2yt.cli.preflight", lambda: None)
    # Make extract_bv_id fail via non-bilibili URL
    rc = cli.main(["https://www.youtube.com/x"])
    assert rc == 1
    out = capsys.readouterr()
    assert "BV" in out.err or "error" in out.err.lower()
