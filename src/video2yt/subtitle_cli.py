"""CLI entry point for ``video2yt-subtitle`` — Stage 3 of the per-segment pipeline.

Plan: ``docs/superpowers/plans/2026-05-27-speech2srt-integration.md`` (v3).

Stage 3 invokes the external ``speech2srt`` CLI (Volcengine 豆包 Seed-ASR +
codex cleanup with a per-project free-form context). The subprocess writes
``<bv>/speech.cleaned.srt``; this CLI converts it to ``<bv>/speech.cleaned.ass``
via ``compose.srt_to_ass`` for Stage 5 (burn) to consume.

External dependencies (preflight-checked):
- ``ffmpeg`` / ``ffprobe`` on PATH (used by ``validate.probe``).
- ``speech2srt`` on PATH (``uv tool install ~/code/speech2srt``).
- ``VOLCENGINE_API_KEY`` either exported or in ``.env`` (speech2srt loads
  ``.env`` from its cwd; we don't validate the env var here — failures
  surface as speech2srt exit code 1 with a clear message).

Inputs:
- ``<dir>/<bv>.mp4`` (positional ``segment``; ffprobe-probed for ASS
  PlayResX/Y + max_line_chars computation).
- ``<dir>/<bv>/speech.wav`` (sibling; produced by ``video2yt-stems``).
- ``--context-file PATH`` (per-project free-form cleanup context; threaded
  to ``speech2srt --cleanup --context-file``; T2 of this plan).

Outputs:
- ``<bv>/speech.cleaned.srt`` (the speech2srt subprocess writes here; we
  pass ``-o`` to land it next to the ASS so the SRT is easy to inspect).
- ``<bv>/speech.cleaned.ass`` (Stage 5 contract; always regenerated).

The legacy preview-burn path (``<segment_stem>_subbed.mp4``) was dropped
in T3. The orchestrator always passes ``--no-preview-burn`` so the preview
re-encode was dead in production; standalone dev users can run Stage 5
directly or just inspect the ASS file.
"""

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from video2yt import compose, validate
from video2yt.compose import _effective_chars_per_line

# Hard wall-clock cap for the speech2srt subprocess. speech2srt has its own
# --cleanup-timeout (default 1200s = 20 min) for the codex step; we set a
# wider outer bound to also cover ASR upload + Volcengine polling. 30 min
# is comfortable for the worst-case 17-min segment seen in production.
SPEECH2SRT_TIMEOUT_SECONDS = 1800


def _log(msg: str) -> None:
    print(f"[video2yt-subtitle] {msg}", file=sys.stderr)


def preflight() -> None:
    """Check external tools needed by Stage 3.

    VOLCENGINE_API_KEY is NOT validated here. speech2srt loads .env from
    its cwd and reports a missing key as exit 1 with a clear message; we
    propagate that exit code unchanged.
    """
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg not found in PATH. brew install ffmpeg")
    if shutil.which("ffprobe") is None:
        raise RuntimeError("ffprobe not found in PATH")
    if shutil.which("speech2srt") is None:
        raise RuntimeError(
            "speech2srt not found in PATH. Install via: "
            "cd ~/code/speech2srt && uv tool install . --force"
        )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="video2yt-subtitle",
        description=(
            "Stage 3 of the per-segment pipeline: run speech2srt (Volcengine "
            "Seed-ASR + codex cleanup) on <bv>/speech.wav and write "
            "<bv>/speech.cleaned.ass for Stage 5 (burn) to pick up."
        ),
    )
    parser.add_argument(
        "segment", type=Path,
        help=(
            "Input MP4 segment (1920x1080 30fps h264). Used for ffprobe "
            "dimensions and as the burn input; the audio source for ASR is "
            "<segment_dir>/<segment_stem>/speech.wav (sibling)."
        ),
    )
    parser.add_argument(
        "--context-file", type=Path, default=None, dest="context_file",
        help=(
            "Per-project free-form cleanup context for speech2srt --cleanup "
            "(plain UTF-8 text, ≤ 2 KB; describes streamer, 流派, key cards, "
            "口頭禪, known ASR errors). T2 of the speech2srt-integration plan. "
            "No sibling fallback — pass explicitly. When --cleanup is on and "
            "this flag is omitted, a stderr warning is emitted and "
            "speech2srt runs without context (quality is lower)."
        ),
    )

    parser.add_argument(
        "--force-asr", action="store_true",
        help=(
            "Delete speech2srt's canonical cache (<wav>.speech2srt.json and "
            "<wav>.speech2srt.srt) before running so the ASR + cleanup is "
            "regenerated fresh and the cache is repopulated with the new "
            "result. Does NOT pass --no-cache (which would skip the cache "
            "store too)."
        ),
    )
    parser.add_argument(
        "--skip-cleanup", action="store_true",
        help=(
            "Omit speech2srt --cleanup. The output SRT is raw Seed-ASR with "
            "no codex post-processing. --context-file becomes irrelevant in "
            "this mode."
        ),
    )

    parser.add_argument("--font-face", default="Hiragino Sans GB")
    parser.add_argument("--font-size", type=int, default=None,
                        help="Default: auto (height * 25/540, min 24)")
    parser.add_argument("--outline-px", type=int, default=4)
    parser.add_argument("--shadow-px", type=int, default=2)
    parser.add_argument(
        "--margin-v", type=int, default=80,
        help=(
            "ASS MarginV in pixels (distance from bottom edge for "
            "bottom-aligned subtitles). Default: 80 — matches the pre-298fad4 "
            "bigger/bolder style validated on the dragon_snip baseline."
        ),
    )

    parser.add_argument(
        "--no-preview-burn", action="store_true",
        help=(
            "Retained for backwards CLI compat with the T7 orchestrator. T3 "
            "of the speech2srt-integration plan dropped the legacy preview "
            "burn entirely — this flag is now a no-op. Stage 3's only output "
            "is <bv>/speech.cleaned.ass."
        ),
    )
    return parser.parse_args(argv)


def _resolve_context_file(
    context_file: Path | None, skip_cleanup: bool,
) -> tuple[Path | None, bool]:
    """Resolve the speech2srt --context-file path. T2 of the
    speech2srt-integration plan.

    Returns (resolved_path, emit_warning):
    - `--skip-cleanup` is set → (None, False). No cleanup, no context, no warning.
    - `context_file` is set → validate it exists; (path, False).
    - `context_file` is None and cleanup is on → (None, True). speech2srt's
      cleanup still runs (works without context), but quality is lower; the
      caller emits the warning.

    No sibling-file fallback. Codex v1 review caught that `<segment>.parent`
    lands in `temp/<dir>/` (not the project folder) under the full-pipeline
    orchestrator, so any sibling fallback would be useless or surprising.

    Raises FileNotFoundError when an explicit path doesn't exist; main()
    maps that to exit 2.
    """
    if skip_cleanup:
        return None, False
    if context_file is None:
        return None, True
    if not context_file.is_file():
        raise FileNotFoundError(f"context file not found: {context_file}")
    return context_file, False


def _build_speech2srt_argv(
    speech_wav: Path,
    srt_out: Path,
    context_path: Path | None,
    skip_cleanup: bool,
    max_line_chars: int,
) -> list[str]:
    """Assemble the speech2srt subprocess argv per the locked T3 contract.

    Always passes ``--force`` (authorizes overwrite of -o; does NOT affect
    speech2srt's own cache). Does NOT pass ``--no-cache``; force-regen is
    handled by deleting speech2srt's sidecar files BEFORE invocation (see
    ``run()``'s --force-asr branch).
    """
    argv = [
        "speech2srt",
        str(speech_wav),
        "-o", str(srt_out),
        "--max-line-chars", str(max_line_chars),
        "--force",
    ]
    if not skip_cleanup:
        argv.append("--cleanup")
        if context_path is not None:
            argv.extend(["--context-file", str(context_path)])
    return argv


def _delete_speech2srt_sidecars(speech_wav: Path) -> None:
    """Remove speech2srt's canonical cache pair (no-op if missing).

    speech2srt writes ``<wav>.speech2srt.json`` (sidecar) and
    ``<wav>.speech2srt.srt`` (canonical SRT) next to the input wav. Deleting
    both forces a fresh ASR + cleanup on the next invocation. We chose this
    over speech2srt's own ``--no-cache`` (which also skips the cache STORE)
    so the new result repopulates the cache normally.
    """
    sidecar_json = speech_wav.parent / f"{speech_wav.name}.speech2srt.json"
    sidecar_srt = speech_wav.parent / f"{speech_wav.name}.speech2srt.srt"
    sidecar_json.unlink(missing_ok=True)
    sidecar_srt.unlink(missing_ok=True)


def run(args: argparse.Namespace) -> Path:
    """Stage 3 entry: speech2srt subprocess → SRT → ASS.

    Returns the path to the written ``<bv>/speech.cleaned.ass``.
    """
    preflight()

    if not args.segment.is_file():
        raise FileNotFoundError(f"segment not found: {args.segment}")

    info = validate.probe(args.segment)
    if info.width != 1920 or info.height != 1080:
        raise ValueError(
            f"input resolution {info.width}x{info.height} != 1920x1080"
        )

    _log(
        f"input: {args.segment.name} "
        f"({info.width}x{info.height}, {info.duration:.2f}s)"
    )

    bv_dir = args.segment.parent / args.segment.stem
    speech_wav = bv_dir / "speech.wav"
    if not speech_wav.is_file():
        raise FileNotFoundError(
            f"required stem not found: {speech_wav}. "
            f"Run video2yt-stems on {args.segment.name} first."
        )

    context_path, emit_warn = _resolve_context_file(
        args.context_file, args.skip_cleanup,
    )
    if emit_warn:
        _log(
            "WARNING: --cleanup is on but no --context-file provided; "
            "speech2srt will run without context (lower quality). Pass "
            "--context-file <path> to a per-project subtitle_context.txt."
        )

    font_size = (
        args.font_size
        if args.font_size is not None
        else max(int(info.height * 25 / 540), 24)
    )
    max_line_chars = _effective_chars_per_line(
        font_size=font_size, video_width=info.width, margin_l=80, margin_r=80,
    )

    cleaned_srt_path = bv_dir / "speech.cleaned.srt"

    if args.force_asr:
        _delete_speech2srt_sidecars(speech_wav)
        _log("--force-asr: deleted speech2srt canonical sidecars")

    argv = _build_speech2srt_argv(
        speech_wav=speech_wav,
        srt_out=cleaned_srt_path,
        context_path=context_path,
        skip_cleanup=args.skip_cleanup,
        max_line_chars=max_line_chars,
    )

    t0 = time.time()
    _log(f"speech2srt: {speech_wav.name} → {cleaned_srt_path.name}...")
    result = subprocess.run(
        argv, check=False, timeout=SPEECH2SRT_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        raise subprocess.CalledProcessError(result.returncode, argv)
    _log(f"speech2srt done in {time.time() - t0:.1f}s")

    if not cleaned_srt_path.is_file():
        raise RuntimeError(
            f"speech2srt exited 0 but {cleaned_srt_path} was not written"
        )

    cleaned_srt_text = cleaned_srt_path.read_text(encoding="utf-8")
    ass_text = compose.srt_to_ass(
        srt_text=cleaned_srt_text,
        video_width=info.width,
        video_height=info.height,
        font_face=args.font_face,
        font_size=font_size,
        position="bottom",
        outline_px=args.outline_px,
        shadow_px=args.shadow_px,
        margin_v=args.margin_v,
    )
    cleaned_ass_path = bv_dir / "speech.cleaned.ass"
    cleaned_ass_path.write_text(ass_text, encoding="utf-8")
    _log(
        f"wrote burn-ready ASS: "
        f"{cleaned_ass_path.relative_to(args.segment.parent)}"
    )

    return cleaned_ass_path


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        run(args)
        return 0
    except FileNotFoundError as e:
        _log(f"error: {e}")
        return 2
    except ValueError as e:
        _log(f"error: {e}")
        return 2
    except RuntimeError as e:
        _log(f"error: {e}")
        return 1
    except subprocess.CalledProcessError as e:
        _log(f"error: speech2srt failed with exit {e.returncode}")
        # Propagate speech2srt's exit code unchanged so callers can
        # distinguish auth (3) from quota (4) from network (5) etc.
        return e.returncode if e.returncode else 3
    except subprocess.TimeoutExpired:
        _log(f"error: speech2srt timed out after {SPEECH2SRT_TIMEOUT_SECONDS}s")
        return 5
