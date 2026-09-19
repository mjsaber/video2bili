"""Integrated loudness (EBU R128) measurement and the voice-relative music-bed gain.

The reference level everywhere is the VOICE'S 85th-PERCENTILE short-term
loudness (``voice_reference_lufs``: the level the streamer's louder speech
reaches, ignoring silence and mumbling). The music bed is mixed
``BED_BELOW_VOICE_DB`` under that reference (burn / short), and merge aligns
every segment — intro TTS included — so its own P85 lands on ``TARGET_P85_LUFS``. Before 2026-09-18 burn.py used a fixed
``volume=0.12`` (≈ −18.4 dB) regardless of how loud speech.wav happened to be,
so the bed-to-voice ratio drifted per streamer / per stream and viewers
complained the music was too loud.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

BED_BELOW_VOICE_DB = 30.0        # bed target = voice reference − this (user picked 30 over 20/26 on 2026-09-18 A/B)
VOICE_PERCENTILE = 85            # user rule 2026-09-18: 「主播全部聲音的高 85pct」
TARGET_P85_LUFS = -13.0          # merge output: every segment's voice P85 lands here
_SILENCE_FLOOR_LUFS = -50.0      # short-term windows below this are silence, not voice
_VOICE_RANGE_DB = 30.0           # …and so are windows more than this under the loudest (P99) window
_S_RE = re.compile(r"\bS:\s*(-?[\d.]+|-inf)")
LEGACY_BED_GAIN_DB = -18.4       # 20·log10(0.12): fallback when a level can't be measured
_MIN_GAIN_DB, _MAX_GAIN_DB = -60.0, 12.0

_I_RE = re.compile(r"\n\s+I:\s+(-?[\d.]+) LUFS")


def measure_lufs(path: Path) -> float | None:
    """Integrated loudness of ``path``'s audio (whole file, R128 gated so silence
    does not count), or None when ffmpeg cannot measure it."""
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-vn", "-af", "ebur128", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    found = _I_RE.findall(proc.stderr or "")
    if proc.returncode != 0 or not found:
        print(f"[loudness] could not measure {path.name}", file=sys.stderr)
        return None
    return float(found[-1])


def voice_reference_lufs(path: Path, percentile: int = VOICE_PERCENTILE) -> float | None:
    """The ``percentile``-th percentile of the 3 s short-term loudness of ``path``
    (100 ms hop, silence below ``_SILENCE_FLOOR_LUFS`` dropped): the level the
    voice's louder passages reach. None when nothing measurable."""
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-vn", "-af", "ebur128", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    err = proc.stderr if isinstance(getattr(proc, "stderr", None), str) else ""
    values = sorted(float(v) for v in _S_RE.findall(err) if v != "-inf" and float(v) > _SILENCE_FLOOR_LUFS)
    if getattr(proc, "returncode", 1) != 0 or not values:
        print(f"[loudness] could not measure voice reference of {path.name}", file=sys.stderr)
        return None
    p99 = values[round(0.99 * (len(values) - 1))]
    values = [v for v in values if v > p99 - _VOICE_RANGE_DB]   # drop bed-only / room-tone windows
    idx = min(len(values) - 1, max(0, round(percentile / 100 * (len(values) - 1))))
    return values[idx]


def bed_gain_db(voice_lufs: float | None, bed_lufs: float | None,
                below_db: float = BED_BELOW_VOICE_DB) -> float:
    """dB gain to apply to the bed so it sits ``below_db`` under the voice
    reference (``voice_reference_lufs``). Falls back to the legacy fixed gain
    when either level is unknown."""
    if voice_lufs is None or bed_lufs is None:
        return LEGACY_BED_GAIN_DB
    return max(_MIN_GAIN_DB, min(_MAX_GAIN_DB, voice_lufs - below_db - bed_lufs))




def align_gain_db(voice_p85: float | None, target: float = TARGET_P85_LUFS) -> float | None:
    """merge: constant gain that puts a segment's voice P85 on ``target``; None → caller
    falls back to single-pass loudnorm."""
    if voice_p85 is None:
        return None
    return max(_MIN_GAIN_DB, min(_MAX_GAIN_DB, target - voice_p85))
