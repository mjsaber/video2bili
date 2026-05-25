"""``video2yt-stems`` — Stage 2 entry point.

Wraps ``stems.separate`` with the standard CLI shape. The actual work
(invoking song-remover, cache-meta sidecar) lives in ``stems.py``.

Spec: ``docs/superpowers/specs/2026-05-24-step6-restructure.md`` §7
``video2yt-stems``.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from video2yt import stems


def _log(msg: str) -> None:
    print(f"[video2yt-stems] {msg}", file=sys.stderr)


def preflight(device: str = "remote") -> None:
    """Fail fast if ``song-remover`` is not on PATH. When ``device='remote'``,
    additionally check that the Modal token file exists — without it the
    remote path fails mid-pipeline with a less useful Modal-internal error."""
    if not stems.song_remover_on_path():
        raise RuntimeError(
            "song-remover not found in PATH. One-time install: "
            "cd ~/code/song-remover && uv tool install '.[remote]'. "
            "Then for the default --device remote path, complete the Modal "
            "setup (see CLAUDE.md 'External dependencies')."
        )
    if device == "remote":
        modal_token = Path.home() / ".modal.toml"
        if not modal_token.exists():
            raise RuntimeError(
                f"Modal token not found at {modal_token}. The default "
                f"--device remote path needs one-time Modal setup. From "
                f"the song-remover repo: "
                f"`uv run modal token new && uv run modal deploy -m modal_app.prep "
                f"&& uv run modal run -m modal_app.prep && "
                f"uv run modal deploy -m modal_app.separator`. "
                f"Or pass --device cpu to run locally."
            )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="video2yt-stems",
        description=(
            "Stage 2 of the per-segment pipeline: run song-remover on a raw "
            "mp4 to produce speech.wav + music.wav + sfx.wav + no_music.wav. "
            "Downstream stages consume only speech.wav."
        ),
    )
    parser.add_argument("raw_mp4", type=Path, help="The <bv>.mp4 produced by video2yt-fetch.")
    parser.add_argument(
        "--device", default="remote",
        choices=["cpu", "mps", "auto", "remote"],
        help=(
            "song-remover separation device. Default: 'remote' (Modal T4 "
            "GPU; ~7.2× faster than local CPU). Use 'cpu' for offline runs."
        ),
    )
    parser.add_argument(
        "--chunk-min", type=int, default=5,
        help=(
            "Chunk length in minutes for --device remote (ignored otherwise). "
            "Default 5 (matches song-remover's own default). Lower it for "
            "more parallelism on long inputs (e.g. 3); set to 0 to disable."
        ),
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Bypass cache and re-invoke song-remover even if speech.wav matches.",
    )
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> stems.StemsResult:
    preflight(device=args.device)
    if not args.raw_mp4.exists():
        raise FileNotFoundError(f"raw mp4 not found: {args.raw_mp4}")
    _log(
        f"separating {args.raw_mp4.name} on device={args.device} "
        f"chunk_min={args.chunk_min} force={args.force}"
    )
    result = stems.separate(
        raw_mp4=args.raw_mp4,
        device=args.device,
        chunk_min=args.chunk_min if args.device == "remote" else None,
        force=args.force,
    )
    cache_tag = " (cached)" if result.from_cache else ""
    _log(f"speech: {result.speech_wav}{cache_tag}")
    _log(
        f"other stems on disk: music={result.music_wav.exists()} "
        f"sfx={result.sfx_wav.exists()} "
        f"no_music={result.no_music_wav.exists()}"
    )
    return result


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
    except SystemExit as e:
        return int(e.code or 0)
    try:
        result = run(args)
        _log(
            f"success: {result.speech_wav}  "
            f"elapsed={result.elapsed:.1f}s  from_cache={result.from_cache}"
        )
        return 0
    except KeyboardInterrupt:
        _log("cancelled")
        return 130
    except subprocess.CalledProcessError as e:
        tool = e.cmd[0] if e.cmd else "subprocess"
        _log(f"error: {tool} failed with exit {e.returncode}")
        if e.stderr:
            print(e.stderr, file=sys.stderr)
        return 1
    except FileNotFoundError as e:
        _log(f"error: {e}")
        return 1
    except RuntimeError as e:
        # RuntimeError covers preflight failures (song-remover missing,
        # Modal not configured) per plan §"Step 6: preflight ... exit 2".
        _log(f"error: {e}")
        return 2
