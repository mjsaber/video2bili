"""Tiny JSON-sidecar helpers for stage-output cache invalidation.

Stages 2 (stems), 3 (subtitle), and 4 (music-mix) each write a
``.<stage>_source_meta.json`` sidecar next to their main outputs. On the
next run, the stage recomputes the expected meta from its current source
file and compares — mismatch ⇒ invalidate downstream caches and rerun.

The hash is a SHA-256 of the first 1 MB of the source file (not the full
file): cheap to compute (~50ms on a 1 GB mp4) and reliably catches any
content change at the head of the file, which is what we need to detect
"yt-dlp re-downloaded at a different quality" or "speech.wav regenerated
with a different separator config".

Writes are atomic (write to ``<path>.tmp``, then ``os.replace``) so a
crash mid-write cannot leave a half-baked sidecar that would silently
mismatch on the next run.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path


HASH_HEAD_BYTES = 1 * 1024 * 1024  # 1 MB


def compute_first_1mb_sha256(file: Path) -> str:
    """SHA-256 of up to the first 1 MB of ``file``. Returns hex string."""
    h = hashlib.sha256()
    with open(file, "rb") as f:
        h.update(f.read(HASH_HEAD_BYTES))
    return h.hexdigest()


def write_meta(path: Path, payload: dict) -> None:
    """Atomically write ``payload`` as JSON to ``path``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def read_meta(path: Path) -> dict | None:
    """Return parsed JSON, or ``None`` if the file is missing or unreadable.

    Unreadable (invalid JSON, permissions, truncated) is treated as
    "missing" — the caller treats it as a cache miss and rewrites.
    """
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def meta_matches(path: Path, expected: dict) -> bool:
    """True iff the sidecar at ``path`` exists AND every key in ``expected``
    matches the value recorded there. Extra keys in the recorded meta are
    ignored (forward-compatible: a future version can add fields without
    invalidating older sidecars).
    """
    recorded = read_meta(path)
    if recorded is None:
        return False
    return all(recorded.get(k) == v for k, v in expected.items())
