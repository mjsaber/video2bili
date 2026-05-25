"""T10: opt-in integration smoke test that invokes the REAL ffmpeg
binary against burn.render's full single-pass graph (chained two-ASS +
sidechain-ducked amix + optional cuts/speed). All other tests mock
subprocess.run; this one is the only end-to-end ffmpeg check we have
for the chained-subtitles + amix combination.

Skipped unless ffmpeg+libass is on PATH (covers CI environments without
libass and developer machines that haven't run the brew-tap install).
Run manually with::

    uv run pytest tests/test_burn_real_ffmpeg.py -v

Spec: ``docs/superpowers/specs/2026-05-24-step6-restructure.md`` §11 Q4.
Owed since codex T1+ reviews verified the chained ASS form in isolation
but not the full graph under cuts+speed+swap.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from video2yt import burn


def _has_ffmpeg_with_libass() -> bool:
    """Probe `ffmpeg -filters` for the subtitles filter — the libass
    dependency surfaces here, and a `brew install ffmpeg` bottle without
    libass would silently lack the `subtitles` filter."""
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        return False
    try:
        result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-filters"],
            check=True, capture_output=True, text=True,
        )
    except (subprocess.CalledProcessError, OSError):
        return False
    return "subtitles" in result.stdout


pytestmark = pytest.mark.skipif(
    not _has_ffmpeg_with_libass(),
    reason="ffmpeg with libass not on PATH; T10 is an opt-in smoke test",
)


# ---------- fixtures ----------

@pytest.fixture
def tiny_video(tmp_path):
    """A 5-second 1920x1080 30fps h264 video with a silent stereo track."""
    out = tmp_path / "seg.mp4"
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        # 5s color bars (smptebars) at 1920x1080 30fps.
        "-f", "lavfi", "-i", "smptebars=size=1920x1080:rate=30:duration=5",
        # 5s silent stereo audio at 48kHz so the swap-off legacy branch
        # has SOMETHING to passthrough.
        "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
        "-shortest",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        str(out),
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    return out


@pytest.fixture
def tiny_ass(tmp_path):
    """A minimal valid ASS with one Dialogue line at 1-2s. Library users
    on top of this fixture inject the file under different basenames."""
    p = tmp_path / "danmaku.ass"
    p.write_text(
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        "PlayResX: 1920\n"
        "PlayResY: 1080\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, "
        "Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
        "MarginR, MarginV, Encoding\n"
        "Style: Default,Arial,40,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,"
        "0,0,0,0,100,100,0,0,1,2,2,2,10,10,30,1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        "Dialogue: 0,0:00:01.00,0:00:02.00,Default,,0,0,0,,real-ffmpeg-smoke\n",
        encoding="utf-8",
    )
    return p


@pytest.fixture
def tiny_speech_wav(tmp_path):
    """A 5s wav at 48kHz stereo so it matches the burn graph's
    aresample/aformat target."""
    out = tmp_path / "speech.wav"
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        # 5s sine tone at 440 Hz; just needs to be a valid wav with audio.
        "-f", "lavfi",
        "-i", "sine=frequency=440:duration=5:sample_rate=48000",
        "-ac", "2",
        "-c:a", "pcm_s16le",
        str(out),
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    return out


@pytest.fixture
def tiny_music_bed_wav(tmp_path):
    """A 5s wav at 48kHz stereo with a different tone (so the sidechain
    duck behaviour has something to act on)."""
    out = tmp_path / "bed.wav"
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi",
        "-i", "sine=frequency=220:duration=5:sample_rate=48000",
        "-ac", "2",
        "-c:a", "pcm_s16le",
        str(out),
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    return out


def _ffprobe(path: Path) -> dict:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-print_format", "json",
            "-show_format", "-show_streams",
            str(path),
        ],
        check=True, capture_output=True, text=True,
    )
    return json.loads(result.stdout)


# ---------- the smoke tests ----------

def test_real_ffmpeg_chained_two_ass_no_cuts_no_speed(
    tmp_path, tiny_video, tiny_ass, tiny_speech_wav, tiny_music_bed_wav,
):
    """The minimal real-ffmpeg smoke: two ASS layers chained, speech +
    bed amix, no cuts, speed=1.0. Asserts the output mp4 has h264 video
    + aac audio, both 5s, and yuv420p+30fps+48kHz for merge strict mode."""
    # The danmaku ASS is the tiny_ass fixture; make a second ASS (the
    # "cleaned subtitle") under the layout burn.render expects:
    # <bv>/speech.cleaned.ass (or anywhere; render handles the symlink).
    bv_dir = tmp_path / "seg"
    bv_dir.mkdir()
    cleaned_ass = bv_dir / "speech.cleaned.ass"
    cleaned_ass.write_text(
        "[Script Info]\nScriptType: v4.00+\nPlayResX: 1920\nPlayResY: 1080\n\n"
        "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        "Style: Default,Arial,18,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,"
        "0,0,0,0,100,100,0,0,1,2,0,2,80,80,15,1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        "Dialogue: 0,0:00:03.00,0:00:04.00,Default,,0,0,0,,cleaned-line\n",
        encoding="utf-8",
    )

    output = tmp_path / "out.mp4"
    burn.render(
        video_path=tiny_video,
        ass_path=tiny_ass,
        output_path=output,
        cleaned_ass=cleaned_ass,
        speech_wav=tiny_speech_wav,
        music_bed_wav=tiny_music_bed_wav,
        apply_subtitle=True,
        apply_music_swap=True,
    )

    assert output.exists()
    probe = _ffprobe(output)
    video_streams = [s for s in probe["streams"] if s["codec_type"] == "video"]
    audio_streams = [s for s in probe["streams"] if s["codec_type"] == "audio"]
    assert len(video_streams) == 1
    assert len(audio_streams) == 1
    v = video_streams[0]
    a = audio_streams[0]
    # Merge strict mode contract from §6 / T6:
    assert v["codec_name"] == "h264"
    assert v["pix_fmt"] == "yuv420p"
    assert v["width"] == 1920 and v["height"] == 1080
    # Frame rate: ffprobe reports it as a fraction like "30/1".
    assert v["r_frame_rate"] in ("30/1", "30000/1000")
    assert a["codec_name"] == "aac"
    assert int(a["sample_rate"]) == 48000
    # Duration: 5s ± 0.5s tolerance (encoder dance).
    duration = float(probe["format"]["duration"])
    assert 4.5 <= duration <= 5.5


def test_real_ffmpeg_cuts_and_speed_with_all_features(
    tmp_path, tiny_video, tiny_ass, tiny_speech_wav, tiny_music_bed_wav,
):
    """All features at once: cuts (single range — keeps middle 1s),
    speed=1.5, both ASS layers, music-swap. Verifies the full graph
    survives the most complex combination."""
    bv_dir = tmp_path / "seg"
    bv_dir.mkdir()
    cleaned_ass = bv_dir / "speech.cleaned.ass"
    cleaned_ass.write_text(
        "[Script Info]\nScriptType: v4.00+\nPlayResX: 1920\nPlayResY: 1080\n\n"
        "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour\n"
        "Style: Default,Arial,18,&H00FFFFFF\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        "Dialogue: 0,0:00:02.00,0:00:03.00,Default,,0,0,0,,middle\n",
        encoding="utf-8",
    )

    output = tmp_path / "out_complex.mp4"
    # Source is 5s. Cut 0-2s and 3-5s; keep just [2,3] = 1s. At speed 1.5,
    # output should be ~1/1.5 = 0.67s.
    burn.render(
        video_path=tiny_video,
        ass_path=tiny_ass,
        output_path=output,
        cleaned_ass=cleaned_ass,
        speech_wav=tiny_speech_wav,
        music_bed_wav=tiny_music_bed_wav,
        apply_subtitle=True,
        apply_music_swap=True,
        keep_ranges=[(2.0, 3.0)],
        cut_ranges=[(0.0, 2.0), (3.0, 5.0)],
        speed=1.5,
    )

    assert output.exists()
    probe = _ffprobe(output)
    duration = float(probe["format"]["duration"])
    # 1s of kept content at 1.5x = ~0.67s ± 0.4s tolerance for short clips.
    assert 0.3 <= duration <= 1.1, f"output duration {duration}s outside band"


def test_real_ffmpeg_legacy_simple_path_still_works(
    tmp_path, tiny_video, tiny_ass,
):
    """The legacy simple path (no cuts/speed/cleaned/swap) routes through
    -vf subtitles= -c:a copy. T6 preserved this branch."""
    output = tmp_path / "out_simple.mp4"
    burn.render(
        video_path=tiny_video,
        ass_path=tiny_ass,
        output_path=output,
    )
    assert output.exists()
    probe = _ffprobe(output)
    # Simple path keeps the source aac copy (no re-encode), so duration
    # matches source within encoder slop.
    duration = float(probe["format"]["duration"])
    assert 4.5 <= duration <= 5.5
