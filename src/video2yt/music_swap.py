"""Audio pipeline for video2yt-music-swap.

Replaces the streamer's copyrighted background music in a burnt Bilibili
segment: extract audio -> isolate the commentary voice with Demucs -> discard
the music+SFX mix -> stitch a CC0 music bed -> mix (with ducking) -> remux the
new audio back into the video (no video re-encode).
"""
from __future__ import annotations

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
    vocal_gate_threshold: float = 0.015
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
    threshold: float = 0.015,
    release_ms: int = 250,
) -> None:
    """Mute low-level residual music bleed in the isolated vocals stem.

    This is a voice-activity-style energy gate, not a semantic speech model.
    Demucs often leaves quiet BGM in ``vocals.wav`` during non-speech regions;
    ``agate`` pushes those regions to silence while keeping louder streamer
    speech. ``highpass`` removes low-end rumble before the gate/mix.

    ``threshold`` is a linear ffmpeg amplitude value. 0.015 is about -36.5 dBFS,
    chosen from the redchroma probe where non-speech residual vocals clustered
    below roughly -45 dBFS and speech peaks clustered around -20 dBFS.
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

        _log("building royalty-free music bed")
        manifest = music_library.load_manifest()
        music_library.ensure_manifest_cached(manifest, music_library.CACHE_DIR)
        pool = music_library.scan_cache(music_library.CACHE_DIR)
        sequence = music_library.select_sequence(
            pool, src_info.duration, crossfade=2.0, seed=inputs.seed
        )
        bed = work / "bed.wav"
        build_music_bed(sequence, src_info.duration, bed, crossfade=2.0)

        _log(f"mixing (music_volume={inputs.music_volume}, duck={inputs.duck})")
        mixed = work / "mixed.wav"
        mix(voice_for_mix, bed, inputs.music_volume, inputs.duck, mixed)

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

        credits = music_library.attribution_lines(sequence, manifest)
        if credits:
            credits_path = _write_credits(inputs.output_path, credits)
            _log(
                f"music credits written to {credits_path.name} — paste them "
                f"into the YouTube description"
            )

        _log(f"success: {inputs.output_path}")
        return inputs.output_path
    finally:
        if inputs.keep_temp:
            _log(f"keeping temp dir: {work}")
        else:
            shutil.rmtree(work, ignore_errors=True)
