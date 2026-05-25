"""Stage 2 of the per-segment pipeline: source separation via song-remover.

Wraps the external ``song-remover`` CLI (`~/code/song-remover`,
Bandit-v2 multilingual) as a subprocess. Produces all 4 stems
(speech / music / sfx / no_music) under ``<dir>/<bv>/``; downstream
stages consume only ``speech.wav`` but the others are kept on disk per
the user's "1.先都留我自己删" decision (spec §3 "What we keep from stems").

Cache key: ``<bv>/.stems_source_meta.json`` records the first-1MB SHA-256,
duration, and quality_label of ``<bv>.mp4`` at the time song-remover ran.
If the recorded meta mismatches the current ``<bv>.mp4`` (e.g. the user
re-ran ``video2yt-fetch --quality 1080`` over an old 480p download),
stems are invalidated and song-remover is re-invoked.

Spec: ``docs/superpowers/specs/2026-05-24-step6-restructure.md`` §4 Stage 2
+ §7 ``video2yt-stems`` + §11 Q9.
"""

from __future__ import annotations

import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from video2yt import meta, validate


META_FILENAME = ".stems_source_meta.json"


@dataclass
class StemsResult:
    bv_dir: Path                       # <raw_mp4 parent>/<raw_mp4 stem>/
    speech_wav: Path                   # bv_dir/speech.wav (the only one downstream uses)
    music_wav: Path                    # bv_dir/music.wav (kept on disk; not consumed)
    sfx_wav: Path                      # bv_dir/sfx.wav (kept on disk; not consumed)
    no_music_wav: Path                 # bv_dir/no_music.wav (kept on disk; not consumed)
    no_music_gain_txt: Path | None     # only present when song-remover peak-normalized
    from_cache: bool
    elapsed: float


def _quality_label(height: int) -> str:
    """Inverse of yt-dlp's --quality cap: pick the standard label that fits."""
    if height >= 1080:
        return "1080p"
    if height >= 720:
        return "720p"
    if height >= 480:
        return "480p"
    return f"{height}p"


def _expected_source_meta(raw_mp4: Path) -> dict:
    """Cache key for the stems sidecar. Includes width/height in addition to
    the quality_label bucket so that e.g. 1079p (which buckets to "720p"
    under our coarse label) is distinguishable from 1080p."""
    info = validate.probe(raw_mp4)
    return {
        "sha256": meta.compute_first_1mb_sha256(raw_mp4),
        "duration": round(info.duration, 3),
        "width": info.width,
        "height": info.height,
        "quality_label": _quality_label(info.height),
    }


# song-remover (as of commit f3380d1 / b2479e4) exposes:
#   --device {auto, mps, cuda, cpu}   inference device (NOT "remote")
#   --remote                          bool — route through Modal cloud GPU
#   --chunk-min N                     only honored under --remote
# So our single "device" abstraction has to translate: when our value is
# "remote", we emit --remote and pass --device auto (song-remover ignores
# --device when --remote is set, but valid is required by its argparse).
_SONG_REMOVER_LOCAL_DEVICES = {"cpu", "mps", "auto"}


def _build_argv(raw_mp4: Path, device: str, chunk_min: int | None) -> list[str]:
    """Compose the song-remover argv. song-remover writes ``out/<basename>/``
    under its ``-o`` flag, so we set ``-o .`` and run from
    ``cwd=raw_mp4.parent`` — song-remover then creates ``<raw_mp4 stem>/``
    siblings of ``raw_mp4`` automatically.

    ``--force`` is always passed: our own cache check is the source of truth;
    song-remover would otherwise refuse to overwrite existing stems on the
    invalidate path.
    """
    cmd = [
        "song-remover",
        raw_mp4.name,
        "-o", ".",
        "--force",
    ]
    if device == "remote":
        cmd.append("--remote")
        cmd.extend(["--device", "auto"])  # ignored under --remote but required to parse
        if chunk_min is not None:
            cmd.extend(["--chunk-min", str(chunk_min)])
    elif device in _SONG_REMOVER_LOCAL_DEVICES:
        cmd.extend(["--device", device])
    else:
        raise ValueError(
            f"unknown device {device!r}; expected one of "
            f"'remote', 'cpu', 'mps', 'auto'"
        )
    return cmd


def separate(
    raw_mp4: Path,
    device: str = "remote",
    chunk_min: int | None = 5,
    force: bool = False,
) -> StemsResult:
    """Run song-remover on ``raw_mp4`` (cache-aware).

    Returns a ``StemsResult``; ``from_cache=True`` means song-remover was
    NOT invoked because the on-disk stems still match ``raw_mp4``'s meta.
    """
    t_start = time.monotonic()

    if not raw_mp4.exists():
        raise FileNotFoundError(f"raw mp4 not found: {raw_mp4}")

    bv_dir = raw_mp4.parent / raw_mp4.stem
    speech_wav = bv_dir / "speech.wav"
    music_wav = bv_dir / "music.wav"
    sfx_wav = bv_dir / "sfx.wav"
    no_music_wav = bv_dir / "no_music.wav"
    no_music_gain_txt = bv_dir / "no_music_gain.txt"
    meta_path = bv_dir / META_FILENAME

    expected = _expected_source_meta(raw_mp4)

    # Cache hit predicate: speech.wav present AND sidecar matches the current mp4.
    # The other three stems are best-effort (downstream only needs speech.wav);
    # we don't gate on their presence.
    if not force and speech_wav.exists() and meta.meta_matches(meta_path, expected):
        return StemsResult(
            bv_dir=bv_dir,
            speech_wav=speech_wav,
            music_wav=music_wav,
            sfx_wav=sfx_wav,
            no_music_wav=no_music_wav,
            no_music_gain_txt=no_music_gain_txt if no_music_gain_txt.exists() else None,
            from_cache=True,
            elapsed=time.monotonic() - t_start,
        )

    # Cache miss → invoke song-remover.
    cmd = _build_argv(raw_mp4, device, chunk_min)
    completed = subprocess.run(
        cmd,
        cwd=raw_mp4.parent,
        check=True,
        capture_output=True,
        text=True,
    )

    if not speech_wav.exists():
        # song-remover exited 0 but didn't produce our expected output. Surface
        # the captured stderr so the user can diagnose (Modal model not
        # deployed, checkpoint download stalled, etc.).
        stderr_tail = (completed.stderr or "").strip().splitlines()[-20:]
        raise RuntimeError(
            f"song-remover exited 0 but did not produce {speech_wav}.\n"
            f"argv={cmd} cwd={raw_mp4.parent}\n"
            f"This usually means the model checkpoint or Modal app deploy "
            f"is missing — see CLAUDE.md 'External dependencies'.\n"
            f"stderr tail:\n  " + "\n  ".join(stderr_tail)
        )

    # Record the meta sidecar AFTER song-remover succeeds, so a mid-run crash
    # leaves the previous sidecar (if any) as the source of truth.
    meta.write_meta(meta_path, expected)

    return StemsResult(
        bv_dir=bv_dir,
        speech_wav=speech_wav,
        music_wav=music_wav,
        sfx_wav=sfx_wav,
        no_music_wav=no_music_wav,
        no_music_gain_txt=no_music_gain_txt if no_music_gain_txt.exists() else None,
        from_cache=False,
        elapsed=time.monotonic() - t_start,
    )


def song_remover_on_path() -> bool:
    """Preflight helper: is the ``song-remover`` CLI installed?"""
    return shutil.which("song-remover") is not None
