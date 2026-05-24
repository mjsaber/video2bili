"""Audio pipeline for video2yt-music-swap.

Replaces the streamer's copyrighted background music in a burnt Bilibili
segment: extract audio -> isolate the commentary voice with Demucs -> discard
the music+SFX mix -> stitch a CC0 music bed -> mix (with ducking) -> remux the
new audio back into the video (no video re-encode).
"""
from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from video2yt import music_library, validate


def _log(msg: str) -> None:
    print(f"[music_swap] {msg}", file=sys.stderr)


@dataclass
class MusicSwapInputs:
    input_path: Path
    output_path: Path
    music_volume: float = 0.25
    duck: bool = True
    model: str = "htdemucs"
    seed: int | None = None
    keep_temp: bool = False
    vocal_gate: bool = True
    vocal_gate_threshold: float = 0.025
    vocal_gate_release_ms: int = 250


def extract_audio(input_path: Path, wav_path: Path) -> None:
    """Extract the input's audio to a 44.1 kHz stereo 16-bit PCM WAV."""
    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_path),
        "-vn",
        "-ac", "2",
        "-ar", "44100",
        "-c:a", "pcm_s16le",
        str(wav_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def _pick_device() -> str:
    """Return the Demucs device: ``mps`` on Apple Silicon if available, else ``cpu``.

    CUDA is intentionally not selected here — the target machine is macOS.
    """
    try:
        import torch
        if torch.backends.mps.is_available():
            return "mps"
    except Exception:
        pass
    return "cpu"


def separate_vocals(wav_path: Path, model: str, out_dir: Path) -> Path:
    """Run Demucs in two-stem mode and return the path to ``vocals.wav``.

    Demucs writes ``<out_dir>/<model>/<wav stem>/{vocals,no_vocals}.wav``.
    ``no_vocals.wav`` (the music + game-SFX mix) is left on disk but ignored —
    it is the Approach A trade-off (spec §2). Demucs runs as a subprocess via
    ``python -m demucs`` so the call is mockable at the ``subprocess.run``
    boundary.
    """
    device = _pick_device()
    _log(f"running Demucs ({model}, device={device}) — this is slow on CPU")
    cmd = [
        sys.executable, "-m", "demucs",
        "--two-stems", "vocals",
        "-n", model,
        "-d", device,
        "-o", str(out_dir),
        str(wav_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    vocals = out_dir / model / wav_path.stem / "vocals.wav"
    if not vocals.exists():
        raise ValueError(
            f"Demucs did not produce {vocals} — separation failed"
        )
    return vocals


def gate_vocals(
    vocals_path: Path,
    gated_path: Path,
    threshold: float = 0.025,
    release_ms: int = 250,
) -> None:
    """Mute low-level residual music bleed in the isolated vocals stem.

    This is a voice-activity-style energy gate, not a semantic speech model.
    Demucs often leaves quiet BGM in ``vocals.wav`` during non-speech regions;
    ``agate`` pushes those regions to silence while keeping louder streamer
    speech. ``highpass`` removes low-end rumble before the gate/mix.

    ``threshold`` is a linear ffmpeg amplitude value. Default 0.025 (about
    -32 dBFS). The original 2026-05-21 default of 0.015 (-36.5 dBFS) — chosen
    from a redchroma probe — turned out too permissive on the 夜吹 (2026-05-23
    mooniron) segment where audible original BGM was still leaking through
    Demucs into the vocals stem at ~-30 dBFS. Bumped to 0.025 after the user
    A/B-tested 0.040 (too aggressive — quiet speech got clipped) vs. 0.025
    on a 60s snippet and picked 0.025. Speech peaks usually cluster around
    -20 dBFS so 0.025 still leaves ~12 dB headroom for the streamer voice.
    """
    if threshold <= 0 or threshold >= 1:
        raise ValueError("vocal gate threshold must be between 0 and 1")
    if release_ms <= 0:
        raise ValueError("vocal gate release must be positive milliseconds")
    filtergraph = (
        "highpass=f=80,"
        f"agate=threshold={threshold}:ratio=20:range=0:"
        f"attack=10:release={release_ms}:detection=rms"
    )
    cmd = [
        "ffmpeg", "-y",
        "-i", str(vocals_path),
        "-af", filtergraph,
        "-c:a", "pcm_s16le",
        str(gated_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def build_music_bed(
    tracks: list,
    target_duration: float,
    bed_path: Path,
    crossfade: float = 2.0,
) -> None:
    """Stitch ``tracks`` into a single music bed of exactly ``target_duration``.

    Consecutive tracks are joined with an ``acrossfade`` of ``crossfade``
    seconds. The result is trimmed to the target with ``-t`` and a
    ``crossfade``-second ``afade`` out is applied at the tail. ``tracks`` is a
    non-empty list of ``music_library.Track``.
    """
    if not tracks:
        raise ValueError("cannot build a music bed from an empty track list")

    cmd = ["ffmpeg", "-y"]
    for t in tracks:
        cmd += ["-i", str(t.path)]

    fade_start = max(0.0, target_duration - crossfade)
    if len(tracks) == 1:
        # Single track: loop it to be safe, then fade + trim.
        filtergraph = (
            f"[0:a]aloop=loop=-1:size=2e9,"
            f"afade=t=out:st={fade_start:.3f}:d={crossfade:.3f}[out]"
        )
    else:
        # Chain acrossfade across all inputs: [0][1]->[a1], [a1][2]->[a2], ...
        steps = []
        prev = "[0:a]"
        for idx in range(1, len(tracks)):
            label = "[out]" if idx == len(tracks) - 1 else f"[a{idx}]"
            steps.append(
                f"{prev}[{idx}:a]acrossfade=d={crossfade:.3f}:c1=tri:c2=tri{label}"
            )
            prev = label
        # Append the tail fade as a second branch off the final label.
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


def build_sparse_music_bed(
    tracks: list,
    intervals: list[tuple[float, float]],
    total_duration: float,
    bed_path: Path,
    crossfade: float = 2.0,
    edge_fade: float = 0.5,
) -> list:
    """Build a music bed that is silent except inside the supplied intervals.

    ``intervals`` is a list of ``(start, end)`` seconds (ascending,
    non-overlapping) where the new CC-BY music should play. Outside those
    intervals the bed is digital silence. Each music segment has a linear
    ``afade=t=in`` of ``edge_fade`` seconds at its start and a matching
    ``afade=t=out`` at its end so cuts don't pop. Output is a single
    ``pcm_s16le`` WAV of exactly ``total_duration`` seconds at ``bed_path``.

    Filtergraph structure (one ``ffmpeg -filter_complex`` invocation):

    1. For each interval, take a slice from the CC-BY ``tracks`` sequence
       (``atrim``/``asetpts``) sized to ``end - start`` seconds. The first
       interval consumes ``tracks[0]``; the second consumes ``tracks[1]``;
       and so on (per-interval cursor, modulo the pool). If a single
       interval is longer than its starting track, the next track is
       chained in with ``acrossfade=d={crossfade}`` so the music keeps
       playing without an audible seam.
    2. Apply ``afade=t=in:st=0:d={edge_fade}`` and
       ``afade=t=out:st=<dur - edge_fade>:d={edge_fade}`` to each interval
       so the cut into / out of silence is smooth.
    3. Emit ``aevalsrc=0:c=stereo:s=44100:d=<gap>`` silence segments for
       the gap before the first interval, every gap between consecutive
       intervals, and the gap after the last interval (zero-length gaps
       are skipped to keep ``concat=n=K`` accurate).
    4. ``concat=n=K:v=0:a=1[out]`` over the silence + interval + silence +
       ... chain, producing the final stream. ``-t total_duration`` clamps
       the output so floating-point drift can't extend the file.

    If ``intervals`` is empty the function emits a single
    ``aevalsrc=0`` segment covering ``total_duration`` and no ``-i``
    inputs — pure silence.

    Returns the ordered list of ``music_library.Track`` objects that were
    actually consumed (one per ``-i`` input in the ffmpeg call). Callers can
    use this for accurate CC-BY attribution — empty list when the bed is
    pure silence.
    """
    if total_duration <= 0:
        raise ValueError(
            f"total_duration must be positive, got {total_duration}"
        )

    if not intervals:
        # No music regions — produce a pure-silence WAV. No -i inputs.
        filtergraph = (
            f"aevalsrc=0:c=stereo:s=44100:d={total_duration:.3f}[out]"
        )
        cmd = [
            "ffmpeg", "-y",
            "-filter_complex", filtergraph,
            "-map", "[out]",
            "-t", f"{total_duration:.3f}",
            "-c:a", "pcm_s16le",
            str(bed_path),
        ]
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        return []

    # Validate intervals: ascending, non-overlapping, within total_duration.
    for start, end in intervals:
        if end <= start:
            raise ValueError(
                f"interval ({start}, {end}) is empty or reversed"
            )
        if start < 0:
            raise ValueError(f"interval start {start} is negative")
        if end > total_duration:
            raise ValueError(
                f"interval end {end} exceeds total_duration {total_duration}"
            )
    for prev, curr in zip(intervals, intervals[1:]):
        if curr[0] < prev[1]:
            raise ValueError(
                f"intervals are not non-overlapping or ascending: "
                f"{prev} then {curr}"
            )

    if not tracks:
        raise ValueError(
            "cannot build a sparse music bed without any CC-BY tracks"
        )

    # Walk through tracks consuming chunks per interval. Each interval starts
    # fresh on the next unused track; if one track isn't long enough the next
    # is chained in with an acrossfade.
    inputs: list = []          # ordered list of music_library.Track to feed via -i
    interval_parts: list[list[str]] = []  # filtergraph parts per interval
    interval_labels: list[str] = []       # output label per interval
    track_cursor = 0
    for i, (start, end) in enumerate(intervals):
        need = end - start
        # Pick enough tracks. First track contributes up to its full duration.
        # Each chained track adds `chunk - crossfade` net seconds because the
        # acrossfade overlaps the seam.
        chunks: list[tuple] = []  # list of (track, slice_seconds)
        remaining = need
        first = True
        while remaining > 1e-6:
            t = tracks[track_cursor % len(tracks)]
            track_cursor += 1
            if first:
                chunk = min(float(t.duration), remaining)
                chunks.append((t, chunk))
                remaining -= chunk
                first = False
            else:
                # The acrossfade consumes `crossfade` seconds from both sides
                # of the seam; the chained slice must be longer than
                # `crossfade` for the filter to add any new audio (and not
                # break with a zero-length output).
                want = remaining + crossfade
                chunk = min(float(t.duration), want)
                if chunk <= crossfade:
                    raise ValueError(
                        f"cannot chain into interval: track {t.name!r} "
                        f"has duration {t.duration:.2f}s but crossfade is "
                        f"{crossfade:.2f}s, leaving <= 0s of new audio. "
                        f"Use a longer track or shrink crossfade."
                    )
                chunks.append((t, chunk))
                remaining -= (chunk - crossfade)
        # Register inputs for each chunk
        input_indices = []
        for (t, _chunk) in chunks:
            input_indices.append(len(inputs))
            inputs.append(t)
        # Slice each chunk: [N:a]atrim=0:duration=<chunk>,asetpts=PTS-STARTPTS[s_i_j]
        parts: list[str] = []
        chunk_labels: list[str] = []
        for j, (in_idx, (_t, chunk)) in enumerate(zip(input_indices, chunks)):
            cl = f"[s_{i}_{j}]"
            parts.append(
                f"[{in_idx}:a]atrim=0:duration={chunk:.3f},"
                f"asetpts=PTS-STARTPTS{cl}"
            )
            chunk_labels.append(cl)
        # Chain via acrossfade across the chunks
        if len(chunk_labels) == 1:
            combined_label = chunk_labels[0]
        else:
            prev_label = chunk_labels[0]
            for j in range(1, len(chunk_labels)):
                next_label = f"[x_{i}_{j}]"
                parts.append(
                    f"{prev_label}{chunk_labels[j]}"
                    f"acrossfade=d={crossfade:.3f}:c1=tri:c2=tri{next_label}"
                )
                prev_label = next_label
            combined_label = prev_label
        # Apply edge fades so the cut into/out of silence is smooth. For very
        # short intervals (need < 2*edge_fade) the fade-in and fade-out would
        # overlap and silence the whole segment — clamp the fade length so
        # the two halves of the interval each get a non-degenerate fade.
        # (Stage 4 callers should not pass intervals <5s, but `need < 1s` is
        # cheap to defend against.)
        actual_fade = min(edge_fade, need / 2.0)
        interval_label = f"[interval_{i}]"
        fade_out_start = max(0.0, need - actual_fade)
        parts.append(
            f"{combined_label}"
            f"afade=t=in:st=0:d={actual_fade:.3f},"
            f"afade=t=out:st={fade_out_start:.3f}:d={actual_fade:.3f}"
            f"{interval_label}"
        )
        interval_parts.append(parts)
        interval_labels.append(interval_label)

    # Now stitch the timeline: silence_0, interval_0, silence_1, interval_1,
    # ..., silence_N. Zero-length silences are skipped so concat=n=K matches.
    all_parts: list[str] = []
    concat_labels: list[str] = []
    silence_idx = 0

    def _emit_silence(dur: float) -> str:
        nonlocal silence_idx
        label = f"[sil_{silence_idx}]"
        silence_idx += 1
        all_parts.append(
            f"aevalsrc=0:c=stereo:s=44100:d={dur:.3f}{label}"
        )
        return label

    # Leading gap
    lead = intervals[0][0]
    if lead > 0:
        concat_labels.append(_emit_silence(lead))
    # Intervals + intermediate gaps + trailing gap
    for i, (_start, end) in enumerate(intervals):
        all_parts.extend(interval_parts[i])
        concat_labels.append(interval_labels[i])
        if i + 1 < len(intervals):
            gap = intervals[i + 1][0] - end
        else:
            gap = total_duration - end
        if gap > 0:
            concat_labels.append(_emit_silence(gap))

    n = len(concat_labels)
    all_parts.append(
        "".join(concat_labels) + f"concat=n={n}:v=0:a=1[out]"
    )
    filtergraph = ";".join(all_parts)

    cmd = ["ffmpeg", "-y"]
    for t in inputs:
        cmd += ["-i", str(t.path)]
    cmd += [
        "-filter_complex", filtergraph,
        "-map", "[out]",
        "-t", f"{total_duration:.3f}",
        "-c:a", "pcm_s16le",
        str(bed_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    return inputs


def mix(
    vocals_path: Path,
    bed_path: Path,
    music_volume: float,
    duck: bool,
    mixed_path: Path,
) -> None:
    """Mix the isolated commentary (input 0) with the music bed (input 1).

    The bed is scaled to ``music_volume`` relative to the voice. When ``duck``
    is true, the bed is side-chain compressed against the voice so it drops in
    level while the streamer talks; otherwise the bed plays at a flat level.
    The voice is always passed through at full level. The two are combined
    with ``amix``; output length follows the voice (input 0).
    """
    if duck:
        filtergraph = (
            f"[1:a]volume={music_volume}[bed];"
            f"[bed][0:a]sidechaincompress="
            f"threshold=0.05:ratio=8:attack=5:release=300[ducked];"
            f"[0:a][ducked]amix=inputs=2:duration=first:"
            f"dropout_transition=0:normalize=0[out]"
        )
    else:
        filtergraph = (
            f"[1:a]volume={music_volume}[bed];"
            f"[0:a][bed]amix=inputs=2:duration=first:"
            f"dropout_transition=0:normalize=0[out]"
        )
    cmd = [
        "ffmpeg", "-y",
        "-i", str(vocals_path),
        "-i", str(bed_path),
        "-filter_complex", filtergraph,
        "-map", "[out]",
        "-c:a", "pcm_s16le",
        str(mixed_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def mask_intervals(
    src_path: Path,
    intervals: list[tuple[float, float]],
    out_path: Path,
) -> None:
    """Zero out audio in ``src_path`` inside each ``(start, end)`` interval.

    Used to strip copyrighted background music from the Demucs ``no_vocals``
    stem at every detected music region (long AND short), so the original
    music never reaches the final mix even if Stage 3's sparse bed didn't
    cover it.

    Implementation: ffmpeg ``volume`` filter with an ``enable`` expression
    that ORs ``between(t,s_i,e_i)`` for every interval. Outside the intervals
    volume stays at 1.0; inside, it's 0. Output is PCM s16le matching the
    input duration exactly.
    """
    if not intervals:
        # No regions to mask — straight copy.
        cmd = [
            "ffmpeg", "-y",
            "-i", str(src_path),
            "-c:a", "pcm_s16le",
            str(out_path),
        ]
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        return

    enable_expr = "+".join(
        f"between(t,{s:.3f},{e:.3f})" for s, e in intervals
    )
    filtergraph = f"volume=enable='{enable_expr}':volume=0"
    cmd = [
        "ffmpeg", "-y",
        "-i", str(src_path),
        "-af", filtergraph,
        "-c:a", "pcm_s16le",
        str(out_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def mix_three_way(
    vocals_path: Path,
    bed_path: Path,
    sfx_path: Path,
    music_volume: float,
    duck: bool,
    mixed_path: Path,
) -> None:
    """Three-way mix: gated vocals + sparse CC-BY bed + masked no_vocals SFX.

    Input layout:
      [0:a] — gated vocals (voice, always at full level)
      [1:a] — sparse CC-BY bed (silent outside detected music regions)
      [2:a] — masked no_vocals stem (silent inside detected music regions —
              so it carries only game SFX / ambience from non-music ranges)

    ``music_volume`` scales the bed (same as the two-way mix). ``duck`` ducks
    the bed under the voice via sidechain compression but does NOT duck the
    SFX — game audio is meant to punctuate. Output length follows the voice
    (input 0).
    """
    if duck:
        filtergraph = (
            f"[1:a]volume={music_volume}[bed];"
            f"[bed][0:a]sidechaincompress="
            f"threshold=0.05:ratio=8:attack=5:release=300[ducked];"
            f"[0:a][ducked][2:a]amix=inputs=3:duration=first:"
            f"dropout_transition=0:normalize=0[out]"
        )
    else:
        filtergraph = (
            f"[1:a]volume={music_volume}[bed];"
            f"[0:a][bed][2:a]amix=inputs=3:duration=first:"
            f"dropout_transition=0:normalize=0[out]"
        )
    cmd = [
        "ffmpeg", "-y",
        "-i", str(vocals_path),
        "-i", str(bed_path),
        "-i", str(sfx_path),
        "-filter_complex", filtergraph,
        "-map", "[out]",
        "-c:a", "pcm_s16le",
        str(mixed_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def remux(input_path: Path, mixed_path: Path, output_path: Path) -> None:
    """Combine the original video stream with the new mixed audio.

    The video stream is stream-copied (``-c:v copy``) — no re-encode — and the
    new audio is encoded to AAC 192k. The original audio stream is dropped.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_path),
        "-i", str(mixed_path),
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "192k",
        "-movflags", "+faststart",
        str(output_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def _write_credits(output_path: Path, credit_lines: list[str]) -> Path:
    """Write the music attribution lines to a ``<output>_music_credits.txt``
    sidecar beside the output, ready to paste into the YouTube description."""
    credits_path = output_path.with_name(
        f"{output_path.stem}_music_credits.txt"
    )
    body = (
        "Music credits — paste these lines into the YouTube video "
        "description and keep them there.\n"
        "The background music is royalty-free but licensed under Creative "
        "Commons Attribution, so the credit is required.\n\n"
        + "\n".join(credit_lines)
        + "\n"
    )
    credits_path.write_text(body, encoding="utf-8")
    return credits_path


# ---------------------------------------------------------------------------
# Debug sidecar (Stage 1 of docs/superpowers/plans/2026-05-23-music-swap-
# conditional-bgm.md).
#
# Every successful render writes ``<output_stem>_music_swap_debug.json``
# beside the output MP4. The sidecar captures the run's config, the bed
# timeline, and per-30s chunk loudness for the ``vocals`` and ``no_vocals``
# Demucs stems so bleed / gating regressions can be diagnosed offline without
# re-running Demucs. Schema is documented inline so future stages of the plan
# can extend it.
# ---------------------------------------------------------------------------


_RMS_LEVEL_RE = re.compile(
    r"lavfi\.astats\.Overall\.RMS_level\s*=\s*(-?\d+(?:\.\d+)?)"
)


def _measure_chunk_loudness(
    wav_path: Path,
    duration_seconds: float,
    chunk_seconds: int = 30,
) -> list[float]:
    """Return one mean-RMS-in-dB number per ``chunk_seconds`` slice of ``wav_path``.

    The output list has length ``ceil(duration_seconds / chunk_seconds)``.
    ffmpeg's ``astats=metadata=1:reset=1`` emits the overall RMS level for the
    samples it sees; running it once per ``-ss start -t chunk`` window gives a
    per-chunk number. Mean RMS (not true integrated LUFS) is the trade-off the
    plan calls for: one ffmpeg invocation per chunk, no second pass, easy to
    mock at the ``subprocess.run`` boundary. Unparseable chunks contribute
    ``-inf`` (preferable to silently dropping data points).
    """
    if chunk_seconds <= 0:
        raise ValueError("chunk_seconds must be a positive integer")
    if duration_seconds <= 0:
        return []
    n_chunks = math.ceil(duration_seconds / chunk_seconds)
    values: list[float] = []
    for i in range(n_chunks):
        start = i * chunk_seconds
        cmd = [
            "ffmpeg", "-hide_banner", "-nostats",
            "-ss", f"{start}",
            "-t", f"{chunk_seconds}",
            "-i", str(wav_path),
            "-af",
            "astats=metadata=1:reset=1,"
            "ametadata=print:key=lavfi.astats.Overall.RMS_level",
            "-f", "null", "-",
        ]
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        # astats writes metadata to stderr by default; some ffmpeg builds also
        # surface it on stdout. Scan both so the parse is resilient.
        haystack = (result.stderr or "") + "\n" + (result.stdout or "")
        matches = _RMS_LEVEL_RE.findall(haystack)
        if matches:
            # One RMS_level per reset window — for a single chunk that's one
            # number. If multiple show up, average them rather than dropping.
            parsed = [float(m) for m in matches]
            values.append(sum(parsed) / len(parsed))
        else:
            values.append(float("-inf"))
    return values


def _compute_track_timeline(
    tracks: list,
    crossfade: float,
    manifest: list[dict] | None = None,
) -> list[dict]:
    """Return the per-track timeline entries for the debug sidecar.

    ``acrossfade`` overlaps consecutive tracks by ``crossfade`` seconds, so for
    a sequence of N tracks the start-of-track in the stitched bed is::

        start_in_bed[N] = sum(durations[0..N-1]) - N * crossfade

    Track 0 starts at 0; subsequent tracks slide left by ``crossfade`` per
    boundary they sit behind. Attribution (when the track is in the manifest)
    is recorded so the sidecar is self-contained.
    """
    by_filename = {}
    if manifest:
        # Mirror music_library._cache_filename without re-importing the helper.
        for entry in manifest:
            ext = Path(entry["url"]).suffix or ".mp3"
            by_filename[f"{entry['name']}{ext}"] = entry

    entries: list[dict] = []
    cumulative_prev_duration = 0.0
    for i, track in enumerate(tracks):
        # start_in_bed = sum(prev durations) - i * crossfade
        start_in_bed = cumulative_prev_duration - i * crossfade
        if start_in_bed < 0:
            start_in_bed = 0.0
        attribution = ""
        entry = by_filename.get(track.name)
        if entry:
            attribution = entry.get("attribution") or ""
        entries.append({
            "name": track.name,
            "start_in_bed": round(float(start_in_bed), 6),
            "duration_seconds": float(track.duration),
            "attribution": attribution,
        })
        cumulative_prev_duration += track.duration
    return entries


def _write_swap_debug(output_path: Path, payload: dict) -> Path:
    """Write the debug sidecar next to ``output_path`` and return its path."""
    sidecar = output_path.with_name(
        f"{output_path.stem}_music_swap_debug.json"
    )
    sidecar.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=False)
        + "\n",
        encoding="utf-8",
    )
    return sidecar


def render(inputs: MusicSwapInputs) -> Path:
    """Run the full music-swap pipeline and return the output path.

    Steps: probe input -> extract audio -> Demucs vocal isolation -> build the
    royalty-free music bed -> mix (with ducking) -> remux into the video ->
    validate -> write the music-credits sidecar. Temp files go in a scratch
    directory removed afterwards unless ``keep_temp`` is set. Final loudness is
    left to ``video2yt-merge``.
    """
    src_info = validate.probe(inputs.input_path)
    if not src_info.has_video:
        raise ValueError(f"input has no video stream: {inputs.input_path}")
    if not src_info.has_audio:
        raise ValueError(f"input has no audio stream: {inputs.input_path}")

    work = Path(tempfile.mkdtemp(prefix="music_swap_"))
    try:
        wav = work / "audio.wav"
        _log("extracting audio")
        extract_audio(inputs.input_path, wav)

        _log("isolating commentary voice")
        demucs_out = work / "demucs"
        vocals = separate_vocals(wav, inputs.model, demucs_out)
        voice_for_mix = vocals
        if inputs.vocal_gate:
            _log(
                "gating isolated vocals "
                f"(threshold={inputs.vocal_gate_threshold}, "
                f"release_ms={inputs.vocal_gate_release_ms})"
            )
            gated = work / "vocals_gated.wav"
            gate_vocals(
                vocals,
                gated,
                threshold=inputs.vocal_gate_threshold,
                release_ms=inputs.vocal_gate_release_ms,
            )
            voice_for_mix = gated

        # Stage 2-4 of 2026-05-23 conditional-bgm plan: detect which ranges
        # of the original audio actually carry copyrighted music, then build
        # a SPARSE bed that only covers ≥5s music regions and PRESERVE the
        # original no_vocals (game SFX) outside those regions.
        no_vocals_path = vocals.with_name("no_vocals.wav")
        _log("detecting music regions on no_vocals stem")
        from . import music_detect  # local import to keep top-level light
        long_intervals, all_intervals = music_detect.detect_music_intervals(
            no_vocals_path, min_duration_s=5.0,
        )
        _log(
            f"detected {len(all_intervals)} music region(s); "
            f"{len(long_intervals)} are >=5s and will get the new bed"
        )

        _log("building royalty-free sparse music bed")
        manifest = music_library.load_manifest()
        music_library.ensure_manifest_cached(manifest, music_library.CACHE_DIR)
        pool = music_library.scan_cache(music_library.CACHE_DIR)
        # Pull enough tracks to cover the worst case (whole video as music).
        # build_sparse_music_bed only consumes what it needs and returns the
        # subset for accurate attribution.
        sequence_pool = music_library.select_sequence(
            pool, src_info.duration, crossfade=2.0, seed=inputs.seed,
        )
        bed = work / "bed.wav"
        consumed_tracks = build_sparse_music_bed(
            sequence_pool, long_intervals, src_info.duration, bed,
            crossfade=2.0, edge_fade=0.5,
        )

        _log(f"masking {len(all_intervals)} music region(s) on no_vocals stem")
        no_vocals_masked = work / "no_vocals_masked.wav"
        mask_intervals(no_vocals_path, all_intervals, no_vocals_masked)

        _log(
            f"three-way mixing (music_volume={inputs.music_volume}, "
            f"duck={inputs.duck})"
        )
        mixed = work / "mixed.wav"
        mix_three_way(
            voice_for_mix, bed, no_vocals_masked,
            inputs.music_volume, inputs.duck, mixed,
        )

        _log("remuxing into the video")
        remux(inputs.input_path, mixed, inputs.output_path)

        _log("validating output")
        out_info = validate.probe(inputs.output_path)
        if not out_info.has_video or not out_info.has_audio:
            raise ValueError("output is missing a video or audio stream")
        if out_info.width != src_info.width or out_info.height != src_info.height:
            raise ValueError(
                f"output resolution {out_info.width}x{out_info.height} "
                f"differs from input {src_info.width}x{src_info.height}"
            )
        if abs(out_info.duration - src_info.duration) >= 1.0:
            raise ValueError(
                f"output duration {out_info.duration:.2f}s differs from input "
                f"{src_info.duration:.2f}s by more than 1 second"
            )

        # Only credit tracks that were actually consumed by the sparse bed
        # (empty long_intervals → empty consumed_tracks → no credits written).
        credits = music_library.attribution_lines(consumed_tracks, manifest)
        if credits:
            credits_path = _write_credits(inputs.output_path, credits)
            _log(
                f"music credits written to {credits_path.name} — paste them "
                f"into the YouTube description"
            )

        # Stage 1 of 2026-05-23 conditional-bgm plan: emit a debug sidecar
        # capturing the run config, bed timeline, and per-30s chunk loudness
        # on both Demucs stems. Measured AFTER validation succeeds so a busted
        # output never produces a misleading sidecar; emitted BEFORE the temp
        # dir is wiped so vocals.wav / no_vocals.wav are still readable.
        loudness_vocals: list[float] = []
        loudness_no_vocals: list[float] = []
        try:
            if vocals.exists():
                loudness_vocals = _measure_chunk_loudness(
                    vocals, src_info.duration, chunk_seconds=30,
                )
            if no_vocals_path.exists():
                loudness_no_vocals = _measure_chunk_loudness(
                    no_vocals_path, src_info.duration, chunk_seconds=30,
                )
        except subprocess.CalledProcessError as e:  # pragma: no cover - defensive
            _log(f"WARNING: chunk-loudness probe failed: {e}; sidecar will be partial")

        debug_payload = {
            "input_path": str(inputs.input_path),
            "output_path": str(inputs.output_path),
            "duration_seconds": float(src_info.duration),
            "config": {
                "model": inputs.model,
                "device": _pick_device(),
                "seed": inputs.seed,
                "music_volume": inputs.music_volume,
                "duck": inputs.duck,
                "vocal_gate": {
                    "enabled": inputs.vocal_gate,
                    "threshold": inputs.vocal_gate_threshold,
                    "release_ms": inputs.vocal_gate_release_ms,
                },
            },
            "music_intervals": {
                "long_seconds": 5.0,
                "long": [list(iv) for iv in long_intervals],
                "all": [list(iv) for iv in all_intervals],
            },
            "music_bed": {
                "crossfade_seconds": 2.0,
                "tracks": _compute_track_timeline(consumed_tracks, crossfade=2.0,
                                                  manifest=manifest),
            },
            "chunk_loudness_db": {
                "chunk_seconds": 30,
                "vocals": loudness_vocals,
                "no_vocals": loudness_no_vocals,
            },
        }
        sidecar_path = _write_swap_debug(inputs.output_path, debug_payload)
        _log(f"debug sidecar written to {sidecar_path.name}")

        _log(f"success: {inputs.output_path}")
        return inputs.output_path
    finally:
        if inputs.keep_temp:
            _log(f"keeping temp dir: {work}")
        else:
            shutil.rmtree(work, ignore_errors=True)
