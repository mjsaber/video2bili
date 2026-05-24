# Plan: Subtitle Pause-Split via silencedetect (Option B)

Date: 2026-05-23
Driver: The 2026-05-23 alignment-based pause-split (commit 4a1947a + fix
0977561) doesn't work for Chinese — whisperx forced alignment falls back
to a uniform-fill that reports every intra-segment word-gap as 0.000s, so
no internal pause ever crosses the threshold. Investigation on a 4:50-9:00
夜吹 snippet showed that ffmpeg `silencedetect` on the Demucs-isolated
vocals stem finds the real pauses cleanly (27 splits across 8 segments
where alignment found 0). Switch the splitter to use silencedetect.

## Architecture change

```
BEFORE                                AFTER
─────────────────                     ────────────────────────────
subtitle.transcribe()                 music-swap saves <stem>.vocals.wav
  → raw segments                        sidecar (gated vocals)
subtitle.transcribe_alignment()       subtitle reads the sidecar:
  → bogus word timing                   silencedetect → silences
subtitle._split_segments_on_pauses    subtitle._split_segments_on_silences
  → no-op (gaps all 0.000s)             → real splits at quiet regions
```

Sub-segment text is distributed by duration proportion (same as the
existing demo on the 夜吹 snippet — imperfect "黏字位置" but the
cleanup step normalises per-line and the timing carries the message).

## Stage 1: music-swap exports gated vocals sidecar

**Goal**: Every successful `video2yt-music-swap` run writes the gated
vocals as `<output_stem>.vocals.wav` next to the output MP4 (always —
not gated behind `--keep-temp`). This is what subtitle silencedetect-s.

**Success criteria**:
- After render() succeeds, `<output_stem>.vocals.wav` exists and has the
  same duration as the video stream.
- File is mono or stereo PCM s16le (silencedetect doesn't care).
- Output filename rule: replace `_clean.mp4` → `_clean.vocals.wav`.

**Tests**:
- `test_music_swap_writes_vocals_sidecar` — render() with stub helpers
  produces the sidecar at the expected path.

**Status**: Not Started

## Stage 2: silencedetect helper + tests

**Goal**: `subtitle.detect_silences(wav_path, noise_db=-40, min_duration_s=0.6)`
returns ascending `[(start, end), ...]` silence intervals.

**Success criteria**:
- Wraps `ffmpeg -af silencedetect=noise=...:duration=...` and parses
  `silence_start` / `silence_end` from stderr.
- Returns `[]` when no silences detected.
- Tested with mocked subprocess output covering normal + empty cases.

**Tests**:
- `test_detect_silences_parses_stderr` — synthetic ffmpeg log → intervals.
- `test_detect_silences_empty_returns_empty_list`
- `test_detect_silences_builds_correct_ffmpeg_command`

**Status**: Not Started

## Stage 3: silence-based segment splitter

**Goal**: Replace `_split_segments_on_pauses` (alignment-based) with
`_split_segments_on_silences(segments, silences, min_split_seconds)`.
For each ASR segment with internal silences ≥ threshold, split into N+1
sub-segments where N is the count of qualifying internal silences. Each
sub-segment text is distributed proportionally by speech-piece duration
(same algorithm as the 2026-05-23 demo).

**Success criteria**:
- Segment with no internal silence ≥ threshold → unchanged.
- Segment with K internal silences → K+1 sub-segments.
- Each sub-segment text is non-empty and contiguous in the original text.
- FIRST sub-segment claims seg.start, LAST claims seg.end (same coverage
  preservation as the old splitter).

**Tests**:
- `test_split_on_silences_passes_through_when_no_silences`
- `test_split_on_silences_single_internal_silence`
- `test_split_on_silences_multiple_silences`
- `test_split_on_silences_ignores_silences_outside_segment`
- `test_split_on_silences_preserves_total_text` (concat of sub-segs = original text)
- `test_split_on_silences_first_last_boundary_preservation`

**Status**: Not Started

## Stage 4: wire into subtitle CLI

**Goal**: After ASR, if `<input_stem>.vocals.wav` exists next to the
input MP4 (music-swap sidecar) and `--pause-split-seconds > 0`, run
silencedetect on it and apply `_split_segments_on_silences`. If the
sidecar is missing, skip pause-split (no fallback to alignment) and log
a one-line note explaining why.

**Success criteria**:
- Sidecar present + threshold > 0 → splits applied; raw segment count
  log shows pre/post.
- Sidecar missing → no split, single log line says "no vocals sidecar
  found; skipping pause-split".
- Threshold 0 → no silencedetect call.
- Cleanup cache filename keeps the threshold suffix (already done).

**Tests**:
- `test_cli_pause_split_uses_silencedetect_when_sidecar_present`
- `test_cli_pause_split_skipped_when_sidecar_missing`
- `test_cli_pause_split_skipped_when_threshold_zero`

**Status**: Not Started

## Stage 5: rip out the alignment path

**Goal**: Delete `_run_alignment`, `transcribe_alignment`,
`_split_segments_on_pauses`, the `.words.json` cache plumbing, and all
their tests. They're dead code now.

**Success criteria**:
- `git grep -l "transcribe_alignment\|_run_alignment\|_split_segments_on_pauses\|words.json"` returns only the plan + this commit's deletion.
- Full test suite still green.

**Status**: Not Started

## Stage 6: end-to-end rerun on full 夜吹 + verify

**Goal**: Re-music-swap the full 夜吹 segment (so the sidecar exists),
re-run subtitle, merge, eye-test the SRT split count and a few specific
pauses.

**Success criteria**:
- Pause-split log shows real split count (e.g. 32 → ~80 segments, not
  32 → 32).
- User confirms specific pauses (e.g. 4:50-9:00 region) now break into
  multiple subtitle blocks.

**Status**: Not Started

## Style adjustments (separate, smaller follow-up after Stage 6)

The 2026-05-23 demo style preview (font 18, MarginV 15, no opaque box,
pure white) was approved by user. Current subtitle CLI defaults are
font_size=auto(50 for 1080p) + BorderStyle box. Adjust defaults to match
the approved demo style. Tracked as a follow-up, not in this plan.
