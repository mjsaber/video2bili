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
