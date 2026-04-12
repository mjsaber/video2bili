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


def test_check_output_accepts_preview_duration():
    """With expected_duration, output can be much shorter than source."""
    source = _mk_info(duration=1260.0, size_bytes=371_000_000)
    output = _mk_info(duration=60.0, size_bytes=26_000_000)
    warnings = validate.check_output(source, output, expected_duration=60.0)
    # Size check: scaled expected = 371M * (60/1260) = ~17.7M; actual 26M
    # is ~1.47x which is within [0.3, 5.0] -> no size warning.
    assert warnings == []


def test_check_output_fails_preview_duration_mismatch():
    """With expected_duration, output mismatch against expected still fails."""
    source = _mk_info(duration=1260.0)
    output = _mk_info(duration=55.0)  # expected 60 but got 55 -> >1s diff
    with pytest.raises(ValueError, match="duration"):
        validate.check_output(source, output, expected_duration=60.0)


from video2yt import download


def test_fetch_builds_correct_yt_dlp_command(tmp_path, monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        # Simulate yt-dlp producing the raw video + danmaku XML
        (tmp_path / "BV191DpBmE2t.mp4").write_bytes(b"fake video")
        (tmp_path / "BV191DpBmE2t.danmaku.xml").write_bytes(
            b'<?xml version="1.0" encoding="UTF-8"?><i>'
            b'<d p="1.0,1,25,16777215,1,0,0,0">hello</d></i>'
        )
        return MagicMock(returncode=0)

    monkeypatch.setattr("video2yt.download.subprocess.run", fake_run)

    video, xml, from_cache = download.fetch(
        url="https://www.bilibili.com/video/BV191DpBmE2t/?spm_id_from=x",
        temp_dir=tmp_path,
        quality=1080,
        browser="chrome",
        bv_id="BV191DpBmE2t",
    )
    assert from_cache is False

    cmd = captured["cmd"]
    assert cmd[0] == "yt-dlp"
    # cookies
    assert "--cookies-from-browser" in cmd
    assert "chrome" in cmd
    # format with quality — h264 is the default codec
    fmt_idx = cmd.index("-f")
    assert "height<=1080" in cmd[fmt_idx + 1]
    assert "[vcodec^=avc1]" in cmd[fmt_idx + 1]
    assert cmd[fmt_idx + 1].endswith("/b")  # fallback sentinel
    # raw danmaku XML via --write-subs + --sub-langs
    assert "--write-subs" in cmd
    assert "--sub-langs" in cmd
    sl_idx = cmd.index("--sub-langs")
    assert cmd[sl_idx + 1] == "danmaku"
    # postprocessor is NOT used anymore — biliass is called from Python
    assert "--use-postprocessor" not in cmd
    # output template contains BV id and %(ext)s
    out_idx = cmd.index("--output")
    assert "BV191DpBmE2t" in cmd[out_idx + 1]
    assert "%(ext)s" in cmd[out_idx + 1]
    # URL at end
    assert cmd[-1] == "https://www.bilibili.com/video/BV191DpBmE2t/?spm_id_from=x"

    assert video == tmp_path / "BV191DpBmE2t.mp4"
    assert xml.suffix == ".xml"
    assert xml == tmp_path / "BV191DpBmE2t.danmaku.xml"


def test_fetch_uses_quality_720(tmp_path, monkeypatch):
    def fake_run(cmd, **kwargs):
        fmt_idx = cmd.index("-f")
        assert "height<=720" in cmd[fmt_idx + 1]
        (tmp_path / "BV.mp4").write_bytes(b"v")
        (tmp_path / "BV.danmaku.xml").write_bytes(
            b"<i><d p='1,1,25,16777215,1,0,0,0'>x</d></i>"
        )
        return MagicMock(returncode=0)

    monkeypatch.setattr("video2yt.download.subprocess.run", fake_run)
    download.fetch("https://x/video/BV", tmp_path, 720, "chrome", "BV")


@pytest.mark.parametrize("codec,expected_tag", [
    ("h264", "[vcodec^=avc1]"),
    ("h265", "[vcodec^=hev1]"),
])
def test_fetch_format_spec_uses_codec(tmp_path, monkeypatch, codec, expected_tag):
    def fake_run(cmd, **kwargs):
        fmt_idx = cmd.index("-f")
        assert expected_tag in cmd[fmt_idx + 1]
        (tmp_path / "BV.mp4").write_bytes(b"v")
        (tmp_path / "BV.danmaku.xml").write_bytes(
            b"<i><d p='1,1,25,16777215,1,0,0,0'>hi</d></i>"
        )
        return MagicMock(returncode=0)
    monkeypatch.setattr("video2yt.download.subprocess.run", fake_run)
    download.fetch("https://x/video/BV", tmp_path, 1080, "chrome", "BV", codec=codec)


def test_fetch_format_spec_auto_has_no_codec_filter(tmp_path, monkeypatch):
    def fake_run(cmd, **kwargs):
        fmt_idx = cmd.index("-f")
        assert "[vcodec^=" not in cmd[fmt_idx + 1]
        (tmp_path / "BV.mp4").write_bytes(b"v")
        (tmp_path / "BV.danmaku.xml").write_bytes(
            b"<i><d p='1,1,25,16777215,1,0,0,0'>hi</d></i>"
        )
        return MagicMock(returncode=0)
    monkeypatch.setattr("video2yt.download.subprocess.run", fake_run)
    download.fetch("https://x/video/BV", tmp_path, 1080, "chrome", "BV", codec="auto")


def test_fetch_raises_when_video_file_missing(tmp_path, monkeypatch):
    def fake_run(cmd, **kwargs):
        # Only create the XML file, skip the video
        (tmp_path / "BV.danmaku.xml").write_bytes(
            b"<i><d p='1,1,25,16777215,1,0,0,0'>x</d></i>"
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
    with pytest.raises(FileNotFoundError, match="XML|xml|danmaku"):
        download.fetch("https://x/video/BV", tmp_path, 1080, "chrome", "BV")


def test_fetch_uses_cache_when_files_exist(tmp_path, monkeypatch):
    """When temp_dir already contains both video and xml, fetch skips yt-dlp."""
    (tmp_path / "BV123.mp4").write_bytes(b"cached video")
    (tmp_path / "BV123.danmaku.xml").write_bytes(b"<i></i>")

    call_count = {"n": 0}
    def fake_run(cmd, **kwargs):
        call_count["n"] += 1
        return MagicMock(returncode=0)
    monkeypatch.setattr("video2yt.download.subprocess.run", fake_run)

    video, xml, from_cache = download.fetch(
        "https://x/video/BV123", tmp_path, 1080, "chrome", "BV123"
    )
    assert call_count["n"] == 0  # yt-dlp NOT invoked
    assert from_cache is True
    assert video == tmp_path / "BV123.mp4"
    assert xml == tmp_path / "BV123.danmaku.xml"


def test_fetch_downloads_when_no_cache(tmp_path, monkeypatch):
    """Empty temp_dir — fetch calls yt-dlp and returns from_cache=False."""
    call_count = {"n": 0}
    def fake_run(cmd, **kwargs):
        call_count["n"] += 1
        (tmp_path / "BV123.mp4").write_bytes(b"v")
        (tmp_path / "BV123.danmaku.xml").write_bytes(b"<i></i>")
        return MagicMock(returncode=0)
    monkeypatch.setattr("video2yt.download.subprocess.run", fake_run)

    video, xml, from_cache = download.fetch(
        "https://x/video/BV123", tmp_path, 1080, "chrome", "BV123"
    )
    assert call_count["n"] == 1
    assert from_cache is False


def test_fetch_downloads_when_xml_missing_from_cache(tmp_path, monkeypatch):
    """Partial cache (only video) -> cache miss -> full download."""
    (tmp_path / "BV123.mp4").write_bytes(b"old video")

    call_count = {"n": 0}
    def fake_run(cmd, **kwargs):
        call_count["n"] += 1
        # Simulate yt-dlp producing both files
        (tmp_path / "BV123.mp4").write_bytes(b"new video")
        (tmp_path / "BV123.danmaku.xml").write_bytes(b"<i></i>")
        return MagicMock(returncode=0)
    monkeypatch.setattr("video2yt.download.subprocess.run", fake_run)

    video, xml, from_cache = download.fetch(
        "https://x/video/BV123", tmp_path, 1080, "chrome", "BV123"
    )
    assert call_count["n"] == 1
    assert from_cache is False


def test_fetch_downloads_when_video_missing_from_cache(tmp_path, monkeypatch):
    """Partial cache (only xml) -> cache miss -> full download."""
    (tmp_path / "BV123.danmaku.xml").write_bytes(b"<i></i>")

    call_count = {"n": 0}
    def fake_run(cmd, **kwargs):
        call_count["n"] += 1
        (tmp_path / "BV123.mp4").write_bytes(b"v")
        return MagicMock(returncode=0)
    monkeypatch.setattr("video2yt.download.subprocess.run", fake_run)

    video, xml, from_cache = download.fetch(
        "https://x/video/BV123", tmp_path, 1080, "chrome", "BV123"
    )
    assert call_count["n"] == 1
    assert from_cache is False


def test_generate_ass_passes_font_params(tmp_path, monkeypatch):
    """generate_ass calls biliass.convert_to_ass with our stage + font params."""
    xml = tmp_path / "BV.danmaku.xml"
    xml.write_bytes(
        b'<?xml version="1.0" encoding="UTF-8"?><i>'
        b'<d p="1.0,1,25,16777215,1,0,0,0">hello</d></i>'
    )
    ass = tmp_path / "BV.danmaku.ass"

    captured = {}

    def fake_convert(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return "[Script Info]\nTitle: test\n\n[Events]\nDialogue: 0,0,0,Default,hi\n"

    monkeypatch.setattr("video2yt.download.biliass.convert_to_ass", fake_convert)

    from video2yt.download import generate_ass
    generate_ass(
        xml_path=xml,
        ass_path=ass,
        width=480,
        height=852,
        font_face="Hiragino Sans GB",
        font_size=39,
    )

    assert ass.exists()
    # biliass signature: convert_to_ass(inputs, stage_width, stage_height, ...)
    assert captured["kwargs"].get("font_face") == "Hiragino Sans GB"
    assert captured["kwargs"].get("font_size") == 39
    assert captured["kwargs"].get("stage_width") == 480
    assert captured["kwargs"].get("stage_height") == 852
    # First positional arg is the XML bytes
    assert captured["args"][0] == xml.read_bytes()


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
    assert cmd[vf_idx + 1] == "subtitles=f='BV.danmaku.ass'"
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


def test_render_adds_t_flag_with_max_duration(tmp_path, monkeypatch):
    temp_dir = tmp_path / "temp"
    temp_dir.mkdir()
    video = temp_dir / "BV.mp4"
    video.write_bytes(b"v")
    ass = temp_dir / "BV.danmaku.ass"
    ass.write_text("data", encoding="utf-8")
    output = tmp_path / "output" / "BV_with_danmaku.mp4"

    captured = {}
    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"burned")
        return MagicMock(returncode=0)
    monkeypatch.setattr("video2yt.burn.subprocess.run", fake_run)

    burn.render(video, ass, output, max_duration=60)

    cmd = captured["cmd"]
    assert "-t" in cmd
    t_idx = cmd.index("-t")
    assert cmd[t_idx + 1] == "60"
    # -t must come after -i and before -vf
    i_idx = cmd.index("-i")
    vf_idx = cmd.index("-vf")
    assert i_idx < t_idx < vf_idx


def test_render_omits_t_flag_without_max_duration(tmp_path, monkeypatch):
    temp_dir = tmp_path / "temp"
    temp_dir.mkdir()
    video = temp_dir / "BV.mp4"
    video.write_bytes(b"v")
    ass = temp_dir / "BV.danmaku.ass"
    ass.write_text("data", encoding="utf-8")
    output = tmp_path / "output" / "BV_with_danmaku.mp4"

    captured = {}
    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"burned")
        return MagicMock(returncode=0)
    monkeypatch.setattr("video2yt.burn.subprocess.run", fake_run)

    burn.render(video, ass, output)  # no max_duration

    cmd = captured["cmd"]
    assert "-t" not in cmd


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
    assert args.font_face == "Hiragino Sans GB"
    assert args.font_size is None
    assert args.codec == "h264"
    assert args.preview_seconds is None


def test_compute_font_size_matches_bilibili_reference():
    assert cli.compute_font_size(540) == 25  # reference point
    assert cli.compute_font_size(1080) == 50
    assert cli.compute_font_size(2160) == 100


def test_compute_font_size_for_test_video():
    # BV191DpBmE2t is 480x852 vertical; height=852 → ~39-40
    result = cli.compute_font_size(852)
    assert 38 <= result <= 41


def test_compute_font_size_for_720p():
    assert cli.compute_font_size(720) == 33  # 720/21.6 = 33.33


def test_parse_args_custom():
    args = cli.parse_args([
        "https://www.bilibili.com/video/BV1",
        "-o", "/tmp/out",
        "-t", "/tmp/tmp",
        "-q", "720",
        "-b", "firefox",
        "--keep-temp",
        "--font-face", "Noto Sans CJK SC",
        "--font-size", "32",
        "--codec", "h265",
        "--preview-seconds", "30",
    ])
    assert args.output_dir == Path("/tmp/out")
    assert args.temp_dir == Path("/tmp/tmp")
    assert args.quality == 720
    assert args.browser == "firefox"
    assert args.keep_temp is True
    assert args.font_face == "Noto Sans CJK SC"
    assert args.font_size == 32
    assert args.codec == "h265"
    assert args.preview_seconds == 30


def test_parse_args_rejects_bad_quality():
    with pytest.raises(SystemExit):
        cli.parse_args(["https://x", "-q", "4320"])


def test_parse_args_rejects_bad_codec():
    with pytest.raises(SystemExit):
        cli.parse_args(["https://x", "--codec", "av1"])


def test_sanitize_title_basic():
    assert cli._sanitize_title("Hello World") == "Hello World"


def test_sanitize_title_chinese():
    t = "恶魔必选沙德沃克！饲料暴风吸入！"
    result = cli._sanitize_title(t)
    assert result == t  # Chinese chars and ！ are allowed (not in forbidden set)


def test_sanitize_title_strips_forbidden_chars():
    assert cli._sanitize_title('foo/bar:baz?qux*.mp4') == "foo_bar_baz_qux_.mp4"


def test_sanitize_title_collapses_whitespace():
    # Control chars (\n, \t) are replaced with '_' first, then whitespace is
    # collapsed, then '_+' is collapsed. So "foo\n\t  bar" becomes "foo_ bar".
    assert cli._sanitize_title("foo\n\t  bar") == "foo_ bar"


def test_sanitize_title_truncates_long_title():
    long = "a" * 200
    result = cli._sanitize_title(long)
    assert len(result) == 60


def test_sanitize_title_truncates_long_chinese_title():
    long = "恶" * 200
    result = cli._sanitize_title(long)
    # Chinese chars count as 1 char each, max 60 chars
    assert len(result) == 60


def test_sanitize_title_empty_falls_back_to_unnamed():
    assert cli._sanitize_title("") == "unnamed"
    assert cli._sanitize_title("   ") == "unnamed"
    assert cli._sanitize_title("...") == "unnamed"


def test_sanitize_title_strips_leading_trailing_dots():
    assert cli._sanitize_title("  foo.  ") == "foo"


def test_build_dir_name_with_long_uploader():
    meta = {"uploader": "炉石郭枫荷", "title": "恶魔必选沙德沃克"}
    assert cli._build_dir_name(meta, "BV1") == "炉石郭枫：恶魔必选沙德沃克"


def test_build_dir_name_with_short_uploader():
    meta = {"uploader": "abc", "title": "Hello"}
    assert cli._build_dir_name(meta, "BV1") == "abc：Hello"


def test_build_dir_name_with_exactly_4_char_uploader():
    meta = {"uploader": "abcd", "title": "Hello"}
    assert cli._build_dir_name(meta, "BV1") == "abcd：Hello"


def test_build_dir_name_missing_uploader():
    meta = {"title": "只有标题"}
    assert cli._build_dir_name(meta, "BV1") == "只有标题"


def test_build_dir_name_empty_uploader():
    meta = {"uploader": "", "title": "只有标题"}
    assert cli._build_dir_name(meta, "BV1") == "只有标题"


def test_build_dir_name_falls_back_to_channel():
    meta = {"channel": "another channel", "title": "Hello"}
    assert cli._build_dir_name(meta, "BV1") == "anot：Hello"


def test_build_dir_name_missing_title_uses_bv_id():
    meta = {"uploader": "炉石郭枫荷"}
    assert cli._build_dir_name(meta, "BV191DpBmE2t") == "炉石郭枫：BV191DpBmE2t"


def test_build_dir_name_truncation_applies():
    meta = {"uploader": "炉石郭枫荷", "title": "a" * 100}
    result = cli._build_dir_name(meta, "BV1")
    assert len(result) == 60  # _sanitize_title truncates to MAX_TITLE_DIR_LENGTH
    assert result.startswith("炉石郭枫：")


def test_build_dir_name_sanitizes_forbidden_chars_in_both():
    meta = {"uploader": "a/b/c/d", "title": "foo:bar"}
    # uploader[:4] = "a/b/", combined = "a/b/：foo:bar" → sanitized
    result = cli._build_dir_name(meta, "BV1")
    # Forbidden halfwidth : and / should be replaced with _
    assert "/" not in result
    assert ":" not in result.replace("：", "")  # strip fullwidth, then no halfwidth
    # "：" fullwidth separator should survive
    assert "：" in result


def test_get_metadata_calls_yt_dlp(monkeypatch):
    captured = {}
    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        result = MagicMock()
        result.stdout = '{"title": "Test Video", "duration": 60, "id": "BV123"}'
        result.returncode = 0
        return result
    monkeypatch.setattr("video2yt.download.subprocess.run", fake_run)
    meta = download.get_metadata("https://www.bilibili.com/video/BV123", "chrome")
    assert meta["title"] == "Test Video"
    assert meta["duration"] == 60
    cmd = captured["cmd"]
    assert cmd[0] == "yt-dlp"
    assert "--cookies-from-browser" in cmd
    assert "chrome" in cmd
    assert "--dump-json" in cmd
    assert "--skip-download" in cmd
    assert cmd[-1] == "https://www.bilibili.com/video/BV123"


def test_run_orchestrates_full_pipeline(tmp_path, monkeypatch, capsys):
    """Full pipeline with all subprocess boundaries mocked; verifies call order."""
    call_log = []

    # Skip dep preflight
    monkeypatch.setattr("video2yt.cli.preflight", lambda: call_log.append("preflight"))
    monkeypatch.setattr(
        "video2yt.cli.download.get_metadata",
        lambda url, browser: {"title": "Test Title"},
    )

    def fake_fetch(url, temp_dir, quality, browser, bv_id, codec="h264"):
        call_log.append(f"fetch:{bv_id}:{quality}:{browser}:{codec}")
        v = temp_dir / f"{bv_id}.mp4"
        v.write_bytes(b"fakevideo")
        x = temp_dir / f"{bv_id}.danmaku.xml"
        x.write_bytes(b"<i><d p='1,1,25,16777215,1,0,0,0'>hi</d></i>")
        return v, x, False

    def fake_generate_ass(xml_path, ass_path, width, height, font_face, font_size):
        call_log.append(f"generate_ass:{width}x{height}:{font_face}:{font_size}")
        ass_path.write_text(
            "[Events]\n"
            "Format: Layer, Start, End, Style, Text\n"
            "Dialogue: 0,0:00:01.00,0:00:05.00,Default,hi\n",
            encoding="utf-8",
        )

    monkeypatch.setattr("video2yt.cli.download.fetch", fake_fetch)
    monkeypatch.setattr("video2yt.cli.download.generate_ass", fake_generate_ass)

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

    def fake_render(video_path, ass_path, output_path, max_duration=None, keep_ranges=None, speed=1.0):
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
    captured_out = capsys.readouterr()

    assert result == tmp_path / "output" / "Test Title" / "BV191DpBmE2t_with_danmaku.mp4"
    assert result.exists()
    # Verify call order
    assert call_log[0] == "preflight"
    assert call_log[1] == "fetch:BV191DpBmE2t:1080:chrome:h264"
    assert call_log[2] == "generate_ass:1920x1080:Hiragino Sans GB:50"
    assert call_log[3] == "render:BV191DpBmE2t_with_danmaku.mp4"
    # Probe called twice: source then output
    assert len(probe_calls) == 2
    # Timing summary should be printed at the end
    assert "timings:" in captured_out.err


def test_run_deletes_derived_ass_on_success(tmp_path, monkeypatch):
    """Default cleanup: derived ASS is removed, raw video+XML preserved for cache."""
    monkeypatch.setattr("video2yt.cli.preflight", lambda: None)
    monkeypatch.setattr(
        "video2yt.cli.download.get_metadata",
        lambda url, browser: {"title": "Test Title"},
    )

    def fake_fetch(url, temp_dir, quality, browser, bv_id, codec="h264"):
        v = temp_dir / f"{bv_id}.mp4"
        v.write_bytes(b"v")
        x = temp_dir / f"{bv_id}.danmaku.xml"
        x.write_bytes(b"<i><d p='1,1,25,16777215,1,0,0,0'>hi</d></i>")
        return v, x, False

    def fake_generate_ass(xml_path, ass_path, width, height, font_face, font_size):
        ass_path.write_text("[Events]\nDialogue: 0,0,0,D,x\n", encoding="utf-8")

    monkeypatch.setattr("video2yt.cli.download.fetch", fake_fetch)
    monkeypatch.setattr("video2yt.cli.download.generate_ass", fake_generate_ass)
    monkeypatch.setattr(
        "video2yt.cli.validate.probe",
        lambda p: MediaInfo(
            duration=60.0, width=1920, height=1080,
            has_video=True, has_audio=True,
            vcodec="h264", acodec="aac", size_bytes=1000,
        ),
    )

    def fake_render(v, a, o, max_duration=None, keep_ranges=None, speed=1.0):
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

    # Raw preserved for cache, derived ASS removed
    subdir = tmp_path / "tmp" / "Test Title"
    assert (subdir / "BV1.mp4").exists()
    assert (subdir / "BV1.danmaku.xml").exists()
    assert not (subdir / "BV1.danmaku.ass").exists()


def test_run_cleanup_removes_cut_ass_by_default(tmp_path, monkeypatch):
    """With --cut, both .danmaku.ass and .danmaku.cut.ass are removed by default (raw kept)."""
    monkeypatch.setattr("video2yt.cli.preflight", lambda: None)
    monkeypatch.setattr(
        "video2yt.cli.download.get_metadata",
        lambda url, browser: {"title": "T", "uploader": "UP"},
    )

    def fake_fetch(url, temp_dir, quality, browser, bv_id, codec="h264"):
        (temp_dir / f"{bv_id}.mp4").write_bytes(b"v")
        (temp_dir / f"{bv_id}.danmaku.xml").write_bytes(b"<i></i>")
        return temp_dir / f"{bv_id}.mp4", temp_dir / f"{bv_id}.danmaku.xml", False

    def fake_generate_ass(xml_path, ass_path, width, height, font_face, font_size):
        ass_path.write_text(
            "[Events]\nFormat: Layer, Start, End, Style\n"
            "Dialogue: 0,0:00:05.00,0:00:10.00,Default,hi\n",
            encoding="utf-8",
        )

    info = MediaInfo(
        duration=200.0, width=1920, height=1080,
        has_video=True, has_audio=True,
        vcodec="h264", acodec="aac", size_bytes=10_000_000,
    )
    out_info = MediaInfo(
        duration=170.0, width=1920, height=1080,
        has_video=True, has_audio=True,
        vcodec="h264", acodec="aac", size_bytes=9_000_000,
    )
    probe_calls = []
    def fake_probe(p):
        probe_calls.append(p)
        return info if len(probe_calls) == 1 else out_info

    monkeypatch.setattr("video2yt.cli.download.fetch", fake_fetch)
    monkeypatch.setattr("video2yt.cli.download.generate_ass", fake_generate_ass)
    monkeypatch.setattr("video2yt.cli.validate.probe", fake_probe)
    monkeypatch.setattr(
        "video2yt.cli.burn.render",
        lambda v, a, o, max_duration=None, keep_ranges=None, speed=1.0: (
            o.parent.mkdir(parents=True, exist_ok=True),
            o.write_bytes(b"x"),
            o,
        )[-1],
    )
    monkeypatch.setattr("video2yt.cli.validate.check_output", lambda s, o, expected_duration=None: [])

    args = cli.parse_args([
        "https://x/video/BV1",
        "-o", str(tmp_path / "out"),
        "-t", str(tmp_path / "tmp"),
        "--cut", "30~60",
    ])
    cli.run(args)

    subdir = tmp_path / "tmp" / "UP：T"
    # Raw preserved
    assert (subdir / "BV1.mp4").exists()
    assert (subdir / "BV1.danmaku.xml").exists()
    # Both derived ASS removed
    assert not (subdir / "BV1.danmaku.ass").exists()
    assert not (subdir / "BV1.danmaku.cut.ass").exists()


def test_run_keep_temp_keeps_all_including_derived(tmp_path, monkeypatch):
    """With --keep-temp and --cut, all four artifacts are preserved after run()."""
    monkeypatch.setattr("video2yt.cli.preflight", lambda: None)
    monkeypatch.setattr(
        "video2yt.cli.download.get_metadata",
        lambda url, browser: {"title": "T", "uploader": "UP"},
    )

    def fake_fetch(url, temp_dir, quality, browser, bv_id, codec="h264"):
        (temp_dir / f"{bv_id}.mp4").write_bytes(b"v")
        (temp_dir / f"{bv_id}.danmaku.xml").write_bytes(b"<i></i>")
        return temp_dir / f"{bv_id}.mp4", temp_dir / f"{bv_id}.danmaku.xml", False

    def fake_generate_ass(xml_path, ass_path, width, height, font_face, font_size):
        ass_path.write_text(
            "[Events]\nFormat: Layer, Start, End, Style\n"
            "Dialogue: 0,0:00:05.00,0:00:10.00,Default,hi\n",
            encoding="utf-8",
        )

    info = MediaInfo(
        duration=200.0, width=1920, height=1080,
        has_video=True, has_audio=True,
        vcodec="h264", acodec="aac", size_bytes=10_000_000,
    )
    out_info = MediaInfo(
        duration=170.0, width=1920, height=1080,
        has_video=True, has_audio=True,
        vcodec="h264", acodec="aac", size_bytes=9_000_000,
    )
    probe_calls = []
    def fake_probe(p):
        probe_calls.append(p)
        return info if len(probe_calls) == 1 else out_info

    monkeypatch.setattr("video2yt.cli.download.fetch", fake_fetch)
    monkeypatch.setattr("video2yt.cli.download.generate_ass", fake_generate_ass)
    monkeypatch.setattr("video2yt.cli.validate.probe", fake_probe)
    monkeypatch.setattr(
        "video2yt.cli.burn.render",
        lambda v, a, o, max_duration=None, keep_ranges=None, speed=1.0: (
            o.parent.mkdir(parents=True, exist_ok=True),
            o.write_bytes(b"x"),
            o,
        )[-1],
    )
    monkeypatch.setattr("video2yt.cli.validate.check_output", lambda s, o, expected_duration=None: [])

    args = cli.parse_args([
        "https://x/video/BV1",
        "-o", str(tmp_path / "out"),
        "-t", str(tmp_path / "tmp"),
        "--cut", "30~60",
        "--keep-temp",
    ])
    cli.run(args)

    subdir = tmp_path / "tmp" / "UP：T"
    # All four artifacts preserved
    assert (subdir / "BV1.mp4").exists()
    assert (subdir / "BV1.danmaku.xml").exists()
    assert (subdir / "BV1.danmaku.ass").exists()
    assert (subdir / "BV1.danmaku.cut.ass").exists()


def test_run_keeps_temp_when_flag_set(tmp_path, monkeypatch):
    monkeypatch.setattr("video2yt.cli.preflight", lambda: None)
    monkeypatch.setattr(
        "video2yt.cli.download.get_metadata",
        lambda url, browser: {"title": "Test Title"},
    )

    def fake_fetch(url, temp_dir, quality, browser, bv_id, codec="h264"):
        v = temp_dir / f"{bv_id}.mp4"
        v.write_bytes(b"v")
        x = temp_dir / f"{bv_id}.danmaku.xml"
        x.write_bytes(b"<i><d p='1,1,25,16777215,1,0,0,0'>hi</d></i>")
        return v, x, False

    def fake_generate_ass(xml_path, ass_path, width, height, font_face, font_size):
        ass_path.write_text("[Events]\nDialogue: 0,0,0,D,x\n", encoding="utf-8")

    monkeypatch.setattr("video2yt.cli.download.fetch", fake_fetch)
    monkeypatch.setattr("video2yt.cli.download.generate_ass", fake_generate_ass)
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
        lambda v, a, o, max_duration=None, keep_ranges=None, speed=1.0: (o.parent.mkdir(parents=True, exist_ok=True), o.write_bytes(b"x"), o)[-1],
    )

    args = cli.parse_args([
        "https://x/video/BV1",
        "-o", str(tmp_path / "out"),
        "-t", str(tmp_path / "tmp"),
        "--keep-temp",
    ])
    cli.run(args)
    subdir = tmp_path / "tmp" / "Test Title"
    assert (subdir / "BV1.mp4").exists()
    assert (subdir / "BV1.danmaku.ass").exists()
    assert (subdir / "BV1.danmaku.xml").exists()


def test_run_computes_font_size_when_auto(tmp_path, monkeypatch):
    """When --font-size is not specified, run() computes it from probed height."""
    monkeypatch.setattr("video2yt.cli.preflight", lambda: None)
    monkeypatch.setattr(
        "video2yt.cli.download.get_metadata",
        lambda url, browser: {"title": "Test Title"},
    )
    captured_font_size = []

    def fake_fetch(url, temp_dir, quality, browser, bv_id, codec="h264"):
        (temp_dir / f"{bv_id}.mp4").write_bytes(b"v")
        (temp_dir / f"{bv_id}.danmaku.xml").write_bytes(
            b"<i><d p='1,1,25,16777215,1,0,0,0'>hi</d></i>"
        )
        return temp_dir / f"{bv_id}.mp4", temp_dir / f"{bv_id}.danmaku.xml", False

    def fake_generate_ass(xml_path, ass_path, width, height, font_face, font_size):
        captured_font_size.append(font_size)
        ass_path.write_text(
            "[Events]\nFormat: Layer\nDialogue: 0,0,0,D,hi\n", encoding="utf-8",
        )

    source_info = MediaInfo(
        duration=60.0, width=480, height=852,
        has_video=True, has_audio=True,
        vcodec="h264", acodec="aac", size_bytes=10_000_000,
    )
    output_info = MediaInfo(
        duration=60.0, width=480, height=852,
        has_video=True, has_audio=True,
        vcodec="h264", acodec="aac", size_bytes=11_000_000,
    )
    probe_calls = []

    def fake_probe(path):
        probe_calls.append(path)
        return source_info if len(probe_calls) == 1 else output_info

    monkeypatch.setattr("video2yt.cli.download.fetch", fake_fetch)
    monkeypatch.setattr("video2yt.cli.download.generate_ass", fake_generate_ass)
    monkeypatch.setattr("video2yt.cli.validate.probe", fake_probe)
    monkeypatch.setattr(
        "video2yt.cli.burn.render",
        lambda v, a, o, max_duration=None, keep_ranges=None, speed=1.0: (o.parent.mkdir(parents=True, exist_ok=True), o.write_bytes(b"x"), o)[-1],
    )

    args = cli.parse_args([
        "https://www.bilibili.com/video/BV1/",
        "-o", str(tmp_path / "out"),
        "-t", str(tmp_path / "tmp"),
    ])
    cli.run(args)
    # auto-computed for height=852: 852/21.6 ≈ 39
    assert 38 <= captured_font_size[0] <= 41


def test_run_uses_explicit_font_size_when_given(tmp_path, monkeypatch):
    """When --font-size is explicit, run() bypasses compute_font_size."""
    monkeypatch.setattr("video2yt.cli.preflight", lambda: None)
    monkeypatch.setattr(
        "video2yt.cli.download.get_metadata",
        lambda url, browser: {"title": "Test Title"},
    )
    captured_font_size = []

    def fake_fetch(url, temp_dir, quality, browser, bv_id, codec="h264"):
        (temp_dir / f"{bv_id}.mp4").write_bytes(b"v")
        (temp_dir / f"{bv_id}.danmaku.xml").write_bytes(
            b"<i><d p='1,1,25,16777215,1,0,0,0'>hi</d></i>"
        )
        return temp_dir / f"{bv_id}.mp4", temp_dir / f"{bv_id}.danmaku.xml", False

    def fake_generate_ass(xml_path, ass_path, width, height, font_face, font_size):
        captured_font_size.append(font_size)
        ass_path.write_text(
            "[Events]\nFormat: Layer\nDialogue: 0,0,0,D,hi\n", encoding="utf-8",
        )

    source_info = MediaInfo(
        duration=60.0, width=480, height=852,
        has_video=True, has_audio=True,
        vcodec="h264", acodec="aac", size_bytes=10_000_000,
    )
    output_info = MediaInfo(
        duration=60.0, width=480, height=852,
        has_video=True, has_audio=True,
        vcodec="h264", acodec="aac", size_bytes=11_000_000,
    )
    probe_calls = []

    def fake_probe(path):
        probe_calls.append(path)
        return source_info if len(probe_calls) == 1 else output_info

    monkeypatch.setattr("video2yt.cli.download.fetch", fake_fetch)
    monkeypatch.setattr("video2yt.cli.download.generate_ass", fake_generate_ass)
    monkeypatch.setattr("video2yt.cli.validate.probe", fake_probe)
    monkeypatch.setattr(
        "video2yt.cli.burn.render",
        lambda v, a, o, max_duration=None, keep_ranges=None, speed=1.0: (o.parent.mkdir(parents=True, exist_ok=True), o.write_bytes(b"x"), o)[-1],
    )

    args = cli.parse_args([
        "https://www.bilibili.com/video/BV1/",
        "-o", str(tmp_path / "out"),
        "-t", str(tmp_path / "tmp"),
        "--font-size", "60",
    ])
    cli.run(args)
    # Explicit value should be used as-is, bypassing compute_font_size
    assert captured_font_size == [60]


def test_main_returns_1_on_value_error(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("video2yt.cli.preflight", lambda: None)
    # Make extract_bv_id fail via non-bilibili URL
    rc = cli.main(["https://www.youtube.com/x"])
    assert rc == 1
    out = capsys.readouterr()
    assert "BV" in out.err or "error" in out.err.lower()


def test_run_passes_expected_duration_in_preview_mode(tmp_path, monkeypatch):
    """With --preview-seconds N, cli.run should pass expected_duration=N to check_output."""
    captured = {}
    monkeypatch.setattr("video2yt.cli.preflight", lambda: None)
    monkeypatch.setattr(
        "video2yt.cli.download.get_metadata",
        lambda url, browser: {"title": "Test Title"},
    )

    def fake_fetch(url, temp_dir, quality, browser, bv_id, codec="h264"):
        (temp_dir / f"{bv_id}.mp4").write_bytes(b"v")
        (temp_dir / f"{bv_id}.danmaku.xml").write_bytes(
            b"<i><d p='1,1,25,16777215,1,0,0,0'>hi</d></i>"
        )
        return temp_dir / f"{bv_id}.mp4", temp_dir / f"{bv_id}.danmaku.xml", False

    def fake_generate_ass(xml_path, ass_path, width, height, font_face, font_size):
        ass_path.write_text("[Events]\nDialogue: 0,0,0,D,x\n", encoding="utf-8")

    source_info = MediaInfo(
        duration=1260.0, width=1920, height=1080,
        has_video=True, has_audio=True,
        vcodec="h264", acodec="aac", size_bytes=371_000_000,
    )
    output_info = MediaInfo(
        duration=60.0, width=1920, height=1080,
        has_video=True, has_audio=True,
        vcodec="h264", acodec="aac", size_bytes=26_000_000,
    )
    probe_calls = []

    def fake_probe(p):
        probe_calls.append(p)
        return source_info if len(probe_calls) == 1 else output_info

    def fake_check_output(source, output, expected_duration=None):
        captured["expected_duration"] = expected_duration
        return []

    monkeypatch.setattr("video2yt.cli.download.fetch", fake_fetch)
    monkeypatch.setattr("video2yt.cli.download.generate_ass", fake_generate_ass)
    monkeypatch.setattr("video2yt.cli.validate.probe", fake_probe)
    monkeypatch.setattr("video2yt.cli.validate.check_output", fake_check_output)
    monkeypatch.setattr(
        "video2yt.cli.burn.render",
        lambda v, a, o, max_duration=None, keep_ranges=None, speed=1.0: (
            o.parent.mkdir(parents=True, exist_ok=True),
            o.write_bytes(b"x"),
            o,
        )[-1],
    )

    args = cli.parse_args([
        "https://x/video/BV1",
        "-o", str(tmp_path / "out"),
        "-t", str(tmp_path / "tmp"),
        "--preview-seconds", "60",
    ])
    cli.run(args)
    assert captured["expected_duration"] == 60.0


def test_run_passes_source_duration_when_not_preview(tmp_path, monkeypatch):
    """Without --preview-seconds, expected_duration defaults to source.duration."""
    captured = {}
    monkeypatch.setattr("video2yt.cli.preflight", lambda: None)
    monkeypatch.setattr(
        "video2yt.cli.download.get_metadata",
        lambda url, browser: {"title": "Test Title"},
    )

    def fake_fetch(url, temp_dir, quality, browser, bv_id, codec="h264"):
        (temp_dir / f"{bv_id}.mp4").write_bytes(b"v")
        (temp_dir / f"{bv_id}.danmaku.xml").write_bytes(
            b"<i><d p='1,1,25,16777215,1,0,0,0'>hi</d></i>"
        )
        return temp_dir / f"{bv_id}.mp4", temp_dir / f"{bv_id}.danmaku.xml", False

    def fake_generate_ass(xml_path, ass_path, width, height, font_face, font_size):
        ass_path.write_text("[Events]\nDialogue: 0,0,0,D,x\n", encoding="utf-8")

    source_info = MediaInfo(
        duration=1260.0, width=1920, height=1080,
        has_video=True, has_audio=True,
        vcodec="h264", acodec="aac", size_bytes=371_000_000,
    )
    output_info = MediaInfo(
        duration=1260.0, width=1920, height=1080,
        has_video=True, has_audio=True,
        vcodec="h264", acodec="aac", size_bytes=371_000_000,
    )
    probe_calls = []

    def fake_probe(p):
        probe_calls.append(p)
        return source_info if len(probe_calls) == 1 else output_info

    def fake_check_output(source, output, expected_duration=None):
        captured["expected_duration"] = expected_duration
        return []

    monkeypatch.setattr("video2yt.cli.download.fetch", fake_fetch)
    monkeypatch.setattr("video2yt.cli.download.generate_ass", fake_generate_ass)
    monkeypatch.setattr("video2yt.cli.validate.probe", fake_probe)
    monkeypatch.setattr("video2yt.cli.validate.check_output", fake_check_output)
    monkeypatch.setattr(
        "video2yt.cli.burn.render",
        lambda v, a, o, max_duration=None, keep_ranges=None, speed=1.0: (
            o.parent.mkdir(parents=True, exist_ok=True),
            o.write_bytes(b"x"),
            o,
        )[-1],
    )

    args = cli.parse_args([
        "https://x/video/BV1",
        "-o", str(tmp_path / "out"),
        "-t", str(tmp_path / "tmp"),
    ])
    cli.run(args)
    assert captured["expected_duration"] == 1260.0


def test_run_creates_subfolder_from_video_title(tmp_path, monkeypatch):
    monkeypatch.setattr("video2yt.cli.preflight", lambda: None)
    monkeypatch.setattr(
        "video2yt.cli.download.get_metadata",
        lambda url, browser: {"title": "我 的/视频: Test"},
    )

    def fake_fetch(url, temp_dir, quality, browser, bv_id, codec="h264"):
        (temp_dir / f"{bv_id}.mp4").write_bytes(b"v")
        (temp_dir / f"{bv_id}.danmaku.xml").write_bytes(
            b"<i><d p='1,1,25,16777215,1,0,0,0'>hi</d></i>"
        )
        return temp_dir / f"{bv_id}.mp4", temp_dir / f"{bv_id}.danmaku.xml", False

    def fake_generate_ass(xml_path, ass_path, width, height, font_face, font_size):
        ass_path.write_text(
            "[Events]\nFormat: Layer\nDialogue: 0,0,0,D,hi\n", encoding="utf-8",
        )

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
    probe_calls = []

    def fake_probe(p):
        probe_calls.append(p)
        return source_info if len(probe_calls) == 1 else output_info

    monkeypatch.setattr("video2yt.cli.download.fetch", fake_fetch)
    monkeypatch.setattr("video2yt.cli.download.generate_ass", fake_generate_ass)
    monkeypatch.setattr("video2yt.cli.validate.probe", fake_probe)
    monkeypatch.setattr(
        "video2yt.cli.burn.render",
        lambda v, a, o, max_duration=None, keep_ranges=None, speed=1.0: (
            o.parent.mkdir(parents=True, exist_ok=True),
            o.write_bytes(b"x"),
            o,
        )[-1],
    )

    args = cli.parse_args([
        "https://www.bilibili.com/video/BV1",
        "-o", str(tmp_path / "out"),
        "-t", str(tmp_path / "tmp"),
        "--keep-temp",
    ])
    result = cli.run(args)

    # Sanitizer behavior: "我 的/视频: Test"
    #   1. '/' -> '_', ':' -> '_'  => "我 的_视频_ Test"
    #   2. whitespace collapse: already single spaces
    #   3. '_+' collapse: already single
    #   4. strip leading/trailing ._ and spaces: unchanged
    expected_dir = "我 的_视频_ Test"
    assert (tmp_path / "tmp" / expected_dir).is_dir()
    assert (tmp_path / "out" / expected_dir).is_dir()
    assert result == tmp_path / "out" / expected_dir / "BV1_with_danmaku.mp4"


def test_run_subfolder_includes_uploader_prefix(tmp_path, monkeypatch):
    monkeypatch.setattr("video2yt.cli.preflight", lambda: None)
    monkeypatch.setattr(
        "video2yt.cli.download.get_metadata",
        lambda url, browser: {"uploader": "炉石郭枫荷", "title": "恶魔必选"},
    )

    def fake_fetch(url, temp_dir, quality, browser, bv_id, codec="h264"):
        (temp_dir / f"{bv_id}.mp4").write_bytes(b"v")
        (temp_dir / f"{bv_id}.danmaku.xml").write_bytes(
            b"<i><d p='1,1,25,16777215,1,0,0,0'>hi</d></i>"
        )
        return temp_dir / f"{bv_id}.mp4", temp_dir / f"{bv_id}.danmaku.xml", False

    def fake_generate_ass(xml_path, ass_path, width, height, font_face, font_size):
        ass_path.write_text(
            "[Events]\nFormat: Layer\nDialogue: 0,0,0,D,hi\n", encoding="utf-8",
        )

    info = MediaInfo(
        duration=60.0, width=1920, height=1080,
        has_video=True, has_audio=True,
        vcodec="h264", acodec="aac", size_bytes=10_000_000,
    )
    probe_calls = []

    def fake_probe(p):
        probe_calls.append(p)
        return info

    monkeypatch.setattr("video2yt.cli.download.fetch", fake_fetch)
    monkeypatch.setattr("video2yt.cli.download.generate_ass", fake_generate_ass)
    monkeypatch.setattr("video2yt.cli.validate.probe", fake_probe)
    monkeypatch.setattr(
        "video2yt.cli.burn.render",
        lambda v, a, o, max_duration=None, keep_ranges=None, speed=1.0: (
            o.parent.mkdir(parents=True, exist_ok=True),
            o.write_bytes(b"x"),
            o,
        )[-1],
    )

    args = cli.parse_args([
        "https://www.bilibili.com/video/BV1",
        "-o", str(tmp_path / "out"),
        "-t", str(tmp_path / "tmp"),
        "--keep-temp",
    ])
    result = cli.run(args)
    expected_dir = "炉石郭枫：恶魔必选"
    assert (tmp_path / "tmp" / expected_dir).is_dir()
    assert (tmp_path / "out" / expected_dir).is_dir()
    assert result == tmp_path / "out" / expected_dir / "BV1_with_danmaku.mp4"


# =============================================================================
# --cut feature tests
# =============================================================================

from video2yt import cuts


# ---- parse_time ----

def test_parse_time_seconds():
    assert cuts.parse_time("30") == 30.0
    assert cuts.parse_time("30.5") == 30.5


def test_parse_time_mm_ss():
    assert cuts.parse_time("1:30") == 90.0
    assert cuts.parse_time("0:05") == 5.0
    assert cuts.parse_time("2:15.5") == 135.5


def test_parse_time_hh_mm_ss():
    assert cuts.parse_time("0:00:30") == 30.0
    assert cuts.parse_time("1:05:30") == 3930.0
    assert cuts.parse_time("1:05:30.75") == 3930.75


def test_parse_time_rejects_invalid():
    with pytest.raises(ValueError):
        cuts.parse_time("abc")
    with pytest.raises(ValueError):
        cuts.parse_time("-30")
    with pytest.raises(ValueError):
        cuts.parse_time("1:2:3:4")


def test_parse_cut_range_seconds():
    assert cuts.parse_cut_range("30~60") == (30.0, 60.0)


def test_parse_cut_range_mm_ss():
    assert cuts.parse_cut_range("0:30~1:00") == (30.0, 60.0)


def test_parse_cut_range_hh_mm_ss():
    assert cuts.parse_cut_range("00:01:30~00:02:00") == (90.0, 120.0)


def test_parse_cut_range_rejects_no_separator():
    with pytest.raises(ValueError, match="~"):
        cuts.parse_cut_range("30,60")


# ---- normalize_cuts ----

def test_normalize_cuts_swaps_reversed():
    result = cuts.normalize_cuts([(60.0, 30.0)], 100.0)
    assert result == [(30.0, 60.0)]


def test_normalize_cuts_drops_zero_width():
    result = cuts.normalize_cuts([(30.0, 30.0), (40.0, 50.0)], 100.0)
    assert result == [(40.0, 50.0)]


def test_normalize_cuts_clips_to_duration():
    result = cuts.normalize_cuts([(90.0, 120.0)], 100.0)
    assert result == [(90.0, 100.0)]


def test_normalize_cuts_drops_fully_outside():
    result = cuts.normalize_cuts([(150.0, 200.0), (30.0, 50.0)], 100.0)
    assert result == [(30.0, 50.0)]


def test_normalize_cuts_sorts():
    result = cuts.normalize_cuts([(60.0, 80.0), (10.0, 30.0)], 100.0)
    assert result == [(10.0, 30.0), (60.0, 80.0)]


def test_normalize_cuts_merges_overlapping():
    result = cuts.normalize_cuts([(10.0, 30.0), (20.0, 40.0)], 100.0)
    assert result == [(10.0, 40.0)]


def test_normalize_cuts_merges_abutting():
    result = cuts.normalize_cuts([(10.0, 20.0), (20.0, 30.0)], 100.0)
    assert result == [(10.0, 30.0)]


def test_normalize_cuts_raises_on_full_coverage():
    with pytest.raises(ValueError, match="entire"):
        cuts.normalize_cuts([(0.0, 100.0)], 100.0)


# ---- keep_ranges_from_cuts ----

def test_keep_ranges_empty_cuts():
    assert cuts.keep_ranges_from_cuts([], 100.0) == [(0.0, 100.0)]


def test_keep_ranges_middle_cut():
    assert cuts.keep_ranges_from_cuts([(30.0, 60.0)], 100.0) == [(0.0, 30.0), (60.0, 100.0)]


def test_keep_ranges_cut_at_start():
    assert cuts.keep_ranges_from_cuts([(0.0, 30.0)], 100.0) == [(30.0, 100.0)]


def test_keep_ranges_cut_at_end():
    assert cuts.keep_ranges_from_cuts([(70.0, 100.0)], 100.0) == [(0.0, 70.0)]


def test_keep_ranges_multiple_cuts():
    assert cuts.keep_ranges_from_cuts(
        [(30.0, 60.0), (135.0, 165.0)], 300.0
    ) == [(0.0, 30.0), (60.0, 135.0), (165.0, 300.0)]


# ---- ASS rewrite ----

_ASS_HEADER = "\n".join([
    "[Script Info]",
    "Title: test",
    "",
    "[V4+ Styles]",
    "Format: Name, Fontname, Fontsize",
    "Style: Default,Arial,40",
    "",
    "[Events]",
    "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
]) + "\n"


def _ass_with_dialogues(dialogues: list[str]) -> str:
    return _ASS_HEADER + "\n".join(f"Dialogue: {d}" for d in dialogues) + "\n"


def test_rewrite_ass_no_cuts_is_noop():
    ass_in = _ass_with_dialogues([
        "0,0:00:10.00,0:00:15.00,Default,,0,0,0,,hello",
    ])
    assert cuts.rewrite_ass_for_cuts(ass_in, []) == ass_in


def test_rewrite_ass_drops_dialogue_inside_cut():
    ass_in = _ass_with_dialogues([
        "0,0:00:40.00,0:00:50.00,Default,,0,0,0,,inside",
        "0,0:00:05.00,0:00:10.00,Default,,0,0,0,,before",
    ])
    out = cuts.rewrite_ass_for_cuts(ass_in, [(30.0, 60.0)])
    assert "inside" not in out
    assert "before" in out


def test_rewrite_ass_drops_straddling_dialogue():
    ass_in = _ass_with_dialogues([
        "0,0:00:25.00,0:00:35.00,Default,,0,0,0,,straddle_start",
        "0,0:00:55.00,0:00:65.00,Default,,0,0,0,,straddle_end",
        "0,0:00:20.00,0:00:70.00,Default,,0,0,0,,spanning",
    ])
    out = cuts.rewrite_ass_for_cuts(ass_in, [(30.0, 60.0)])
    assert "straddle_start" not in out
    assert "straddle_end" not in out
    assert "spanning" not in out


def test_rewrite_ass_shifts_after_cut():
    # Cut: 30~60 (30s removed). A dialogue at 70-75 in source should move to 40-45 in output.
    ass_in = _ass_with_dialogues([
        "0,0:01:10.00,0:01:15.00,Default,,0,0,0,,after",
    ])
    out = cuts.rewrite_ass_for_cuts(ass_in, [(30.0, 60.0)])
    assert "0:00:40.00" in out
    assert "0:00:45.00" in out
    assert "after" in out


def test_rewrite_ass_multiple_cuts_cumulative_shift():
    # Cuts: 10~20 (10s) and 30~40 (10s). A dialogue at 50-55 -> shift by 20 -> 30-35
    ass_in = _ass_with_dialogues([
        "0,0:00:50.00,0:00:55.00,Default,,0,0,0,,later",
    ])
    out = cuts.rewrite_ass_for_cuts(ass_in, [(10.0, 20.0), (30.0, 40.0)])
    assert "0:00:30.00" in out
    assert "0:00:35.00" in out


def test_rewrite_ass_preserves_headers():
    ass_in = _ass_with_dialogues(["0,0:00:10.00,0:00:15.00,Default,,0,0,0,,a"])
    out = cuts.rewrite_ass_for_cuts(ass_in, [(100.0, 200.0)])
    assert "[Script Info]" in out
    assert "[V4+ Styles]" in out
    assert "[Events]" in out
    assert "Style: Default,Arial,40" in out


# ---- burn filter_complex ----

def test_build_filter_complex_single_keep_range():
    from video2yt.burn import _build_filter_complex
    s = _build_filter_complex([(0.0, 100.0)], "x.ass")
    assert "trim=0" in s or "trim=start=0" in s
    assert "concat=n=1" in s
    assert "subtitles=f='x.ass'" in s


def test_build_filter_complex_multiple_keep_ranges():
    from video2yt.burn import _build_filter_complex
    s = _build_filter_complex([(0.0, 30.0), (60.0, 100.0)], "x.ass")
    assert "concat=n=2" in s
    assert "atrim=0" in s or "atrim=start=0" in s
    assert "atrim=60" in s or "atrim=start=60" in s
    assert "subtitles=f='x.ass'" in s


def test_build_filter_complex_speed_only_no_cut():
    from video2yt.burn import _build_filter_complex
    fc = _build_filter_complex(None, "x.ass", speed=1.5)
    assert "[0:v]null[cv]" in fc
    assert "[0:a]anull[ca]" in fc
    assert "subtitles=f='x.ass'[sv]" in fc
    assert "setpts=PTS/1.5[outv]" in fc
    assert "atempo=1.5[outa]" in fc


def test_build_filter_complex_cut_and_speed():
    from video2yt.burn import _build_filter_complex
    fc = _build_filter_complex([(0.0, 30.0), (60.0, 100.0)], "x.ass", speed=2.0)
    assert "trim=start=0.0:end=30.0" in fc
    assert "trim=start=60.0:end=100.0" in fc
    assert "concat=n=2:v=1:a=1[cv][ca]" in fc
    assert "subtitles=f='x.ass'[sv]" in fc
    assert "setpts=PTS/2.0[outv]" in fc
    assert "atempo=2.0[outa]" in fc


def test_build_filter_complex_cut_no_speed_still_produces_outv_outa():
    """With cuts but speed=1.0, still emits [outv] and [outa] via null filters."""
    from video2yt.burn import _build_filter_complex
    fc = _build_filter_complex([(0.0, 30.0), (60.0, 100.0)], "x.ass", speed=1.0)
    assert "concat=n=2:v=1:a=1[cv][ca]" in fc
    assert "subtitles=f='x.ass'[sv]" in fc
    assert "[sv]null[outv]" in fc
    assert "[ca]anull[outa]" in fc
    # Should NOT contain setpts or atempo
    assert "setpts=PTS/" not in fc
    assert "atempo=" not in fc


def test_build_filter_complex_no_cut_no_speed_uses_passthrough():
    """With no cut and speed=1.0, filter_complex is all passthrough (this fn is typically not called then)."""
    from video2yt.burn import _build_filter_complex
    fc = _build_filter_complex(None, "x.ass", speed=1.0)
    assert "[0:v]null[cv]" in fc
    assert "[0:a]anull[ca]" in fc
    assert "[sv]null[outv]" in fc
    assert "[ca]anull[outa]" in fc


def test_render_with_cut_ranges_uses_filter_complex(tmp_path, monkeypatch):
    temp_dir = tmp_path / "temp"
    temp_dir.mkdir()
    video = temp_dir / "BV.mp4"
    video.write_bytes(b"v")
    ass = temp_dir / "BV.danmaku.ass"
    ass.write_text("data", encoding="utf-8")
    output = tmp_path / "output" / "BV_out.mp4"

    captured = {}
    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"burned")
        return MagicMock(returncode=0)
    monkeypatch.setattr("video2yt.burn.subprocess.run", fake_run)

    burn.render(video, ass, output, keep_ranges=[(0.0, 30.0), (60.0, 100.0)])

    cmd = captured["cmd"]
    assert "-filter_complex" in cmd
    assert "-c:a" in cmd
    ca_idx = cmd.index("-c:a")
    assert cmd[ca_idx + 1] == "aac"
    assert "-vf" not in cmd
    # Both maps point to outv/outa (speed change made [outa] uniform)
    assert any(a == "[outv]" for a in cmd)
    assert any(a == "[outa]" for a in cmd)


def test_render_with_speed_uses_filter_complex(tmp_path, monkeypatch):
    temp_dir = tmp_path / "temp"
    temp_dir.mkdir()
    video = temp_dir / "BV.mp4"
    video.write_bytes(b"v")
    ass = temp_dir / "BV.danmaku.ass"
    ass.write_text("data", encoding="utf-8")
    output = tmp_path / "output" / "BV_out.mp4"

    captured = {}
    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"burned")
        return MagicMock(returncode=0)
    monkeypatch.setattr("video2yt.burn.subprocess.run", fake_run)

    burn.render(video, ass, output, speed=1.5)

    cmd = captured["cmd"]
    assert "-filter_complex" in cmd
    fc_idx = cmd.index("-filter_complex")
    assert "setpts=PTS/1.5" in cmd[fc_idx + 1]
    assert "atempo=1.5" in cmd[fc_idx + 1]
    # Both maps point to outv/outa
    assert any(a == "[outv]" for a in cmd)
    assert any(a == "[outa]" for a in cmd)
    # Audio re-encoded
    ca_idx = cmd.index("-c:a")
    assert cmd[ca_idx + 1] == "aac"


def test_render_with_cut_maps_outa_now(tmp_path, monkeypatch):
    """Cut-only test: filter_complex now always maps [outa] instead of [ca]."""
    temp_dir = tmp_path / "temp"
    temp_dir.mkdir()
    video = temp_dir / "BV.mp4"
    video.write_bytes(b"v")
    ass = temp_dir / "BV.danmaku.ass"
    ass.write_text("data", encoding="utf-8")
    output = tmp_path / "output" / "BV_out.mp4"

    captured = {}
    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"burned")
        return MagicMock(returncode=0)
    monkeypatch.setattr("video2yt.burn.subprocess.run", fake_run)

    burn.render(video, ass, output, keep_ranges=[(0.0, 30.0), (60.0, 100.0)], speed=1.0)

    cmd = captured["cmd"]
    assert "-filter_complex" in cmd
    assert any(a == "[outv]" for a in cmd)
    assert any(a == "[outa]" for a in cmd)  # now always outa
    ca_idx = cmd.index("-c:a")
    assert cmd[ca_idx + 1] == "aac"


def test_render_without_cut_without_speed_uses_simple_path(tmp_path, monkeypatch):
    """When speed=1.0 and no cuts, still use the simple -vf path."""
    temp_dir = tmp_path / "temp"
    temp_dir.mkdir()
    video = temp_dir / "BV.mp4"
    video.write_bytes(b"v")
    ass = temp_dir / "BV.danmaku.ass"
    ass.write_text("data", encoding="utf-8")
    output = tmp_path / "output" / "BV_out.mp4"

    captured = {}
    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"burned")
        return MagicMock(returncode=0)
    monkeypatch.setattr("video2yt.burn.subprocess.run", fake_run)

    burn.render(video, ass, output)  # defaults: keep_ranges=None, speed=1.0

    cmd = captured["cmd"]
    assert "-filter_complex" not in cmd
    assert "-vf" in cmd
    ca_idx = cmd.index("-c:a")
    assert cmd[ca_idx + 1] == "copy"


def test_render_without_cut_ranges_uses_simple_path(tmp_path, monkeypatch):
    temp_dir = tmp_path / "temp"
    temp_dir.mkdir()
    video = temp_dir / "BV.mp4"
    video.write_bytes(b"v")
    ass = temp_dir / "BV.danmaku.ass"
    ass.write_text("data", encoding="utf-8")
    output = tmp_path / "output" / "BV_out.mp4"

    captured = {}
    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"burned")
        return MagicMock(returncode=0)
    monkeypatch.setattr("video2yt.burn.subprocess.run", fake_run)

    burn.render(video, ass, output)  # no keep_ranges

    cmd = captured["cmd"]
    assert "-vf" in cmd
    assert "-filter_complex" not in cmd
    ca_idx = cmd.index("-c:a")
    assert cmd[ca_idx + 1] == "copy"


# ---- CLI integration ----

def test_parse_args_cut_empty_default():
    args = cli.parse_args(["https://x/video/BV1"])
    assert args.cut == []


def test_parse_args_cut_single():
    args = cli.parse_args(["https://x/video/BV1", "--cut", "30~60"])
    assert args.cut == ["30~60"]


def test_parse_args_cut_multiple():
    args = cli.parse_args([
        "https://x/video/BV1",
        "--cut", "30~60",
        "--cut", "2:15~2:45",
    ])
    assert args.cut == ["30~60", "2:15~2:45"]


def test_run_passes_keep_ranges_and_rewrites_ass(tmp_path, monkeypatch):
    """End-to-end mock: --cut should cause keep_ranges to reach burn.render and
    the ASS to be rewritten before burn."""
    monkeypatch.setattr("video2yt.cli.preflight", lambda: None)
    monkeypatch.setattr(
        "video2yt.cli.download.get_metadata",
        lambda url, browser: {"title": "Test", "uploader": "TestUp"},
    )

    def fake_fetch(url, temp_dir, quality, browser, bv_id, codec="h264"):
        (temp_dir / f"{bv_id}.mp4").write_bytes(b"v")
        (temp_dir / f"{bv_id}.danmaku.xml").write_bytes(
            b"<i><d p='1,1,25,16777215,1,0,0,0'>hi</d></i>"
        )
        return temp_dir / f"{bv_id}.mp4", temp_dir / f"{bv_id}.danmaku.xml", False

    def fake_generate_ass(xml_path, ass_path, width, height, font_face, font_size):
        ass_path.write_text(
            _ass_with_dialogues([
                "0,0:00:10.00,0:00:15.00,Default,,0,0,0,,keep1",
                "0,0:00:40.00,0:00:50.00,Default,,0,0,0,,cut",
                "0,0:01:10.00,0:01:15.00,Default,,0,0,0,,keep2",
            ]),
            encoding="utf-8",
        )

    info = MediaInfo(
        duration=200.0, width=1920, height=1080,
        has_video=True, has_audio=True,
        vcodec="h264", acodec="aac", size_bytes=10_000_000,
    )
    out_info = MediaInfo(
        duration=170.0, width=1920, height=1080,
        has_video=True, has_audio=True,
        vcodec="h264", acodec="aac", size_bytes=9_000_000,
    )
    probe_calls = []
    def fake_probe(p):
        probe_calls.append(p)
        return info if len(probe_calls) == 1 else out_info

    captured_render = {}
    def fake_render(video_path, ass_path, output_path, max_duration=None, keep_ranges=None, speed=1.0):
        captured_render["keep_ranges"] = keep_ranges
        captured_render["ass_path"] = ass_path
        captured_render["ass_text"] = ass_path.read_text(encoding="utf-8")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"x")
        return output_path

    monkeypatch.setattr("video2yt.cli.download.fetch", fake_fetch)
    monkeypatch.setattr("video2yt.cli.download.generate_ass", fake_generate_ass)
    monkeypatch.setattr("video2yt.cli.validate.probe", fake_probe)
    monkeypatch.setattr("video2yt.cli.burn.render", fake_render)
    monkeypatch.setattr("video2yt.cli.validate.check_output", lambda s, o, expected_duration=None: [])

    args = cli.parse_args([
        "https://www.bilibili.com/video/BV1",
        "-o", str(tmp_path / "out"),
        "-t", str(tmp_path / "tmp"),
        "--cut", "30~60",
        "--keep-temp",
    ])
    cli.run(args)

    assert captured_render["keep_ranges"] == [(0.0, 30.0), (60.0, 200.0)]
    ass = captured_render["ass_text"]
    # keep1 unchanged (before cut)
    assert "0:00:10.00" in ass
    assert "0:00:15.00" in ass
    # keep2 shifted by 30s: 70-75 -> 40-45
    assert "0:00:40.00" in ass
    assert "0:00:45.00" in ass
    # "cut" line at 40-50 should be dropped entirely
    assert "cut" not in ass


def test_run_with_cut_and_preview_seconds(tmp_path, monkeypatch):
    """When both --cut and --preview-seconds are set: cut first, then preview clamps."""
    captured = {}
    monkeypatch.setattr("video2yt.cli.preflight", lambda: None)
    monkeypatch.setattr(
        "video2yt.cli.download.get_metadata",
        lambda url, browser: {"title": "Test"},
    )

    def fake_fetch(url, temp_dir, quality, browser, bv_id, codec="h264"):
        (temp_dir / f"{bv_id}.mp4").write_bytes(b"v")
        (temp_dir / f"{bv_id}.danmaku.xml").write_bytes(
            b"<i><d p='1,1,25,16777215,1,0,0,0'>hi</d></i>"
        )
        return temp_dir / f"{bv_id}.mp4", temp_dir / f"{bv_id}.danmaku.xml", False

    def fake_generate_ass(xml_path, ass_path, width, height, font_face, font_size):
        ass_path.write_text(
            _ass_with_dialogues([
                "0,0:00:05.00,0:00:08.00,Default,,0,0,0,,a",
            ]),
            encoding="utf-8",
        )

    source_info = MediaInfo(
        duration=200.0, width=1920, height=1080,
        has_video=True, has_audio=True,
        vcodec="h264", acodec="aac", size_bytes=10_000_000,
    )
    output_info = MediaInfo(
        duration=60.0, width=1920, height=1080,
        has_video=True, has_audio=True,
        vcodec="h264", acodec="aac", size_bytes=5_000_000,
    )
    probe_calls = []
    def fake_probe(p):
        probe_calls.append(p)
        return source_info if len(probe_calls) == 1 else output_info

    def fake_check_output(source, output, expected_duration=None):
        captured["expected_duration"] = expected_duration
        return []

    def fake_render(video_path, ass_path, output_path, max_duration=None, keep_ranges=None, speed=1.0):
        captured["keep_ranges"] = keep_ranges
        captured["max_duration"] = max_duration
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"x")
        return output_path

    monkeypatch.setattr("video2yt.cli.download.fetch", fake_fetch)
    monkeypatch.setattr("video2yt.cli.download.generate_ass", fake_generate_ass)
    monkeypatch.setattr("video2yt.cli.validate.probe", fake_probe)
    monkeypatch.setattr("video2yt.cli.validate.check_output", fake_check_output)
    monkeypatch.setattr("video2yt.cli.burn.render", fake_render)

    args = cli.parse_args([
        "https://www.bilibili.com/video/BV1",
        "-o", str(tmp_path / "out"),
        "-t", str(tmp_path / "tmp"),
        "--cut", "30~60",
        "--preview-seconds", "60",
        "--keep-temp",
    ])
    cli.run(args)

    # Cut 30~60 (30s removed) on 200s source -> kept_duration = 170
    # preview = 60 -> expected_duration = min(60, 170) = 60
    assert captured["expected_duration"] == 60.0
    assert captured["keep_ranges"] == [(0.0, 30.0), (60.0, 200.0)]
    assert captured["max_duration"] == 60


# ---- --speed CLI + run() integration ----

def test_parse_args_speed_default():
    args = cli.parse_args(["https://x/video/BV1"])
    assert args.speed == 1.0


def test_parse_args_speed_custom():
    args = cli.parse_args(["https://x/video/BV1", "--speed", "1.5"])
    assert args.speed == 1.5


def test_parse_args_speed_accepts_float():
    args = cli.parse_args(["https://x/video/BV1", "--speed", "1.25"])
    assert args.speed == 1.25


def test_run_rejects_speed_above_range(tmp_path, monkeypatch):
    monkeypatch.setattr("video2yt.cli.preflight", lambda: None)
    args = cli.parse_args(["https://x/video/BV1", "--speed", "3.0"])
    with pytest.raises(ValueError, match="0.5 and 2.0"):
        cli.run(args)


def test_run_rejects_speed_below_range(tmp_path, monkeypatch):
    monkeypatch.setattr("video2yt.cli.preflight", lambda: None)
    args = cli.parse_args(["https://x/video/BV1", "--speed", "0.25"])
    with pytest.raises(ValueError, match="0.5 and 2.0"):
        cli.run(args)


def test_run_passes_speed_to_burn_and_scales_expected_duration(tmp_path, monkeypatch):
    """With --speed 2.0, expected_duration should be halved."""
    monkeypatch.setattr("video2yt.cli.preflight", lambda: None)
    monkeypatch.setattr(
        "video2yt.cli.download.get_metadata",
        lambda url, browser: {"title": "T", "uploader": "UP"},
    )

    def fake_fetch(url, temp_dir, quality, browser, bv_id, codec="h264"):
        (temp_dir / f"{bv_id}.mp4").write_bytes(b"v")
        (temp_dir / f"{bv_id}.danmaku.xml").write_bytes(b"<i></i>")
        return (temp_dir / f"{bv_id}.mp4", temp_dir / f"{bv_id}.danmaku.xml", False)

    def fake_generate_ass(xml_path, ass_path, width, height, font_face, font_size):
        ass_path.write_text(
            "[Events]\nFormat: Layer, Start, End, Style\n"
            "Dialogue: 0,0:00:05.00,0:00:10.00,Default,hi\n",
            encoding="utf-8",
        )

    source_info = MediaInfo(
        duration=120.0, width=1920, height=1080,
        has_video=True, has_audio=True,
        vcodec="h264", acodec="aac", size_bytes=10_000_000,
    )
    output_info = MediaInfo(
        duration=60.0, width=1920, height=1080,
        has_video=True, has_audio=True,
        vcodec="h264", acodec="aac", size_bytes=9_000_000,
    )
    probe_calls = []
    def fake_probe(p):
        probe_calls.append(p)
        return source_info if len(probe_calls) == 1 else output_info

    captured = {}
    def fake_render(video_path, ass_path, output_path, max_duration=None, keep_ranges=None, speed=1.0):
        captured["speed"] = speed
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"x")
        return output_path

    def fake_check_output(source, output, expected_duration=None):
        captured["expected_duration"] = expected_duration
        return []

    monkeypatch.setattr("video2yt.cli.download.fetch", fake_fetch)
    monkeypatch.setattr("video2yt.cli.download.generate_ass", fake_generate_ass)
    monkeypatch.setattr("video2yt.cli.validate.probe", fake_probe)
    monkeypatch.setattr("video2yt.cli.burn.render", fake_render)
    monkeypatch.setattr("video2yt.cli.validate.check_output", fake_check_output)

    args = cli.parse_args([
        "https://x/video/BV1",
        "-o", str(tmp_path / "out"),
        "-t", str(tmp_path / "tmp"),
        "--speed", "2.0",
    ])
    cli.run(args)

    assert captured["speed"] == 2.0
    # source 120s / speed 2.0 = 60s expected
    assert abs(captured["expected_duration"] - 60.0) < 0.01


def test_run_speed_with_cut_scales_kept_duration(tmp_path, monkeypatch):
    """With both --cut and --speed: expected_duration = kept_duration / speed."""
    monkeypatch.setattr("video2yt.cli.preflight", lambda: None)
    monkeypatch.setattr(
        "video2yt.cli.download.get_metadata",
        lambda url, browser: {"title": "T", "uploader": "UP"},
    )

    def fake_fetch(url, temp_dir, quality, browser, bv_id, codec="h264"):
        (temp_dir / f"{bv_id}.mp4").write_bytes(b"v")
        (temp_dir / f"{bv_id}.danmaku.xml").write_bytes(b"<i></i>")
        return (temp_dir / f"{bv_id}.mp4", temp_dir / f"{bv_id}.danmaku.xml", False)

    def fake_generate_ass(xml_path, ass_path, width, height, font_face, font_size):
        ass_path.write_text(
            _ass_with_dialogues([
                "0,0:00:05.00,0:00:08.00,Default,,0,0,0,,a",
            ]),
            encoding="utf-8",
        )

    source_info = MediaInfo(
        duration=120.0, width=1920, height=1080,
        has_video=True, has_audio=True,
        vcodec="h264", acodec="aac", size_bytes=10_000_000,
    )
    output_info = MediaInfo(
        duration=60.0, width=1920, height=1080,
        has_video=True, has_audio=True,
        vcodec="h264", acodec="aac", size_bytes=9_000_000,
    )
    probe_calls = []
    def fake_probe(p):
        probe_calls.append(p)
        return source_info if len(probe_calls) == 1 else output_info

    captured = {}
    def fake_render(video_path, ass_path, output_path, max_duration=None, keep_ranges=None, speed=1.0):
        captured["speed"] = speed
        captured["keep_ranges"] = keep_ranges
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"x")
        return output_path

    def fake_check_output(source, output, expected_duration=None):
        captured["expected_duration"] = expected_duration
        return []

    monkeypatch.setattr("video2yt.cli.download.fetch", fake_fetch)
    monkeypatch.setattr("video2yt.cli.download.generate_ass", fake_generate_ass)
    monkeypatch.setattr("video2yt.cli.validate.probe", fake_probe)
    monkeypatch.setattr("video2yt.cli.burn.render", fake_render)
    monkeypatch.setattr("video2yt.cli.validate.check_output", fake_check_output)

    args = cli.parse_args([
        "https://x/video/BV1",
        "-o", str(tmp_path / "out"),
        "-t", str(tmp_path / "tmp"),
        "--cut", "30~60",
        "--speed", "1.5",
    ])
    cli.run(args)

    # source 120s, cut 30~60 removes 30s -> kept = 90s, 90/1.5 = 60s
    assert captured["speed"] == 1.5
    assert abs(captured["expected_duration"] - 60.0) < 0.01


# ---------------------------------------------------------------------------
# Output filename suffixes: _cut, _<speed>x, _preview
# ---------------------------------------------------------------------------

def test_build_output_filename_default():
    assert cli._build_output_filename("BV1", False, 1.0, False) == "BV1_with_danmaku.mp4"


def test_build_output_filename_cut_only():
    assert cli._build_output_filename("BV1", True, 1.0, False) == "BV1_with_danmaku_cut.mp4"


def test_build_output_filename_speed_only():
    assert cli._build_output_filename("BV1", False, 1.5, False) == "BV1_with_danmaku_1.5x.mp4"


def test_build_output_filename_integer_speed():
    assert cli._build_output_filename("BV1", False, 2.0, False) == "BV1_with_danmaku_2x.mp4"


def test_build_output_filename_fractional_speed():
    assert cli._build_output_filename("BV1", False, 1.25, False) == "BV1_with_danmaku_1.25x.mp4"


def test_build_output_filename_preview_only():
    assert cli._build_output_filename("BV1", False, 1.0, True) == "BV1_with_danmaku_preview.mp4"


def test_build_output_filename_cut_and_speed():
    assert cli._build_output_filename("BV1", True, 1.5, False) == "BV1_with_danmaku_cut_1.5x.mp4"


def test_build_output_filename_all_three():
    assert cli._build_output_filename("BV1", True, 1.25, True) == "BV1_with_danmaku_cut_1.25x_preview.mp4"


def test_build_output_filename_cut_and_preview():
    assert cli._build_output_filename("BV1", True, 1.0, True) == "BV1_with_danmaku_cut_preview.mp4"


def test_build_output_filename_speed_and_preview():
    assert cli._build_output_filename("BV1", False, 1.5, True) == "BV1_with_danmaku_1.5x_preview.mp4"


def test_run_output_filename_includes_cut_suffix(tmp_path, monkeypatch):
    """With --cut, output filename gets _cut suffix."""
    monkeypatch.setattr("video2yt.cli.preflight", lambda: None)
    monkeypatch.setattr(
        "video2yt.cli.download.get_metadata",
        lambda url, browser: {"title": "T", "uploader": "UP"},
    )

    def fake_fetch(url, temp_dir, quality, browser, bv_id, codec="h264"):
        (temp_dir / f"{bv_id}.mp4").write_bytes(b"v")
        (temp_dir / f"{bv_id}.danmaku.xml").write_bytes(b"<i></i>")
        return (temp_dir / f"{bv_id}.mp4", temp_dir / f"{bv_id}.danmaku.xml", False)

    def fake_generate_ass(xml_path, ass_path, width, height, font_face, font_size):
        ass_path.write_text(
            "[Events]\nFormat: Layer, Start, End, Style\n"
            "Dialogue: 0,0:00:05.00,0:00:10.00,Default,hi\n",
            encoding="utf-8",
        )

    info = MediaInfo(
        duration=120.0, width=1920, height=1080,
        has_video=True, has_audio=True,
        vcodec="h264", acodec="aac", size_bytes=10_000_000,
    )
    out_info = MediaInfo(
        duration=90.0, width=1920, height=1080,
        has_video=True, has_audio=True,
        vcodec="h264", acodec="aac", size_bytes=9_000_000,
    )
    probe_calls = []
    def fake_probe(p):
        probe_calls.append(p)
        return info if len(probe_calls) == 1 else out_info

    monkeypatch.setattr("video2yt.cli.download.fetch", fake_fetch)
    monkeypatch.setattr("video2yt.cli.download.generate_ass", fake_generate_ass)
    monkeypatch.setattr("video2yt.cli.validate.probe", fake_probe)
    monkeypatch.setattr(
        "video2yt.cli.burn.render",
        lambda v, a, o, max_duration=None, keep_ranges=None, speed=1.0: (
            o.parent.mkdir(parents=True, exist_ok=True),
            o.write_bytes(b"x"),
            o,
        )[-1],
    )
    monkeypatch.setattr("video2yt.cli.validate.check_output", lambda s, o, expected_duration=None: [])

    args = cli.parse_args([
        "https://x/video/BV1",
        "-o", str(tmp_path / "out"),
        "-t", str(tmp_path / "tmp"),
        "--cut", "30~60",
    ])
    result = cli.run(args)
    assert result.name == "BV1_with_danmaku_cut.mp4"


def test_run_output_filename_includes_speed_suffix(tmp_path, monkeypatch):
    """With --speed 1.25, output filename gets _1.25x suffix."""
    monkeypatch.setattr("video2yt.cli.preflight", lambda: None)
    monkeypatch.setattr(
        "video2yt.cli.download.get_metadata",
        lambda url, browser: {"title": "T", "uploader": "UP"},
    )

    def fake_fetch(url, temp_dir, quality, browser, bv_id, codec="h264"):
        (temp_dir / f"{bv_id}.mp4").write_bytes(b"v")
        (temp_dir / f"{bv_id}.danmaku.xml").write_bytes(b"<i></i>")
        return (temp_dir / f"{bv_id}.mp4", temp_dir / f"{bv_id}.danmaku.xml", False)

    def fake_generate_ass(xml_path, ass_path, width, height, font_face, font_size):
        ass_path.write_text(
            "[Events]\nFormat: Layer, Start, End, Style\n"
            "Dialogue: 0,0:00:05.00,0:00:10.00,Default,hi\n",
            encoding="utf-8",
        )

    info = MediaInfo(
        duration=120.0, width=1920, height=1080,
        has_video=True, has_audio=True,
        vcodec="h264", acodec="aac", size_bytes=10_000_000,
    )
    out_info = MediaInfo(
        duration=96.0, width=1920, height=1080,
        has_video=True, has_audio=True,
        vcodec="h264", acodec="aac", size_bytes=9_000_000,
    )
    probe_calls = []
    def fake_probe(p):
        probe_calls.append(p)
        return info if len(probe_calls) == 1 else out_info

    monkeypatch.setattr("video2yt.cli.download.fetch", fake_fetch)
    monkeypatch.setattr("video2yt.cli.download.generate_ass", fake_generate_ass)
    monkeypatch.setattr("video2yt.cli.validate.probe", fake_probe)
    monkeypatch.setattr(
        "video2yt.cli.burn.render",
        lambda v, a, o, max_duration=None, keep_ranges=None, speed=1.0: (
            o.parent.mkdir(parents=True, exist_ok=True),
            o.write_bytes(b"x"),
            o,
        )[-1],
    )
    monkeypatch.setattr("video2yt.cli.validate.check_output", lambda s, o, expected_duration=None: [])

    args = cli.parse_args([
        "https://x/video/BV1",
        "-o", str(tmp_path / "out"),
        "-t", str(tmp_path / "tmp"),
        "--speed", "1.25",
    ])
    result = cli.run(args)
    assert result.name == "BV1_with_danmaku_1.25x.mp4"


def test_run_output_filename_combines_cut_speed_preview(tmp_path, monkeypatch):
    """All three: --cut, --speed 1.5, --preview-seconds 30."""
    monkeypatch.setattr("video2yt.cli.preflight", lambda: None)
    monkeypatch.setattr(
        "video2yt.cli.download.get_metadata",
        lambda url, browser: {"title": "T", "uploader": "UP"},
    )

    def fake_fetch(url, temp_dir, quality, browser, bv_id, codec="h264"):
        (temp_dir / f"{bv_id}.mp4").write_bytes(b"v")
        (temp_dir / f"{bv_id}.danmaku.xml").write_bytes(b"<i></i>")
        return (temp_dir / f"{bv_id}.mp4", temp_dir / f"{bv_id}.danmaku.xml", False)

    def fake_generate_ass(xml_path, ass_path, width, height, font_face, font_size):
        ass_path.write_text(
            "[Events]\nFormat: Layer, Start, End, Style\n"
            "Dialogue: 0,0:00:05.00,0:00:10.00,Default,hi\n",
            encoding="utf-8",
        )

    info = MediaInfo(
        duration=120.0, width=1920, height=1080,
        has_video=True, has_audio=True,
        vcodec="h264", acodec="aac", size_bytes=10_000_000,
    )
    out_info = MediaInfo(
        duration=30.0, width=1920, height=1080,
        has_video=True, has_audio=True,
        vcodec="h264", acodec="aac", size_bytes=3_000_000,
    )
    probe_calls = []
    def fake_probe(p):
        probe_calls.append(p)
        return info if len(probe_calls) == 1 else out_info

    monkeypatch.setattr("video2yt.cli.download.fetch", fake_fetch)
    monkeypatch.setattr("video2yt.cli.download.generate_ass", fake_generate_ass)
    monkeypatch.setattr("video2yt.cli.validate.probe", fake_probe)
    monkeypatch.setattr(
        "video2yt.cli.burn.render",
        lambda v, a, o, max_duration=None, keep_ranges=None, speed=1.0: (
            o.parent.mkdir(parents=True, exist_ok=True),
            o.write_bytes(b"x"),
            o,
        )[-1],
    )
    monkeypatch.setattr("video2yt.cli.validate.check_output", lambda s, o, expected_duration=None: [])

    args = cli.parse_args([
        "https://x/video/BV1",
        "-o", str(tmp_path / "out"),
        "-t", str(tmp_path / "tmp"),
        "--cut", "30~60",
        "--speed", "1.5",
        "--preview-seconds", "30",
    ])
    result = cli.run(args)
    assert result.name == "BV1_with_danmaku_cut_1.5x_preview.mp4"


# ---------------------------------------------------------------------------
# video2yt-compose tests
# ---------------------------------------------------------------------------

from video2yt import compose, compose_cli  # noqa: E402


def test_check_srt_basic_count(tmp_path):
    srt = tmp_path / "test.srt"
    srt.write_text(
        "1\n"
        "00:00:01,000 --> 00:00:05,000\n"
        "Hello world\n"
        "\n"
        "2\n"
        "00:00:06,000 --> 00:00:10,000\n"
        "Second line\n",
        encoding="utf-8",
    )
    assert compose.check_srt(srt) == 2


def test_check_srt_chinese(tmp_path):
    srt = tmp_path / "test.srt"
    srt.write_text(
        "1\n"
        "00:00:01,000 --> 00:00:05,000\n"
        "你好世界\n"
        "\n",
        encoding="utf-8",
    )
    assert compose.check_srt(srt) == 1


def test_check_srt_raises_on_missing_file(tmp_path):
    with pytest.raises(ValueError, match="not found"):
        compose.check_srt(tmp_path / "missing.srt")


def test_check_srt_raises_on_no_timecodes(tmp_path):
    srt = tmp_path / "test.srt"
    srt.write_text("Just some text\nNo timecodes here\n", encoding="utf-8")
    with pytest.raises(ValueError, match="no subtitle blocks"):
        compose.check_srt(srt)


def test_check_srt_handles_dot_separator(tmp_path):
    """Some SRT dialects use `.` instead of `,` in timecodes."""
    srt = tmp_path / "test.srt"
    srt.write_text(
        "1\n"
        "00:00:01.000 --> 00:00:05.000\n"
        "Hello\n",
        encoding="utf-8",
    )
    assert compose.check_srt(srt) == 1


def test_check_srt_gbk_fallback(tmp_path):
    """If UTF-8 decode fails, try GBK."""
    srt = tmp_path / "test.srt"
    content = (
        "1\n"
        "00:00:01,000 --> 00:00:05,000\n"
        "你好\n"
    )
    srt.write_bytes(content.encode("gbk"))
    assert compose.check_srt(srt) == 1


def test_build_subtitles_filter_includes_style():
    from video2yt.compose import _build_subtitles_filter
    f = _build_subtitles_filter("test.srt", "Hiragino Sans GB", 42)
    assert "subtitles=f='test.srt'" in f
    assert "FontName=Hiragino Sans GB" in f
    assert "FontSize=42" in f
    assert "PrimaryColour=&HFFFFFF" in f
    assert "Alignment=2" in f


def test_build_filter_complex_includes_scale_pad_subtitles():
    from video2yt.compose import _build_filter_complex
    fc = _build_filter_complex("test.srt", "Hiragino Sans GB", 42)
    assert "scale=1920:1080:force_original_aspect_ratio=decrease" in fc
    assert "pad=1920:1080" in fc
    assert "subtitles=f='test.srt'" in fc
    assert "[bg]" in fc
    assert "[outv]" in fc


def test_render_builds_correct_ffmpeg_command(tmp_path, monkeypatch):
    work_dir = tmp_path / "srt_dir"
    work_dir.mkdir()
    srt = work_dir / "subs.srt"
    srt.write_text(
        "1\n00:00:01,000 --> 00:00:05,000\nhi\n", encoding="utf-8",
    )
    audio = tmp_path / "audio.mp3"
    audio.write_bytes(b"fake audio")
    image = tmp_path / "bg.jpg"
    image.write_bytes(b"fake image")
    output = tmp_path / "out" / "test.mp4"

    captured = {}
    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"composed")
        return MagicMock(returncode=0)
    monkeypatch.setattr("video2yt.compose.subprocess.run", fake_run)

    inputs = compose.ComposeInputs(
        audio_path=audio,
        image_path=image,
        srt_path=srt,
        title="Test",
        output_dir=tmp_path / "out",
        font_face="Hiragino Sans GB",
        font_size=42,
    )
    compose.render(inputs, output)

    cmd = captured["cmd"]
    assert cmd[0] == "ffmpeg"
    assert "-loop" in cmd
    loop_idx = cmd.index("-loop")
    assert cmd[loop_idx + 1] == "1"
    # Two -i inputs: image first, then audio
    i_indexes = [i for i, a in enumerate(cmd) if a == "-i"]
    assert len(i_indexes) == 2
    assert str(image.resolve()) == cmd[i_indexes[0] + 1]
    assert str(audio.resolve()) == cmd[i_indexes[1] + 1]
    # filter_complex present
    assert "-filter_complex" in cmd
    fc_idx = cmd.index("-filter_complex")
    assert "subtitles=f='subs.srt'" in cmd[fc_idx + 1]
    assert "FontName=Hiragino Sans GB" in cmd[fc_idx + 1]
    assert "scale=1920:1080" in cmd[fc_idx + 1]
    # Maps
    assert "-map" in cmd
    map_values = [cmd[i + 1] for i, a in enumerate(cmd) if a == "-map"]
    assert "[outv]" in map_values
    assert "1:a" in map_values
    # Codecs and tune
    assert "libx264" in cmd
    assert "-tune" in cmd
    tune_idx = cmd.index("-tune")
    assert cmd[tune_idx + 1] == "stillimage"
    assert "-pix_fmt" in cmd
    pix_idx = cmd.index("-pix_fmt")
    assert cmd[pix_idx + 1] == "yuv420p"
    assert "aac" in cmd
    assert "-shortest" in cmd
    # cwd is the srt's parent
    assert captured["kwargs"]["cwd"] == work_dir


def test_compose_cli_parse_args_required_fields():
    with pytest.raises(SystemExit):
        compose_cli.parse_args([])


def test_compose_cli_parse_args_defaults(tmp_path):
    args = compose_cli.parse_args([
        "--audio", "a.mp3",
        "--image", "b.jpg",
        "--srt", "c.srt",
        "--title", "My Title",
    ])
    assert args.audio == Path("a.mp3")
    assert args.image == Path("b.jpg")
    assert args.srt == Path("c.srt")
    assert args.title == "My Title"
    assert args.output_dir == Path("./output")
    assert args.font_face == "Hiragino Sans GB"
    assert args.font_size == 42


def test_compose_cli_run_happy_path(tmp_path, monkeypatch):
    audio = tmp_path / "audio.mp3"
    audio.write_bytes(b"fake")
    image = tmp_path / "bg.jpg"
    image.write_bytes(b"fake")
    srt = tmp_path / "subs.srt"
    srt.write_text(
        "1\n00:00:01,000 --> 00:00:05,000\nhello\n", encoding="utf-8",
    )

    monkeypatch.setattr("video2yt.compose_cli.preflight", lambda: None)

    audio_info = MediaInfo(
        duration=120.0, width=0, height=0,
        has_video=False, has_audio=True,
        vcodec="", acodec="aac", size_bytes=1000,
    )
    output_info = MediaInfo(
        duration=120.0, width=1920, height=1080,
        has_video=True, has_audio=True,
        vcodec="h264", acodec="aac", size_bytes=5_000_000,
    )
    probe_calls = []
    def fake_probe(p):
        probe_calls.append(p)
        return audio_info if len(probe_calls) == 1 else output_info
    monkeypatch.setattr("video2yt.compose_cli.validate.probe", fake_probe)

    def fake_render(inputs, output_path):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"composed")
        return output_path
    monkeypatch.setattr("video2yt.compose_cli.compose.render", fake_render)

    args = compose_cli.parse_args([
        "--audio", str(audio),
        "--image", str(image),
        "--srt", str(srt),
        "--title", "Test Title",
        "-o", str(tmp_path / "out"),
    ])
    result = compose_cli.run(args)
    assert result == tmp_path / "out" / "Test Title" / "Test Title.mp4"
    assert result.exists()


def test_compose_cli_run_rejects_missing_audio(tmp_path, monkeypatch):
    image = tmp_path / "bg.jpg"
    image.write_bytes(b"fake")
    srt = tmp_path / "subs.srt"
    srt.write_text("1\n00:00:01,000 --> 00:00:05,000\nhi\n", encoding="utf-8")
    monkeypatch.setattr("video2yt.compose_cli.preflight", lambda: None)

    args = compose_cli.parse_args([
        "--audio", str(tmp_path / "missing.mp3"),
        "--image", str(image),
        "--srt", str(srt),
        "--title", "T",
    ])
    with pytest.raises(FileNotFoundError, match="audio"):
        compose_cli.run(args)


def test_compose_cli_run_rejects_empty_srt(tmp_path, monkeypatch):
    audio = tmp_path / "audio.mp3"
    audio.write_bytes(b"fake")
    image = tmp_path / "bg.jpg"
    image.write_bytes(b"fake")
    srt = tmp_path / "subs.srt"
    srt.write_text("no timecodes here\n", encoding="utf-8")

    monkeypatch.setattr("video2yt.compose_cli.preflight", lambda: None)
    audio_info = MediaInfo(
        duration=120.0, width=0, height=0,
        has_video=False, has_audio=True,
        vcodec="", acodec="aac", size_bytes=1000,
    )
    monkeypatch.setattr("video2yt.compose_cli.validate.probe", lambda p: audio_info)

    args = compose_cli.parse_args([
        "--audio", str(audio),
        "--image", str(image),
        "--srt", str(srt),
        "--title", "T",
    ])
    with pytest.raises(ValueError, match="no subtitle blocks"):
        compose_cli.run(args)


def test_compose_cli_run_rejects_audio_with_no_audio_stream(tmp_path, monkeypatch):
    audio = tmp_path / "audio.mp3"
    audio.write_bytes(b"fake")
    image = tmp_path / "bg.jpg"
    image.write_bytes(b"fake")
    srt = tmp_path / "subs.srt"
    srt.write_text("1\n00:00:01,000 --> 00:00:05,000\nhi\n", encoding="utf-8")

    monkeypatch.setattr("video2yt.compose_cli.preflight", lambda: None)
    fake_info = MediaInfo(
        duration=120.0, width=0, height=0,
        has_video=False, has_audio=False,
        vcodec="", acodec=None, size_bytes=1000,
    )
    monkeypatch.setattr("video2yt.compose_cli.validate.probe", lambda p: fake_info)

    args = compose_cli.parse_args([
        "--audio", str(audio),
        "--image", str(image),
        "--srt", str(srt),
        "--title", "T",
    ])
    with pytest.raises(ValueError, match="no audio stream"):
        compose_cli.run(args)
