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


def test_srt_time_to_ass_time_basic():
    from video2yt.compose import _srt_time_to_ass_time
    assert _srt_time_to_ass_time("00:00:00,000") == "0:00:00.00"
    assert _srt_time_to_ass_time("00:00:01,500") == "0:00:01.50"
    assert _srt_time_to_ass_time("00:01:23,456") == "0:01:23.46"
    assert _srt_time_to_ass_time("01:23:45,999") == "1:23:46.00"


def test_srt_time_to_ass_time_dot_separator():
    from video2yt.compose import _srt_time_to_ass_time
    assert _srt_time_to_ass_time("00:00:01.500") == "0:00:01.50"


def test_srt_time_to_ass_time_rejects_invalid():
    from video2yt.compose import _srt_time_to_ass_time
    with pytest.raises(ValueError):
        _srt_time_to_ass_time("not a time")


def test_srt_to_ass_has_script_info_section():
    from video2yt.compose import srt_to_ass
    srt = "1\n00:00:00,000 --> 00:00:02,000\nhello\n"
    ass = srt_to_ass(srt, 1920, 1080, "Hiragino Sans GB", 42)
    assert "[Script Info]" in ass
    assert "PlayResX: 1920" in ass
    assert "PlayResY: 1080" in ass
    assert "ScriptType: v4.00+" in ass


def test_srt_to_ass_has_style_section_with_font():
    from video2yt.compose import srt_to_ass
    srt = "1\n00:00:00,000 --> 00:00:02,000\nhi\n"
    ass = srt_to_ass(srt, 1920, 1080, "Hiragino Sans GB", 42)
    assert "[V4+ Styles]" in ass
    assert "Hiragino Sans GB" in ass
    assert ",42," in ass
    assert "&H00FFFFFF" in ass
    assert "&H00000000" in ass


def test_srt_to_ass_converts_dialogue():
    from video2yt.compose import srt_to_ass
    srt = (
        "1\n00:00:00,000 --> 00:00:02,500\n第一句\n\n"
        "2\n00:00:03,000 --> 00:00:05,750\n第二句\n"
    )
    ass = srt_to_ass(srt, 1920, 1080, "Hiragino Sans GB", 42)
    assert "Dialogue: 0,0:00:00.00,0:00:02.50,Default,,0,0,0,,第一句" in ass
    assert "Dialogue: 0,0:00:03.00,0:00:05.75,Default,,0,0,0,,第二句" in ass


def test_srt_to_ass_handles_multiline_text():
    from video2yt.compose import srt_to_ass
    srt = "1\n00:00:00,000 --> 00:00:02,000\nline one\nline two\n"
    ass = srt_to_ass(srt, 1920, 1080, "Hiragino Sans GB", 42)
    assert "line one\\Nline two" in ass


def test_srt_to_ass_skips_malformed_blocks():
    from video2yt.compose import srt_to_ass
    srt = (
        "1\n00:00:00,000 --> 00:00:02,000\ngood\n\n"
        "gibberish\nno timecode\n\n"
        "2\n00:00:03,000 --> 00:00:05,000\nanother good\n"
    )
    ass = srt_to_ass(srt, 1920, 1080, "Font", 42)
    assert "good" in ass
    assert "another good" in ass
    assert "gibberish" not in ass


def test_srt_to_ass_raises_on_all_malformed():
    from video2yt.compose import srt_to_ass
    srt = "just some gibberish\nnot an srt file\n"
    with pytest.raises(ValueError, match="no parseable dialogue"):
        srt_to_ass(srt, 1920, 1080, "Font", 42)


def test_srt_to_ass_with_different_font_size_reflects_in_style():
    from video2yt.compose import srt_to_ass
    srt = "1\n00:00:00,000 --> 00:00:02,000\nhi\n"
    ass = srt_to_ass(srt, 1920, 1080, "Hiragino Sans GB", 28)
    assert ",28," in ass
    assert ",42," not in ass


def test_srt_to_ass_default_position_is_center():
    from video2yt.compose import srt_to_ass
    srt = "1\n00:00:00,000 --> 00:00:02,000\nhi\n"
    ass = srt_to_ass(srt, 1920, 1080, "Font", 42)
    style_line = [l for l in ass.splitlines() if l.startswith("Style: Default,")][0]
    fields = style_line.split(",")
    # Alignment is at index 18 (see verified field layout in implementation plan).
    assert fields[18].strip() == "5"


def test_srt_to_ass_bottom_position_alignment_2():
    from video2yt.compose import srt_to_ass
    srt = "1\n00:00:00,000 --> 00:00:02,000\nhi\n"
    ass = srt_to_ass(srt, 1920, 1080, "Font", 42, position="bottom")
    style_line = [l for l in ass.splitlines() if l.startswith("Style: Default,")][0]
    fields = style_line.split(",")
    assert fields[18].strip() == "2"


def test_srt_to_ass_top_position_alignment_8():
    from video2yt.compose import srt_to_ass
    srt = "1\n00:00:00,000 --> 00:00:02,000\nhi\n"
    ass = srt_to_ass(srt, 1920, 1080, "Font", 42, position="top")
    style_line = [l for l in ass.splitlines() if l.startswith("Style: Default,")][0]
    fields = style_line.split(",")
    assert fields[18].strip() == "8"


def test_srt_to_ass_rejects_invalid_position():
    from video2yt.compose import srt_to_ass
    srt = "1\n00:00:00,000 --> 00:00:02,000\nhi\n"
    with pytest.raises(ValueError, match="invalid position"):
        srt_to_ass(srt, 1920, 1080, "Font", 42, position="sideways")


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

    # Mock validate.probe so render() doesn't try to ffprobe the fake audio.
    from video2yt import validate as _validate
    fake_info = _validate.MediaInfo(
        duration=12.345, width=0, height=0,
        has_video=False, has_audio=True, vcodec="", acodec="mp3", size_bytes=10,
    )
    monkeypatch.setattr("video2yt.validate.probe", lambda p: fake_info)

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
    assert "subtitles=f='subs.compose.ass'" in cmd[fc_idx + 1]
    assert "force_style" not in cmd[fc_idx + 1]
    assert "scale=1920:1080" in cmd[fc_idx + 1]
    # Verify the intermediate ASS file was written with pixel-accurate
    # PlayRes and the requested font face
    ass_file = work_dir / "subs.compose.ass"
    assert ass_file.exists()
    ass_text = ass_file.read_text(encoding="utf-8")
    assert "PlayResY: 1080" in ass_text
    assert "PlayResX: 1920" in ass_text
    assert "Hiragino Sans GB" in ass_text
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
    # -t clamps output to the probed audio duration (workaround for -shortest
    # not stopping the looped video stream when AAC flushes its tail).
    assert "-t" in cmd
    t_idx = cmd.index("-t")
    assert cmd[t_idx + 1] == "12.345"
    assert t_idx > i_indexes[1]  # -t must come after inputs (output option)
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
    assert args.font_size is None
    assert args.position == "center"


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


def test_compose_cli_parse_args_default_position_center():
    args = compose_cli.parse_args([
        "--audio", "a.mp3", "--image", "b.jpg",
        "--srt", "c.srt", "--title", "T",
    ])
    assert args.position == "center"
    assert args.font_size is None  # auto, resolved in run()


def test_compose_cli_parse_args_position_bottom():
    args = compose_cli.parse_args([
        "--audio", "a.mp3", "--image", "b.jpg",
        "--srt", "c.srt", "--title", "T",
        "--position", "bottom",
    ])
    assert args.position == "bottom"


def test_compose_cli_parse_args_rejects_invalid_position():
    with pytest.raises(SystemExit):
        compose_cli.parse_args([
            "--audio", "a.mp3", "--image", "b.jpg",
            "--srt", "c.srt", "--title", "T",
            "--position", "diagonal",
        ])


def _compose_cli_run_fixture(tmp_path, monkeypatch):
    """Build common fakes/paths for compose_cli.run auto-font-size tests."""
    audio = tmp_path / "audio.mp3"
    audio.write_bytes(b"fake")
    image = tmp_path / "bg.jpg"
    image.write_bytes(b"fake")
    srt = tmp_path / "subs.srt"
    srt.write_text("1\n00:00:01,000 --> 00:00:05,000\nhi\n", encoding="utf-8")

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

    captured: dict = {}

    def fake_render(inputs, output_path):
        captured["font_size"] = inputs.font_size
        captured["position"] = inputs.position
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"fake")
        return output_path

    monkeypatch.setattr("video2yt.compose_cli.compose.render", fake_render)
    return audio, image, srt, captured


def test_compose_cli_run_center_default_font_size_72(tmp_path, monkeypatch):
    """--position center with no --font-size -> font_size=72 passed to render."""
    audio, image, srt, captured = _compose_cli_run_fixture(tmp_path, monkeypatch)
    args = compose_cli.parse_args([
        "--audio", str(audio), "--image", str(image),
        "--srt", str(srt), "--title", "T",
        "-o", str(tmp_path / "out"),
    ])
    compose_cli.run(args)
    assert captured["font_size"] == 72
    assert captured["position"] == "center"


def test_compose_cli_run_bottom_default_font_size_42(tmp_path, monkeypatch):
    """--position bottom with no --font-size -> font_size=42."""
    audio, image, srt, captured = _compose_cli_run_fixture(tmp_path, monkeypatch)
    args = compose_cli.parse_args([
        "--audio", str(audio), "--image", str(image),
        "--srt", str(srt), "--title", "T",
        "-o", str(tmp_path / "out"),
        "--position", "bottom",
    ])
    compose_cli.run(args)
    assert captured["font_size"] == 42
    assert captured["position"] == "bottom"


def test_compose_cli_run_top_default_font_size_42(tmp_path, monkeypatch):
    """--position top with no --font-size -> font_size=42."""
    audio, image, srt, captured = _compose_cli_run_fixture(tmp_path, monkeypatch)
    args = compose_cli.parse_args([
        "--audio", str(audio), "--image", str(image),
        "--srt", str(srt), "--title", "T",
        "-o", str(tmp_path / "out"),
        "--position", "top",
    ])
    compose_cli.run(args)
    assert captured["font_size"] == 42
    assert captured["position"] == "top"


def test_compose_cli_run_explicit_font_size_wins(tmp_path, monkeypatch):
    """--position center --font-size 50 -> 50 passed to render (explicit wins)."""
    audio, image, srt, captured = _compose_cli_run_fixture(tmp_path, monkeypatch)
    args = compose_cli.parse_args([
        "--audio", str(audio), "--image", str(image),
        "--srt", str(srt), "--title", "T",
        "-o", str(tmp_path / "out"),
        "--position", "center",
        "--font-size", "50",
    ])
    compose_cli.run(args)
    assert captured["font_size"] == 50
    assert captured["position"] == "center"


# ---------------------------------------------------------------------------
# compose: Python-side subtitle wrapping (_effective_chars_per_line,
# _wrap_text_for_ass, srt_to_ass integration)
# ---------------------------------------------------------------------------


def test_effective_chars_per_line_72_at_1920():
    from video2yt.compose import _effective_chars_per_line
    # 1920 - 2*80 = 1760 usable, * 0.95 safety = 1672, // 72 = 23
    result = _effective_chars_per_line(72, 1920, 80, 80)
    assert result == 23


def test_effective_chars_per_line_42_at_1920():
    from video2yt.compose import _effective_chars_per_line
    # 1760 * 0.95 = 1672, // 42 = 39
    result = _effective_chars_per_line(42, 1920, 80, 80)
    assert result == 39


def test_wrap_text_short_sentence_no_split():
    from video2yt.compose import _wrap_text_for_ass
    result = _wrap_text_for_ass("炉石战旗 S13灾变降临4月15号正式开启。", 23)
    # 23-char line holds the whole 20-char sentence
    assert result == ["炉石战旗 S13灾变降临4月15号正式开启。"]


def test_wrap_text_long_sentence_with_commas():
    from video2yt.compose import _wrap_text_for_ass
    # Long sentence with multiple natural break points
    text = "这个新赛季最大的变化，包括 饰品回归、新英雄加入，以及多个种族都拿到了新的关键词和新玩法。"
    result = _wrap_text_for_ass(text, 23)
    # Should produce multiple lines, each <= 23 chars
    assert len(result) >= 2
    for line in result:
        assert len(line) <= 23, f"line too long: {line!r}"
    # Content should be preserved when lines are joined (ignoring spaces)
    joined = "".join(result)
    assert joined.replace(" ", "") == text.replace(" ", "")


def test_wrap_text_unbreakable_long_clause_hard_wraps():
    from video2yt.compose import _wrap_text_for_ass
    # A 30-char clause with no soft breaks; must be hard-wrapped
    text = "一二三四五六七八九十一二三四五六七八九十一二三四五六七八九十"
    result = _wrap_text_for_ass(text, 10)
    assert len(result) == 3
    for line in result:
        assert len(line) <= 10


def test_wrap_text_prefers_soft_break_over_hard():
    from video2yt.compose import _wrap_text_for_ass
    text = "前缀很短，后面有一个长到需要换行的长长长长长长的后缀。"
    # The comma at position 5 should be a soft break point
    result = _wrap_text_for_ass(text, 12)
    # First line should end at or near the soft break
    assert len(result[0]) <= 12
    # No line exceeds max
    for line in result:
        assert len(line) <= 12


def test_wrap_text_respects_existing_short_line():
    from video2yt.compose import _wrap_text_for_ass
    result = _wrap_text_for_ass("短句。", 23)
    assert result == ["短句。"]


def test_wrap_text_empty_input():
    from video2yt.compose import _wrap_text_for_ass
    assert _wrap_text_for_ass("", 20) == []
    assert _wrap_text_for_ass("   ", 20) == []


def test_wrap_text_preserves_latin():
    from video2yt.compose import _wrap_text_for_ass
    text = "Hello World, this is a test."
    result = _wrap_text_for_ass(text, 15)
    # Should break at the comma
    assert len(result) >= 2
    for line in result:
        assert len(line) <= 15


def test_wrap_text_merges_orphan_terminal_punctuation():
    """A trailing '。' that would otherwise end up alone on the last line
    should be merged into the preceding line."""
    from video2yt.compose import _wrap_text_for_ass
    # 22 chars of content + "。" = 23 chars. With max_chars=22, the
    # algorithm will finalize after 22 chars and leave "。" stranded.
    # Post-process should merge it.
    text = "一二三四五六七八九十一二三四五六七八九十一二。"
    result = _wrap_text_for_ass(text, 22)
    # Must NOT contain a line that is ONLY "。"
    for line in result:
        assert line != "。", f"orphan period survived: {result}"
    # The last line should end with 。 (it got merged in)
    assert result[-1].endswith("。")


def test_wrap_text_merges_multiple_orphan_punct_chars():
    """A trailing "。！" combination also should not orphan."""
    from video2yt.compose import _wrap_text_for_ass
    text = "一二三四五六七八九十一二三四五六七八九十一二。！"
    result = _wrap_text_for_ass(text, 22)
    for line in result:
        assert line not in ("。", "！", "。！"), f"orphan punct: {result}"
    assert result[-1].endswith("。！")


def test_wrap_text_standalone_punctuation_text_is_not_merged():
    """If the ENTIRE text is just punctuation, produce a single line
    (not merge into nothing). This covers a corner case."""
    from video2yt.compose import _wrap_text_for_ass
    text = "。！？"
    result = _wrap_text_for_ass(text, 22)
    # Should produce exactly one line with all the punct
    assert result == ["。！？"]


def test_srt_to_ass_wraps_long_chinese_line():
    from video2yt.compose import srt_to_ass
    srt = (
        "1\n00:00:00,000 --> 00:00:05,000\n"
        "这个新赛季最大的变化，包括 饰品回归、新英雄加入，以及多个种族都拿到了新的关键词和新玩法。\n"
    )
    ass = srt_to_ass(srt, 1920, 1080, "Hiragino Sans GB", 72)
    # The Dialogue line should contain \N separators (multi-line wrap)
    dialogue = [l for l in ass.splitlines() if l.startswith("Dialogue: ")][0]
    assert "\\N" in dialogue
    # Extract the text part (after ',,')
    text = dialogue.split(",,", 1)[1]
    visual_lines = text.split("\\N")
    for line in visual_lines:
        assert len(line) <= 23


def test_srt_to_ass_uses_wrap_style_2():
    from video2yt.compose import srt_to_ass
    srt = "1\n00:00:00,000 --> 00:00:02,000\nhi\n"
    ass = srt_to_ass(srt, 1920, 1080, "Font", 42)
    assert "WrapStyle: 2" in ass


def test_srt_to_ass_uses_80px_margins_in_style():
    from video2yt.compose import srt_to_ass
    srt = "1\n00:00:00,000 --> 00:00:02,000\nhi\n"
    ass = srt_to_ass(srt, 1920, 1080, "Font", 42)
    style = [l for l in ass.splitlines() if l.startswith("Style: Default,")][0]
    fields = style.split(",")
    # After the fix, MarginL=80, MarginR=80, MarginV=80
    assert fields[19].strip() == "80"
    assert fields[20].strip() == "80"
    assert fields[21].strip() == "80"


# ---------------------------------------------------------------------------
# transcribe: script-to-audio forced alignment
# ---------------------------------------------------------------------------


def test_strip_markdown_removes_headings():
    from video2yt.transcribe import strip_markdown
    md = "# Title\n\nSome text.\n\n## Subtitle\n\nMore text."
    result = strip_markdown(md)
    assert "#" not in result
    assert "Title" in result
    assert "Some text" in result


def test_strip_markdown_removes_list_markers():
    from video2yt.transcribe import strip_markdown
    md = "- item one\n- item two\n1. first\n2. second"
    result = strip_markdown(md)
    assert "- " not in result
    assert "1. " not in result
    assert "item one" in result
    assert "first" in result


def test_strip_markdown_removes_emphasis():
    from video2yt.transcribe import strip_markdown
    md = "This is **bold** and *italic* and __also bold__."
    result = strip_markdown(md)
    assert "*" not in result
    assert "_" not in result
    assert "bold" in result
    assert "italic" in result


def test_strip_markdown_removes_code_fences_and_inline_code():
    from video2yt.transcribe import strip_markdown
    md = "Before ```python\nprint('x')\n``` after `inline` end."
    result = strip_markdown(md)
    assert "```" not in result
    assert "print" not in result
    assert "inline" not in result
    assert "Before" in result
    assert "after" in result
    assert "end" in result


def test_split_into_sentences_chinese():
    from video2yt.transcribe import split_into_sentences
    text = "第一句。第二句！第三句？"
    result = split_into_sentences(text)
    assert len(result) == 3
    assert result[0] == "第一句。"
    assert result[1] == "第二句！"
    assert result[2] == "第三句？"


def test_split_into_sentences_mixed():
    from video2yt.transcribe import split_into_sentences
    text = "Hello world. 你好世界。"
    result = split_into_sentences(text)
    assert len(result) == 2


def test_split_into_sentences_no_terminal_punctuation():
    from video2yt.transcribe import split_into_sentences
    text = "A sentence without ending"
    result = split_into_sentences(text)
    assert result == ["A sentence without ending"]


def test_align_script_to_words_proportional():
    from video2yt.transcribe import align_script_to_words
    sentences = ["短句。", "中等长度的句子。", "这是一个明显更长更长更长的句子。"]
    word_timestamps = [("x", 0.0, 0.5), ("y", 29.5, 30.0)]
    segments = align_script_to_words(sentences, word_timestamps)
    assert len(segments) == 3
    assert segments[0].start == 0.0
    assert segments[-1].end == pytest.approx(30.0)
    assert segments[1].start == segments[0].end
    assert segments[2].start == segments[1].end
    dur0 = segments[0].end - segments[0].start
    dur2 = segments[2].end - segments[2].start
    assert dur2 > dur0


def test_align_script_to_words_empty_timestamps_raises():
    from video2yt.transcribe import align_script_to_words
    with pytest.raises(ValueError, match="no word timestamps"):
        align_script_to_words(["a."], [])


def test_align_script_to_words_empty_sentences_raises():
    from video2yt.transcribe import align_script_to_words
    with pytest.raises(ValueError, match="no script sentences"):
        align_script_to_words([], [("x", 0.0, 1.0)])


def test_align_script_to_words_zero_duration_raises():
    from video2yt.transcribe import align_script_to_words
    with pytest.raises(ValueError, match="zero duration"):
        align_script_to_words(["a。"], [("x", 5.0, 5.0)])


def test_format_srt_time():
    from video2yt.transcribe import _format_srt_time
    assert _format_srt_time(0.0) == "00:00:00,000"
    assert _format_srt_time(1.5) == "00:00:01,500"
    assert _format_srt_time(61.25) == "00:01:01,250"
    assert _format_srt_time(3661.999) == "01:01:01,999"


def test_segments_to_srt_basic():
    from video2yt.transcribe import segments_to_srt, AlignedSegment
    segs = [
        AlignedSegment(text="Hello.", start=0.0, end=2.0),
        AlignedSegment(text="World.", start=2.0, end=4.0),
    ]
    srt = segments_to_srt(segs)
    assert "1\n00:00:00,000 --> 00:00:02,000\nHello." in srt
    assert "2\n00:00:02,000 --> 00:00:04,000\nWorld." in srt


def test_transcribe_script_end_to_end_mocked(monkeypatch):
    from video2yt import transcribe
    fake_words = [("你", 0.0, 0.5), ("好", 0.5, 1.0), ("世", 1.0, 1.5), ("界", 1.5, 2.0)]
    monkeypatch.setattr(
        "video2yt.transcribe.run_whisperx_alignment",
        lambda audio_path, language, model_name, device: fake_words,
    )
    srt = transcribe.transcribe_script(
        audio_path=Path("fake.mp3"),
        script_text="你好。世界。",
    )
    assert "你好。" in srt
    assert "世界。" in srt
    assert "00:00:00,000" in srt
    assert srt.count("\n\n") >= 1


def test_transcribe_cli_parse_args_defaults():
    from video2yt import transcribe_cli
    args = transcribe_cli.parse_args([
        "--audio", "a.mp3",
        "--script", "s.md",
    ])
    assert args.audio == Path("a.mp3")
    assert args.script == Path("s.md")
    assert args.output is None
    assert args.language == "zh"
    assert args.model == "small"
    assert args.device == "cpu"


def test_transcribe_cli_run_happy_path(tmp_path, monkeypatch):
    from video2yt import transcribe_cli
    audio = tmp_path / "audio.mp3"
    audio.write_bytes(b"fake")
    script = tmp_path / "script.md"
    script.write_text("第一句。第二句。\n", encoding="utf-8")

    monkeypatch.setattr("video2yt.transcribe_cli.preflight", lambda: None)
    audio_info = MediaInfo(
        duration=30.0, width=0, height=0,
        has_video=False, has_audio=True,
        vcodec="", acodec="mp3", size_bytes=1000,
    )
    monkeypatch.setattr("video2yt.transcribe_cli.validate.probe", lambda p: audio_info)
    monkeypatch.setattr(
        "video2yt.transcribe_cli.transcribe.transcribe_script",
        lambda **kwargs: (
            "1\n00:00:00,000 --> 00:00:05,000\n第一句。\n\n"
            "2\n00:00:05,000 --> 00:00:10,000\n第二句。\n"
        ),
    )

    args = transcribe_cli.parse_args([
        "--audio", str(audio),
        "--script", str(script),
    ])
    result = transcribe_cli.run(args)
    assert result == audio.with_suffix(".srt")
    assert result.exists()
    assert "第一句" in result.read_text(encoding="utf-8")


def test_transcribe_cli_run_rejects_missing_audio(tmp_path, monkeypatch):
    from video2yt import transcribe_cli
    script = tmp_path / "s.md"
    script.write_text("text", encoding="utf-8")
    monkeypatch.setattr("video2yt.transcribe_cli.preflight", lambda: None)

    args = transcribe_cli.parse_args([
        "--audio", str(tmp_path / "missing.mp3"),
        "--script", str(script),
    ])
    with pytest.raises(FileNotFoundError, match="audio"):
        transcribe_cli.run(args)


def test_transcribe_cli_run_rejects_audio_without_audio_stream(tmp_path, monkeypatch):
    from video2yt import transcribe_cli
    audio = tmp_path / "audio.mp3"
    audio.write_bytes(b"fake")
    script = tmp_path / "s.md"
    script.write_text("text。", encoding="utf-8")

    monkeypatch.setattr("video2yt.transcribe_cli.preflight", lambda: None)
    bad_info = MediaInfo(
        duration=30.0, width=0, height=0,
        has_video=False, has_audio=False,
        vcodec="", acodec=None, size_bytes=1000,
    )
    monkeypatch.setattr("video2yt.transcribe_cli.validate.probe", lambda p: bad_info)

    args = transcribe_cli.parse_args([
        "--audio", str(audio),
        "--script", str(script),
    ])
    with pytest.raises(ValueError, match="no audio stream"):
        transcribe_cli.run(args)


def test_split_long_sentences_disabled_when_zero():
    from video2yt.transcribe import split_long_sentences
    sents = ["一；二；三；四；五。"]
    assert split_long_sentences(sents, max_chars=0) == sents


def test_split_long_sentences_short_sentence_unchanged():
    from video2yt.transcribe import split_long_sentences
    assert split_long_sentences(["短句。"], max_chars=20) == ["短句。"]


def test_split_long_sentences_chinese_semicolon():
    from video2yt.transcribe import split_long_sentences
    s = "我們先做一件事；然後做第二件事；最後做第三件事"
    out = split_long_sentences([s], max_chars=10)
    assert len(out) == 3
    assert out[0].endswith("；")
    assert out[1].endswith("；")
    assert out[2] == "最後做第三件事"


def test_split_long_sentences_mixed_punctuation():
    from video2yt.transcribe import split_long_sentences
    s = "AAAAA，BBBBB；CCCCC、DDDDD"
    out = split_long_sentences([s], max_chars=10)
    assert len(out) == 4


def test_split_long_sentences_no_secondary_punct_returns_intact():
    from video2yt.transcribe import split_long_sentences
    s = "無任何次要標點符號的超長字串無法被切分"
    out = split_long_sentences([s], max_chars=5)
    assert out == [s]


def test_transcribe_cli_parse_args_max_block_chars():
    from video2yt import transcribe_cli
    args = transcribe_cli.parse_args([
        "--audio", "a.mp3",
        "--script", "s.md",
        "--max-block-chars", "40",
    ])
    assert args.max_block_chars == 40


def test_transcribe_cli_parse_args_max_block_chars_default_zero():
    from video2yt import transcribe_cli
    args = transcribe_cli.parse_args([
        "--audio", "a.mp3",
        "--script", "s.md",
    ])
    assert args.max_block_chars == 0


def test_transcribe_script_passes_max_block_chars(monkeypatch):
    from video2yt import transcribe
    fake_words = [("x", 0.0, 0.5), ("y", 9.5, 10.0)]
    monkeypatch.setattr(
        "video2yt.transcribe.run_whisperx_alignment",
        lambda audio_path, language, model_name, device: fake_words,
    )
    # 一段 25-char 的句子，含分号；max_block_chars=10 时应被切为多块。
    script = "我們先做一件事；然後做第二件事；最後做第三件事。"
    srt = transcribe.transcribe_script(
        audio_path=Path("fake.mp3"),
        script_text=script,
        max_block_chars=10,
    )
    # 期望至少 3 个 SRT block (用 "1\n", "2\n", "3\n" 起首做粗略检查)
    assert "1\n00:" in srt
    assert "2\n00:" in srt
    assert "3\n00:" in srt


# =========================================================================
# video2yt-merge tests
# =========================================================================


def test_format_chapter_time_under_hour():
    from video2yt.merge import _format_chapter_time
    assert _format_chapter_time(0) == "00:00"
    assert _format_chapter_time(25) == "00:25"
    assert _format_chapter_time(125) == "02:05"
    assert _format_chapter_time(3599) == "59:59"


def test_format_chapter_time_over_hour():
    from video2yt.merge import _format_chapter_time
    assert _format_chapter_time(3600) == "01:00:00"
    assert _format_chapter_time(3661) == "01:01:01"


def test_generate_chapters_text_three_segments():
    from video2yt.merge import generate_chapters_text, Segment
    from pathlib import Path as P
    segs = [
        Segment(P("a.mp4"), "Intro", duration=25.0),
        Segment(P("b.mp4"), "恶魔解析", duration=300.0),
        Segment(P("c.mp4"), "实战", duration=400.0),
    ]
    text = generate_chapters_text(segs)
    lines = text.strip().splitlines()
    assert lines[0] == "00:00 Intro"
    assert lines[1] == "00:25 恶魔解析"
    assert lines[2] == "05:25 实战"


def test_generate_ffmetadata_three_segments():
    from video2yt.merge import generate_ffmetadata, Segment
    from pathlib import Path as P
    segs = [
        Segment(P("a.mp4"), "Intro", duration=25.0),
        Segment(P("b.mp4"), "恶魔解析", duration=300.0),
        Segment(P("c.mp4"), "实战", duration=400.0),
    ]
    text = generate_ffmetadata(segs)
    assert text.startswith(";FFMETADATA1\n")
    assert text.count("[CHAPTER]") == 3
    assert text.count("TIMEBASE=1/1000") == 3
    # First chapter spans 0..25000 ms, contiguous with the next.
    assert "START=0\nEND=25000\ntitle=Intro" in text
    assert "START=25000\nEND=325000\ntitle=恶魔解析" in text
    assert "START=325000\nEND=725000\ntitle=实战" in text


def test_merge_render_embeds_chapter_metadata(tmp_path, monkeypatch):
    """render() must pass the ffmetadata file as an input and -map_metadata it
    so YouTube reads chapter markers straight from the uploaded MP4."""
    from video2yt import merge
    segs = [
        merge.Segment(tmp_path / "a.mp4", "Intro", duration=25.0),
        merge.Segment(tmp_path / "b.mp4", "实战", duration=300.0),
    ]
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return MagicMock()

    monkeypatch.setattr("video2yt.merge.subprocess.run", fake_run)
    output_path = tmp_path / "out.mp4"
    merge.render(merge.MergeInputs(segments=segs, title="T"), output_path)

    cmd = captured["cmd"]
    ffmeta_path = tmp_path / "out_ffmeta.txt"
    assert ffmeta_path.exists()
    assert str(ffmeta_path.resolve()) in cmd
    # -map_metadata and -map_chapters both point at the ffmetadata input index
    # (the trailing input, after the segments). -map_chapters must be explicit:
    # otherwise ffmpeg falls back to copying chapters from the first input that
    # happens to have any.
    ffmeta_idx = str(len(segs))
    assert "-map_metadata" in cmd
    assert cmd[cmd.index("-map_metadata") + 1] == ffmeta_idx
    assert "-map_chapters" in cmd
    assert cmd[cmd.index("-map_chapters") + 1] == ffmeta_idx


def test_build_filter_complex_has_concat_and_loudnorm():
    from video2yt.merge import _build_filter_complex, Segment
    from pathlib import Path as P
    segs = [
        Segment(P("a.mp4"), "Intro", duration=25.0),
        Segment(P("b.mp4"), "Main", duration=300.0),
    ]
    fc = _build_filter_complex(segs)
    # loudnorm applied to each audio input
    assert fc.count("loudnorm=I=-14:TP=-1:LRA=11") == 2
    # concat of 2 inputs straight to the final output labels
    assert "concat=n=2:v=1:a=1[outv][outa]" in fc
    # no burned-in progress bar overlay / highlight anymore
    assert "overlay" not in fc
    assert "drawbox" not in fc


def test_validate_segments_strict_rejects_wrong_resolution(tmp_path, monkeypatch):
    from video2yt.merge import validate_segments_strict, Segment
    seg = Segment(tmp_path / "bad.mp4", "x")
    (tmp_path / "bad.mp4").write_bytes(b"fake")
    def fake_run(cmd, **kwargs):
        import json
        result = MagicMock()
        result.stdout = json.dumps({
            "streams": [
                {"codec_type": "video", "codec_name": "h264", "width": 1280, "height": 720, "r_frame_rate": "30/1"},
                {"codec_type": "audio", "codec_name": "aac"},
            ],
            "format": {"duration": "60.0"},
        })
        return result
    monkeypatch.setattr("video2yt.merge.subprocess.run", fake_run)
    with pytest.raises(ValueError, match="1280x720"):
        validate_segments_strict([seg])


def test_validate_segments_strict_rejects_non_h264(tmp_path, monkeypatch):
    from video2yt.merge import validate_segments_strict, Segment
    seg = Segment(tmp_path / "bad.mp4", "x")
    (tmp_path / "bad.mp4").write_bytes(b"fake")
    def fake_run(cmd, **kwargs):
        import json
        result = MagicMock()
        result.stdout = json.dumps({
            "streams": [
                {"codec_type": "video", "codec_name": "hevc", "width": 1920, "height": 1080, "r_frame_rate": "30/1"},
                {"codec_type": "audio", "codec_name": "aac"},
            ],
            "format": {"duration": "60.0"},
        })
        return result
    monkeypatch.setattr("video2yt.merge.subprocess.run", fake_run)
    with pytest.raises(ValueError, match="hevc"):
        validate_segments_strict([seg])


def test_validate_segments_strict_accepts_valid_input(tmp_path, monkeypatch):
    from video2yt.merge import validate_segments_strict, Segment
    seg = Segment(tmp_path / "good.mp4", "x")
    (tmp_path / "good.mp4").write_bytes(b"fake")
    def fake_run(cmd, **kwargs):
        import json
        result = MagicMock()
        result.stdout = json.dumps({
            "streams": [
                {"codec_type": "video", "codec_name": "h264", "width": 1920, "height": 1080, "r_frame_rate": "30/1"},
                {"codec_type": "audio", "codec_name": "aac"},
            ],
            "format": {"duration": "60.5"},
        })
        return result
    monkeypatch.setattr("video2yt.merge.subprocess.run", fake_run)
    validate_segments_strict([seg])
    assert seg.duration == 60.5


def test_validate_segments_strict_rejects_sub_10s_segment(tmp_path, monkeypatch):
    """Each chapter must be at least 10s — YouTube discards the entire chapter
    list otherwise. Segments shorter than that are rejected up front."""
    from video2yt.merge import validate_segments_strict, Segment
    seg = Segment(tmp_path / "short.mp4", "x")
    (tmp_path / "short.mp4").write_bytes(b"fake")
    def fake_run(cmd, **kwargs):
        import json
        result = MagicMock()
        result.stdout = json.dumps({
            "streams": [
                {"codec_type": "video", "codec_name": "h264", "width": 1920, "height": 1080, "r_frame_rate": "30/1"},
                {"codec_type": "audio", "codec_name": "aac"},
            ],
            "format": {"duration": "7.4"},
        })
        return result
    monkeypatch.setattr("video2yt.merge.subprocess.run", fake_run)
    with pytest.raises(ValueError, match="< 10s"):
        validate_segments_strict([seg])


def test_merge_cli_parse_args_defaults():
    from video2yt import merge_cli
    args = merge_cli.parse_args([
        "--segment", "a.mp4", "--label", "A",
        "--segment", "b.mp4", "--label", "B",
        "--title", "T",
    ])
    assert len(args.segment) == 2
    assert args.label == ["A", "B"]
    assert args.title == "T"
    assert args.output is None


def test_merge_cli_run_mismatched_counts_raises(monkeypatch):
    from video2yt import merge_cli
    monkeypatch.setattr("video2yt.merge_cli.preflight", lambda: None)
    args = merge_cli.parse_args([
        "--segment", "a.mp4",
        "--segment", "b.mp4",
        "--label", "A",
        "--title", "T",
    ])
    with pytest.raises(ValueError, match="counts must match"):
        merge_cli.run(args)


def test_merge_cli_run_too_few_segments_raises(monkeypatch):
    """Fewer than 3 segments means fewer than 3 chapters — YouTube won't render
    chapter segmentation, so the merge is rejected up front."""
    from video2yt import merge_cli
    monkeypatch.setattr("video2yt.merge_cli.preflight", lambda: None)
    for seg_args in (
        ["--segment", "a.mp4", "--label", "A"],
        ["--segment", "a.mp4", "--label", "A", "--segment", "b.mp4", "--label", "B"],
    ):
        args = merge_cli.parse_args([*seg_args, "--title", "T"])
        with pytest.raises(ValueError, match="at least 3 segments"):
            merge_cli.run(args)


def test_merge_cli_run_happy_path_default_output_in_first_segment_dir(tmp_path, monkeypatch):
    """Output defaults to the first segment's parent directory + sanitized title."""
    from video2yt import merge_cli
    seg_dir = tmp_path / "seg_home"
    seg_dir.mkdir()
    a = seg_dir / "a.mp4"
    a.write_bytes(b"fake")
    b = seg_dir / "b.mp4"
    b.write_bytes(b"fake")
    c = seg_dir / "c.mp4"
    c.write_bytes(b"fake")

    monkeypatch.setattr("video2yt.merge_cli.preflight", lambda: None)

    def fake_validate(segs):
        for s in segs:
            s.duration = 30.0
    monkeypatch.setattr("video2yt.merge_cli.merge.validate_segments_strict", fake_validate)

    captured = {}
    def fake_render(inputs, output_path):
        captured["output"] = output_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"merged")
        return output_path
    monkeypatch.setattr("video2yt.merge_cli.merge.render", fake_render)

    fake_info = MediaInfo(
        duration=90.0, width=1920, height=1080,
        has_video=True, has_audio=True,
        vcodec="h264", acodec="aac", size_bytes=1_000_000,
    )
    monkeypatch.setattr("video2yt.merge_cli.validate.probe", lambda p: fake_info)

    args = merge_cli.parse_args([
        "--segment", str(a), "--label", "A",
        "--segment", str(b), "--label", "B",
        "--segment", str(c), "--label", "C",
        "--title", "Test Merge",
    ])
    result = merge_cli.run(args)
    # Should be in seg_dir with sanitized title filename
    assert result.parent == seg_dir
    assert result.name == "Test Merge.mp4"


# =========================================================================
# video2yt-research-card tests
# =========================================================================


def _bg_card(name="Ring Bearer", card_id="BG34_921", **extra):
    """Tiny factory for fake BG card dicts."""
    return {"name": name, "id": card_id, "set": "BATTLEGROUNDS", **extra}


def _constructed_card(name="Fireball", card_id="EX1_277", **extra):
    return {"name": name, "id": card_id, "set": "EXPERT1", **extra}


class _FakeResponse:
    def __init__(self, *, status_code=200, content=b"", json_data=None):
        self.status_code = status_code
        self.content = content
        self._json = json_data

    def raise_for_status(self):
        if self.status_code >= 400:
            from requests.exceptions import HTTPError
            raise HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return self._json


def test_research_card_slugify_basic():
    from video2yt.research_card import slugify
    assert slugify("Ring Bearer") == "ring_bearer"


def test_research_card_slugify_punctuation():
    from video2yt.research_card import slugify
    assert slugify("M.T. Smyth!") == "m_t_smyth"


def test_research_card_slugify_strips_outer_underscores():
    from video2yt.research_card import slugify
    assert slugify("---hello---") == "hello"


def test_research_card_is_battlegrounds_set():
    from video2yt.research_card import is_battlegrounds
    assert is_battlegrounds({"set": "BATTLEGROUNDS"}) is True


def test_research_card_is_battlegrounds_techlevel():
    from video2yt.research_card import is_battlegrounds
    assert is_battlegrounds({"techLevel": 6, "set": "OTHER"}) is True


def test_research_card_is_battlegrounds_constructed():
    from video2yt.research_card import is_battlegrounds
    assert is_battlegrounds(_constructed_card()) is False


def test_research_card_pick_best_single_candidate():
    from video2yt.research_card import pick_best
    c = _bg_card()
    assert pick_best([c]) is c


def test_research_card_pick_best_prefers_battlegrounds():
    from video2yt.research_card import pick_best
    bg = _bg_card()
    cons = _constructed_card("Ring Bearer", "OG_001")
    result = pick_best([cons, bg])
    assert result is bg


def test_research_card_pick_best_drops_golden_variant():
    from video2yt.research_card import pick_best
    plain = _bg_card(card_id="BG34_921")
    golden = _bg_card(card_id="BG34_921_G")
    assert pick_best([plain, golden]) is plain
    assert pick_best([golden, plain]) is plain


def test_research_card_pick_best_returns_none_when_still_ambiguous():
    from video2yt.research_card import pick_best
    a = _bg_card("Card A", "BG_A")
    b = _bg_card("Card B", "BG_B")
    assert pick_best([a, b]) is None


def test_research_card_find_exact_match():
    from video2yt.research_card import find_card
    cards = [_bg_card("Ring Bearer", "BG34_921"), _bg_card("Other", "BG34_999")]
    assert find_card(cards, "Ring Bearer")["id"] == "BG34_921"


def test_research_card_find_case_insensitive():
    from video2yt.research_card import find_card
    cards = [_bg_card("Ring Bearer", "BG34_921")]
    assert find_card(cards, "ring bearer")["id"] == "BG34_921"


def test_research_card_find_substring_match():
    from video2yt.research_card import find_card
    cards = [_bg_card("Ring Bearer", "BG34_921"), _bg_card("Frostbite", "BG_OTHER")]
    assert find_card(cards, "ring bear")["id"] == "BG34_921"


def test_research_card_find_no_match_raises():
    from video2yt.research_card import find_card
    cards = [_bg_card("Ring Bearer", "BG34_921")]
    with pytest.raises(ValueError, match="no card found"):
        find_card(cards, "Nonexistent")


def test_research_card_find_ambiguous_after_tiebreak_raises():
    from video2yt.research_card import find_card
    cards = [_bg_card("Card A", "BG_A"), _bg_card("Card B", "BG_B")]
    with pytest.raises(ValueError, match="ambiguous"):
        find_card(cards, "Card")


def test_research_card_load_cards_uses_fresh_cache(tmp_path, monkeypatch):
    from video2yt import research_card
    cache = tmp_path / "cards.json"
    cache.write_text(json.dumps([{"name": "Cached", "id": "X1"}]), encoding="utf-8")
    # Make the cache fresh (mtime is now by default).

    def boom(*a, **kw):
        raise AssertionError("requests.get should not be called when cache is fresh")
    monkeypatch.setattr("video2yt.research_card.requests.get", boom)

    out = research_card.load_cards(cache_path=cache)
    assert out == [{"name": "Cached", "id": "X1"}]


def test_research_card_load_cards_fetches_when_cache_stale(tmp_path, monkeypatch):
    import os
    from video2yt import research_card
    cache = tmp_path / "cards.json"
    cache.write_text(json.dumps([{"name": "Old", "id": "OLD"}]), encoding="utf-8")
    # Backdate to 8 days old (TTL is 7 days).
    old = research_card.CACHE_TTL_SECS + 86400
    os.utime(cache, (cache.stat().st_atime - old, cache.stat().st_mtime - old))

    fresh_payload = [{"name": "Fresh", "id": "NEW"}]
    fresh_bytes = json.dumps(fresh_payload).encode("utf-8")
    monkeypatch.setattr(
        "video2yt.research_card.requests.get",
        lambda url, timeout: _FakeResponse(content=fresh_bytes, json_data=fresh_payload),
    )

    out = research_card.load_cards(cache_path=cache)
    assert out == fresh_payload
    assert json.loads(cache.read_text(encoding="utf-8")) == fresh_payload


def test_research_card_load_cards_no_cache_flag_forces_fetch(tmp_path, monkeypatch):
    from video2yt import research_card
    cache = tmp_path / "cards.json"
    cache.write_text(json.dumps([{"name": "Cached", "id": "X"}]), encoding="utf-8")

    fresh_payload = [{"name": "Fresh", "id": "NEW"}]
    fresh_bytes = json.dumps(fresh_payload).encode("utf-8")
    monkeypatch.setattr(
        "video2yt.research_card.requests.get",
        lambda url, timeout: _FakeResponse(content=fresh_bytes, json_data=fresh_payload),
    )

    out = research_card.load_cards(no_cache=True, cache_path=cache)
    assert out == fresh_payload


def test_research_card_download_art_writes_bytes(tmp_path, monkeypatch):
    from video2yt import research_card
    monkeypatch.setattr(
        "video2yt.research_card.requests.get",
        lambda url, timeout: _FakeResponse(content=b"PNG_BYTES_HERE"),
    )
    out = tmp_path / "subdir" / "card.png"
    research_card.download_art("BG34_921", "bgs", out)
    assert out.read_bytes() == b"PNG_BYTES_HERE"


def test_research_card_download_art_404_helpful_error(tmp_path, monkeypatch):
    from video2yt import research_card
    monkeypatch.setattr(
        "video2yt.research_card.requests.get",
        lambda url, timeout: _FakeResponse(status_code=404),
    )
    out = tmp_path / "card.png"
    with pytest.raises(ValueError, match="art not found"):
        research_card.download_art("BG34_921", "render", out)
    assert not out.exists()


def test_research_card_cli_parse_args_defaults():
    from video2yt import research_card_cli
    args = research_card_cli.parse_args(["--name", "Ring Bearer"])
    assert args.name == "Ring Bearer"
    assert args.id is None
    assert args.style == "auto"
    assert args.output is None
    assert args.no_cache is False


def test_research_card_cli_parse_args_id_path():
    from video2yt import research_card_cli
    args = research_card_cli.parse_args(["--id", "BG34_921", "--style", "render"])
    assert args.id == "BG34_921"
    assert args.style == "render"


def test_research_card_cli_parse_args_requires_name_or_id():
    from video2yt import research_card_cli
    with pytest.raises(SystemExit):
        research_card_cli.parse_args([])


def test_research_card_cli_run_by_id_skips_metadata(tmp_path, monkeypatch):
    from video2yt import research_card_cli
    fetched: list[bool] = []
    monkeypatch.setattr(
        "video2yt.research_card_cli.research_card.load_cards",
        lambda **kw: fetched.append(True) or [],
    )
    monkeypatch.setattr(
        "video2yt.research_card_cli.research_card.download_art",
        lambda card_id, style, output: output.parent.mkdir(parents=True, exist_ok=True) or output.write_bytes(b"X"),
    )
    out = tmp_path / "card.png"
    args = research_card_cli.parse_args(["--id", "BG34_921", "-o", str(out)])
    result = research_card_cli.run(args)
    assert result == out
    assert out.exists()
    assert fetched == [], "load_cards should NOT be called when --id is used"


def test_research_card_cli_run_by_name_full_path(tmp_path, monkeypatch):
    from video2yt import research_card_cli
    fake_cards = [_bg_card("Ring Bearer", "BG34_921")]
    monkeypatch.setattr(
        "video2yt.research_card_cli.research_card.load_cards",
        lambda **kw: fake_cards,
    )
    captured: dict = {}
    def fake_dl(card_id, style, output):
        captured["card_id"] = card_id
        captured["style"] = style
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"PNG")
    monkeypatch.setattr(
        "video2yt.research_card_cli.research_card.download_art",
        fake_dl,
    )
    out = tmp_path / "card.png"
    args = research_card_cli.parse_args(["--name", "Ring Bearer", "-o", str(out)])
    research_card_cli.run(args)
    assert captured == {"card_id": "BG34_921", "style": "bgs"}
    assert out.read_bytes() == b"PNG"


def test_research_card_cli_run_auto_style_render_for_constructed(tmp_path, monkeypatch):
    from video2yt import research_card_cli
    fake_cards = [_constructed_card("Fireball", "EX1_277")]
    monkeypatch.setattr(
        "video2yt.research_card_cli.research_card.load_cards",
        lambda **kw: fake_cards,
    )
    captured: dict = {}
    def fake_dl(card_id, style, output):
        captured["style"] = style
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"X")
    monkeypatch.setattr(
        "video2yt.research_card_cli.research_card.download_art",
        fake_dl,
    )
    args = research_card_cli.parse_args([
        "--name", "Fireball", "-o", str(tmp_path / "f.png"),
    ])
    research_card_cli.run(args)
    assert captured["style"] == "render"


def test_research_card_cli_run_explicit_style_override(tmp_path, monkeypatch):
    from video2yt import research_card_cli
    fake_cards = [_bg_card("Ring Bearer", "BG34_921")]
    monkeypatch.setattr(
        "video2yt.research_card_cli.research_card.load_cards",
        lambda **kw: fake_cards,
    )
    captured: dict = {}
    def fake_dl(card_id, style, output):
        captured["style"] = style
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"X")
    monkeypatch.setattr(
        "video2yt.research_card_cli.research_card.download_art",
        fake_dl,
    )
    args = research_card_cli.parse_args([
        "--name", "Ring Bearer", "--style", "render", "-o", str(tmp_path / "x.png"),
    ])
    research_card_cli.run(args)
    assert captured["style"] == "render"


def test_research_card_cli_main_returns_1_on_value_error(tmp_path, monkeypatch):
    from video2yt import research_card_cli
    monkeypatch.setattr(
        "video2yt.research_card_cli.research_card.load_cards",
        lambda **kw: [],
    )
    rc = research_card_cli.main(["--name", "Nonexistent", "-o", str(tmp_path / "x.png")])
    assert rc == 1


def test_research_card_cli_default_output_uses_assets_cards(tmp_path, monkeypatch):
    from video2yt import research_card_cli
    monkeypatch.setattr(
        "video2yt.research_card_cli.research_card.load_cards",
        lambda **kw: [_bg_card("Ring Bearer", "BG34_921")],
    )
    captured: dict = {}
    def fake_dl(card_id, style, output):
        captured["output"] = output
    monkeypatch.setattr(
        "video2yt.research_card_cli.research_card.download_art",
        fake_dl,
    )
    monkeypatch.chdir(tmp_path)
    args = research_card_cli.parse_args(["--name", "Ring Bearer"])
    research_card_cli.run(args)
    assert captured["output"] == Path("assets/cards") / "ring_bearer_512.png"


# =========================================================================
# video2yt-thumbnail tests
# =========================================================================


def test_thumbnail_tokenize_pure_cjk():
    from video2yt.thumbnail import tokenize_for_vertical
    assert tokenize_for_vertical("最强阵容") == ["最", "强", "阵", "容"]


def test_thumbnail_tokenize_ascii_cluster_stays_together():
    from video2yt.thumbnail import tokenize_for_vertical
    assert tokenize_for_vertical("S13测试") == ["S13", "测", "试"]


def test_thumbnail_tokenize_drops_spaces_and_mixes():
    from video2yt.thumbnail import tokenize_for_vertical
    assert tokenize_for_vertical("  S13  最强 1080P ") == ["S13", "最", "强", "1080P"]


def test_thumbnail_render_raises_when_card_missing_for_card_tilt():
    from pathlib import Path as _P

    from video2yt.thumbnail import render_thumbnail
    with pytest.raises(ValueError, match="--card is required"):
        render_thumbnail(
            bg_path=_P("/nonexistent/bg.png"),
            logo_path=_P("/nonexistent/logo.png"),
            title="t",
            output_path=_P("/nonexistent/out.png"),
            orientation="card-tilt-right",
            card_path=None,
        )


def test_thumbnail_render_raises_on_unknown_orientation():
    from pathlib import Path as _P

    from video2yt.thumbnail import render_thumbnail
    with pytest.raises(ValueError, match="unknown orientation"):
        render_thumbnail(
            bg_path=_P("/nonexistent/bg.png"),
            logo_path=_P("/nonexistent/logo.png"),
            title="t",
            output_path=_P("/nonexistent/out.png"),
            orientation="diagonal-rainbow",
        )


def test_thumbnail_cli_parse_args_defaults():
    from video2yt import thumbnail_cli
    args = thumbnail_cli.parse_args([
        "--bg", "bg.png", "--logo", "logo.png",
        "--title", "测试", "-o", "out.png",
    ])
    assert args.orientation == "card-impact"  # new Bilibili-BG default
    assert args.target_size == "1280x720"
    assert args.font_size == 128
    assert args.card is None
    assert args.hook == ""
    assert args.subtitle == ""
    assert args.result_badge == ""
    assert args.hook_size == 240
    assert args.hook_rotation_deg == -8.0
    assert args.vignette_strength == 0.55
    assert args.speed_lines_enabled is True
    # Sentinel-None defaults so each orientation resolves its own value.
    assert args.card_tilt_deg is None
    assert args.logo_width_ratio is None


def test_thumbnail_cli_parse_args_orientation_choice_validated():
    from video2yt import thumbnail_cli
    with pytest.raises(SystemExit):
        thumbnail_cli.parse_args([
            "--bg", "bg.png", "--logo", "logo.png",
            "--title", "t", "-o", "o.png",
            "--orientation", "diagonal-rainbow",
        ])


def test_thumbnail_cli_parse_args_required_flags():
    from video2yt import thumbnail_cli
    with pytest.raises(SystemExit):
        thumbnail_cli.parse_args([])


def test_thumbnail_cli_run_passes_args_to_render(monkeypatch, tmp_path):
    from video2yt import thumbnail_cli
    captured: dict = {}

    def fake_render(**kw):
        captured.update(kw)

    monkeypatch.setattr("video2yt.thumbnail_cli.thumbnail.render_thumbnail", fake_render)
    out = tmp_path / "thumb.png"
    args = thumbnail_cli.parse_args([
        "--bg", "bg.png", "--logo", "logo.png",
        "--title", "S13最强", "-o", str(out),
        "--card", "card.png", "--season", "S13",
        "--target-size", "1920x1080",
        "--orientation", "card-tilt-right",
    ])
    result = thumbnail_cli.run(args)
    assert result == out
    assert captured["title"] == "S13最强"
    assert captured["target_w"] == 1920
    assert captured["target_h"] == 1080
    assert captured["orientation"] == "card-tilt-right"
    assert captured["season_text"] == "S13"


def test_thumbnail_cli_main_returns_1_on_value_error(monkeypatch, tmp_path):
    from video2yt import thumbnail_cli

    def boom(**kw):
        raise ValueError("boom")

    monkeypatch.setattr("video2yt.thumbnail_cli.thumbnail.render_thumbnail", boom)
    rc = thumbnail_cli.main([
        "--bg", "bg.png", "--logo", "logo.png",
        "--title", "t", "-o", str(tmp_path / "o.png"),
        "--card", "c.png",
    ])
    assert rc == 1


def test_thumbnail_cli_main_returns_0_on_success(monkeypatch, tmp_path):
    from video2yt import thumbnail_cli
    monkeypatch.setattr("video2yt.thumbnail_cli.thumbnail.render_thumbnail", lambda **kw: None)
    rc = thumbnail_cli.main([
        "--bg", "bg.png", "--logo", "logo.png",
        "--title", "t", "-o", str(tmp_path / "o.png"),
        "--card", "c.png",
    ])
    assert rc == 0


def test_thumbnail_cli_main_returns_1_on_pil_oserror(monkeypatch, tmp_path):
    """PIL UnidentifiedImageError / ImageFont.truetype OSError must exit 1, not traceback."""
    from PIL import UnidentifiedImageError

    from video2yt import thumbnail_cli

    def boom(**kw):
        raise UnidentifiedImageError("cannot identify image file 'bg.png'")

    monkeypatch.setattr("video2yt.thumbnail_cli.thumbnail.render_thumbnail", boom)
    rc = thumbnail_cli.main([
        "--bg", "bg.png", "--logo", "logo.png",
        "--title", "t", "-o", str(tmp_path / "o.png"),
        "--card", "c.png",
    ])
    assert rc == 1


def test_thumbnail_render_card_impact_requires_card():
    from pathlib import Path as _P

    from video2yt.thumbnail import render_thumbnail
    with pytest.raises(ValueError, match="--card is required"):
        render_thumbnail(
            bg_path=_P("/x/bg.png"), logo_path=_P("/x/logo.png"),
            title="t", output_path=_P("/x/o.png"),
            orientation="card-impact",
            card_path=None, hook="破局",
        )


def test_thumbnail_render_card_impact_requires_hook():
    from pathlib import Path as _P

    from video2yt.thumbnail import render_thumbnail
    with pytest.raises(ValueError, match="--hook is required"):
        render_thumbnail(
            bg_path=_P("/x/bg.png"), logo_path=_P("/x/logo.png"),
            title="t", output_path=_P("/x/o.png"),
            orientation="card-impact",
            card_path=_P("/x/c.png"), hook="",
        )


def test_thumbnail_tokenize_unchanged_for_punctuation_and_period():
    """Sanity check tokenize still works after refactor."""
    from video2yt.thumbnail import tokenize_for_vertical
    assert tokenize_for_vertical("T0破局") == ["T0", "破", "局"]


def test_thumbnail_auto_shrink_hook_returns_smaller_when_overflow():
    """Hook auto-shrink picks a size whose text fits within max_width."""
    import os

    from video2yt.thumbnail import DEFAULT_FONT, auto_shrink_font_for_hook
    if not os.path.exists(DEFAULT_FONT):
        pytest.skip("Hiragino Sans GB not available on this platform")
    size = auto_shrink_font_for_hook(
        font_path=DEFAULT_FONT, font_index=1,
        requested_size=400, text="T0最强阵容",
        max_width=400,  # very narrow → forces shrink
    )
    assert size < 400


def test_thumbnail_cli_card_tilt_deg_default_is_none_so_orientation_resolves():
    """`--card-tilt-deg` default None lets each orientation resolve its own default."""
    from video2yt import thumbnail_cli
    args = thumbnail_cli.parse_args([
        "--bg", "bg.png", "--logo", "logo.png",
        "--title", "t", "-o", "o.png",
    ])
    assert args.card_tilt_deg is None


def test_thumbnail_cli_logo_width_ratio_default_is_none():
    """Same pattern for --logo-width-ratio so card-impact gets a smaller default."""
    from video2yt import thumbnail_cli
    args = thumbnail_cli.parse_args([
        "--bg", "bg.png", "--logo", "logo.png",
        "--title", "t", "-o", "o.png",
    ])
    assert args.logo_width_ratio is None


def test_thumbnail_cli_no_impact_logo_target_w_flag():
    """Flag was redundant with --logo-target-w; ensure it is gone."""
    from video2yt import thumbnail_cli
    with pytest.raises(SystemExit):
        thumbnail_cli.parse_args([
            "--bg", "bg.png", "--logo", "logo.png", "--title", "t", "-o", "o.png",
            "--impact-logo-target-w", "200",
        ])


def test_thumbnail_render_card_impact_card_tilt_deg_user_value_is_honored(monkeypatch, tmp_path):
    """User-passed --card-tilt-deg flows through; it must NOT be silently
    overridden to the orientation default. Real bug previously: -12.0 default
    → silent +10 swap in card-impact.
    """
    import os

    from PIL import Image as _Image

    from video2yt.thumbnail import DEFAULT_FONT, render_thumbnail
    if not os.path.exists(DEFAULT_FONT):
        pytest.skip("Hiragino Sans GB not available on this platform")

    bg = tmp_path / "bg.png"
    _Image.new("RGB", (1280, 720), (40, 30, 60)).save(bg)
    logo = tmp_path / "logo.png"
    _Image.new("RGBA", (200, 80), (255, 200, 0, 255)).save(logo)
    card = tmp_path / "card.png"
    _Image.new("RGBA", (300, 420), (50, 100, 200, 255)).save(card)
    out = tmp_path / "thumb.png"

    captured: dict = {}
    real_paste = __import__("video2yt.thumbnail", fromlist=["_paste_card_half_bleed"])._paste_card_half_bleed

    def spy_paste(canvas, card_path, **kw):
        captured["tilt_deg"] = kw["tilt_deg"]
        return real_paste(canvas, card_path, **kw)

    monkeypatch.setattr("video2yt.thumbnail._paste_card_half_bleed", spy_paste)

    # Pass an unusual value (-25°) — must not be swapped to anything else.
    render_thumbnail(
        bg_path=bg, logo_path=logo, title="T",
        output_path=out, orientation="card-impact",
        card_path=card, hook="破", card_tilt_deg=-25.0,
    )
    assert captured["tilt_deg"] == -25.0


def test_thumbnail_render_card_impact_logo_target_w_user_value_wins(monkeypatch, tmp_path):
    """`--logo-target-w 200` in card-impact must produce a 200-wide logo, not
    the orientation default of 160 (=0.125 * 1280)."""
    import os

    from PIL import Image as _Image

    from video2yt.thumbnail import DEFAULT_FONT, render_thumbnail
    if not os.path.exists(DEFAULT_FONT):
        pytest.skip("Hiragino Sans GB not available on this platform")

    bg = tmp_path / "bg.png"
    _Image.new("RGB", (1280, 720), (40, 30, 60)).save(bg)
    logo = tmp_path / "logo.png"
    _Image.new("RGBA", (400, 160), (255, 200, 0, 255)).save(logo)
    card = tmp_path / "card.png"
    _Image.new("RGBA", (300, 420), (50, 100, 200, 255)).save(card)
    out = tmp_path / "thumb.png"

    sizes_seen: list[tuple[int, int]] = []
    real_resize = _Image.Image.resize

    def spy_resize(self, size, *args, **kwargs):
        sizes_seen.append(size)
        return real_resize(self, size, *args, **kwargs)

    monkeypatch.setattr("PIL.Image.Image.resize", spy_resize)

    render_thumbnail(
        bg_path=bg, logo_path=logo, title="T",
        output_path=out, orientation="card-impact",
        card_path=card, hook="破", logo_target_w=200,
    )
    # The logo source is 400x160; at logo_target_w=200, scale=0.5 → resized to (200, 80).
    assert (200, 80) in sizes_seen


def test_thumbnail_render_card_impact_smoke_writes_png(tmp_path):
    """End-to-end card-impact: real Pillow render writes a 1280x720 RGB PNG.

    Requires Hiragino Sans GB to load (macOS-only). Skipped elsewhere.
    """
    import os

    from PIL import Image as _Image

    from video2yt.thumbnail import DEFAULT_FONT, render_thumbnail
    if not os.path.exists(DEFAULT_FONT):
        pytest.skip("Hiragino Sans GB not available on this platform")

    bg = tmp_path / "bg.png"
    _Image.new("RGB", (1280, 720), (40, 30, 60)).save(bg)
    logo = tmp_path / "logo.png"
    _Image.new("RGBA", (200, 80), (255, 200, 0, 255)).save(logo)
    card = tmp_path / "card.png"
    _Image.new("RGBA", (300, 420), (50, 100, 200, 255)).save(card)
    out = tmp_path / "thumb.png"

    render_thumbnail(
        bg_path=bg, logo_path=logo, title="T",
        output_path=out, orientation="card-impact",
        card_path=card, hook="破局",
        subtitle="戒指龙最强配置",
        result_badge="9鸡", season_text="S13E07",
    )
    assert out.exists()
    img = _Image.open(out)
    assert img.size == (1280, 720)
    assert img.mode == "RGB"


# =========================================================================
# video2yt-tts tests
# =========================================================================


class _FakeTtsResponse:
    """Mimic requests.Response used as a context manager + streaming iterator."""

    def __init__(self, *, status_code=200, lines=None, text="", logid="logid-fake"):
        self.status_code = status_code
        self.text = text
        self.headers = {"X-Tt-Logid": logid}
        self._lines = lines or []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def iter_lines(self, decode_unicode=False):
        for line in self._lines:
            yield line


def _tts_chunk(audio_b64="", code=0, sentence=None):
    import base64

    msg = {"code": code}
    if audio_b64:
        msg["data"] = audio_b64
    if sentence:
        msg["sentence"] = sentence
    return json.dumps(msg).encode("utf-8")


def test_tts_synthesize_writes_decoded_audio(monkeypatch, tmp_path):
    import base64

    from video2yt import tts as tts_mod
    audio_part_a = b"AUDIO_A"
    audio_part_b = b"AUDIO_B"
    lines = [
        _tts_chunk(audio_b64=base64.b64encode(audio_part_a).decode("ascii")),
        _tts_chunk(audio_b64=base64.b64encode(audio_part_b).decode("ascii"), sentence="一句"),
        _tts_chunk(code=20000000),
    ]

    def fake_post(url, headers=None, json=None, stream=None, timeout=None):
        assert url == tts_mod.ENDPOINT
        assert headers["X-Api-Key"] == "secret-key"
        assert json["req_params"]["text"] == "你好"
        return _FakeTtsResponse(lines=lines)

    monkeypatch.setattr("video2yt.tts.requests.post", fake_post)

    out = tmp_path / "out.mp3"
    info = tts_mod.synthesize("你好", "secret-key", "voice-a", out)
    assert out.read_bytes() == audio_part_a + audio_part_b
    assert info["bytes"] == len(audio_part_a) + len(audio_part_b)
    assert info["chunks"] == 2
    assert info["sentences"] == 1


def test_tts_synthesize_raises_on_http_error(monkeypatch, tmp_path):
    from video2yt import tts as tts_mod
    monkeypatch.setattr(
        "video2yt.tts.requests.post",
        lambda *a, **kw: _FakeTtsResponse(status_code=500, text="boom"),
    )
    with pytest.raises(RuntimeError, match="HTTP 500"):
        tts_mod.synthesize("hi", "k", "v", tmp_path / "o.mp3")


def test_tts_synthesize_raises_on_nonzero_code(monkeypatch, tmp_path):
    from video2yt import tts as tts_mod
    err = json.dumps({"code": 40001, "message": "auth fail"}).encode("utf-8")
    monkeypatch.setattr(
        "video2yt.tts.requests.post",
        lambda *a, **kw: _FakeTtsResponse(lines=[err]),
    )
    with pytest.raises(RuntimeError, match="code=40001"):
        tts_mod.synthesize("hi", "k", "v", tmp_path / "o.mp3")


def test_tts_synthesize_raises_when_no_audio_returned(monkeypatch, tmp_path):
    from video2yt import tts as tts_mod
    monkeypatch.setattr(
        "video2yt.tts.requests.post",
        lambda *a, **kw: _FakeTtsResponse(lines=[_tts_chunk(code=20000000)]),
    )
    with pytest.raises(RuntimeError, match="no audio chunks"):
        tts_mod.synthesize("hi", "k", "v", tmp_path / "o.mp3")


def test_tts_cli_parse_args_text_inline():
    from video2yt import tts_cli
    args = tts_cli.parse_args(["--text", "你好", "-o", "out.mp3"])
    assert args.text == "你好"
    assert args.text_file is None
    assert args.speech_rate == 0


def test_tts_cli_parse_args_requires_text_or_file():
    from video2yt import tts_cli
    with pytest.raises(SystemExit):
        tts_cli.parse_args(["-o", "out.mp3"])


def test_tts_cli_run_errors_when_api_key_missing(monkeypatch, tmp_path):
    from video2yt import tts_cli
    monkeypatch.delenv("VOLCENGINE_API_KEY", raising=False)
    monkeypatch.setattr("video2yt.tts_cli.load_dotenv", lambda: None)
    args = tts_cli.parse_args(["--text", "你好", "-o", str(tmp_path / "o.mp3")])
    with pytest.raises(ValueError, match="VOLCENGINE_API_KEY"):
        tts_cli.run(args)


def test_tts_cli_run_reads_text_file(monkeypatch, tmp_path):
    from video2yt import tts_cli
    monkeypatch.setenv("VOLCENGINE_API_KEY", "k")
    monkeypatch.setattr("video2yt.tts_cli.load_dotenv", lambda: None)
    txt = tmp_path / "script.txt"
    txt.write_text("从文件读取的文本", encoding="utf-8")
    captured: dict = {}

    def fake_synth(**kw):
        captured.update(kw)
        return {"bytes": 100, "chunks": 1, "sentences": 1, "logid": "x", "usage": None}

    monkeypatch.setattr("video2yt.tts_cli.tts.synthesize", fake_synth)
    args = tts_cli.parse_args(["--text-file", str(txt), "-o", str(tmp_path / "o.mp3")])
    tts_cli.run(args)
    assert captured["text"] == "从文件读取的文本"
    assert captured["api_key"] == "k"


def test_tts_cli_run_errors_on_empty_text(monkeypatch, tmp_path):
    from video2yt import tts_cli
    monkeypatch.setenv("VOLCENGINE_API_KEY", "k")
    monkeypatch.setattr("video2yt.tts_cli.load_dotenv", lambda: None)
    txt = tmp_path / "empty.txt"
    txt.write_text("   \n", encoding="utf-8")
    args = tts_cli.parse_args(["--text-file", str(txt), "-o", str(tmp_path / "o.mp3")])
    with pytest.raises(ValueError, match="text is empty"):
        tts_cli.run(args)


def test_tts_cli_main_returns_1_on_runtime_error(monkeypatch, tmp_path):
    from video2yt import tts_cli
    monkeypatch.setenv("VOLCENGINE_API_KEY", "k")
    monkeypatch.setattr("video2yt.tts_cli.load_dotenv", lambda: None)

    def boom(**kw):
        raise RuntimeError("upstream broke")

    monkeypatch.setattr("video2yt.tts_cli.tts.synthesize", boom)
    rc = tts_cli.main(["--text", "x", "-o", str(tmp_path / "o.mp3")])
    assert rc == 1


def test_tts_cli_main_returns_0_on_success(monkeypatch, tmp_path):
    from video2yt import tts_cli
    monkeypatch.setenv("VOLCENGINE_API_KEY", "k")
    monkeypatch.setattr("video2yt.tts_cli.load_dotenv", lambda: None)
    monkeypatch.setattr(
        "video2yt.tts_cli.tts.synthesize",
        lambda **kw: {"bytes": 1, "chunks": 1, "sentences": 0, "logid": "x", "usage": None},
    )
    rc = tts_cli.main(["--text", "x", "-o", str(tmp_path / "o.mp3")])
    assert rc == 0


# =========================================================================
# video2yt-image tests
# =========================================================================


def test_image_parse_size_basic():
    from video2yt.image_gen import parse_size
    assert parse_size("1920x1080") == (1920, 1080)
    assert parse_size("512X512") == (512, 512)


def test_image_fit_to_size_cover_crops_landscape_to_square():
    from PIL import Image as _Image

    from video2yt.image_gen import fit_to_size
    src = _Image.new("RGB", (200, 100), (255, 0, 0))
    out = fit_to_size(src, 50, 50, "cover")
    assert out.size == (50, 50)


def test_image_fit_to_size_contain_letterboxes():
    from PIL import Image as _Image

    from video2yt.image_gen import fit_to_size
    src = _Image.new("RGB", (200, 100), (255, 0, 0))
    out = fit_to_size(src, 100, 100, "contain")
    assert out.size == (100, 100)
    # Top row is black padding (letterbox), middle row is the resized image (red).
    assert out.getpixel((50, 5)) == (0, 0, 0)
    assert out.getpixel((50, 50)) == (255, 0, 0)


def test_image_fit_to_size_unknown_mode_raises():
    from PIL import Image as _Image

    from video2yt.image_gen import fit_to_size
    src = _Image.new("RGB", (10, 10), (0, 0, 0))
    with pytest.raises(ValueError, match="unknown fit mode"):
        fit_to_size(src, 10, 10, "stretch")


def test_image_generate_codex_invokes_codex_exec(monkeypatch, tmp_path):
    from PIL import Image as _Image

    from video2yt import image_gen as ig

    captured: dict = {}

    def fake_run(cmd, check=None, timeout=None):
        # Recreate the contract: codex agent saved a PNG at tmpdir/image.png
        # The tmpdir lives inside cmd as `--cd <path>`.
        cd_idx = cmd.index("--cd") + 1
        cwd = Path(cmd[cd_idx])
        (cwd / "image.png").write_bytes(_PIL_PNG_BYTES())
        captured["cmd"] = cmd
        captured["timeout"] = timeout
        return None

    monkeypatch.setattr("video2yt.image_gen.subprocess.run", fake_run)
    img = ig.generate_codex("a cat", codex_size="1024x1024", timeout=42)
    assert img.size == (1, 1)
    assert "codex" == captured["cmd"][0]
    assert captured["timeout"] == 42
    assert "1024x1024" in " ".join(captured["cmd"])


def test_image_generate_codex_raises_when_output_missing(monkeypatch):
    from video2yt import image_gen as ig

    monkeypatch.setattr("video2yt.image_gen.subprocess.run", lambda *a, **kw: None)
    with pytest.raises(RuntimeError, match="does not exist"):
        ig.generate_codex("prompt")


def test_image_generate_codex_raises_on_timeout(monkeypatch):
    import subprocess as _sp

    from video2yt import image_gen as ig

    def boom(cmd, check=None, timeout=None):
        raise _sp.TimeoutExpired(cmd=cmd, timeout=timeout)

    monkeypatch.setattr("video2yt.image_gen.subprocess.run", boom)
    with pytest.raises(RuntimeError, match="timed out"):
        ig.generate_codex("prompt", timeout=5)


def test_image_generate_codex_raises_on_called_process_error(monkeypatch):
    import subprocess as _sp

    from video2yt import image_gen as ig

    def boom(cmd, check=None, timeout=None):
        raise _sp.CalledProcessError(returncode=2, cmd=cmd)

    monkeypatch.setattr("video2yt.image_gen.subprocess.run", boom)
    with pytest.raises(RuntimeError, match="exit code 2"):
        ig.generate_codex("prompt")


def test_image_generate_gemini_wraps_sdk_exception_without_hint_for_non_quota(monkeypatch):
    """Non-quota SDK exceptions get wrapped without the billing hint appended."""
    from video2yt import image_gen as ig

    class _BoomModels:
        def generate_content(self, **kw):
            raise RuntimeError("Authentication failed: invalid API key")

    class _FakeClient:
        def __init__(self, **kw):
            self.models = _BoomModels()

    monkeypatch.setattr("google.genai.Client", _FakeClient)
    with pytest.raises(RuntimeError, match="Gemini SDK error") as exc_info:
        ig.generate_gemini("prompt", "key")
    # The billing/quota hint is only appended for quota errors, not generic ones.
    assert "enable billing" not in str(exc_info.value)
    assert "free-tier" not in str(exc_info.value)


def test_image_generate_gemini_quota_error_includes_billing_hint(monkeypatch):
    from video2yt import image_gen as ig

    class _BoomModels:
        def generate_content(self, **kw):
            raise RuntimeError("RESOURCE_EXHAUSTED on free_tier")

    class _FakeClient:
        def __init__(self, **kw):
            self.models = _BoomModels()

    monkeypatch.setattr("google.genai.Client", _FakeClient)
    with pytest.raises(RuntimeError, match="enable billing"):
        ig.generate_gemini("prompt", "key")


def test_image_generate_gemini_raises_when_response_has_no_image(monkeypatch):
    from video2yt import image_gen as ig

    class _EmptyResponse:
        candidates = []
        text = ""

    class _Models:
        def generate_content(self, **kw):
            return _EmptyResponse()

    class _FakeClient:
        def __init__(self, **kw):
            self.models = _Models()

    monkeypatch.setattr("google.genai.Client", _FakeClient)
    with pytest.raises(RuntimeError, match="no image returned"):
        ig.generate_gemini("prompt", "key")


def test_image_cli_parse_args_defaults():
    from video2yt import image_gen_cli
    args = image_gen_cli.parse_args(["--prompt", "p", "-o", "o.png"])
    assert args.backend == "codex"
    assert args.fit == "cover"
    assert args.target_size == "1920x1080"


def test_image_cli_parse_args_requires_prompt():
    from video2yt import image_gen_cli
    with pytest.raises(SystemExit):
        image_gen_cli.parse_args(["-o", "o.png"])


def test_image_cli_run_gemini_errors_when_api_key_missing(monkeypatch, tmp_path):
    from video2yt import image_gen_cli
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr("video2yt.image_gen_cli.load_dotenv", lambda: None)
    args = image_gen_cli.parse_args([
        "--prompt", "p", "-o", str(tmp_path / "o.png"), "--backend", "gemini",
    ])
    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        image_gen_cli.run(args)


def test_image_cli_run_codex_full_pipeline(monkeypatch, tmp_path):
    from PIL import Image as _Image

    from video2yt import image_gen_cli

    monkeypatch.setattr("video2yt.image_gen_cli.load_dotenv", lambda: None)
    captured: dict = {}

    def fake_codex(prompt, codex_size=None, timeout=None):
        captured["prompt"] = prompt
        captured["codex_size"] = codex_size
        return _Image.new("RGB", (1536, 1024), (10, 20, 30))

    monkeypatch.setattr("video2yt.image_gen_cli.image_gen.generate_codex", fake_codex)
    out = tmp_path / "out.png"
    args = image_gen_cli.parse_args([
        "--prompt", "test prompt", "-o", str(out),
        "--target-size", "1920x1080", "--fit", "cover",
    ])
    result = image_gen_cli.run(args)
    assert result == out
    assert out.exists()
    assert _Image.open(out).size == (1920, 1080)
    assert captured["prompt"] == "test prompt"


def test_image_cli_run_reads_prompt_file_and_save_raw(monkeypatch, tmp_path):
    from PIL import Image as _Image

    from video2yt import image_gen_cli

    monkeypatch.setattr("video2yt.image_gen_cli.load_dotenv", lambda: None)
    pf = tmp_path / "prompt.txt"
    pf.write_text("from-file", encoding="utf-8")
    raw = tmp_path / "raw.png"
    out = tmp_path / "out.png"

    def fake_codex(prompt, codex_size=None, timeout=None):
        assert prompt == "from-file"
        return _Image.new("RGB", (200, 100), (255, 0, 0))

    monkeypatch.setattr("video2yt.image_gen_cli.image_gen.generate_codex", fake_codex)
    args = image_gen_cli.parse_args([
        "--prompt-file", str(pf), "-o", str(out),
        "--save-raw", str(raw), "--fit", "none",
    ])
    image_gen_cli.run(args)
    assert raw.exists()
    assert out.exists()
    # With --fit none, output should preserve the raw 200x100 dimensions.
    assert _Image.open(out).size == (200, 100)


def test_image_cli_main_returns_1_on_runtime_error(monkeypatch, tmp_path):
    from video2yt import image_gen_cli
    monkeypatch.setattr("video2yt.image_gen_cli.load_dotenv", lambda: None)

    def boom(prompt, codex_size=None, timeout=None):
        raise RuntimeError("codex broke")

    monkeypatch.setattr("video2yt.image_gen_cli.image_gen.generate_codex", boom)
    rc = image_gen_cli.main(["--prompt", "x", "-o", str(tmp_path / "o.png")])
    assert rc == 1


def _PIL_PNG_BYTES() -> bytes:
    """Smallest valid PNG (1x1) for fixture use in tests."""
    import io as _io

    from PIL import Image as _Image

    buf = _io.BytesIO()
    _Image.new("RGB", (1, 1), (0, 0, 0)).save(buf, format="PNG")
    return buf.getvalue()


# =========================================================================
# video2yt-upload tests
# =========================================================================


class _ExecuteWrapper:
    def __init__(self, result):
        self._result = result

    def execute(self):
        return self._result


class _NextChunkRequest:
    """Yields one progress 50% then a final response with the given video_id."""

    def __init__(self, video_id):
        self._video_id = video_id
        self._step = 0

    def next_chunk(self):
        self._step += 1
        if self._step == 1:
            class _Status:
                def progress(self_inner):
                    return 0.5

            return _Status(), None
        return None, {"id": self._video_id}


class _FakeYoutube:
    """Mimics the chained Discovery client API just enough for upload.py."""

    def __init__(self, *, channels=None, video_id="vid123", set_thumbnail_result=None,
                 insert_raises=None, set_raises=None):
        self._channels = channels or []
        self._video_id = video_id
        self._set_result = set_thumbnail_result or {"items": []}
        self._insert_raises = insert_raises
        self._set_raises = set_raises
        self.insert_body: dict | None = None

    def channels(self):
        outer = self

        class _Channels:
            def list(self, **kw):
                return _ExecuteWrapper({"items": outer._channels})

        return _Channels()

    def videos(self):
        outer = self

        class _Videos:
            def insert(self, **kw):
                if outer._insert_raises:
                    raise outer._insert_raises
                outer.insert_body = kw["body"]
                return _NextChunkRequest(outer._video_id)

        return _Videos()

    def thumbnails(self):
        outer = self

        class _Thumbnails:
            def set(self, **kw):
                if outer._set_raises:
                    raise outer._set_raises
                return _ExecuteWrapper(outer._set_result)

        return _Thumbnails()


def _meta_dict(video_path: Path, thumb_path: Path, *, channel="UC_TEST"):
    return {
        "title": "T",
        "description": "D",
        "tags": ["a", "b"],
        "category_id": "20",
        "default_language": "zh",
        "default_audio_language": "zh",
        "privacy_status": "private",
        "made_for_kids": False,
        "video_path": str(video_path),
        "thumbnail_path": str(thumb_path),
        "expected_channel_id": channel,
    }


def test_upload_list_channels_returns_items():
    from video2yt import upload as up
    yt = _FakeYoutube(channels=[{"id": "UC_A", "snippet": {"title": "A"}}])
    items = up.list_channels(yt)
    assert items == [{"id": "UC_A", "snippet": {"title": "A"}}]


def test_upload_validate_meta_passes_complete_dict(tmp_path):
    from video2yt import upload as up
    meta = _meta_dict(tmp_path / "v.mp4", tmp_path / "t.png")
    up.validate_meta(meta)  # no exception


def test_upload_validate_meta_lists_missing_keys():
    from video2yt import upload as up
    incomplete = {"title": "T", "video_path": "v.mp4"}
    with pytest.raises(ValueError, match="metadata missing required keys"):
        up.validate_meta(incomplete)


def test_upload_validate_meta_rejects_non_dict():
    from video2yt import upload as up
    with pytest.raises(ValueError, match="must be a JSON object"):
        up.validate_meta(["not", "a", "dict"])


def test_upload_get_credentials_oauth_flow_error_becomes_runtime_error(tmp_path, monkeypatch):
    """`run_local_server` failing (port conflict, closed browser, etc.) → RuntimeError."""
    from video2yt import upload as up

    class _BoomFlow:
        def run_local_server(self, **kw):
            raise OSError("[Errno 48] Address already in use")

    monkeypatch.setattr(
        "video2yt.upload.InstalledAppFlow.from_client_secrets_file",
        lambda path, scopes: _BoomFlow(),
    )
    with pytest.raises(RuntimeError, match="OAuth flow failed"):
        up.get_credentials(tmp_path / "secret.json", tmp_path / "token.json")


def test_upload_video_builds_correct_body_and_returns_id(tmp_path):
    from video2yt import upload as up
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x" * 1024)
    yt = _FakeYoutube(video_id="newvid42")
    meta = _meta_dict(video, tmp_path / "thumb.png")
    vid = up.upload_video(yt, meta, video)
    assert vid == "newvid42"
    assert yt.insert_body["snippet"]["title"] == "T"
    assert yt.insert_body["snippet"]["tags"] == ["a", "b"]
    assert yt.insert_body["status"]["privacyStatus"] == "private"
    assert yt.insert_body["status"]["embeddable"] is True


def test_upload_thumbnail_calls_set(tmp_path):
    from video2yt import upload as up
    thumb = tmp_path / "thumb.png"
    thumb.write_bytes(_PIL_PNG_BYTES())
    yt = _FakeYoutube()
    up.upload_thumbnail(yt, "vid123", thumb)
    # No assertion error means the chained .set().execute() path didn't raise.


def test_upload_get_credentials_returns_cached_when_valid(tmp_path, monkeypatch):
    from video2yt import upload as up

    class _FakeCreds:
        valid = True
        expired = False
        refresh_token = None

        def to_json(self):
            return "{}"

    token = tmp_path / "token.json"
    token.write_text("{}")
    monkeypatch.setattr(
        "video2yt.upload.Credentials.from_authorized_user_file",
        lambda path, scopes: _FakeCreds(),
    )

    def boom(*a, **kw):
        raise AssertionError("flow should not run when creds are valid")

    monkeypatch.setattr(
        "video2yt.upload.InstalledAppFlow.from_client_secrets_file", boom
    )
    creds = up.get_credentials(tmp_path / "secret.json", token)
    assert isinstance(creds, _FakeCreds)


def test_upload_get_credentials_recovers_from_refresh_error(tmp_path, monkeypatch):
    from google.auth.exceptions import RefreshError

    from video2yt import upload as up

    class _ExpiredCreds:
        valid = False
        expired = True
        refresh_token = "rt"

        def refresh(self, request):
            raise RefreshError("Token has been expired or revoked.")

    class _FreshCreds:
        valid = True

        def to_json(self):
            return '{"refresh_token": "new"}'

    token = tmp_path / "token.json"
    token.write_text("{}")

    monkeypatch.setattr(
        "video2yt.upload.Credentials.from_authorized_user_file",
        lambda path, scopes: _ExpiredCreds(),
    )

    class _FakeFlow:
        def run_local_server(self, port=0, prompt=None):
            return _FreshCreds()

    monkeypatch.setattr(
        "video2yt.upload.InstalledAppFlow.from_client_secrets_file",
        lambda path, scopes: _FakeFlow(),
    )

    creds = up.get_credentials(tmp_path / "secret.json", token)
    assert isinstance(creds, _FreshCreds)
    assert token.read_text() == '{"refresh_token": "new"}'


def test_upload_cli_parse_args_defaults():
    from video2yt import upload_cli
    args = upload_cli.parse_args(["--metadata", "m.json"])
    assert args.client_secret == Path("client_secret.json")
    assert args.token == Path("youtube_token.json")
    assert args.skip_thumbnail is False
    assert args.dry_run is False


def test_upload_cli_run_errors_when_metadata_missing(tmp_path):
    from video2yt import upload_cli
    args = upload_cli.parse_args(["--metadata", str(tmp_path / "missing.json")])
    with pytest.raises(FileNotFoundError, match="metadata not found"):
        upload_cli.run(args)


def test_upload_cli_run_errors_on_malformed_metadata_keys(tmp_path):
    """Hand-written metadata.json missing fields gets a ValueError, not a KeyError."""
    from video2yt import upload_cli
    meta = tmp_path / "meta.json"
    meta.write_text(json.dumps({"title": "T"}), encoding="utf-8")
    args = upload_cli.parse_args(["--metadata", str(meta)])
    with pytest.raises(ValueError, match="metadata missing required keys"):
        upload_cli.run(args)


def test_upload_cli_run_errors_on_malformed_metadata_json(tmp_path):
    from video2yt import upload_cli
    meta = tmp_path / "meta.json"
    meta.write_text("{this is not json", encoding="utf-8")
    args = upload_cli.parse_args(["--metadata", str(meta)])
    with pytest.raises(ValueError, match="malformed metadata JSON"):
        upload_cli.run(args)


def test_upload_cli_run_errors_when_video_missing(tmp_path):
    from video2yt import upload_cli
    meta = tmp_path / "meta.json"
    thumb = tmp_path / "t.png"
    thumb.write_bytes(_PIL_PNG_BYTES())
    meta.write_text(json.dumps(_meta_dict(tmp_path / "missing.mp4", thumb)), encoding="utf-8")
    args = upload_cli.parse_args(["--metadata", str(meta)])
    with pytest.raises(FileNotFoundError, match="video not found"):
        upload_cli.run(args)


def test_upload_cli_run_dry_run_skips_upload(tmp_path, monkeypatch):
    from video2yt import upload_cli

    video = tmp_path / "v.mp4"
    video.write_bytes(b"x" * 1024)
    thumb = tmp_path / "t.png"
    thumb.write_bytes(_PIL_PNG_BYTES())
    meta = tmp_path / "meta.json"
    meta.write_text(json.dumps(_meta_dict(video, thumb, channel="UC_OK")), encoding="utf-8")

    monkeypatch.setattr("video2yt.upload_cli.upload.get_credentials", lambda s, t: object())
    monkeypatch.setattr(
        "video2yt.upload_cli.build",
        lambda *a, **kw: _FakeYoutube(channels=[{"id": "UC_OK"}]),
    )
    args = upload_cli.parse_args(["--metadata", str(meta), "--dry-run"])
    result = upload_cli.run(args)
    assert result["dry_run"] is True
    assert result["video_id"] is None


def test_upload_cli_run_wrong_channel_raises(tmp_path, monkeypatch):
    from video2yt import upload_cli

    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")
    thumb = tmp_path / "t.png"
    thumb.write_bytes(_PIL_PNG_BYTES())
    meta = tmp_path / "meta.json"
    meta.write_text(json.dumps(_meta_dict(video, thumb, channel="UC_EXPECTED")), encoding="utf-8")

    monkeypatch.setattr("video2yt.upload_cli.upload.get_credentials", lambda s, t: object())
    monkeypatch.setattr(
        "video2yt.upload_cli.build",
        lambda *a, **kw: _FakeYoutube(channels=[{"id": "UC_OTHER"}]),
    )
    args = upload_cli.parse_args(["--metadata", str(meta)])
    with pytest.raises(RuntimeError, match="not in authenticated channels"):
        upload_cli.run(args)


def test_upload_cli_run_full_happy_path(tmp_path, monkeypatch):
    from video2yt import upload_cli

    video = tmp_path / "v.mp4"
    video.write_bytes(b"x" * 1024)
    thumb = tmp_path / "t.png"
    thumb.write_bytes(_PIL_PNG_BYTES())
    meta = tmp_path / "meta.json"
    meta.write_text(json.dumps(_meta_dict(video, thumb, channel="UC_OK")), encoding="utf-8")

    monkeypatch.setattr("video2yt.upload_cli.upload.get_credentials", lambda s, t: object())
    monkeypatch.setattr(
        "video2yt.upload_cli.build",
        lambda *a, **kw: _FakeYoutube(channels=[{"id": "UC_OK"}], video_id="vidXYZ"),
    )
    args = upload_cli.parse_args(["--metadata", str(meta)])
    result = upload_cli.run(args)
    assert result["video_id"] == "vidXYZ"
    assert "youtube.com/watch?v=vidXYZ" in result["video_url"]
    assert "studio.youtube.com/video/vidXYZ" in result["studio_url"]


def test_upload_cli_run_http_error_on_insert_becomes_runtime_error(tmp_path, monkeypatch):
    from googleapiclient.errors import HttpError

    from video2yt import upload_cli

    video = tmp_path / "v.mp4"
    video.write_bytes(b"x" * 1024)
    thumb = tmp_path / "t.png"
    thumb.write_bytes(_PIL_PNG_BYTES())
    meta = tmp_path / "meta.json"
    meta.write_text(json.dumps(_meta_dict(video, thumb, channel="UC_OK")), encoding="utf-8")

    class _Resp:
        status = 403
        reason = "Forbidden"

    err = HttpError(_Resp(), b'{"error": "quota"}')
    monkeypatch.setattr("video2yt.upload_cli.upload.get_credentials", lambda s, t: object())
    monkeypatch.setattr(
        "video2yt.upload_cli.build",
        lambda *a, **kw: _FakeYoutube(channels=[{"id": "UC_OK"}], insert_raises=err),
    )
    args = upload_cli.parse_args(["--metadata", str(meta)])
    with pytest.raises(RuntimeError, match="upload failed"):
        upload_cli.run(args)


def test_upload_cli_run_http_error_on_list_channels_becomes_runtime_error(
    tmp_path, monkeypatch
):
    """Without the wrap, HttpError from channels().list() bypasses main()'s catch."""
    from googleapiclient.errors import HttpError

    from video2yt import upload_cli

    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")
    thumb = tmp_path / "t.png"
    thumb.write_bytes(_PIL_PNG_BYTES())
    meta = tmp_path / "meta.json"
    meta.write_text(json.dumps(_meta_dict(video, thumb, channel="UC_OK")), encoding="utf-8")

    class _Resp:
        status = 401
        reason = "Unauthorized"

    err = HttpError(_Resp(), b'{"error": "auth"}')

    class _FailingChannels:
        def list(self, **kw):
            raise err

    class _FailingYt:
        def channels(self):
            return _FailingChannels()

    monkeypatch.setattr("video2yt.upload_cli.upload.get_credentials", lambda s, t: object())
    monkeypatch.setattr("video2yt.upload_cli.build", lambda *a, **kw: _FailingYt())
    args = upload_cli.parse_args(["--metadata", str(meta)])
    with pytest.raises(RuntimeError, match="list channels"):
        upload_cli.run(args)


def test_upload_cli_run_thumbnail_http_error_is_swallowed(tmp_path, monkeypatch):
    """Failing thumbnail upload after a successful video upload is recoverable."""
    from googleapiclient.errors import HttpError

    from video2yt import upload_cli

    video = tmp_path / "v.mp4"
    video.write_bytes(b"x" * 1024)
    thumb = tmp_path / "t.png"
    thumb.write_bytes(_PIL_PNG_BYTES())
    meta = tmp_path / "meta.json"
    meta.write_text(json.dumps(_meta_dict(video, thumb, channel="UC_OK")), encoding="utf-8")

    class _Resp:
        status = 400
        reason = "Bad Request"

    err = HttpError(_Resp(), b'{"error": "thumbnail too small"}')
    monkeypatch.setattr("video2yt.upload_cli.upload.get_credentials", lambda s, t: object())
    monkeypatch.setattr(
        "video2yt.upload_cli.build",
        lambda *a, **kw: _FakeYoutube(
            channels=[{"id": "UC_OK"}], video_id="vid42", set_raises=err,
        ),
    )
    args = upload_cli.parse_args(["--metadata", str(meta)])
    result = upload_cli.run(args)
    assert result["video_id"] == "vid42"
    assert result["dry_run"] is False


def test_upload_cli_main_returns_1_on_missing_metadata(tmp_path):
    from video2yt import upload_cli
    rc = upload_cli.main(["--metadata", str(tmp_path / "nope.json")])
    assert rc == 1


def test_upload_cli_main_returns_0_on_dry_run(tmp_path, monkeypatch):
    from video2yt import upload_cli

    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")
    thumb = tmp_path / "t.png"
    thumb.write_bytes(_PIL_PNG_BYTES())
    meta = tmp_path / "meta.json"
    meta.write_text(json.dumps(_meta_dict(video, thumb, channel="UC_OK")), encoding="utf-8")

    monkeypatch.setattr("video2yt.upload_cli.upload.get_credentials", lambda s, t: object())
    monkeypatch.setattr(
        "video2yt.upload_cli.build",
        lambda *a, **kw: _FakeYoutube(channels=[{"id": "UC_OK"}]),
    )
    rc = upload_cli.main(["--metadata", str(meta), "--dry-run"])
    assert rc == 0


# ===================== video2yt-topic =====================

def _topic_candidate(
    bvid="BV1xx",
    title="郭枫战旗实战",
    streamer="郭枫",
    play=100000,
    duration=900,
    description="实战录像",
    created_ts=1_700_000_000,
):
    from video2yt.topic import VideoCandidate
    return VideoCandidate(
        bvid=bvid,
        title=title,
        description=description,
        duration_seconds=duration,
        play_count=play,
        created_ts=created_ts,
        streamer=streamer,
    )


def _topic_summary(
    candidate=None,
    strategy="戒指龙流",
    core_card="戒指龙",
    summary="戒指龙滚雪球",
    highlights="新饰品加速",
):
    from video2yt.topic import VideoSummary
    return VideoSummary(
        candidate=candidate or _topic_candidate(),
        strategy=strategy,
        core_card=core_card,
        summary=summary,
        highlights=highlights,
    )


def test_topic_parse_streamers_basic(tmp_path):
    from video2yt import topic
    f = tmp_path / "s.txt"
    f.write_text(
        "# comment\n\n炉石郭枫 12345\n超凡景清 67890\n瓦莉拉 11 mixed\n",
        encoding="utf-8",
    )
    out = topic.parse_streamers(f)
    assert len(out) == 3
    assert out[0].name == "炉石郭枫" and out[0].uid == 12345 and out[0].is_mixed is False
    assert out[1].name == "超凡景清" and out[1].uid == 67890 and out[1].is_mixed is False
    assert out[2].name == "瓦莉拉" and out[2].uid == 11 and out[2].is_mixed is True


def test_topic_parse_streamers_invalid_3rd_token(tmp_path):
    from video2yt import topic
    f = tmp_path / "s.txt"
    f.write_text("瓦莉拉 11 something\n", encoding="utf-8")
    with pytest.raises(ValueError, match="3rd token must be 'mixed'"):
        topic.parse_streamers(f)


def test_topic_parse_streamers_missing_file(tmp_path):
    from video2yt import topic
    with pytest.raises(FileNotFoundError):
        topic.parse_streamers(tmp_path / "nope.txt")


def test_topic_parse_streamers_invalid_format(tmp_path):
    from video2yt import topic
    f = tmp_path / "s.txt"
    f.write_text("郭枫\n", encoding="utf-8")
    with pytest.raises(ValueError, match=r"expected '<name> <uid> \[mixed\]'"):
        topic.parse_streamers(f)
    f.write_text("郭枫 1 mixed extra\n", encoding="utf-8")
    with pytest.raises(ValueError, match=r"expected '<name> <uid> \[mixed\]'"):
        topic.parse_streamers(f)


def test_topic_parse_streamers_uid_must_be_positive_int(tmp_path):
    from video2yt import topic
    f = tmp_path / "s.txt"
    f.write_text("郭枫 0\n", encoding="utf-8")
    with pytest.raises(ValueError, match="uid must be positive"):
        topic.parse_streamers(f)
    f.write_text("郭枫 abc\n", encoding="utf-8")
    with pytest.raises(ValueError, match="uid must be int"):
        topic.parse_streamers(f)


def test_topic_parse_streamers_empty_raises(tmp_path):
    from video2yt import topic
    f = tmp_path / "s.txt"
    f.write_text("# only comments\n\n", encoding="utf-8")
    with pytest.raises(ValueError, match="no valid streamer entries"):
        topic.parse_streamers(f)


def test_topic_parse_done_topics_returns_set(tmp_path):
    from video2yt import topic
    f = tmp_path / "d.txt"
    f.write_text("# comment\n戒指龙\n\n背靠背流\n", encoding="utf-8")
    assert topic.parse_done_topics(f) == {"戒指龙", "背靠背流"}


def test_topic_parse_done_topics_missing_returns_empty(tmp_path):
    from video2yt import topic
    assert topic.parse_done_topics(tmp_path / "nope.txt") == set()


def test_topic_scan_done_corpus_from_output(tmp_path):
    from video2yt import topic
    out_root = tmp_path / "output"
    proj = out_root / "back2back"
    proj.mkdir(parents=True)
    (proj / "intro_script.txt").write_text("S13 版本最强的背靠背流", encoding="utf-8")
    proj2 = out_root / "ringnaga"
    proj2.mkdir(parents=True)
    (proj2 / "intro_script.txt").write_text("護戒娜迦：核心是戒指龍", encoding="utf-8")
    corpus = topic.scan_done_corpus_from_output(out_root)
    assert set(corpus.keys()) == {"output/back2back", "output/ringnaga"}
    # blob includes folder name + script body
    assert "back2back" in corpus["output/back2back"]
    assert "背靠背流" in corpus["output/back2back"]
    assert "戒指龍" in corpus["output/ringnaga"]


def test_topic_scan_done_corpus_from_output_missing(tmp_path):
    from video2yt import topic
    assert topic.scan_done_corpus_from_output(tmp_path / "missing") == {}


def test_topic_parse_length_string_mmss():
    from video2yt import topic
    assert topic.parse_length_string("12:34") == 12 * 60 + 34


def test_topic_parse_length_string_hhmmss():
    from video2yt import topic
    assert topic.parse_length_string("1:02:03") == 3600 + 120 + 3


def test_topic_parse_length_string_invalid():
    from video2yt import topic
    with pytest.raises(ValueError):
        topic.parse_length_string("nope")


def test_topic_fetch_recent_videos_filters(monkeypatch):
    """Default behavior: no positive title filter (BG-dedicated streamer)."""
    from video2yt import topic

    fixture = [
        # passes: recent, long enough, plain title — no '战棋' required for BG-only channels
        {"bvid": "BV1aa", "title": "实战对局", "description": "d", "length": "12:00", "play": 50000, "created": 2000},
        # filtered: too short
        {"bvid": "BV1bb", "title": "实战对局", "description": "d", "length": "05:00", "play": 50000, "created": 2000},
        # filtered: bad title (教程)
        {"bvid": "BV1cc", "title": "新版本教程", "description": "d", "length": "12:00", "play": 50000, "created": 2000},
        # filtered: too old (created < since_ts)
        {"bvid": "BV1dd", "title": "实战对局", "description": "d", "length": "12:00", "play": 50000, "created": 500},
    ]
    async def fake(uid, pages, credential=None):
        assert uid == 999 and pages == 2
        return fixture
    monkeypatch.setattr(topic, "_async_fetch_videos", fake)

    out = topic.fetch_recent_videos(
        topic.Streamer(name="测试", uid=999),
        since_ts=1000,
        min_duration_seconds=600,
        pages=2,
    )
    assert len(out) == 1
    assert out[0].bvid == "BV1aa"
    assert out[0].streamer == "测试"
    assert out[0].duration_seconds == 720


def test_topic_fetch_recent_videos_include_filter_accepts_zhanqi_variants(monkeypatch):
    """When the include filter is supplied, both 战棋 and 战旗 pass; non-BG fails."""
    from video2yt import topic

    fixture = [
        {"bvid": "BV1q", "title": "酒馆战棋实战", "description": "d", "length": "12:00", "play": 1, "created": 2000},
        {"bvid": "BV1z", "title": "炉石战旗对局", "description": "d", "length": "12:00", "play": 1, "created": 2000},
        {"bvid": "BV1n", "title": "炉石传说宿伞之魂", "description": "d", "length": "12:00", "play": 1, "created": 2000},
    ]
    async def fake(uid, pages, credential=None):
        return fixture
    monkeypatch.setattr(topic, "_async_fetch_videos", fake)

    out = topic.fetch_recent_videos(
        topic.Streamer(name="测试", uid=999, is_mixed=True),
        since_ts=1000,
        min_duration_seconds=600,
        pages=1,
        include_title_re=topic.DEFAULT_INCLUDE_TITLE_RE,
    )
    assert {c.bvid for c in out} == {"BV1q", "BV1z"}


def test_topic_fetch_danmaku_sample_evenly_spaced(monkeypatch):
    from video2yt import topic
    texts = [f"d{i}" for i in range(1000)]
    async def fake(bvid, credential=None):
        assert bvid == "BV1aa"
        return texts
    monkeypatch.setattr(topic, "_async_fetch_danmaku", fake)
    out = topic.fetch_danmaku_sample("BV1aa", sample_size=10)
    assert len(out) == 10
    assert out[0] == "d0"
    # last sample picks index round(9*100) = d900
    assert out[-1].startswith("d9")


def test_topic_fetch_danmaku_sample_returns_all_when_small(monkeypatch):
    from video2yt import topic
    async def fake(bvid, credential=None):
        return ["a", "b", "c"]
    monkeypatch.setattr(topic, "_async_fetch_danmaku", fake)
    assert topic.fetch_danmaku_sample("BV", sample_size=10) == ["a", "b", "c"]


def test_topic_summarize_with_codex_writes_input_reads_output(tmp_path, monkeypatch):
    from video2yt import topic

    cands = [_topic_candidate(bvid="BV1aa"), _topic_candidate(bvid="BV1bb", title="景清实战", streamer="景清")]
    danmaku = {"BV1aa": ["d1", "d2"], "BV1bb": ["x", "y"]}

    captured: dict = {}

    def fake_run(cmd, **kw):
        # cmd[3] is "--cd", cmd[4] is the tempdir
        cd_idx = cmd.index("--cd") + 1
        tmpdir = Path(cmd[cd_idx])
        captured["input"] = json.loads((tmpdir / "input.json").read_text(encoding="utf-8"))
        # Simulate Codex writing the output file:
        out = [
            {"bvid": "BV1aa", "strategy": "戒指龙流", "core_card": "戒指龙",
             "summary": "郭枫戒指龙", "highlights": "新饰品"},
            {"bvid": "BV1bb", "strategy": "戒指龙流", "core_card": "戒指龙",
             "summary": "景清戒指龙", "highlights": "更激进英雄选择"},
        ]
        (tmpdir / "output.json").write_text(json.dumps(out), encoding="utf-8")
        return MagicMock(returncode=0)

    monkeypatch.setattr("video2yt.topic.subprocess.run", fake_run)
    summaries = topic.summarize_with_codex(cands, danmaku, timeout=60)

    assert len(summaries) == 2
    assert summaries[0].strategy == "戒指龙流"
    assert summaries[1].candidate.streamer == "景清"
    # Input JSON well-formed and contains expected keys
    assert captured["input"]["videos"][0]["bvid"] == "BV1aa"
    assert captured["input"]["videos"][0]["danmaku"] == ["d1", "d2"]


def test_topic_summarize_with_codex_no_candidates_skips(monkeypatch):
    from video2yt import topic
    called: list = []
    monkeypatch.setattr("video2yt.topic.subprocess.run", lambda *a, **kw: called.append(1))
    assert topic.summarize_with_codex([], {}) == []
    assert called == []


def test_topic_summarize_with_codex_missing_output_raises(tmp_path, monkeypatch):
    from video2yt import topic
    cands = [_topic_candidate()]
    monkeypatch.setattr(
        "video2yt.topic.subprocess.run",
        lambda *a, **kw: MagicMock(returncode=0),
    )
    with pytest.raises(RuntimeError, match="does not exist"):
        topic.summarize_with_codex(cands, {"BV1xx": []}, timeout=60)


def test_topic_summarize_with_codex_subprocess_failure_raises(monkeypatch):
    from video2yt import topic
    import subprocess as sp
    cands = [_topic_candidate()]
    def fake(*a, **kw):
        raise sp.CalledProcessError(returncode=2, cmd=a[0] if a else [])
    monkeypatch.setattr("video2yt.topic.subprocess.run", fake)
    with pytest.raises(RuntimeError, match="codex exec failed"):
        topic.summarize_with_codex(cands, {"BV1xx": []}, timeout=60)


def test_topic_group_pairs_keeps_two_distinct_streamers():
    from video2yt import topic
    s1 = _topic_summary(
        candidate=_topic_candidate(bvid="BV1", streamer="郭枫", play=100000),
        strategy="戒指龙流", core_card="戒指龙",
    )
    s2 = _topic_summary(
        candidate=_topic_candidate(bvid="BV2", streamer="景清", play=80000),
        strategy="戒指龙流", core_card="戒指龙",
    )
    s3 = _topic_summary(
        candidate=_topic_candidate(bvid="BV3", streamer="郭枫", play=50000),
        strategy="戒指龙流", core_card="戒指龙",
    )  # second video by same streamer; should be dropped
    pairs = topic.group_pairs([s1, s2, s3])
    assert len(pairs) == 1
    assert pairs[0].strategy == "戒指龙流"
    assert {s.candidate.streamer for s in pairs[0].summaries} == {"郭枫", "景清"}


def test_topic_group_pairs_unifies_via_core_card_when_strategy_differs():
    """Real-world case: Codex returns slightly different strategy names for
    the same comp ('戒指龙流' vs '亡灵戒指龙'), but core_card is the same."""
    from video2yt import topic
    s1 = _topic_summary(
        candidate=_topic_candidate(bvid="BV1", streamer="郭枫", play=100000),
        strategy="戒指龙流", core_card="戒指龙",
    )
    s2 = _topic_summary(
        candidate=_topic_candidate(bvid="BV2", streamer="景清", play=80000),
        strategy="亡灵戒指龙", core_card="戒指龙",
    )
    pairs = topic.group_pairs([s1, s2])
    assert len(pairs) == 1
    # The displayed strategy is the higher-played one's strategy
    assert pairs[0].strategy == "戒指龙流"


def test_topic_group_pairs_drops_singletons():
    from video2yt import topic
    s1 = _topic_summary(
        candidate=_topic_candidate(streamer="郭枫"),
        strategy="孤儿流", core_card="孤儿卡",
    )
    assert topic.group_pairs([s1]) == []


def test_topic_group_pairs_skips_blank_core_card():
    from video2yt import topic
    s1 = _topic_summary(candidate=_topic_candidate(streamer="郭枫"), core_card="")
    s2 = _topic_summary(candidate=_topic_candidate(streamer="景清"), core_card="")
    assert topic.group_pairs([s1, s2]) == []


def test_topic_annotate_already_done_via_corpus_substring():
    from video2yt import topic
    pair = topic.TopicPair(
        strategy="戒指龙流",
        summaries=[_topic_summary(), _topic_summary()],
        is_already_done=False,
        done_marker=None,
    )
    corpus = {"output/ringnaga": "ringnaga\n戒指龙阵容是核心"}
    topic.annotate_already_done([pair], corpus, set())
    assert pair.is_already_done is True
    assert pair.done_marker == "output/ringnaga/"


def test_topic_annotate_already_done_matches_via_core_card():
    """If only the core_card appears in the past corpus (not the strategy name)
    the pair should still be marked done."""
    from video2yt import topic
    s1 = _topic_summary(strategy="新名字流", core_card="戒指龙")
    s2 = _topic_summary(strategy="新名字流", core_card="戒指龙")
    pair = topic.TopicPair(
        strategy="新名字流",
        summaries=[s1, s2],
        is_already_done=False,
        done_marker=None,
    )
    corpus = {"output/ringnaga": "ringnaga\n核心是戒指龙"}
    topic.annotate_already_done([pair], corpus, set())
    assert pair.is_already_done is True


def test_topic_annotate_already_done_via_done_topics_file():
    from video2yt import topic
    pair = topic.TopicPair(
        strategy="背靠背流",
        summaries=[_topic_summary(), _topic_summary()],
        is_already_done=False,
        done_marker=None,
    )
    topic.annotate_already_done([pair], {}, {"背靠背"})
    assert pair.is_already_done is True
    assert pair.done_marker.startswith("done_topics:")


def test_topic_annotate_already_done_no_match_keeps_novel():
    from video2yt import topic
    s1 = _topic_summary(strategy="火车头流", core_card="火车头")
    s2 = _topic_summary(strategy="火车头流", core_card="火车头")
    pair = topic.TopicPair(
        strategy="火车头流",
        summaries=[s1, s2],
        is_already_done=False,
        done_marker=None,
    )
    corpus = {"output/x": "x\n背靠背流是T0"}
    topic.annotate_already_done([pair], corpus, {"戒指龙"})
    assert pair.is_already_done is False
    assert pair.done_marker is None


def test_topic_annotate_skips_one_char_needles():
    """Strategy '流' alone (norm length 0) must not match every blob."""
    from video2yt import topic
    s1 = _topic_summary(strategy="流", core_card="单")
    s2 = _topic_summary(strategy="流", core_card="单")
    pair = topic.TopicPair(
        strategy="流",
        summaries=[s1, s2],
        is_already_done=False,
        done_marker=None,
    )
    topic.annotate_already_done([pair], {"output/x": "anything"}, {"anything"})
    assert pair.is_already_done is False


def test_topic_annotate_traditional_simplified_bridged_via_done_topics():
    """Regression: ringnaga's intro is in 繁體 ('戒指龍'); a Codex strategy of
    '戒指龙流' (簡體) won't match the corpus directly, but a done_topics.txt
    entry of '戒指龙' must bridge the gap."""
    from video2yt import topic
    s1 = _topic_summary(strategy="戒指龙流", core_card="戒指龙")
    s2 = _topic_summary(strategy="戒指龙流", core_card="戒指龙")
    pair = topic.TopicPair(
        strategy="戒指龙流",
        summaries=[s1, s2],
        is_already_done=False,
        done_marker=None,
    )
    trad_corpus = {"output/ringnaga": "ringnaga\n核心是戒指龍，靠酒館法術"}
    topic.annotate_already_done([pair], trad_corpus, {"戒指龙"})
    assert pair.is_already_done is True
    assert "戒指龙" in pair.done_marker


def test_topic_score_pair_novel_gets_bonus():
    from video2yt import topic
    s1 = _topic_summary(candidate=_topic_candidate(play=100000, streamer="A"))
    s2 = _topic_summary(candidate=_topic_candidate(play=100000, streamer="B"))
    novel = topic.TopicPair(strategy="x", summaries=[s1, s2], is_already_done=False, done_marker=None)
    done = topic.TopicPair(strategy="x", summaries=[s1, s2], is_already_done=True, done_marker="output/x/")
    assert topic.score_pair(novel) == pytest.approx(topic.score_pair(done) + 2.0)


def test_topic_render_markdown_empty_message():
    from video2yt import topic
    md = topic.render_markdown([], window_days=7, generated_at="2026-05-09")
    assert "选题候选" in md
    assert "2026-05-09" in md
    assert "没有任何流派" in md


def test_topic_render_markdown_populated_includes_links_and_marker():
    from video2yt import topic
    s1 = _topic_summary(
        candidate=_topic_candidate(bvid="BV1", streamer="郭枫", title="郭枫战旗"),
        strategy="戒指龙流",
        summary="郭枫戒指龙",
        highlights="新饰品",
    )
    s2 = _topic_summary(
        candidate=_topic_candidate(bvid="BV2", streamer="景清", title="景清战旗"),
        strategy="戒指龙流",
        summary="景清戒指龙",
        highlights="更激进英雄",
    )
    pair_novel = topic.TopicPair(strategy="戒指龙流", summaries=[s1, s2], is_already_done=False, done_marker=None, score=7.5)
    pair_done = topic.TopicPair(strategy="背靠背流", summaries=[s1, s2], is_already_done=True, done_marker="output/back2back/", score=5.0)
    md = topic.render_markdown([pair_novel, pair_done], window_days=7, generated_at="2026-05-09")
    assert "戒指龙流" in md
    assert "[新流派" in md
    assert "已做过 → output/back2back/" in md
    assert "https://www.bilibili.com/video/BV1" in md
    assert "https://www.bilibili.com/video/BV2" in md


def test_topic_run_topic_orchestrator_writes_report(tmp_path, monkeypatch):
    from video2yt import topic

    streamers = [topic.Streamer(name="郭枫", uid=1), topic.Streamer(name="景清", uid=2)]

    def fake_fetch(s, **kw):
        if s.name == "郭枫":
            return [_topic_candidate(bvid="BVa", streamer="郭枫", play=100000)]
        return [_topic_candidate(bvid="BVb", streamer="景清", play=80000)]
    monkeypatch.setattr(topic, "fetch_recent_videos", fake_fetch)
    monkeypatch.setattr(topic, "fetch_danmaku_sample", lambda b, *a, **kw: ["d"])
    monkeypatch.setattr(
        topic,
        "summarize_with_codex",
        lambda cs, dm, **kw: [
            _topic_summary(candidate=cs[0], strategy="戒指龙流"),
            _topic_summary(candidate=cs[1], strategy="戒指龙流"),
        ],
    )

    report = tmp_path / "out" / "report.md"
    result = topic.run_topic(
        streamers=streamers,
        days=7,
        output_root=tmp_path / "no_output",
        done_topics_file=None,
        report_path=report,
        now_ts=1_700_000_000,
    )
    assert result == report
    text = report.read_text(encoding="utf-8")
    assert "戒指龙流" in text
    assert "[新流派" in text  # nothing under output_root


def test_topic_run_topic_applies_include_filter_only_to_mixed_streamers(tmp_path, monkeypatch):
    """BG-only streamers fetch with no include filter; mixed streamers get the
    战棋|战旗 filter so constructed-mode uploads are dropped before Codex."""
    from video2yt import topic

    streamers = [
        topic.Streamer(name="郭枫", uid=1),                 # BG-dedicated
        topic.Streamer(name="瓦莉拉", uid=2, is_mixed=True),  # general HS
    ]
    seen: dict[str, object] = {}

    def fake_fetch(s, **kw):
        seen[s.name] = kw.get("include_title_re")
        return []
    monkeypatch.setattr(topic, "fetch_recent_videos", fake_fetch)

    topic.run_topic(
        streamers=streamers,
        days=7,
        output_root=tmp_path / "no_output",
        done_topics_file=None,
        report_path=tmp_path / "report.md",
    )
    assert seen["郭枫"] is None
    assert seen["瓦莉拉"] is topic.DEFAULT_INCLUDE_TITLE_RE


def test_topic_run_topic_no_candidates_writes_empty_report(tmp_path, monkeypatch):
    from video2yt import topic
    monkeypatch.setattr(topic, "fetch_recent_videos", lambda s, **kw: [])
    summary_called: list = []
    monkeypatch.setattr(
        topic,
        "summarize_with_codex",
        lambda *a, **kw: summary_called.append(1) or [],
    )
    report = tmp_path / "report.md"
    topic.run_topic(
        streamers=[topic.Streamer(name="x", uid=1)],
        days=7,
        output_root=tmp_path / "no_output",
        done_topics_file=None,
        report_path=report,
    )
    assert report.exists()
    assert "没有任何流派" in report.read_text(encoding="utf-8")
    assert summary_called == [], "should not call codex when there are no candidates"


def test_topic_run_topic_swallows_per_streamer_fetch_failure(tmp_path, monkeypatch):
    from video2yt import topic
    def fake_fetch(s, **kw):
        if s.name == "broken":
            raise RuntimeError("boom")
        return [_topic_candidate(streamer=s.name)]
    monkeypatch.setattr(topic, "fetch_recent_videos", fake_fetch)
    monkeypatch.setattr(topic, "fetch_danmaku_sample", lambda b, *a, **kw: [])
    monkeypatch.setattr(topic, "summarize_with_codex", lambda cs, dm, **kw: [])
    streamers = [
        topic.Streamer(name="broken", uid=1),
        topic.Streamer(name="ok", uid=2),
    ]
    report = tmp_path / "r.md"
    topic.run_topic(
        streamers=streamers,
        days=7,
        output_root=tmp_path / "no_output",
        done_topics_file=None,
        report_path=report,
    )
    assert report.exists()


def test_topic_cli_parse_args_defaults():
    from video2yt import topic_cli
    args = topic_cli.parse_args([])
    assert args.days == 7
    assert args.whitelist == Path("assets/topic/streamers.txt")
    assert args.done_topics == Path("assets/topic/done_topics.txt")
    assert args.output_root == Path("output")
    assert args.report is None


def test_topic_cli_parse_args_overrides():
    from video2yt import topic_cli
    args = topic_cli.parse_args([
        "--days", "14", "--whitelist", "/tmp/s.txt",
        "--report", "/tmp/r.md", "--min-duration", "300",
    ])
    assert args.days == 14
    assert args.whitelist == Path("/tmp/s.txt")
    assert args.report == Path("/tmp/r.md")
    assert args.min_duration == 300


def test_topic_cli_run_invokes_run_topic_with_parsed_args(tmp_path, monkeypatch):
    from video2yt import topic, topic_cli
    streamers_file = tmp_path / "s.txt"
    streamers_file.write_text("郭枫 1\n", encoding="utf-8")
    captured: dict = {}
    def fake_run_topic(**kw):
        captured.update(kw)
        return kw["report_path"]
    monkeypatch.setattr(topic, "run_topic", fake_run_topic)
    monkeypatch.setattr(topic, "load_credential_from_browser", lambda b: f"CRED:{b}")
    args = topic_cli.parse_args([
        "--whitelist", str(streamers_file),
        "--report", str(tmp_path / "r.md"),
        "--days", "3",
    ])
    out = topic_cli.run(args)
    assert out == tmp_path / "r.md"
    assert captured["days"] == 3
    assert captured["report_path"] == tmp_path / "r.md"
    assert len(captured["streamers"]) == 1
    assert captured["credential"] == "CRED:chrome"


def test_topic_cli_run_skips_credential_when_browser_empty(tmp_path, monkeypatch):
    from video2yt import topic, topic_cli
    streamers_file = tmp_path / "s.txt"
    streamers_file.write_text("郭枫 1\n", encoding="utf-8")
    captured: dict = {}
    monkeypatch.setattr(topic, "run_topic", lambda **kw: captured.update(kw) or kw["report_path"])
    def boom(b):
        raise AssertionError("should not be called when --cookies-from-browser=''")
    monkeypatch.setattr(topic, "load_credential_from_browser", boom)
    args = topic_cli.parse_args([
        "--whitelist", str(streamers_file),
        "--report", str(tmp_path / "r.md"),
        "--cookies-from-browser", "",
    ])
    topic_cli.run(args)
    assert captured["credential"] is None


def test_topic_cli_run_default_report_path_uses_today(tmp_path, monkeypatch):
    from video2yt import topic, topic_cli
    streamers_file = tmp_path / "s.txt"
    streamers_file.write_text("郭枫 1\n", encoding="utf-8")
    captured: dict = {}
    monkeypatch.setattr(topic, "run_topic", lambda **kw: captured.update(kw) or kw["report_path"])
    monkeypatch.setattr(topic, "load_credential_from_browser", lambda b: None)
    args = topic_cli.parse_args(["--whitelist", str(streamers_file)])
    topic_cli.run(args)
    assert captured["report_path"].parent == Path("output") / "topics"
    assert captured["report_path"].suffix == ".md"


def test_topic_cli_main_returns_1_on_missing_whitelist(tmp_path):
    from video2yt import topic_cli
    rc = topic_cli.main(["--whitelist", str(tmp_path / "missing.txt")])
    assert rc == 1


def test_topic_load_credential_wraps_yt_dlp_exception(monkeypatch):
    """yt_dlp can raise a wide range of exception types (browser missing,
    keyring failure, locked cookie DB, unsupported browser). They must NOT
    bubble out — they must surface as a RuntimeError that main() can catch."""
    from video2yt import topic
    class WeirdYtDlpError(Exception):
        pass
    def boom(browser):
        raise WeirdYtDlpError("simulated keyring blowup")
    monkeypatch.setattr("yt_dlp.cookies.extract_cookies_from_browser", boom)
    with pytest.raises(RuntimeError, match="could not load cookies"):
        topic.load_credential_from_browser("chrome")


def test_topic_cli_main_returns_1_when_browser_cookies_blow_up(tmp_path, monkeypatch):
    """Default `--cookies-from-browser chrome` must not produce a stack trace
    when the user has no Chrome / no Bilibili login / locked DB."""
    from video2yt import topic_cli
    streamers_file = tmp_path / "s.txt"
    streamers_file.write_text("郭枫 1\n", encoding="utf-8")
    class WeirdYtDlpError(Exception):
        pass
    def boom(browser):
        raise WeirdYtDlpError("no chrome installed")
    monkeypatch.setattr("yt_dlp.cookies.extract_cookies_from_browser", boom)
    rc = topic_cli.main(["--whitelist", str(streamers_file)])
    assert rc == 1


def test_topic_cli_main_returns_0_on_success(tmp_path, monkeypatch):
    from video2yt import topic, topic_cli
    streamers_file = tmp_path / "s.txt"
    streamers_file.write_text("郭枫 1\n", encoding="utf-8")
    monkeypatch.setattr(topic, "run_topic", lambda **kw: kw["report_path"])
    monkeypatch.setattr(topic, "load_credential_from_browser", lambda b: None)
    rc = topic_cli.main([
        "--whitelist", str(streamers_file),
        "--report", str(tmp_path / "r.md"),
    ])
    assert rc == 0
