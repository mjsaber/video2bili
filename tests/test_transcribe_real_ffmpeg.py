"""Opt-in integration test for transcribe.detect_speech_span against the
REAL ffmpeg/ffprobe binaries. All other transcribe tests mock the
subprocess boundary; this is the only end-to-end check of silencedetect
parsing + ffprobe duration on real files.

Skipped unless ffmpeg AND ffprobe are on PATH. Run manually with::

    uv run --extra dev pytest tests/test_transcribe_real_ffmpeg.py -v

Spec: ``docs/superpowers/specs/2026-07-04-transcribe-ffmpeg-span.md``
(test plan item 6: mono fixture, stereo one-silent-channel fixture, VBR
MP3 re-encode).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from video2yt import transcribe

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe not on PATH",
)

# Fixture shape: 0.8s silence + 3.0s tone + 1.2s silence = 5.0s total.
_LEAD = 0.8
_TONE = 3.0
_TAIL = 1.2
_TOTAL = _LEAD + _TONE + _TAIL


def _make_mono_wav(path: Path) -> None:
    subprocess.run(
        [
            "ffmpeg", "-v", "error", "-y",
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={_TONE}",
            "-af",
            f"adelay={int(_LEAD * 1000)}:all=1,apad=pad_dur={_TAIL}",
            "-ar", "16000", "-ac", "1",
            str(path),
        ],
        check=True, capture_output=True,
    )


def test_span_mono_wav(tmp_path):
    wav = tmp_path / "mono.wav"
    _make_mono_wav(wav)
    start, end = transcribe.detect_speech_span(wav)
    assert start == pytest.approx(_LEAD, abs=0.15)
    assert end == pytest.approx(_LEAD + _TONE, abs=0.15)


def test_span_stereo_one_silent_channel(tmp_path):
    # Tone only on the left channel; right channel fully silent. The mono
    # downmix must still detect the tone span (regression: without the
    # explicit downmix, per-channel behavior could skew detection).
    wav = tmp_path / "stereo.wav"
    subprocess.run(
        [
            "ffmpeg", "-v", "error", "-y",
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={_TONE}",
            "-f", "lavfi", "-i", f"anullsrc=r=16000:cl=mono:d={_TONE}",
            "-filter_complex",
            (
                f"[0:a]adelay={int(_LEAD * 1000)}:all=1,"
                f"apad=pad_dur={_TAIL}[l];"
                f"[1:a]adelay={int(_LEAD * 1000)}:all=1,"
                f"apad=pad_dur={_TAIL}[r];"
                "[l][r]join=inputs=2:channel_layout=stereo[out]"
            ),
            "-map", "[out]", "-ar", "16000",
            str(wav),
        ],
        check=True, capture_output=True,
    )
    start, end = transcribe.detect_speech_span(wav)
    assert start == pytest.approx(_LEAD, abs=0.15)
    assert end == pytest.approx(_LEAD + _TONE, abs=0.15)


def test_span_vbr_mp3(tmp_path):
    # VBR MP3 re-encode of the mono fixture: header duration and decoder
    # padding may disagree with the decoded stream; the EOF tolerance must
    # absorb that and still classify the tail run as trailing.
    wav = tmp_path / "mono.wav"
    _make_mono_wav(wav)
    mp3 = tmp_path / "vbr.mp3"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", str(wav), "-q:a", "5", str(mp3)],
        check=True, capture_output=True,
    )
    start, end = transcribe.detect_speech_span(mp3)
    assert start == pytest.approx(_LEAD, abs=0.15)
    assert end == pytest.approx(_LEAD + _TONE, abs=0.15)
