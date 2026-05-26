"""CLI entry point for ``video2yt-subtitle``.

Spec: ``docs/superpowers/specs/2026-05-24-step6-restructure.md`` §4 Stage 3
+ §7 ``video2yt-subtitle`` + §11 Q9.

Stage 3 of the new five-stage pipeline. Input is ``<dir>/<bv>.mp4`` (kept
so ffprobe can recover width/height for ASS PlayResX/Y); the audio source
for ASR + silencedetect is ``<dir>/<bv>/speech.wav`` (a sibling, produced
by Stage 2 ``video2yt-stems``).

Cache invalidation chain: ``<bv>/.speech_source_meta.json`` records the
first-1MB sha256 of ``speech.wav``. On mismatch (because Stage 2
regenerated speech.wav), Stage 3 deletes ``speech.raw.srt`` AND every
``speech.cleaned.*.srt`` (glob — covers all historical thresholds) and
rewrites the sidecar before rerunning ASR + cleanup. Avoids the subtle
"fresh raw.srt + stale cleaned.<old-threshold>.srt silently wins" bug
flagged in codex review.
"""

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

from video2yt import compose, meta, subtitle, validate
from video2yt.compose import _effective_chars_per_line


def _log(msg: str) -> None:
    print(f"[video2yt-subtitle] {msg}", file=sys.stderr)


def preflight() -> None:
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg not found in PATH. brew install ffmpeg")
    if shutil.which("ffprobe") is None:
        raise RuntimeError("ffprobe not found in PATH")
    if shutil.which("codex") is None:
        raise RuntimeError(
            "codex CLI not found in PATH. brew install codex && codex login"
        )
    try:
        __import__("whisperx")
    except ImportError as e:
        raise RuntimeError(
            "whisperx not installed (this should be a top-level dep). "
            "Run: uv sync"
        ) from e


def _threshold_filename_suffix(threshold: float) -> str:
    """Encode a pause-split threshold as a safe filename token.

    Examples: 0.6 → ``p0p6``, 1.25 → ``p1p25``, 0 → ``p0``. Used in
    ``<stem>.cleaned.{suffix}.srt`` so changing the threshold invalidates
    the cleanup cache (since cleanup input depends on pause-split output).
    """
    return "p" + format(threshold, "g").replace(".", "p").replace("-", "neg")


def _default_output(segment: Path) -> Path:
    return segment.parent / f"{segment.stem}_subbed.mp4"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="video2yt-subtitle",
        description=(
            "Stage 3 of the per-segment pipeline: run whisperx ASR on the "
            "sibling <bv>/speech.wav (produced by video2yt-stems), clean the "
            "transcript with Codex, and write <bv>/speech.cleaned.ass for "
            "Stage 5 (burn) to pick up. Also produces a stand-alone "
            "<bv>_subbed.mp4 preview for dev/eyeball checks."
        ),
    )
    parser.add_argument(
        "segment", type=Path,
        help="Input MP4 segment (1920x1080 30fps h264). Used for ffprobe "
             "dimensions and as the burn input; the audio source for ASR is "
             "<segment_dir>/<segment_stem>/speech.wav (sibling).",
    )
    parser.add_argument(
        "--glossary", type=Path, default=None,
        help="Override packaged glossary YAML (default: bundled bg_glossary.yaml)",
    )

    parser.add_argument("--force-asr", action="store_true")
    parser.add_argument("--force-cleanup", action="store_true")
    parser.add_argument("--skip-cleanup", action="store_true")
    parser.add_argument(
        "--pause-split-seconds", type=float, default=0.6,
        help=(
            "Split ASR segments at any word-level pause >= this many seconds "
            "(needs whisperx forced alignment, adds ~2-3 min). 0 disables. "
            "Default: 0.6s — typical inter-sentence pauses are 0.3-0.8s."
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
            "bigger/bolder style validated on the dragon_snip baseline. "
            "(Earlier 2026-05-24 experiment with margin_v=15 + smaller font "
            "was reverted 2026-05-25 after A/B against the original style.)"
        ),
    )

    parser.add_argument(
        "-o", "--output", type=Path, default=None,
        help="Output MP4. Default: <segment_stem>_subbed.mp4",
    )
    parser.add_argument(
        "--no-preview-burn", action="store_true",
        help=(
            "Skip the legacy preview burn (don't produce <segment_stem>_subbed.mp4). "
            "Use this from the T7 orchestrator path, which invokes Stage 5 "
            "(burn) directly with the speech.cleaned.ass produced here — the "
            "preview re-encode is just wasted work in that flow."
        ),
    )
    return parser.parse_args(argv)


def _invalidate_subtitle_caches(bv_dir: Path) -> int:
    """Delete speech.raw.srt AND every speech.cleaned.*.srt under ``bv_dir``.

    Returns the count of files deleted. Called when the
    ``.speech_source_meta.json`` sidecar mismatches the current speech.wav
    (i.e. Stage 2 regenerated speech.wav). The glob covers ALL threshold
    variants, not just the current run's threshold — see spec §11 Q9.
    """
    deleted = 0
    raw = bv_dir / "speech.raw.srt"
    if raw.exists():
        raw.unlink()
        deleted += 1
    for stale in bv_dir.glob("speech.cleaned.*.srt"):
        stale.unlink()
        deleted += 1
    return deleted


def run(args: argparse.Namespace) -> Path:
    preflight()

    if not args.segment.is_file():
        raise FileNotFoundError(f"segment not found: {args.segment}")

    info = validate.probe(args.segment)
    if info.width != 1920 or info.height != 1080:
        raise ValueError(
            f"input resolution {info.width}x{info.height} != 1920x1080"
        )

    _log(f"input: {args.segment.name} ({info.width}x{info.height}, {info.duration:.2f}s)")

    # Sibling lookup for stems (T4: replaces the old <input>.vocals.wav
    # sibling lookup that depended on video2yt-music-swap output). Errors
    # cleanly if Stage 2 hasn't run yet.
    bv_dir = args.segment.parent / args.segment.stem
    speech_wav = bv_dir / "speech.wav"
    if not speech_wav.is_file():
        raise FileNotFoundError(
            f"required stem not found: {speech_wav}. "
            f"Run video2yt-stems on {args.segment.name} first."
        )

    output = args.output or _default_output(args.segment)

    # Cache invalidation chain (single point — see module docstring + spec §11 Q9).
    # On speech.wav change, drop raw.srt AND every cleaned.*.srt (glob covers
    # all historical thresholds; the current threshold is just one of them).
    speech_meta_path = bv_dir / ".speech_source_meta.json"
    expected_speech_meta = {"sha256": meta.compute_first_1mb_sha256(speech_wav)}
    if not meta.meta_matches(speech_meta_path, expected_speech_meta):
        n_dropped = _invalidate_subtitle_caches(bv_dir)
        if n_dropped > 0:
            _log(
                f"speech.wav changed since last run — invalidated "
                f"{n_dropped} stale SRT cache file(s)"
            )
        meta.write_meta(speech_meta_path, expected_speech_meta)

    # ASR (cache: speech.raw.srt under bv_dir; invalidated above on
    # speech.wav change, so simple presence-check is correct here).
    raw_srt_path = bv_dir / "speech.raw.srt"
    if raw_srt_path.exists() and not args.force_asr:
        _log(f"ASR cache hit: {raw_srt_path.name}")
        raw_segments = subtitle.parse_srt_to_segments(
            raw_srt_path.read_text(encoding="utf-8")
        )
    else:
        t0 = time.time()
        _log(f"ASR: whisperx (large-v3) on {speech_wav.name}...")
        raw_segments = subtitle.transcribe(speech_wav)
        raw_srt_path.write_text(
            subtitle.segments_to_srt(raw_segments), encoding="utf-8"
        )
        _log(f"ASR done in {time.time() - t0:.1f}s ({len(raw_segments)} segments)")

    # Pause-split via silencedetect on speech.wav directly (was: on the
    # Demucs vocals.wav sidecar; song-remover's speech.wav is the cleaner
    # input). Alignment-based pause-split was removed 2026-05-23.
    if args.pause_split_seconds > 0:
        t0 = time.time()
        _log(f"silencedetect on {speech_wav.name}...")
        silences = subtitle.detect_silences(
            speech_wav,
            noise_db=-40.0,
            min_duration_s=args.pause_split_seconds,
        )
        pre_count = len(raw_segments)
        raw_segments = subtitle._split_segments_on_silences(
            raw_segments, silences,
            min_split_seconds=args.pause_split_seconds,
        )
        _log(
            f"silencedetect: {len(silences)} silence(s) >={args.pause_split_seconds}s; "
            f"pause-split: {pre_count} → {len(raw_segments)} segments "
            f"({time.time() - t0:.1f}s)"
        )

    # Cleanup (threshold-keyed cache because cleanup input depends on
    # pause-split output. Sidecar-invalidation above ensures we don't reuse
    # a cleanup file derived from a previous speech.wav.).
    th_suffix = _threshold_filename_suffix(args.pause_split_seconds)
    cleaned_srt_path = bv_dir / f"speech.cleaned.{th_suffix}.srt"
    if args.skip_cleanup:
        cleaned_segments = raw_segments
        _log("cleanup skipped (--skip-cleanup)")
    elif cleaned_srt_path.exists() and not args.force_cleanup:
        _log(f"cleanup cache hit: {cleaned_srt_path.name}")
        cleaned_segments = subtitle.parse_srt_to_segments(
            cleaned_srt_path.read_text(encoding="utf-8")
        )
    else:
        t0 = time.time()
        glossary = subtitle.load_glossary(args.glossary)
        _log(f"cleanup: codex exec with {len(glossary.corrections)} corrections...")
        cleaned_segments = subtitle.cleanup_with_codex(raw_segments, glossary)
        cleaned_srt_path.write_text(
            subtitle.segments_to_srt(cleaned_segments), encoding="utf-8"
        )
        _log(f"cleanup done in {time.time() - t0:.1f}s")

    # Split (style-dependent, never cached).
    font_size = args.font_size if args.font_size is not None else max(int(info.height * 25 / 540), 24)
    max_line_chars = _effective_chars_per_line(
        font_size=font_size, video_width=info.width, margin_l=80, margin_r=80,
    )
    final_entries = subtitle.split_segments(cleaned_segments, max_line_chars=max_line_chars)
    _log(f"split: {len(cleaned_segments)} cleaned → {len(final_entries)} final SRT entries (MAX_LINE_CHARS={max_line_chars})")

    # T4 NEW: write speech.cleaned.ass alongside speech.wav for Stage 5
    # (burn) to pick up. Always rebuilt (sub-second; style params can
    # change between runs without touching the SRT cache).
    cleaned_ass_path = bv_dir / "speech.cleaned.ass"
    final_srt_text = subtitle.segments_to_srt(final_entries)
    ass_text = compose.srt_to_ass(
        srt_text=final_srt_text,
        video_width=info.width,
        video_height=info.height,
        font_face=args.font_face,
        font_size=font_size,
        position="bottom",
        outline_px=args.outline_px,
        shadow_px=args.shadow_px,
        margin_v=args.margin_v,
    )
    cleaned_ass_path.write_text(ass_text, encoding="utf-8")
    _log(f"wrote burn-ready ASS: {cleaned_ass_path.relative_to(args.segment.parent)}")

    if args.no_preview_burn:
        _log("skipping legacy preview burn (--no-preview-burn)")
        return cleaned_ass_path

    # Burn (legacy preview output — Stage 5 (T6) will replace this when the
    # T7 orchestrator wires up the full pipeline. Pass --no-preview-burn to
    # skip this step).
    t0 = time.time()
    _log(f"burn: subtitles → {output}")
    subtitle.burn_subtitles(
        args.segment, final_entries, output,
        font_face=args.font_face, font_size=font_size,
        outline_px=args.outline_px, shadow_px=args.shadow_px,
        margin_v=args.margin_v,
        video_width=info.width, video_height=info.height,
    )
    _log(f"burn done in {time.time() - t0:.1f}s")

    out_info = validate.probe(output)
    if abs(out_info.duration - info.duration) > 1.0:
        raise ValueError(
            f"output duration {out_info.duration:.2f}s differs from input {info.duration:.2f}s by > 1s"
        )

    _log(f"success: {output}")
    return output


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
        _log(f"error: {(e.cmd[0] if e.cmd else 'subprocess')} failed with exit {e.returncode}")
        if e.stderr:
            print(e.stderr, file=sys.stderr)
        return 3
