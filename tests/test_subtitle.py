"""Unit tests for video2yt-subtitle. All subprocess boundaries are mocked."""

import logging
import subprocess
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


@patch("video2yt.subtitle._invoke_codex")
def test_cleanup_happy_path_replaces_text(mock_codex):
    segs = [
        subtitle.FunASRSegment(0.0, 2.0, "戰旗很有趣"),
        subtitle.FunASRSegment(2.0, 5.0, "拉法母真的強"),
    ]
    glossary = subtitle.Glossary(
        corrections={"戰旗": "戰棋", "拉法母": "拉法姆"},
        canonical=[],
    )
    mock_codex.return_value = "戰棋很有趣\n拉法姆真的強\n"
    out = subtitle.cleanup_with_codex(segs, glossary)
    assert out[0].text == "戰棋很有趣"
    assert out[1].text == "拉法姆真的強"
    # Timestamps preserved exactly
    assert out[0].start == 0.0 and out[0].end == 2.0
    assert out[1].start == 2.0 and out[1].end == 5.0


@patch("video2yt.subtitle._invoke_codex")
def test_cleanup_line_count_mismatch_falls_back(mock_codex, caplog):
    """Codex returns the wrong number of lines → return raw + WARNING."""
    segs = [
        subtitle.FunASRSegment(0.0, 2.0, "abc"),
        subtitle.FunASRSegment(2.0, 4.0, "def"),
    ]
    glossary = subtitle.Glossary({}, [])
    mock_codex.return_value = "abc\n"   # only 1 line, expected 2
    with caplog.at_level(logging.WARNING):
        out = subtitle.cleanup_with_codex(segs, glossary)
    assert out == segs
    assert any("line count" in r.message.lower() for r in caplog.records)


@patch("video2yt.subtitle._invoke_codex")
def test_cleanup_length_blown_per_line_falls_back(mock_codex, caplog):
    """One line's length ratio is outside [0.8, 1.2] → fall back, WARN."""
    segs = [
        subtitle.FunASRSegment(0.0, 2.0, "短"),    # 1 char
        subtitle.FunASRSegment(2.0, 4.0, "也短"),  # 2 chars
    ]
    glossary = subtitle.Glossary({}, [])
    # Line 2 expanded from 2 chars to 10 chars → ratio 5.0, way over 1.2
    mock_codex.return_value = "短\n這是個被改寫太多的句子\n"
    with caplog.at_level(logging.WARNING):
        out = subtitle.cleanup_with_codex(segs, glossary)
    assert out == segs
    assert any("length" in r.message.lower() for r in caplog.records)


@patch("video2yt.subtitle._invoke_codex")
def test_cleanup_codex_timeout_falls_back(mock_codex, caplog):
    segs = [subtitle.FunASRSegment(0.0, 2.0, "abc")]
    mock_codex.side_effect = subprocess.TimeoutExpired(cmd="codex", timeout=30)
    with caplog.at_level(logging.WARNING):
        out = subtitle.cleanup_with_codex(segs, subtitle.Glossary({}, []))
    assert out == segs
    assert any("timeout" in r.message.lower() for r in caplog.records)


@patch("video2yt.subtitle._invoke_codex")
def test_cleanup_boundary_length_ratio_accepted(mock_codex):
    """Length ratio of exactly 0.8 / 1.2 is accepted (closed boundary)."""
    segs = [subtitle.FunASRSegment(0.0, 1.0, "abcde")]   # 5 effective chars (ASCII counts as 0.5 each → 2.5)
    glossary = subtitle.Glossary({}, [])
    # Replacement with same effective char count is trivially in-range
    mock_codex.return_value = "abcde\n"
    out = subtitle.cleanup_with_codex(segs, glossary)
    assert out[0].text == "abcde"


# ---- Task 10: split_segments ----

def test_split_char_ok_segment_unchanged():
    """15 chars under MAX=30 -> single entry, identical timing."""
    seg = subtitle.FunASRSegment(0.0, 3.0, "短短的一句話只有幾個字")
    out = subtitle.split_segments([seg], max_line_chars=30)
    assert len(out) == 1
    assert out[0].start == 0.0 and out[0].end == 3.0
    assert out[0].text == seg.text


def test_split_long_duration_short_text_not_split():
    """25 chars / 9 seconds / no punctuation -> kept as ONE entry (rule §5.1 C)."""
    seg = subtitle.FunASRSegment(0.0, 9.0, "二十五個字大概就是這樣長的一句話可以讀完")
    out = subtitle.split_segments([seg], max_line_chars=30)
    assert len(out) == 1
    assert out[0].end == 9.0


def test_split_sentence_punctuation():
    """45 chars with 。in middle -> Pass 1 useful split."""
    text = "前半段大概有二十多個字。後半段也有差不多二十多個字。"
    seg = subtitle.FunASRSegment(0.0, 6.0, text)
    out = subtitle.split_segments([seg], max_line_chars=20)
    assert len(out) >= 2
    assert "前半段" in out[0].text
    assert out[-1].end == 6.0


def test_split_clause_only():
    """No 。 but has ，-> Pass 2 used."""
    text = "前半段大概有二十多個字，後半段也有差不多二十多個字"
    seg = subtitle.FunASRSegment(0.0, 6.0, text)
    out = subtitle.split_segments([seg], max_line_chars=20)
    assert len(out) >= 2


def test_split_no_punctuation_uses_midpoint():
    """40+ chars with zero punctuation -> Pass 3 midpoint."""
    text = "一" * 40
    seg = subtitle.FunASRSegment(0.0, 4.0, text)
    out = subtitle.split_segments([seg], max_line_chars=10)
    assert len(out) >= 4
    assert all(len(e.text) <= 10 for e in out)
    assert out[0].start == 0.0
    assert out[-1].end == 4.0


def test_split_termination_edge_punctuation_only_at_end():
    """Was the infinite-recursion bug: '一'*99 + '。' must split via Pass 3, not loop."""
    text = "一" * 99 + "。"
    seg = subtitle.FunASRSegment(0.0, 10.0, text)
    out = subtitle.split_segments([seg], max_line_chars=30)
    assert len(out) >= 4
    assert all(len(e.text) <= 30 for e in out)


def test_split_punctuation_only_at_start():
    text = "。" + "一" * 99
    seg = subtitle.FunASRSegment(0.0, 10.0, text)
    out = subtitle.split_segments([seg], max_line_chars=30)
    # Useful Pass 1 split: ["。", "一"*99]; the long piece then recurses to Pass 3
    assert len(out) >= 4


def test_split_proportional_time_allocation():
    """Pieces weighted by effective-char counts inside (0.0, 10.0)."""
    text = "AAAA。BBB。CCC"
    seg = subtitle.FunASRSegment(0.0, 10.0, text)
    out = subtitle.split_segments([seg], max_line_chars=2)
    assert out[0].start == 0.0
    assert out[-1].end == 10.0


def test_split_hard_floor_extends_short_pieces():
    """Pieces shorter than 0.8s get extended; cascade pushes forward, no overlap."""
    text = "一二三四五。六七八九十。"
    seg = subtitle.FunASRSegment(0.0, 1.0, text)
    out = subtitle.split_segments([seg], max_line_chars=4)
    for prev, curr in zip(out, out[1:]):
        assert curr.start >= prev.end - 1e-6


def test_apply_hard_floor_cascade_exceeds_budget_no_invalid_ranges():
    """When cascade would push downstream entries past their ends, the
    result must still have valid time ranges (start <= end) and no overlaps."""
    entries = [
        subtitle.SrtEntry(0.0, 0.333, "a"),
        subtitle.SrtEntry(0.333, 0.667, "b"),
        subtitle.SrtEntry(0.667, 1.0, "c"),
    ]
    out = subtitle._apply_hard_floor(entries)
    # Hard rule 1: no invalid ranges
    for e in out:
        assert e.start <= e.end, f"invalid range: {e}"
    # Hard rule 2: no overlaps
    for prev, curr in zip(out, out[1:]):
        assert curr.start >= prev.end, f"overlap: {prev} -> {curr}"
    # Hard rule 3: no overrun
    assert out[-1].end <= 1.0 + 1e-9


def test_split_hard_floor_cascade_does_not_bleed_into_next_segment():
    """Cascade overflow from one FunASR segment must not push subsequent
    segments' entries past their natural start. Spec §5.1 C — the cap
    is per-segment, not per-overall-video."""
    segs = [
        subtitle.FunASRSegment(0.0, 1.0, "一二三。四五六。七八九。"),  # 3 short pieces
        subtitle.FunASRSegment(1.0, 10.0, "下一段的字幕內容"),         # natural start at 1.0
    ]
    out = subtitle.split_segments(segs, max_line_chars=4)
    # The entry corresponding to the second FunASR segment must start AT or AFTER 1.0
    # (not pushed forward by the first segment's cascade).
    # Find entries whose text is from segment 2:
    seg2_entries = [e for e in out if "下一段" in e.text or "字幕內容" in e.text]
    assert seg2_entries, "expected seg2 entries to survive splitting"
    assert seg2_entries[0].start <= 1.0 + 1e-6, (
        f"seg2's first entry got pushed past natural start: {seg2_entries[0]}"
    )
    # And no entry from seg1 should end past 1.0 (the seg1 boundary)
    seg1_entries = [e for e in out if e not in seg2_entries]
    for e in seg1_entries:
        assert e.end <= 1.0 + 1e-6, (
            f"seg1 entry bled past seg1.end=1.0: {e}"
        )


def test_split_threshold_is_strict_greater_than():
    """Exactly MAX_LINE_CHARS chars -> no split."""
    text = "一" * 30
    seg = subtitle.FunASRSegment(0.0, 3.0, text)
    out = subtitle.split_segments([seg], max_line_chars=30)
    assert len(out) == 1


@patch("subprocess.run")
def test_burn_constructs_ffmpeg_command_with_basename(mock_run, tmp_path):
    """ffmpeg subprocess uses cwd=temp_dir and an ASS basename, not absolute path
    (same path-escape avoidance as burn.py)."""
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
    input_mp4 = tmp_path / "seg.mp4"
    input_mp4.write_bytes(b"fake")
    output_mp4 = tmp_path / "seg_subbed.mp4"
    entries = [subtitle.SrtEntry(0.0, 2.0, "你好")]
    subtitle.burn_subtitles(
        input_mp4, entries, output_mp4,
        font_face="Hiragino Sans GB", font_size=42,
        outline_px=4, shadow_px=2,
        video_width=1920, video_height=1080,
    )
    assert mock_run.called
    call_args = mock_run.call_args
    cmd = call_args.kwargs.get("args") or call_args.args[0]
    cwd = call_args.kwargs.get("cwd")
    # ASS path referenced by basename via subtitles=f='<name>'
    assert any("subtitles=f='" in arg for arg in cmd)
    # Filter does NOT contain the full path of the ASS
    assert not any(str(tmp_path) in arg and ".ass" in arg for arg in cmd)
    # cwd is set
    assert cwd is not None


@patch("subprocess.run")
def test_burn_passes_outline_shadow_via_compose(mock_run, tmp_path):
    """The ASS written to disk has BorderStyle=1, Outline=4, Shadow=2 in style."""
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
    input_mp4 = tmp_path / "seg.mp4"
    input_mp4.write_bytes(b"fake")
    output_mp4 = tmp_path / "seg_subbed.mp4"
    entries = [subtitle.SrtEntry(0.0, 2.0, "你好")]
    subtitle.burn_subtitles(
        input_mp4, entries, output_mp4,
        font_face="Hiragino Sans GB", font_size=42,
        outline_px=4, shadow_px=2,
        video_width=1920, video_height=1080,
    )
    # The temp ASS file gets created beside the input (subtitle.py uses input.parent)
    ass_files = list(input_mp4.parent.glob("*.ass"))
    assert ass_files, "expected an ASS file to be written next to the input"
    ass_text = ass_files[0].read_text(encoding="utf-8")
    assert "1,4,2,2," in ass_text   # BorderStyle=1, Outline=4, Shadow=2, Alignment=2


@patch("subprocess.run")
def test_burn_uses_audio_copy(mock_run, tmp_path):
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
    input_mp4 = tmp_path / "seg.mp4"
    input_mp4.write_bytes(b"fake")
    entries = [subtitle.SrtEntry(0.0, 2.0, "abc")]
    subtitle.burn_subtitles(
        input_mp4, entries, tmp_path / "out.mp4",
        font_face="x", font_size=42, outline_px=4, shadow_px=2,
        video_width=1920, video_height=1080,
    )
    cmd = mock_run.call_args.kwargs.get("args") or mock_run.call_args.args[0]
    assert "-c:a" in cmd
    assert cmd[cmd.index("-c:a") + 1] == "copy"


def test_passthrough_hardlinks_same_filesystem(tmp_path):
    src = tmp_path / "seg.mp4"
    src.write_bytes(b"hello")
    dst = tmp_path / "seg_subbed.mp4"
    subtitle.passthrough(src, dst)
    assert dst.exists()
    assert dst.read_bytes() == b"hello"
    # On the same filesystem, hardlink: same inode
    assert dst.stat().st_ino == src.stat().st_ino


@patch("video2yt.subtitle.os.link")
def test_passthrough_falls_back_to_copy_on_exdev(mock_link, tmp_path):
    mock_link.side_effect = OSError(18, "Cross-device link not permitted")
    src = tmp_path / "seg.mp4"
    src.write_bytes(b"data")
    dst = tmp_path / "out.mp4"
    subtitle.passthrough(src, dst)
    assert dst.exists()
    assert dst.read_bytes() == b"data"
    # Different inodes because it's a copy
    assert dst.stat().st_ino != src.stat().st_ino


def test_passthrough_overwrites_existing(tmp_path):
    src = tmp_path / "a.mp4"
    src.write_bytes(b"new")
    dst = tmp_path / "b.mp4"
    dst.write_bytes(b"old")
    subtitle.passthrough(src, dst)
    assert dst.read_bytes() == b"new"


from video2yt import subtitle_cli


def test_parse_args_mutex_force_flags_rejected():
    with pytest.raises(SystemExit):
        subtitle_cli.parse_args(["seg.mp4", "--force-add", "--force-skip"])


def test_parse_args_defaults():
    args = subtitle_cli.parse_args(["seg.mp4"])
    assert args.segment == Path("seg.mp4")
    assert args.danmaku is None
    assert args.glossary is None
    assert args.force is None
    assert args.enable_ocr is False
    assert args.ocr_interval == 5.0
    assert args.danmaku_min_fixed == 10
    assert args.danmaku_min_coverage == 30
    assert args.skip_cleanup is False
    assert args.font_face == "Hiragino Sans GB"
    assert args.outline_px == 4
    assert args.shadow_px == 2


def test_parse_args_enable_ocr():
    args = subtitle_cli.parse_args(["seg.mp4", "--enable-ocr"])
    assert args.enable_ocr is True


def test_parse_args_force_add():
    args = subtitle_cli.parse_args(["seg.mp4", "--force-add"])
    assert args.force == "add"


def test_parse_args_force_skip():
    args = subtitle_cli.parse_args(["seg.mp4", "--force-skip"])
    assert args.force == "skip"


def test_default_output_path_uses_subbed_suffix():
    args = subtitle_cli.parse_args(["/tmp/seg.mp4"])
    out = subtitle_cli._default_output(args.segment)
    assert out == Path("/tmp/seg_subbed.mp4")


@patch("video2yt.subtitle_cli.shutil.which")
def test_preflight_fails_when_ffmpeg_missing(mock_which):
    mock_which.return_value = None
    with pytest.raises(RuntimeError, match="ffmpeg"):
        subtitle_cli.preflight()


@patch("video2yt.subtitle_cli.shutil.which", return_value="/usr/bin/found")
@patch("builtins.__import__")
def test_preflight_fails_with_helpful_message_when_extras_missing(mock_import, mock_which):
    """When 'funasr' or 'rapidocr_onnxruntime' aren't installed, preflight says how to fix."""
    def fake_import(name, *args, **kwargs):
        if name in ("funasr", "rapidocr_onnxruntime"):
            raise ImportError(name)
        return __import__(name, *args, **kwargs)
    mock_import.side_effect = fake_import
    with pytest.raises(RuntimeError, match="subtitle.*extra"):
        subtitle_cli.preflight()
