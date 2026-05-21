"""CC0 royalty-free music library: manifest, download cache, track selection.

The cache directory ``~/.cache/video2yt/music/`` is the source of truth — the
music bed is built from every audio file present there. The committed manifest
(``data/music_library.json``) is an auto-fill convenience that downloads
redistributable CC0 tracks into the cache on first use. Users may also drop
their own tracks into the cache directory by hand.
"""
from __future__ import annotations

import hashlib
import json
import random
import sys
from dataclasses import dataclass
from pathlib import Path

import requests

MANIFEST_PATH = Path(__file__).parent / "data" / "music_library.json"
CACHE_DIR = Path.home() / ".cache" / "video2yt" / "music"
AUDIO_EXTENSIONS = {".mp3", ".m4a", ".wav", ".flac", ".ogg", ".opus"}


def _log(msg: str) -> None:
    print(f"[music_library] {msg}", file=sys.stderr)


def load_manifest(manifest_path: Path | None = None) -> list[dict]:
    """Parse the committed manifest JSON and return its ``tracks`` list.

    Raises ``ValueError`` if the file is missing or not valid JSON, or if the
    top-level ``tracks`` key is absent.
    """
    path = manifest_path if manifest_path is not None else MANIFEST_PATH
    if not path.exists():
        raise ValueError(f"music manifest not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"music manifest is not valid JSON: {path}: {e}") from e
    if not isinstance(data, dict) or "tracks" not in data:
        raise ValueError(f"music manifest missing 'tracks' key: {path}")
    return list(data["tracks"])
