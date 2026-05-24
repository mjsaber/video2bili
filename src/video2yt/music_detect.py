"""Music-presence detection on Demucs's ``no_vocals.wav`` stem.

Stage 2 of the conditional-sparse-bed pipeline (see
``docs/superpowers/plans/2026-05-23-music-swap-conditional-bgm.md``).

The job here is: given the music+SFX stem produced by Demucs, return the time
ranges that look like *music* (tonal + sustained) so the downstream sparse-bed
builder can know where to lay the new royalty-free track.  Game SFX, silence,
and noisy bursts should NOT be flagged.

The detector is pure numpy/scipy/soundfile and runs in-process — no subprocess
boundary, no ffmpeg.  Tests synthesize WAV fixtures directly.

Default parameters (tunable; documented here so future agents can iterate):

    window_s        = 1.0      analysis window in seconds
    hop_s           = 0.25     hop between windows
    rms_db_threshold= -45.0    windows below this are "too quiet" → not music
    flatness_max    = 0.30     spectral flatness; music ≈ tonal ≈ low flatness;
                               white-noise SFX ≈ near 1.0 → reject
    gap_fill_s      = 1.0      merge two music intervals separated by ≤ this

Public API:

    detect_music_intervals(no_vocals_path, min_duration_s=5.0)
        -> (long_intervals, all_intervals)
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.stats import gmean


# --- Detection parameters (see module docstring for context) ----------------

WINDOW_S = 1.0
HOP_S = 0.25
RMS_DB_THRESHOLD = -45.0
FLATNESS_MAX = 0.30
GAP_FILL_S = 1.0


def _load_mono(path: Path) -> tuple[np.ndarray, int]:
    """Read ``path`` and return (mono float32 samples, sample_rate)."""
    data, sr = sf.read(str(path), always_2d=False, dtype="float32")
    if data.ndim == 2:
        data = data.mean(axis=1).astype(np.float32)
    return data, sr


def _window_rms_db(window: np.ndarray) -> float:
    """RMS level of ``window`` in dBFS."""
    rms = float(np.sqrt(np.mean(window.astype(np.float64) ** 2)))
    return 20.0 * math.log10(rms + 1e-12)


def _spectral_flatness(window: np.ndarray) -> float:
    """Spectral flatness in [0, 1].

    flatness = geometric_mean(|X|) / arithmetic_mean(|X|)

    Pure sine → near 0 (single tonal peak).  White noise → near 1.  Silence
    is ill-defined here; callers should gate by RMS first.
    """
    # Real FFT magnitude.  Skip DC to avoid biasing toward "flat" on AC-coupled
    # signals.
    mag = np.abs(np.fft.rfft(window))[1:]
    if mag.size == 0:
        return 1.0
    # Avoid log(0) inside gmean — add a tiny floor.
    mag = mag + 1e-12
    arith = float(np.mean(mag))
    if arith <= 0.0:
        return 1.0
    geo = float(gmean(mag))
    return geo / arith


def _classify_windows(
    samples: np.ndarray, sr: int
) -> tuple[list[bool], float]:
    """Return per-window "is music" flags plus the hop length in seconds.

    Windows shorter than ``WINDOW_S`` at the tail are discarded so every flag
    represents a full ``WINDOW_S`` of audio.
    """
    win_n = int(round(WINDOW_S * sr))
    hop_n = int(round(HOP_S * sr))
    if win_n <= 0 or hop_n <= 0:
        raise ValueError("window and hop must be positive")
    flags: list[bool] = []
    if samples.size < win_n:
        return flags, HOP_S
    last_start = samples.size - win_n
    for start in range(0, last_start + 1, hop_n):
        w = samples[start : start + win_n]
        rms_db = _window_rms_db(w)
        if rms_db <= RMS_DB_THRESHOLD:
            flags.append(False)
            continue
        flatness = _spectral_flatness(w)
        flags.append(flatness < FLATNESS_MAX)
    return flags, HOP_S


def _flags_to_intervals(
    flags: list[bool], hop_s: float
) -> list[tuple[float, float]]:
    """Convert a per-window boolean stream into ``(start, end)`` seconds.

    A window starting at hop index ``i`` covers ``[i * hop_s, i * hop_s +
    WINDOW_S)``.  Runs of consecutive True flags collapse into one interval.
    """
    intervals: list[tuple[float, float]] = []
    in_run = False
    run_start_idx = 0
    for i, is_music in enumerate(flags):
        if is_music and not in_run:
            in_run = True
            run_start_idx = i
        elif not is_music and in_run:
            in_run = False
            start = run_start_idx * hop_s
            end = (i - 1) * hop_s + WINDOW_S
            intervals.append((start, end))
    if in_run:
        start = run_start_idx * hop_s
        end = (len(flags) - 1) * hop_s + WINDOW_S
        intervals.append((start, end))
    return intervals


def _merge_gaps(
    intervals: list[tuple[float, float]], gap_s: float
) -> list[tuple[float, float]]:
    """Join intervals separated by ≤ ``gap_s`` seconds."""
    if not intervals:
        return []
    merged = [intervals[0]]
    for start, end in intervals[1:]:
        prev_start, prev_end = merged[-1]
        if start - prev_end <= gap_s:
            merged[-1] = (prev_start, max(prev_end, end))
        else:
            merged.append((start, end))
    return merged


def detect_music_intervals(
    no_vocals_path: Path,
    min_duration_s: float = 5.0,
) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    """Return ``(long_intervals, all_intervals)`` for the input WAV.

    ``long_intervals``: music regions with duration ≥ ``min_duration_s``.  These
    feed Stage 3's sparse bed placement.

    ``all_intervals``:  every detected music region regardless of duration.
    Stage 4 uses this to zero out *all* copyrighted music in the no_vocals
    stem, including sub-5s blips that won't get a replacement bed.

    Both lists are ascending, non-overlapping ``(start, end)`` tuples in
    seconds.
    """
    samples, sr = _load_mono(Path(no_vocals_path))
    flags, hop_s = _classify_windows(samples, sr)
    raw = _flags_to_intervals(flags, hop_s)
    all_intervals = _merge_gaps(raw, GAP_FILL_S)
    long_intervals = [
        (s, e) for s, e in all_intervals if (e - s) >= min_duration_s
    ]
    return long_intervals, all_intervals
