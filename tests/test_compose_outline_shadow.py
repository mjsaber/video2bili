"""Tests for srt_to_ass outline_px/shadow_px parameters added for video2yt-subtitle."""

from video2yt.compose import srt_to_ass

SAMPLE_SRT = """1
00:00:00,000 --> 00:00:02,000
你好世界
"""


def test_default_outline_and_shadow_match_existing_behavior():
    """Default behavior unchanged: outline=2, shadow=0 in the ASS style line."""
    ass = srt_to_ass(SAMPLE_SRT, 1920, 1080, "Hiragino Sans GB", 42, position="bottom")
    # ASS style format: ...BorderStyle,Outline,Shadow,Alignment,...
    # Existing values were "1,2,0,{alignment}" — keep that as the default.
    assert "1,2,0,2," in ass     # BorderStyle=1, Outline=2, Shadow=0, Alignment=2 (bottom)


def test_outline_px_propagates_to_ass_style():
    ass = srt_to_ass(
        SAMPLE_SRT, 1920, 1080, "Hiragino Sans GB", 42,
        position="bottom", outline_px=4, shadow_px=2,
    )
    assert "1,4,2,2," in ass     # BorderStyle=1, Outline=4, Shadow=2, Alignment=2


def test_intro_call_signature_unchanged():
    """Existing intro path (no outline/shadow kwargs) must still work."""
    ass = srt_to_ass(SAMPLE_SRT, 1920, 1080, "Hiragino Sans GB", 42)
    # Default position="center" → Alignment=5
    assert "1,2,0,5," in ass
