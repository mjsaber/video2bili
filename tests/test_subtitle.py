"""Unit tests for video2yt-subtitle. All subprocess boundaries are mocked."""

from pathlib import Path

import pytest

from video2yt import subtitle


def test_constants_exist():
    assert subtitle.BILIBILI_FIXED_DANMAKU_SECONDS == 5.0
    assert subtitle.HARD_FLOOR_SECONDS == 0.8
    assert subtitle.CLEANUP_TIMEOUT_SECONDS == 30
    assert subtitle.SENTENCE_PUNCT == "。！？"
    assert subtitle.CLAUSE_PUNCT == "；，、"


def test_packaged_glossary_yaml_exists_and_parses():
    """The default glossary ships inside the package and can be located."""
    import importlib.resources
    files = importlib.resources.files("video2yt.data")
    glossary_path = files / "bg_glossary.yaml"
    assert glossary_path.is_file()
    import yaml
    data = yaml.safe_load(glossary_path.read_text(encoding="utf-8"))
    assert "corrections" in data
    assert "canonical" in data
    assert isinstance(data["corrections"], dict)
    assert isinstance(data["canonical"], list)


def test_load_glossary_default():
    """Calling load_glossary with no path loads the packaged yaml."""
    g = subtitle.load_glossary(None)
    assert isinstance(g, subtitle.Glossary)
    assert g.corrections.get("戰旗") == "戰棋"
    assert "酒館" in g.canonical


def test_load_glossary_custom_path(tmp_path: Path):
    p = tmp_path / "my.yaml"
    p.write_text(
        "corrections:\n  foo: bar\ncanonical:\n  - baz\n",
        encoding="utf-8",
    )
    g = subtitle.load_glossary(p)
    assert g.corrections == {"foo": "bar"}
    assert g.canonical == ["baz"]


def test_load_glossary_missing_file_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        subtitle.load_glossary(tmp_path / "nope.yaml")


def test_load_glossary_malformed_yaml_raises(tmp_path: Path):
    p = tmp_path / "bad.yaml"
    p.write_text("corrections: [this is a list not a dict]\n", encoding="utf-8")
    with pytest.raises(ValueError):
        subtitle.load_glossary(p)


DANMAKU_XML_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<i>
{entries}
</i>
"""


def _make_danmaku(entries: list[tuple[float, int]]) -> str:
    """Build a minimal danmaku XML from (start_seconds, type) tuples."""
    lines = []
    for start, dtype in entries:
        # p format: time,type,size,color,timestamp,pool,userid,id
        p = f"{start:.2f},{dtype},25,16777215,1700000000,0,abc,1"
        lines.append(f'  <d p="{p}">text</d>')
    return DANMAKU_XML_TEMPLATE.format(entries="\n".join(lines))


def test_scan_danmaku_ignores_rolling(tmp_path):
    xml = tmp_path / "d.xml"
    xml.write_text(_make_danmaku([(1.0, 1), (5.0, 1)]), encoding="utf-8")
    sig = subtitle.scan_danmaku(xml, segment_duration=100.0)
    assert sig.fixed_count == 0
    assert sig.coverage_seconds == 0.0


def test_scan_danmaku_counts_only_type_4(tmp_path):
    xml = tmp_path / "d.xml"
    xml.write_text(
        _make_danmaku([(1.0, 4), (10.0, 5), (20.0, 1), (30.0, 4)]),
        encoding="utf-8",
    )
    sig = subtitle.scan_danmaku(xml, segment_duration=100.0)
    assert sig.fixed_count == 2


def test_scan_danmaku_overlap_union(tmp_path):
    """Two type=4 at t=10 and t=12 → union [10,15] ∪ [12,17] = [10,17] = 7s."""
    xml = tmp_path / "d.xml"
    xml.write_text(_make_danmaku([(10.0, 4), (12.0, 4)]), encoding="utf-8")
    sig = subtitle.scan_danmaku(xml, segment_duration=100.0)
    assert sig.fixed_count == 2
    assert abs(sig.coverage_seconds - 7.0) < 0.01


def test_scan_danmaku_disjoint_intervals(tmp_path):
    """Two type=4 at t=10 and t=100 → two disjoint 5s windows = 10s total."""
    xml = tmp_path / "d.xml"
    xml.write_text(_make_danmaku([(10.0, 4), (100.0, 4)]), encoding="utf-8")
    sig = subtitle.scan_danmaku(xml, segment_duration=200.0)
    assert abs(sig.coverage_seconds - 10.0) < 0.01


def test_scan_danmaku_clipped_to_segment_end(tmp_path):
    """type=4 at t=98 with segment_duration=100 → clipped to [98,100] = 2s."""
    xml = tmp_path / "d.xml"
    xml.write_text(_make_danmaku([(98.0, 4)]), encoding="utf-8")
    sig = subtitle.scan_danmaku(xml, segment_duration=100.0)
    assert abs(sig.coverage_seconds - 2.0) < 0.01


def test_scan_danmaku_threshold_pass(tmp_path):
    """10 type=4 entries spread 0-50s, 5s each (mostly overlapping in clusters)."""
    xml = tmp_path / "d.xml"
    entries = [(t, 4) for t in range(0, 60, 6)]  # 10 entries at 0,6,12,...,54
    xml.write_text(_make_danmaku(entries), encoding="utf-8")
    sig = subtitle.scan_danmaku(
        xml, segment_duration=100.0,
        min_fixed=10, min_coverage_ratio=0.30,
    )
    assert sig.fixed_count == 10
    # Coverage: ~50s of windows, with some 1s overlap at each boundary → ≈40-50s of 100s
    assert sig.hit is True


def test_scan_danmaku_threshold_fail_count(tmp_path):
    """9 type=4 entries → fixed_count below threshold even if coverage is high."""
    xml = tmp_path / "d.xml"
    entries = [(t, 4) for t in range(0, 45, 5)]  # 9 entries at 0,5,...,40
    xml.write_text(_make_danmaku(entries), encoding="utf-8")
    sig = subtitle.scan_danmaku(
        xml, segment_duration=100.0,
        min_fixed=10, min_coverage_ratio=0.30,
    )
    assert sig.fixed_count == 9
    assert sig.hit is False


def test_scan_danmaku_corrupted_xml_raises(tmp_path):
    xml = tmp_path / "d.xml"
    xml.write_text("<i><d p='no commas here'>text</d></i>", encoding="utf-8")
    with pytest.raises(ValueError):
        subtitle.scan_danmaku(xml, segment_duration=100.0)


def _dummy_danmaku(hit: bool, fixed: int = 0, cov: float = 0.0) -> subtitle.DanmakuSignal:
    return subtitle.DanmakuSignal(
        fixed_count=fixed,
        coverage_seconds=cov,
        coverage_ratio=cov / 100.0,
        hit=hit,
    )


def _dummy_ocr(hit: bool, sampled: int = 10, stable: int = 0) -> subtitle.OcrSignal:
    return subtitle.OcrSignal(
        sampled_frames=sampled,
        frames_with_stable_text=stable,
        stable_text_ratio=stable / max(sampled, 1),
        hit=hit,
    )


def test_decide_force_add_short_circuits():
    d = subtitle.decide(
        force="add",
        danmaku=_dummy_danmaku(hit=True),
        ocr=_dummy_ocr(hit=True),
    )
    assert d.add_subtitles is True
    assert "force" in d.reason.lower()


def test_decide_force_skip_short_circuits():
    d = subtitle.decide(
        force="skip",
        danmaku=_dummy_danmaku(hit=False),
        ocr=_dummy_ocr(hit=False),
    )
    assert d.add_subtitles is False
    assert "force" in d.reason.lower()


def test_decide_danmaku_hit_overrides_ocr_miss():
    d = subtitle.decide(
        force=None,
        danmaku=_dummy_danmaku(hit=True, fixed=20, cov=40.0),
        ocr=_dummy_ocr(hit=False),
    )
    assert d.add_subtitles is False
    assert "danmaku" in d.reason.lower()


def test_decide_ocr_hit_when_danmaku_miss():
    d = subtitle.decide(
        force=None,
        danmaku=_dummy_danmaku(hit=False, fixed=2, cov=1.5),
        ocr=_dummy_ocr(hit=True, sampled=20, stable=12),
    )
    assert d.add_subtitles is False
    assert "ocr" in d.reason.lower()


def test_decide_both_miss_returns_add():
    d = subtitle.decide(
        force=None,
        danmaku=_dummy_danmaku(hit=False),
        ocr=_dummy_ocr(hit=False),
    )
    assert d.add_subtitles is True


def test_decide_no_danmaku_signal_uses_ocr_only():
    d = subtitle.decide(force=None, danmaku=None, ocr=_dummy_ocr(hit=True))
    assert d.add_subtitles is False


def test_decide_no_ocr_signal_uses_danmaku_only():
    d = subtitle.decide(force=None, danmaku=_dummy_danmaku(hit=False), ocr=None)
    assert d.add_subtitles is True


def test_decide_invalid_force_raises():
    with pytest.raises(ValueError):
        subtitle.decide(force="bogus", danmaku=None, ocr=None)


from unittest.mock import MagicMock, patch


@patch("video2yt.subtitle._extract_frames")
@patch("video2yt.subtitle._run_rapidocr")
def test_sample_ocr_no_text_detected(mock_ocr, mock_extract):
    """All sampled frames return no OCR boxes → stable_text_ratio=0, hit=False."""
    mock_extract.return_value = [b"frame0_bytes"] * 10
    mock_ocr.return_value = []   # no boxes detected
    sig = subtitle.sample_ocr(
        Path("seg.mp4"), segment_duration=50.0, interval_seconds=5.0,
        min_stable_ratio=0.30,
    )
    assert sig.sampled_frames == 10
    assert sig.frames_with_stable_text == 0
    assert sig.hit is False


@patch("video2yt.subtitle._extract_frames")
@patch("video2yt.subtitle._run_rapidocr")
def test_sample_ocr_stable_cluster_triggers_hit(mock_ocr, mock_extract):
    """6 of 10 frames have a text box in the same y-position cluster → ratio=0.6 → hit."""
    mock_extract.return_value = [b"f"] * 10
    # Each call returns either [] or a box at y≈950 in the bottom band.
    # Frames 0-5 (6 frames) have a stable box at y=950; frames 6-9 have nothing.
    box_at_y950 = [(((100, 950), (300, 950), (300, 990), (100, 990)), "字幕", 0.9)]
    mock_ocr.side_effect = [box_at_y950] * 6 + [[]] * 4
    sig = subtitle.sample_ocr(
        Path("seg.mp4"), segment_duration=50.0, interval_seconds=5.0,
        min_stable_ratio=0.30,
    )
    assert sig.sampled_frames == 10
    assert sig.frames_with_stable_text == 6
    assert abs(sig.stable_text_ratio - 0.6) < 0.01
    assert sig.hit is True


@patch("video2yt.subtitle._extract_frames")
@patch("video2yt.subtitle._run_rapidocr")
def test_sample_ocr_drifting_boxes_not_stable(mock_ocr, mock_extract):
    """Boxes detected but at different y-positions per frame (e.g. floating danmaku)
    do NOT cluster as a stable subtitle position → ratio low → no hit."""
    mock_extract.return_value = [b"f"] * 10
    # Each frame has a box at a different y position (drifting downward)
    def box_at(y: int) -> list:
        return [(((100, y), (300, y), (300, y + 30), (100, y + 30)), "弹幕", 0.9)]
    mock_ocr.side_effect = [box_at(900 + i * 30) for i in range(10)]
    sig = subtitle.sample_ocr(
        Path("seg.mp4"), segment_duration=50.0, interval_seconds=5.0,
        min_stable_ratio=0.30,
    )
    # Each box is in a unique y-cluster of size 1 → no cluster has ≥30% support
    assert sig.frames_with_stable_text < 3
    assert sig.hit is False


@patch("video2yt.subtitle._extract_frames")
def test_sample_ocr_fails_open_on_extract_error(mock_extract):
    """ffmpeg failure → fall back to no-detection (fail-open), not raise. Spec §7."""
    mock_extract.side_effect = RuntimeError("ffmpeg crashed")
    sig = subtitle.sample_ocr(
        Path("seg.mp4"), segment_duration=50.0, interval_seconds=5.0,
        min_stable_ratio=0.30,
    )
    assert sig.sampled_frames == 0
    assert sig.hit is False


@patch("video2yt.subtitle._extract_wav")
@patch("video2yt.subtitle._run_funasr")
def test_transcribe_returns_funasr_segments(mock_funasr, mock_extract, tmp_path):
    mock_extract.return_value = tmp_path / "audio.wav"
    mock_funasr.return_value = [
        (0.0, 2.5, "你好"),
        (2.5, 5.0, "世界"),
    ]
    result = subtitle.transcribe(Path("seg.mp4"))
    assert result == [
        subtitle.FunASRSegment(0.0, 2.5, "你好"),
        subtitle.FunASRSegment(2.5, 5.0, "世界"),
    ]


@patch("video2yt.subtitle._extract_wav")
@patch("video2yt.subtitle._run_funasr")
def test_transcribe_strips_whitespace(mock_funasr, mock_extract, tmp_path):
    mock_extract.return_value = tmp_path / "audio.wav"
    mock_funasr.return_value = [(0.0, 2.0, "  你好  ")]
    result = subtitle.transcribe(Path("seg.mp4"))
    assert result[0].text == "你好"


def test_segments_to_srt_roundtrip():
    segs = [
        subtitle.FunASRSegment(0.0, 2.5, "你好"),
        subtitle.FunASRSegment(2.5, 5.0, "世界，再見。"),
    ]
    srt = subtitle.segments_to_srt(segs)
    assert "1\n00:00:00,000 --> 00:00:02,500" in srt
    assert "你好" in srt
    assert "00:00:02,500 --> 00:00:05,000" in srt
    parsed = subtitle.parse_srt_to_segments(srt)
    assert parsed == segs


def test_segments_to_srt_handles_fractional_seconds():
    segs = [subtitle.FunASRSegment(1.234, 5.678, "abc")]
    srt = subtitle.segments_to_srt(segs)
    assert "00:00:01,234 --> 00:00:05,678" in srt


def test_parse_srt_skips_empty_blocks():
    srt = "1\n00:00:00,000 --> 00:00:01,000\nfoo\n\n\n2\n00:00:01,000 --> 00:00:02,000\nbar\n"
    parsed = subtitle.parse_srt_to_segments(srt)
    assert len(parsed) == 2
    assert parsed[0].text == "foo"
    assert parsed[1].text == "bar"
