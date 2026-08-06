"""Focused tests for structured YouTube upload metadata validation."""

import pytest

from video2yt import upload


def valid_meta() -> dict:
    return {
        "video_path": "video.mp4",
        "thumbnail_path": "thumbnail.png",
        "title": "title",
        "description": "description",
        "tags": [],
        "category_id": "20",
        "default_language": "zh-Hant",
        "default_audio_language": "zh-Hant",
        "privacy_status": "public",
        "expected_channel_id": "channel",
        "season": 14,
    }


def test_validate_meta_accepts_positive_integer_season():
    upload.validate_meta(valid_meta())


def test_validate_meta_requires_season():
    meta = valid_meta()
    del meta["season"]

    with pytest.raises(ValueError, match="season"):
        upload.validate_meta(meta)


@pytest.mark.parametrize("season", [True, False, 0, -1, "14", 14.0, None])
def test_validate_meta_rejects_invalid_season(season):
    meta = valid_meta()
    meta["season"] = season

    with pytest.raises(ValueError, match="positive integer"):
        upload.validate_meta(meta)
