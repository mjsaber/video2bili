"""Unit tests for video2yt-subtitle. All subprocess boundaries are mocked."""

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
