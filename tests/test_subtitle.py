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
