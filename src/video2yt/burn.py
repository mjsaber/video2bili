"""Stage 5 of the per-segment pipeline: single-pass ffmpeg burn.

Combines danmaku ASS, cleaned subtitle ASS, speech+CC0-bed amix, optional
``--cut`` time-range removal, and optional ``--speed`` playback multiplier
into a single ffmpeg ``-filter_complex`` invocation — no intermediate
files, one video re-encode, one audio re-encode.

Spec: ``docs/superpowers/specs/2026-05-24-step6-restructure.md`` §4 Stage
5 + §6. Codex review 2026-05-24 verified that two ``subtitles=`` filters
chained in one filter_complex render correctly under ffmpeg 8.1 + libass.

The pre-T6 simple-mode path (``-vf subtitles= -c:a copy`` for the no-cut/
no-speed/no-music-swap case) is preserved so existing legacy callers
(``cli.run`` before the T7 orchestrator wires up the new stages) keep
working.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from video2yt import cuts


# Audio constants ported from music_swap.mix(): the known-good ducking
# config when mixing CC0 bed under speech. See spec §6 note 6.
_SIDECHAIN_PARAMS = "threshold=0.05:ratio=8:attack=5:release=300"
_MUSIC_BED_VOLUME = 0.18  # was 0.25 in music_swap; slightly lower since
# Bandit-v2 speech.wav has higher relative loudness than Demucs vocals.


def _build_filter_complex(
    keep_ranges: list[tuple[float, float]] | None,
    danmaku_ass_filename: str,
    speed: float = 1.0,
    cleaned_ass_filename: str | None = None,
    speech_input_index: int | None = None,
    music_bed_input_index: int | None = None,
) -> str:
    """Build an ffmpeg ``-filter_complex`` string.

    The graph always emits ``[outv]`` and ``[outa]`` so callers can pass
    ``-map "[outv]" -map "[outa]"`` uniformly regardless of which optional
    stages are enabled.

    Optional stages (each can be turned on/off independently):
      - ``cleaned_ass_filename``: when non-None, a SECOND ``subtitles=``
        filter is chained after the danmaku one. ffmpeg renders the
        cleaned subtitle on top of the danmaku frame (acceptable because
        cleaned subs live at the bottom and danmaku floats top-to-mid).
      - ``speech_input_index`` + ``music_bed_input_index``: when BOTH are
        non-None, the audio chain switches from "[0:a] passthrough" to
        "speech + sidechain-ducked CC0 bed → amix". Both indices are
        required together; passing one without the other raises.

    Video chain stages (each preserves graph shape with a passthrough when
    its config is the identity):
      V0 input → V1 cut → V2 burn danmaku → V3 burn cleaned (optional)
          → V4 speed → [outv]

    Audio chain stages:
      A0 normalize speech+bed to 48k stereo (only when music-swap on)
      A1 cut → A2 mix (or passthrough) → A3 speed → [aout]

    Subtitles are burned BEFORE the speed stage so the danmaku timeline
    matches the original video timeline; ``setpts`` then time-scales the
    already-burned-in pixels. Same logic extends to the cleaned subtitle.
    """
    music_swap_on = (
        speech_input_index is not None
        and music_bed_input_index is not None
    )
    if (speech_input_index is None) != (music_bed_input_index is None):
        raise ValueError(
            "speech_input_index and music_bed_input_index must both be "
            "passed together (or both omitted)"
        )

    parts: list[str] = []

    # ===== VIDEO chain =====

    # V1: cut → [cv]
    if keep_ranges and len(keep_ranges) > 0:
        for i, (start, end) in enumerate(keep_ranges):
            parts.append(
                f"[0:v]trim=start={start}:end={end},setpts=PTS-STARTPTS[v{i}]"
            )
        n = len(keep_ranges)
        concat_inputs = "".join(f"[v{i}]" for i in range(n))
        parts.append(f"{concat_inputs}concat=n={n}:v=1:a=0[cv]")
    else:
        parts.append("[0:v]null[cv]")

    # V2/V3: burn danmaku, then (optionally) cleaned subtitles.
    parts.append(f"[cv]subtitles=f='{danmaku_ass_filename}'[sv1]")
    if cleaned_ass_filename is not None:
        parts.append(f"[sv1]subtitles=f='{cleaned_ass_filename}'[sv]")
    else:
        parts.append("[sv1]null[sv]")

    # V4: speed → [outv]
    if speed != 1.0:
        parts.append(f"[sv]setpts=PTS/{speed}[outv]")
    else:
        parts.append("[sv]null[outv]")

    # ===== AUDIO chain =====

    if music_swap_on:
        sp = f"[{speech_input_index}:a]"
        bed = f"[{music_bed_input_index}:a]"
        # A0/A1: normalize both to 48k stereo (sample-rate mismatches in
        # the CC0 bed pool would otherwise cause amix to silently
        # resample), then cut speech and bed in lock-step with the video.
        #
        # When there are multiple cut ranges, ffmpeg requires each filter
        # output label to be consumed exactly once. So we asplit the
        # normalized speech/bed into N branches BEFORE the per-range trims.
        # Codex T6 review caught this: emitting `[spN]atrim...` twice in a
        # multi-range graph is rejected by libavfilter.
        if keep_ranges and len(keep_ranges) > 0:
            n = len(keep_ranges)
            sp_branches = "".join(f"[sp_b{i}]" for i in range(n))
            bed_branches = "".join(f"[bed_b{i}]" for i in range(n))
            parts.append(
                f"{sp}aresample=48000,aformat=channel_layouts=stereo,"
                f"asplit={n}{sp_branches}"
            )
            parts.append(
                f"{bed}aresample=48000,aformat=channel_layouts=stereo,"
                f"asplit={n}{bed_branches}"
            )
            for i, (start, end) in enumerate(keep_ranges):
                parts.append(
                    f"[sp_b{i}]atrim=start={start}:end={end},"
                    f"asetpts=PTS-STARTPTS[sp_c{i}]"
                )
                parts.append(
                    f"[bed_b{i}]atrim=start={start}:end={end},"
                    f"asetpts=PTS-STARTPTS[bed_c{i}]"
                )
            sp_concat = "".join(f"[sp_c{i}]" for i in range(n))
            bed_concat = "".join(f"[bed_c{i}]" for i in range(n))
            parts.append(f"{sp_concat}concat=n={n}:v=0:a=1[csp]")
            parts.append(f"{bed_concat}concat=n={n}:v=0:a=1[cbed]")
        else:
            # No cuts: A0 normalize + A1 passthrough fold into a single
            # filter chain per input.
            parts.append(
                f"{sp}aresample=48000,aformat=channel_layouts=stereo[csp]"
            )
            parts.append(
                f"{bed}aresample=48000,aformat=channel_layouts=stereo[cbed]"
            )

        # A2: sidechain-duck the bed against the speech, then amix.
        parts.append("[csp]asplit=2[sp_a][sp_b]")
        parts.append(f"[cbed]volume={_MUSIC_BED_VOLUME}[bed_scaled]")
        parts.append(
            f"[bed_scaled][sp_a]sidechaincompress={_SIDECHAIN_PARAMS}[bed_ducked]"
        )
        parts.append(
            "[sp_b][bed_ducked]amix=inputs=2:duration=first:"
            "dropout_transition=0:normalize=0[mixed]"
        )

        # A3: speed → [aout]
        if speed != 1.0:
            parts.append(f"[mixed]atempo={speed}[outa]")
        else:
            parts.append("[mixed]anull[outa]")
    else:
        # Legacy audio path: cut + speed on [0:a], no amix.
        if keep_ranges and len(keep_ranges) > 0:
            for i, (start, end) in enumerate(keep_ranges):
                parts.append(
                    f"[0:a]atrim=start={start}:end={end},"
                    f"asetpts=PTS-STARTPTS[a{i}]"
                )
            n = len(keep_ranges)
            concat_inputs = "".join(f"[a{i}]" for i in range(n))
            parts.append(f"{concat_inputs}concat=n={n}:v=0:a=1[ca]")
        else:
            parts.append("[0:a]anull[ca]")

        if speed != 1.0:
            parts.append(f"[ca]atempo={speed}[outa]")
        else:
            parts.append("[ca]anull[outa]")

    return ";".join(parts)


def _rewrite_ass_for_cuts(
    src: Path, dst: Path, cut_ranges: list[tuple[float, float]],
) -> None:
    """Rewrite ``src`` ASS into ``dst`` with dialogues inside cut ranges
    dropped and dialogues after cuts shifted onto the new timeline."""
    original = src.read_text(encoding="utf-8")
    rewritten = cuts.rewrite_ass_for_cuts(original, cut_ranges)
    dst.write_text(rewritten, encoding="utf-8")


def render(
    video_path: Path,
    ass_path: Path,
    output_path: Path,
    max_duration: int | None = None,
    keep_ranges: list[tuple[float, float]] | None = None,
    speed: float = 1.0,
    cleaned_ass: Path | None = None,
    speech_wav: Path | None = None,
    music_bed_wav: Path | None = None,
    apply_subtitle: bool = False,
    apply_music_swap: bool = False,
    cut_ranges: list[tuple[float, float]] | None = None,
) -> Path:
    """Render the final segment mp4 via a single ffmpeg invocation.

    Required:
      - ``video_path``: ``<bv>.mp4``. Must live in the same directory as
        ``ass_path``.
      - ``ass_path``: ``<bv>.danmaku.ass`` (un-cut; T6 rewrites it
        ephemerally if cuts are requested).
      - ``output_path``: where the final mp4 lands.

    Optional Stage 5 inputs (added in T6 of step6-restructure):
      - ``cleaned_ass``: path to the cleaned-subtitle ASS. If under a
        subdir (``<bv>/speech.cleaned.ass``), pre-flight symlinks it to
        ``<bv>.cleaned.ass`` next to ``video_path`` so the ffmpeg
        cwd-with-basename quoting trick works for both ASS layers.
      - ``speech_wav``, ``music_bed_wav``: audio sources for the new
        speech + sidechain-ducked CC0-bed amix. Both required together.
      - ``apply_subtitle``: gate for ``cleaned_ass`` (orchestrator's
        ``--no-subtitle`` corresponds to False).
      - ``apply_music_swap``: gate for the audio mix (orchestrator's
        ``--no-music-swap`` corresponds to False; the ``[0:a]`` native
        audio is mapped instead).
      - ``cut_ranges``: the input ``--cut`` ranges (as ``(start,end)``
        seconds). When non-empty, BOTH ASS files are ephemerally
        rewritten via ``cuts.rewrite_ass_for_cuts`` so the burn renders
        the correct subset of subtitle lines.

    ffmpeg output args include ``-pix_fmt yuv420p -r 30 -ar 48000`` so the
    result satisfies ``video2yt-merge`` strict mode (1920x1080 30fps h264)
    AND keeps audio at 48kHz to match the song-remover speech.wav rate.

    Branches:
      - **Legacy simple** (no cuts, ``speed == 1.0``, no cleaned_ass, no
        music-swap): ``-vf "subtitles=f='...'"`` + ``-c:a copy``. Fastest;
        no audio re-encode. Preserves pre-T6 behavior for the in-flight
        legacy ``cli.run`` path.
      - **Complex** (anything else): ``-filter_complex`` via
        ``_build_filter_complex``. Audio is always re-encoded (``aac
        160k``) because we either ``atrim``/``atempo`` or ``amix``.
    """
    if video_path.parent != ass_path.parent:
        raise ValueError(
            f"video and ASS must live in the same directory "
            f"(got {video_path.parent} and {ass_path.parent})"
        )
    if apply_music_swap:
        if speech_wav is None or music_bed_wav is None:
            raise ValueError(
                "apply_music_swap=True requires both speech_wav and "
                "music_bed_wav"
            )
    if apply_subtitle and cleaned_ass is None:
        raise ValueError(
            "apply_subtitle=True requires cleaned_ass"
        )

    temp_dir = video_path.parent
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # ----- pre-flight: place cleaned ASS as a flat sibling of <bv>.mp4 -----
    # ffmpeg 8.x's subtitles= filter is fussy about path escaping; we use
    # cwd-with-basename to dodge it. The cleaned ASS lives under
    # <bv>/speech.cleaned.ass (T4 design), so we symlink it to
    # <bv>.cleaned.ass at burn-stage entry. Ephemeral — removed on success.
    sym_path: Path | None = None
    ephemeral_paths: list[Path] = []
    danmaku_basename = ass_path.name
    cleaned_basename: str | None = None
    if apply_subtitle and cleaned_ass is not None:
        sym_path = temp_dir / f"{video_path.stem}.cleaned.ass"
        # Resolve the target to an absolute path BEFORE symlink_to —
        # symlink_to records the path verbatim, and a relative target
        # resolves against the symlink's parent (not cwd), which gives a
        # broken link when `temp_dir` itself is relative. Codex T6 review
        # caught this.
        cleaned_target = cleaned_ass.resolve()
        # Recreate symlink fresh each time (idempotent across reruns).
        if sym_path.exists() or sym_path.is_symlink():
            sym_path.unlink()
        try:
            sym_path.symlink_to(cleaned_target)
        except OSError:
            # Filesystem doesn't support symlinks — copy instead.
            shutil.copy(cleaned_target, sym_path)
        ephemeral_paths.append(sym_path)
        cleaned_basename = sym_path.name

    # ----- ephemeral cut-rewrite of both ASS files when --cut is set -----
    # T6: cut rewriting moves OUT of cli.run / fetch into burn so stages
    # 1-4 stay flag-free. We never persist the .cut.ass files — they're
    # an artifact of the in-flight ffmpeg invocation.
    danmaku_ass_for_burn = ass_path
    cleaned_ass_for_burn_basename = cleaned_basename
    if cut_ranges and len(cut_ranges) > 0:
        danmaku_cut_path = temp_dir / f"{video_path.stem}.danmaku.cut.ass"
        _rewrite_ass_for_cuts(ass_path, danmaku_cut_path, cut_ranges)
        ephemeral_paths.append(danmaku_cut_path)
        danmaku_ass_for_burn = danmaku_cut_path
        if apply_subtitle and sym_path is not None:
            cleaned_cut_path = temp_dir / f"{video_path.stem}.cleaned.cut.ass"
            # Rewrite the symlinked cleaned ASS (read through the symlink).
            _rewrite_ass_for_cuts(sym_path, cleaned_cut_path, cut_ranges)
            ephemeral_paths.append(cleaned_cut_path)
            cleaned_ass_for_burn_basename = cleaned_cut_path.name

    needs_complex = (
        (keep_ranges is not None and len(keep_ranges) > 0)
        or speed != 1.0
        or apply_subtitle
        or apply_music_swap
    )

    cmd = ["ffmpeg", "-y", "-i", video_path.name]
    if apply_music_swap and speech_wav is not None and music_bed_wav is not None:
        cmd.extend(["-i", str(speech_wav.resolve())])
        cmd.extend(["-i", str(music_bed_wav.resolve())])
        speech_idx, bed_idx = 1, 2
    else:
        speech_idx = bed_idx = None
    if max_duration is not None:
        cmd.extend(["-t", str(max_duration)])

    try:
        if needs_complex:
            filter_complex = _build_filter_complex(
                keep_ranges=keep_ranges,
                danmaku_ass_filename=danmaku_ass_for_burn.name,
                speed=speed,
                cleaned_ass_filename=cleaned_ass_for_burn_basename,
                speech_input_index=speech_idx,
                music_bed_input_index=bed_idx,
            )
            cmd.extend([
                "-filter_complex", filter_complex,
                "-map", "[outv]",
                "-map", "[outa]",
                "-c:v", "libx264",
                "-preset", "medium",
                "-crf", "20",
                "-pix_fmt", "yuv420p",
                "-r", "30",
                "-c:a", "aac",
                "-b:a", "160k",
                "-ar", "48000",
                str(output_path.resolve()),
            ])
        else:
            # Legacy simple path: no audio re-encode, no second subtitle.
            cmd.extend([
                "-vf", f"subtitles=f='{danmaku_ass_for_burn.name}'",
                "-c:a", "copy",
                "-c:v", "libx264",
                "-preset", "medium",
                "-crf", "20",
                str(output_path.resolve()),
            ])
        subprocess.run(cmd, check=True, capture_output=True, text=True, cwd=temp_dir)
    finally:
        # Clean up ephemeral artifacts even on failure so a retry isn't
        # affected by stale .cut.ass files.
        for p in ephemeral_paths:
            try:
                p.unlink()
            except FileNotFoundError:
                pass

    return output_path
