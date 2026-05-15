"""video2yt-subtitle — detection + ASR + cleanup + split + burn pipeline.

Spec: docs/superpowers/specs/2026-05-14-video2yt-subtitle-design.md
"""

from dataclasses import dataclass
from pathlib import Path

import yaml

# Bilibili's renderer convention for type=4 (bottom-fixed) danmaku display time.
# Source: spec §5.1 D. Changing this requires re-tuning danmaku detection thresholds.
BILIBILI_FIXED_DANMAKU_SECONDS = 5.0

# Subtitle entries shorter than this get extended forward (cascading; never overlap).
# Spec §5.1 C.
HARD_FLOOR_SECONDS = 0.8

# Codex CLI subprocess timeout per cleanup call. Spec §7 — failure here is
# downgraded to WARNING + raw-ASR fallback.
CLEANUP_TIMEOUT_SECONDS = 30

# Split-stage punctuation classes (spec §5.1 C).
SENTENCE_PUNCT = "。！？"
CLAUSE_PUNCT = "；，、"


@dataclass(frozen=True)
class Glossary:
    corrections: dict[str, str]
    canonical: list[str]


def load_glossary(path: Path | None) -> Glossary:
    """Load a glossary YAML. ``None`` → packaged default ``bg_glossary.yaml``."""
    if path is None:
        import importlib.resources
        text = (
            importlib.resources.files("video2yt.data")
            / "bg_glossary.yaml"
        ).read_text(encoding="utf-8")
    else:
        if not path.is_file():
            raise FileNotFoundError(f"glossary file not found: {path}")
        text = path.read_text(encoding="utf-8")
    data = yaml.safe_load(text) or {}
    corrections = data.get("corrections", {})
    canonical = data.get("canonical", [])
    if not isinstance(corrections, dict):
        raise ValueError(f"glossary 'corrections' must be a mapping, got {type(corrections).__name__}")
    if not isinstance(canonical, list):
        raise ValueError(f"glossary 'canonical' must be a list, got {type(canonical).__name__}")
    return Glossary(corrections=corrections, canonical=canonical)
