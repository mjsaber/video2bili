"""Stage 4 of the per-segment pipeline: build the CC0 music bed for Stage 5.

Originally carved out of the now-deleted ``music_swap.py``. The bed-build
is the only part of the old music-swap path that survived the
step6-restructure — Demucs was replaced by song-remover (Stage 2), and
the bed-vs-vocals mix moved into the single ffmpeg burn pass (Stage 5).

Contract: given ``<bv>.mp4``, produce ``<bv>.music_bed.wav`` (a stitched
CC0 bed exactly matching the source duration) plus
``<bv>.music_credits.txt`` (the attribution lines the user must paste into
the YouTube description). Cache key:
``<bv>.music_bed_meta.json`` records the source duration; mismatch
re-runs the bed build.

Spec: ``docs/superpowers/specs/2026-05-24-step6-restructure.md`` §4 Stage
4 + §7 ``video2yt-music-mix`` + §11 Q9.
"""

from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from video2yt import meta, music_library, validate


META_FILENAME_SUFFIX = ".music_bed_meta.json"
# Every library track is gain-matched to this integrated loudness before the
# bed is stitched, so burn.py's fixed bed volume means the same thing whatever
# track the shuffle picks (the raw pool spans -29..-9 LUFS; viewer complaint
# 2026-09-18 「音樂真的太吵了」).
TRACK_TARGET_LUFS = -23.0
_MAX_TRACK_GAIN_DB = 20.0
BED_FILENAME_SUFFIX = ".music_bed.wav"
CREDITS_FILENAME_SUFFIX = ".music_credits.txt"

# Allowed mismatch between the recorded source duration and the current
# ffprobe-reported duration. ffprobe occasionally jitters by a few ms across
# runs; anything bigger than this means the source actually changed.
DURATION_TOLERANCE_SECONDS = 0.5


@dataclass
class MusicMixResult:
    bed_wav: Path
    credits_txt: Path
    meta_path: Path
    duration_seconds: float
    tracks_used: int
    from_cache: bool
    elapsed: float


def _expected_meta(info: validate.MediaInfo) -> dict:
    """Cache key: source duration rounded to 1 decimal (well within the
    tolerance constant) plus the integer width/height so a re-fetch at a
    different quality doesn't reuse a bed of the wrong length."""
    return {
        "duration": round(info.duration, 1),
        "width": info.width,
        "height": info.height,
    }


def _meta_is_stale(meta_path: Path, info: validate.MediaInfo) -> bool:
    """True iff the sidecar is missing or its recorded duration is more
    than ``DURATION_TOLERANCE_SECONDS`` from the current source duration."""
    recorded = meta.read_meta(meta_path)
    if recorded is None:
        return True
    rec_dur = recorded.get("duration")
    if rec_dur is None:
        return True
    if abs(float(rec_dur) - info.duration) > DURATION_TOLERANCE_SECONDS:
        return True
    # Width/height are not load-bearing for the bed (audio-only), but a
    # change in either signals the source mp4 was substituted — invalidate
    # to stay aligned with stems-stage invalidation semantics.
    return recorded.get("width") != info.width or recorded.get("height") != info.height


def _write_credits(credits_path: Path, credit_lines: list[str]) -> None:
    """Atomically write the music attribution lines to ``credits_path``.

    Format matches the legacy music_swap output so users can copy-paste from
    either path during the migration. CC BY 3.0 tracks need credit; YouTube
    Audio Library tracks (no manifest entry) need none — caller passes the
    de-duplicated lines from ``music_library.attribution_lines``.

    The write is atomic (temp file + ``os.replace``) so a mid-run failure
    cannot leave a half-baked credits file alongside a stale-but-still-valid
    sidecar — codex T5 review caught that path: bed + sidecar landed but
    credits write crashed, next run accepts the cache, user pastes truncated
    attribution. Now the bad write either succeeds atomically or leaves the
    previous valid credits in place.
    """
    body = (
        "Music credits — paste these lines into the YouTube video "
        "description and keep them there.\n"
        "The background music is royalty-free but licensed under Creative "
        "Commons Attribution, so the credit is required.\n\n"
        + "\n".join(credit_lines)
        + "\n"
    )
    credits_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = credits_path.with_suffix(credits_path.suffix + ".tmp")
    tmp.write_text(body, encoding="utf-8")
    os.replace(tmp, credits_path)


def track_gain_db(loudness_lufs: float | None) -> float:
    """Gain that brings a track of ``loudness_lufs`` to ``TRACK_TARGET_LUFS``
    (0 dB when unmeasured; clamped to ±_MAX_TRACK_GAIN_DB)."""
    if loudness_lufs is None:
        return 0.0
    gain = TRACK_TARGET_LUFS - loudness_lufs
    return max(-_MAX_TRACK_GAIN_DB, min(_MAX_TRACK_GAIN_DB, gain))


def _build_music_bed(
    tracks: list[music_library.Track],
    target_duration: float,
    bed_path: Path,
    crossfade: float = 2.0,
    gains_db: list[float] | None = None,
) -> None:
    """Stitch ``tracks`` into a single music bed of exactly ``target_duration``.

    Inlined from the old ``music_swap.build_music_bed`` so this module
    stands alone post-step6-restructure. Each input is first gain-matched
    with ``volume=<gains_db[i]>dB`` (see ``TRACK_TARGET_LUFS``), then
    consecutive tracks are joined with an ``acrossfade`` of ``crossfade``
    seconds. The result is trimmed to the target with ``-t`` and a
    ``crossfade``-second ``afade`` out is applied at the tail.
    """
    if not tracks:
        raise ValueError("cannot build a music bed from an empty track list")
    gains_db = gains_db or [0.0] * len(tracks)
    if len(gains_db) != len(tracks):
        raise ValueError("gains_db must have one entry per track")

    cmd = ["ffmpeg", "-y"]
    for t in tracks:
        cmd += ["-i", str(t.path)]

    fade_start = max(0.0, target_duration - crossfade)
    norm = [f"[{i}:a]volume={g:+.1f}dB[n{i}]" for i, g in enumerate(gains_db)]
    if len(tracks) == 1:
        filtergraph = (
            f"{norm[0]};[n0]aloop=loop=-1:size=2e9,"
            f"afade=t=out:st={fade_start:.3f}:d={crossfade:.3f}[out]"
        )
    else:
        steps = list(norm)
        prev = "[n0]"
        for idx in range(1, len(tracks)):
            label = "[out]" if idx == len(tracks) - 1 else f"[a{idx}]"
            steps.append(
                f"{prev}[n{idx}]acrossfade=d={crossfade:.3f}:c1=tri:c2=tri{label}"
            )
            prev = label
        joined = ";".join(steps)
        filtergraph = (
            joined.replace("[out]", "[mix]")
            + f";[mix]afade=t=out:st={fade_start:.3f}:d={crossfade:.3f}[out]"
        )

    cmd += [
        "-filter_complex", filtergraph,
        "-map", "[out]",
        "-t", f"{target_duration:.3f}",
        "-c:a", "pcm_s16le",
        str(bed_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def render(
    raw_mp4: Path,
    crossfade: float = 2.0,
    seed: int | None = None,
    force: bool = False,
) -> MusicMixResult:
    """Build the CC0 music bed for ``raw_mp4`` (cache-aware).

    Outputs live next to ``raw_mp4``:
      - ``<bv>.music_bed.wav`` — PCM s16le wav matching source duration.
      - ``<bv>.music_credits.txt`` — attribution lines for the YouTube description.
      - ``<bv>.music_bed_meta.json`` — cache-validity sidecar (duration + size).
    """
    t_start = time.monotonic()
    if not raw_mp4.exists():
        raise FileNotFoundError(f"raw mp4 not found: {raw_mp4}")

    bed_path = raw_mp4.with_name(raw_mp4.stem + BED_FILENAME_SUFFIX)
    credits_path = raw_mp4.with_name(raw_mp4.stem + CREDITS_FILENAME_SUFFIX)
    meta_path = raw_mp4.with_name(raw_mp4.stem + META_FILENAME_SUFFIX)

    info = validate.probe(raw_mp4)
    expected = _expected_meta(info)

    # Cache hit: bed + credits + sidecar all present AND meta matches.
    if (
        not force
        and bed_path.exists()
        and credits_path.exists()
        and not _meta_is_stale(meta_path, info)
    ):
        # Tracks-used count is purely informational; we don't have it from
        # cache (sidecar doesn't record it). Caller treats from_cache=True
        # as "trust the on-disk outputs".
        return MusicMixResult(
            bed_wav=bed_path,
            credits_txt=credits_path,
            meta_path=meta_path,
            duration_seconds=info.duration,
            tracks_used=0,
            from_cache=True,
            elapsed=time.monotonic() - t_start,
        )

    # Cache miss: build fresh.
    manifest = music_library.load_manifest()
    music_library.ensure_manifest_cached(manifest, music_library.CACHE_DIR)
    pool = music_library.scan_cache(music_library.CACHE_DIR)
    tracks = music_library.select_sequence(
        pool=pool,
        target_duration=info.duration,
        crossfade=crossfade,
        seed=seed,
    )
    gains = [track_gain_db(music_library.track_loudness(t.path)) for t in tracks]
    _build_music_bed(
        tracks=tracks,
        target_duration=info.duration,
        bed_path=bed_path,
        crossfade=crossfade,
        gains_db=gains,
    )
    _write_credits(
        credits_path,
        music_library.attribution_lines(tracks, manifest),
    )
    meta.write_meta(meta_path, expected)

    return MusicMixResult(
        bed_wav=bed_path,
        credits_txt=credits_path,
        meta_path=meta_path,
        duration_seconds=info.duration,
        tracks_used=len(tracks),
        from_cache=False,
        elapsed=time.monotonic() - t_start,
    )
