"""CLI entry point for ``video2yt-subtitle``.

Spec: docs/superpowers/specs/2026-05-14-video2yt-subtitle-design.md
"""

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

from video2yt import subtitle, validate
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


def _default_output(segment: Path) -> Path:
    return segment.parent / f"{segment.stem}_subbed.mp4"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="video2yt-subtitle",
        description=(
            "Detect whether a Bilibili segment already has bottom subtitles "
            "(via danmaku XML scan, visual OCR sample, or manual flag); "
            "if not, add STT-generated subtitles via SenseVoice + Codex cleanup."
        ),
    )
    parser.add_argument(
        "segment", type=Path,
        help="Input MP4 segment (1920x1080 30fps h264)",
    )
    parser.add_argument(
        "--danmaku", type=Path, default=None,
        help="Bilibili danmaku XML (enables danmaku detection signal)",
    )
    parser.add_argument(
        "--glossary", type=Path, default=None,
        help="Override packaged glossary YAML (default: bundled bg_glossary.yaml)",
    )

    force = parser.add_mutually_exclusive_group()
    force.add_argument(
        "--force-add", dest="force", action="store_const", const="add",
        help="Skip detection and force-burn subtitles",
    )
    force.add_argument(
        "--force-skip", dest="force", action="store_const", const="skip",
        help="Skip detection and passthrough",
    )

    parser.add_argument(
        "--enable-ocr", action="store_true",
        help=(
            "Enable OCR-based detection of pre-burned bottom subtitles. "
            "OFF by default: game UI (e.g. Hearthstone Battlegrounds hand cards) "
            "is also stable bottom text and triggers false positives. "
            "Turn on for source material where the bottom of the frame is plain "
            "(e.g. talking-head streams) and you want to detect burnt-in subs."
        ),
    )
    parser.add_argument("--ocr-interval", type=float, default=5.0,
                        help="Only meaningful with --enable-ocr")
    parser.add_argument("--danmaku-min-fixed", type=int, default=10)
    parser.add_argument("--danmaku-min-coverage", type=float, default=30,
                        help="Coverage percentage threshold (0-100)")

    parser.add_argument("--force-asr", action="store_true")
    parser.add_argument("--force-cleanup", action="store_true")
    parser.add_argument("--skip-cleanup", action="store_true")

    parser.add_argument("--font-face", default="Hiragino Sans GB")
    parser.add_argument("--font-size", type=int, default=None,
                        help="Default: auto (height * 25/540)")
    parser.add_argument("--outline-px", type=int, default=4)
    parser.add_argument("--shadow-px", type=int, default=2)

    parser.add_argument(
        "-o", "--output", type=Path, default=None,
        help="Output MP4. Default: <segment_stem>_subbed.mp4",
    )
    return parser.parse_args(argv)


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

    output = args.output or _default_output(args.segment)

    # Decision
    danmaku_signal = None
    if args.danmaku is not None and args.force is None:
        danmaku_signal = subtitle.scan_danmaku(
            args.danmaku, segment_duration=info.duration,
            min_fixed=args.danmaku_min_fixed,
            min_coverage_ratio=args.danmaku_min_coverage / 100.0,
        )
        _log(
            f"danmaku scan: {danmaku_signal.fixed_count} type=4 fixed, "
            f"{danmaku_signal.coverage_ratio * 100:.1f}% coverage "
            f"→ {'HIT' if danmaku_signal.hit else 'continue'}"
        )

    ocr_signal = None
    if args.enable_ocr and args.force is None and (danmaku_signal is None or not danmaku_signal.hit):
        ocr_signal = subtitle.sample_ocr(
            args.segment, segment_duration=info.duration,
            interval_seconds=args.ocr_interval,
        )
        _log(
            f"OCR sample: {ocr_signal.frames_with_stable_text}/{ocr_signal.sampled_frames} "
            f"frames with stable bottom text ({ocr_signal.stable_text_ratio * 100:.1f}%) "
            f"→ {'HIT' if ocr_signal.hit else 'continue'}"
        )

    decision = subtitle.decide(force=args.force, danmaku=danmaku_signal, ocr=ocr_signal)
    _log(f"decision: {decision.reason}")

    if not decision.add_subtitles:
        subtitle.passthrough(args.segment, output)
        _log(f"passthrough -> {output}")
        return output

    # ASR (with cache)
    raw_srt_path = args.segment.parent / f"{args.segment.stem}.raw.srt"
    if raw_srt_path.exists() and not args.force_asr:
        _log(f"ASR cache hit: {raw_srt_path.name}")
        raw_segments = subtitle.parse_srt_to_segments(
            raw_srt_path.read_text(encoding="utf-8")
        )
    else:
        t0 = time.time()
        _log(f"ASR: SenseVoice-Small on {info.duration:.2f}s audio...")
        raw_segments = subtitle.transcribe(args.segment)
        raw_srt_path.write_text(
            subtitle.segments_to_srt(raw_segments), encoding="utf-8"
        )
        _log(f"ASR done in {time.time() - t0:.1f}s ({len(raw_segments)} segments)")

    # Cleanup (with cache)
    cleaned_srt_path = args.segment.parent / f"{args.segment.stem}.cleaned.srt"
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

    # Split (style-dependent, never cached)
    font_size = args.font_size if args.font_size is not None else max(int(info.height * 25 / 540), 24)
    max_line_chars = _effective_chars_per_line(
        font_size=font_size, video_width=info.width, margin_l=80, margin_r=80,
    )
    final_entries = subtitle.split_segments(cleaned_segments, max_line_chars=max_line_chars)
    _log(f"split: {len(cleaned_segments)} cleaned → {len(final_entries)} final SRT entries (MAX_LINE_CHARS={max_line_chars})")

    # Burn
    t0 = time.time()
    _log(f"burn: subtitles → {output}")
    subtitle.burn_subtitles(
        args.segment, final_entries, output,
        font_face=args.font_face, font_size=font_size,
        outline_px=args.outline_px, shadow_px=args.shadow_px,
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
