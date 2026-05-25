import argparse
import importlib
import shutil
import subprocess
import sys
import time
from pathlib import Path

from video2yt import burn, cuts, download, fetch, music_mix, stems, validate

# Re-exports: fetch.py is the canonical home for these (T2 of step6-restructure).
# Each name is reached as `cli.<name>` by either compose_cli/merge_cli or tests.
# Constants left off (BV_PATTERN, REFERENCE_*, MAX_TITLE_DIR_LENGTH,
# UPLOADER_*): no caller accesses them via `cli.`.
_build_dir_name = fetch._build_dir_name
_sanitize_title = fetch._sanitize_title
compute_font_size = fetch.compute_font_size
extract_bv_id = fetch.extract_bv_id


def _build_output_filename(
    bv_id: str,
    has_cut: bool,
    speed: float,
    has_preview: bool,
) -> str:
    """Build the per-run output filename with suffixes describing what's IN the output.

    Format: ``<bv_id>_final[_cut][_<speed>x][_preview].mp4`` (T7 of
    step6-restructure replaced the legacy ``_with_danmaku`` /
    ``_clean`` / ``_subbed`` pipeline-stage suffixes with a single
    ``_final``; the new orchestrator does all three in one ffmpeg pass).

    The suffix order is fixed (cut, speed, preview) so a given parameter
    combination always produces the same filename. Default filename
    (no modifiers) is ``<bv_id>_final.mp4``.
    """
    parts = []
    if has_cut:
        parts.append("cut")
    if speed != 1.0:
        parts.append(f"{speed:g}x")
    if has_preview:
        parts.append("preview")
    suffix = ("_" + "_".join(parts)) if parts else ""
    return f"{bv_id}_final{suffix}.mp4"


def preflight() -> None:
    """Fail fast if required external dependencies are missing."""
    if shutil.which("ffmpeg") is None:
        raise RuntimeError(
            "ffmpeg not found in PATH. Install with: brew install ffmpeg"
        )
    if shutil.which("ffprobe") is None:
        raise RuntimeError(
            "ffprobe not found in PATH (usually ships with ffmpeg)"
        )
    try:
        mod = importlib.import_module("biliass")
        if mod is None:
            raise ImportError("biliass is None")
    except ImportError as e:
        raise RuntimeError(
            "yt-dlp-danmaku / biliass not available. Install with: "
            "uv add yt-dlp-danmaku"
        ) from e


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="video2yt",
        description="Download a Bilibili video and burn danmaku into the output MP4",
    )
    parser.add_argument("url", help="Bilibili video URL")
    parser.add_argument(
        "-o", "--output-dir", type=Path, default=Path("./output"),
        help="Directory for the final MP4 (default: ./output)",
    )
    parser.add_argument(
        "-t", "--temp-dir", type=Path, default=Path("./temp"),
        help="Directory for intermediate files (default: ./temp)",
    )
    parser.add_argument(
        "-q", "--quality", type=int, default=1080, choices=[1080, 720, 480],
        help="Max video quality (default: 1080)",
    )
    parser.add_argument(
        "-b", "--browser", default="chrome",
        help="Browser to read cookies from (default: chrome)",
    )
    parser.add_argument(
        "--keep-temp", action="store_true",
        help=(
            "Also keep derived ASS files after success. Raw downloads "
            "(video + danmaku XML) are ALWAYS kept for caching."
        ),
    )
    parser.add_argument(
        "--font-face", default="Hiragino Sans GB",
        help=(
            "Font family for rendered danmaku (default: Hiragino Sans GB). "
            "This font is preinstalled on macOS and visible to Homebrew "
            "fontconfig, so libass can actually find it. PingFang SC lives "
            "inside a SIP-protected .ttc that libass cannot open."
        ),
    )
    parser.add_argument(
        "--font-size", type=int, default=None,
        help=(
            "Font size in pixels for standard (size=25) danmaku. "
            "Default: auto — computed from video height using Bilibili's "
            "native formula video_height * 25 / 540."
        ),
    )
    parser.add_argument(
        "--codec", default="h264", choices=["h264", "h265", "auto"],
        help=(
            "Video codec preference (default: h264 — most compatible, "
            "preferred by YouTube). 'h265' for smaller files on modern players. "
            "'auto' lets yt-dlp decide by its own sort rules."
        ),
    )
    parser.add_argument(
        "--preview-seconds", type=int, default=None,
        help=(
            "If set, burn only the first N seconds of the video (passed to "
            "ffmpeg as -t N). Useful for quickly previewing style/codec choices "
            "without re-encoding the whole video."
        ),
    )
    parser.add_argument(
        "--cut", action="append", default=[], metavar="START~END",
        help=(
            "Time range to REMOVE from the output. Repeatable. "
            "START/END accept SS, MM:SS, or HH:MM:SS with optional "
            "fractional seconds. Examples: "
            "--cut 30~60, --cut 0:30~1:00, --cut 00:01:30~00:02:00."
        ),
    )
    parser.add_argument(
        "--speed", type=float, default=1.0,
        help=(
            "Playback speed multiplier for the output (default: 1.0 = original). "
            "Common values: 1.1, 1.25, 1.5, 2.0. Range [0.5, 2.0]. "
            "Applies to video, audio (pitch-preserved via atempo), and danmaku."
        ),
    )
    # T7 step6-restructure orchestrator flags.
    parser.add_argument(
        "--no-subtitle", action="store_true",
        help=(
            "Skip Stage 3 (STT subtitle generation). For source material "
            "that already has burned-in subs (e.g. 郭楓荷's stream)."
        ),
    )
    parser.add_argument(
        "--no-music-swap", action="store_true",
        help=(
            "Skip Stage 4 (CC0 music bed build) and use the source's "
            "native audio in Stage 5. For streamers whose source music is "
            "already royalty-clear or already CC-licensed."
        ),
    )
    parser.add_argument(
        "--device", default="remote", choices=["cpu", "mps", "auto", "remote"],
        help=(
            "Stage 2 (song-remover) separation device. Default: 'remote' "
            "(Modal T4 GPU, ~7.2× faster than local CPU; see CLAUDE.md "
            "'External dependencies' for the one-time setup)."
        ),
    )
    parser.add_argument(
        "--chunk-min", type=int, default=5,
        help=(
            "Stage 2 chunk length in minutes for --device remote (ignored "
            "otherwise). Default 5 (matches song-remover's own default)."
        ),
    )
    return parser.parse_args(argv)


def _log(msg: str) -> None:
    print(f"[video2yt] {msg}", file=sys.stderr)


def run(args: argparse.Namespace) -> Path:
    timings: dict[str, float] = {}
    t_start = time.monotonic()

    if not (0.5 <= args.speed <= 2.0):
        raise ValueError(
            f"--speed must be between 0.5 and 2.0, got {args.speed}"
        )

    preflight()

    # Early Modal-token check: stems' Modal preflight otherwise fires only
    # AFTER fetch completes (30s wasted on every misconfigured remote run).
    # Codex T7 review N6.
    needs_stems_early = not (args.no_subtitle and args.no_music_swap)
    if needs_stems_early and args.device == "remote":
        from video2yt import stems_cli
        stems_cli.preflight(device="remote")

    # Stage 1: fetch + biliass via the new fetch.py module (T2 of step6-restructure).
    # This single call replaces the old metadata / download.fetch /
    # download.generate_ass / validate.check_ass chain. Timings for the
    # individual sub-phases are no longer broken out — fetch_and_build reports
    # one combined elapsed.
    t0 = time.monotonic()
    _log(
        f"fetching {args.url} (quality<={args.quality}, "
        f"codec={args.codec}, browser={args.browser})"
    )
    fetch_result = fetch.fetch_and_build(
        url=args.url,
        temp_dir=args.temp_dir,
        quality=args.quality,
        codec=args.codec,
        browser=args.browser,
        font_face=args.font_face,
        font_size=args.font_size,
    )
    timings["fetch"] = time.monotonic() - t0

    bv_id = fetch_result.bv_id
    metadata = fetch_result.metadata
    temp_subdir = fetch_result.temp_subdir
    source_info = fetch_result.info
    video_path = fetch_result.raw_video
    ass_path = fetch_result.danmaku_ass
    n_danmaku = fetch_result.n_danmaku

    # Per-segment output subdir mirrors the temp subdir name.
    output_subdir = args.output_dir / temp_subdir.name
    output_subdir.mkdir(parents=True, exist_ok=True)

    for w in validate.check_source(source_info, args.quality):
        _log(f"warning: {w}")

    if fetch_result.from_cache:
        _log(f"using cached download from {temp_subdir}")
    _log(
        f"title: {metadata.get('title')!r} -> subfolder: {temp_subdir.name!r}; "
        f"source {source_info.width}x{source_info.height}, codec={source_info.vcodec}, "
        f"{n_danmaku} danmaku lines"
    )

    # Stage 2 (stems) runs unless --no-music-swap AND --no-subtitle (in
    # that case nothing downstream consumes speech.wav, so the slow
    # song-remover call would be wasted).
    needs_stems = not (args.no_subtitle and args.no_music_swap)
    bv_dir = temp_subdir / bv_id
    speech_wav: Path | None = None
    if needs_stems:
        _log(
            f"stems: song-remover (device={args.device}, "
            f"chunk_min={args.chunk_min}) on {video_path.name}..."
        )
        t0 = time.monotonic()
        stems_result = stems.separate(
            raw_mp4=video_path,
            device=args.device,
            chunk_min=args.chunk_min if args.device == "remote" else None,
        )
        timings["stems"] = time.monotonic() - t0
        speech_wav = stems_result.speech_wav
        cache_tag = " (cached)" if stems_result.from_cache else ""
        _log(f"stems done{cache_tag} in {timings['stems']:.1f}s -> {speech_wav}")

    # Stage 3 (subtitle): produces <bv>/speech.cleaned.ass for Stage 5
    # to pick up. Uses the legacy preview burn under --no-preview-burn so
    # the orchestrator doesn't re-encode twice (T4 added that flag).
    cleaned_ass_path: Path | None = None
    if not args.no_subtitle:
        from video2yt import subtitle_cli  # lazy: brings in whisperx
        _log("subtitle: whisperx ASR + codex cleanup...")
        t0 = time.monotonic()
        subtitle_args = subtitle_cli.parse_args([
            str(video_path),
            "--font-face", args.font_face,
            "--no-preview-burn",
        ])
        subtitle_cli.run(subtitle_args)
        timings["subtitle"] = time.monotonic() - t0
        cleaned_ass_path = bv_dir / "speech.cleaned.ass"
        _log(f"subtitle done in {timings['subtitle']:.1f}s -> {cleaned_ass_path}")

    # Stage 4 (music-mix): build the CC0 bed for Stage 5 to amix.
    music_bed_path: Path | None = None
    music_credits_path: Path | None = None
    if not args.no_music_swap:
        _log("music-mix: building CC0 bed...")
        t0 = time.monotonic()
        mix_result = music_mix.render(raw_mp4=video_path)
        timings["music_mix"] = time.monotonic() - t0
        music_bed_path = mix_result.bed_wav
        music_credits_path = mix_result.credits_txt
        cache_tag = " (cached)" if mix_result.from_cache else ""
        _log(
            f"music-mix done{cache_tag} in {timings['music_mix']:.1f}s "
            f"({mix_result.tracks_used} tracks) -> {music_bed_path}"
        )

    # Parse --cut arguments (if any), normalize, and compute keep ranges.
    # Cut-rewrite is NOT done here in T7 — burn.render does the ephemeral
    # rewrite on both ASS files inside the single ffmpeg invocation.
    raw_cuts = [cuts.parse_cut_range(s) for s in args.cut]
    cut_ranges: list[tuple[float, float]] = []
    keep_ranges: list[tuple[float, float]] | None = None
    if raw_cuts:
        cut_ranges = cuts.normalize_cuts(
            raw_cuts, total_duration=source_info.duration
        )
        keep_ranges = cuts.keep_ranges_from_cuts(
            cut_ranges, total_duration=source_info.duration
        )
        total_removed = sum(end - start for start, end in cut_ranges)
        _log(
            f"cut ranges (raw): {raw_cuts} -> normalized: {cut_ranges} "
            f"-> keep: {keep_ranges} (removed {total_removed:.2f}s)"
        )

    has_cut = len(args.cut) > 0
    has_preview = args.preview_seconds is not None
    output_filename = _build_output_filename(
        bv_id=bv_id,
        has_cut=has_cut,
        speed=args.speed,
        has_preview=has_preview,
    )
    output_path = output_subdir / output_filename
    preview_tag = (
        f" (preview first {args.preview_seconds}s)"
        if args.preview_seconds else ""
    )
    cut_tag = f" (cuts applied: {len(cut_ranges)})" if cut_ranges else ""
    speed_tag = f" @ {args.speed}x" if args.speed != 1.0 else ""
    sub_tag = "" if args.no_subtitle else " +subtitle"
    swap_tag = "" if args.no_music_swap else " +music-swap"
    _log(
        f"burning {output_path.name}{preview_tag}{cut_tag}{speed_tag}"
        f"{sub_tag}{swap_tag}"
    )
    t0 = time.monotonic()
    burn.render(
        video_path,
        ass_path,
        output_path,
        max_duration=args.preview_seconds,
        keep_ranges=keep_ranges,
        speed=args.speed,
        cleaned_ass=cleaned_ass_path,
        speech_wav=speech_wav if not args.no_music_swap else None,
        music_bed_wav=music_bed_path,
        apply_subtitle=not args.no_subtitle,
        apply_music_swap=not args.no_music_swap,
        cut_ranges=cut_ranges or None,
    )
    timings["burn"] = time.monotonic() - t0

    # Copy the music_credits.txt next to the final mp4 so the YouTube
    # description has everything in one folder.
    if music_credits_path is not None and music_credits_path.exists():
        dest = output_path.with_name(
            output_path.stem + "_music_credits.txt"
        )
        dest.write_text(music_credits_path.read_text(encoding="utf-8"),
                       encoding="utf-8")

    _log("validating output")
    t0 = time.monotonic()
    output_info = validate.probe(output_path)
    if keep_ranges is not None:
        kept_duration = sum(end - start for start, end in keep_ranges)
    else:
        kept_duration = source_info.duration
    played_duration = kept_duration / args.speed
    expected_duration = (
        min(float(args.preview_seconds), played_duration)
        if args.preview_seconds is not None
        else played_duration
    )
    for w in validate.check_output(
        source_info, output_info, expected_duration=expected_duration
    ):
        _log(f"warning: {w}")
    timings["validate_output"] = time.monotonic() - t0

    # --keep-temp is a no-op now (raw + stems + subtitle SRT caches are
    # ALWAYS preserved per spec §8). The flag remains for backwards CLI
    # compat — orchestrator-managed cleanup is a follow-up.
    _ = args.keep_temp

    total = time.monotonic() - t_start
    stage_timings = " ".join(
        f"{name}={t:.1f}s" for name, t in timings.items()
    )
    _log(f"timings: {stage_timings} total={total:.1f}s")
    return output_path


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        output_path = run(args)
        _log(f"success: {output_path}")
        return 0
    except KeyboardInterrupt:
        _log("cancelled; temp files kept for debugging")
        return 130
    except subprocess.CalledProcessError as e:
        tool = e.cmd[0] if e.cmd else "subprocess"
        _log(f"error: {tool} failed with exit {e.returncode}")
        if e.stderr:
            print(e.stderr, file=sys.stderr)
        return 1
    except (ValueError, FileNotFoundError, RuntimeError) as e:
        _log(f"error: {e}")
        return 1
