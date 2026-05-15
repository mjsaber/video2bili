"""video2yt-subtitle — detection + ASR + cleanup + split + burn pipeline.

Spec: docs/superpowers/specs/2026-05-14-video2yt-subtitle-design.md
"""

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
