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
