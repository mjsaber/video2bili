# Plan: Subtitle Pause-Based Splitting

Date: 2026-05-23
Driver: On the 夜吹 mooniron segment, two sentences separated by an audible
0.5-1s pause were collapsed into a single SRT block because whisperx ASR
returned them as one segment and the existing splitter only triggers on
character count (default 33). Users see one subtitle line that lingers across
the pause and into the next sentence.

## Goal

When whisperx ASR returns a segment whose internal word-level timestamps show
a silence ≥ `pause_threshold_s` between adjacent words, split the segment
into multiple sub-segments AT THAT PAUSE. This runs BEFORE cleanup so the
finer-grained inputs flow naturally through the existing pipeline.

## Approach

Reuse `transcribe.run_whisperx_alignment` (already in the repo and used by
the intro forced-alignment flow). It returns `list[(word, start, end)]` for
the full audio. We then:

1. Run regular ASR (current `_run_asr`) — produces segment-level
   `(start, end, text)` triples.
2. Run forced alignment on the same audio — produces word-level
   `(word, start, end)` triples.
3. For each ASR segment, slice the word list to those whose `start ≥
   seg.start AND end ≤ seg.end + 0.2s tolerance`.
4. Walk the slice: when `words[i+1].start - words[i].end ≥ pause_threshold_s`,
   open a new sub-segment. Text for each sub-segment is the concatenation of
   its words (whisperx Chinese alignment usually emits one word per char or
   per token).
5. Emit `FunASRSegment(sub_start, sub_end, sub_text)` for each sub-segment.

If alignment fails (no word timestamps returned), fall back to the original
ASR segments unchanged with a WARNING log line — the splitter cost is bounded
and recovery is silent.

## Default and CLI flag

- Default `pause_threshold_s = 0.6` (typical inter-sentence pause is 0.3-0.8s).
- New CLI flag `--pause-split-seconds FLOAT` (default 0.6, `0` to disable).
- Document the tradeoff: lower threshold → more splits, may break mid-clause;
  higher → may keep the original "two-sentences-one-block" defect.

## Stage 1: Word-gap splitter helpers + tests
**Goal**: Implement `_split_segments_on_pauses(segments, words, pause_s)`
and `_words_within(seg, words, tolerance)` in `src/video2yt/subtitle.py`.

**Success criteria**:
- `_split_segments_on_pauses` correctly splits a segment with a single
  internal gap into 2 sub-segments at the gap.
- Segments with no gaps ≥ threshold pass through unchanged.
- Words outside the segment's time range are ignored.
- Empty word list → segments returned unchanged (graceful fallback).

**Tests** (in `tests/test_smoke.py`):
- `test_pause_split_single_internal_gap` — one ASR segment 0-10s with words
  ending at 4.0s and next starting at 4.8s → two sub-segments [0, 4.0]
  and [4.8, 10].
- `test_pause_split_no_gaps_passes_through` — words evenly spaced with
  100ms gaps and threshold 0.6 → segments unchanged.
- `test_pause_split_multiple_gaps` — two internal gaps → three sub-segments.
- `test_pause_split_ignores_out_of_range_words` — alignment includes words
  before segment.start or after segment.end → skipped.
- `test_pause_split_empty_words_passthrough` — words=[] → segments unchanged.
- `test_pause_split_text_concatenation` — Chinese chars joined without spaces
  (CJK convention); English/digits keep their spaces.

**Status**: Not Started

## Stage 2: Wire into transcribe() + CLI flag
**Goal**: Update `transcribe()` to run alignment and apply the pause splitter
before returning segments. Add `--pause-split-seconds` to the CLI.

**Success criteria**:
- `transcribe(video_path, pause_split_seconds=0.6)` runs ASR + alignment +
  pause-split and returns finer-grained `FunASRSegment`s.
- `pause_split_seconds=0` skips alignment entirely (no-op for the pipeline).
- Alignment failure → log WARNING, fall back to ASR-only segments.
- CLI flag `--pause-split-seconds` plumbs through to `transcribe()`.

**Tests**:
- `test_transcribe_calls_alignment_when_pause_split_enabled` — monkeypatch
  alignment, verify it's invoked.
- `test_transcribe_skips_alignment_when_pause_split_zero` — alignment NOT
  invoked.
- `test_transcribe_alignment_failure_falls_back_to_asr_segments` — alignment
  raises → returns ASR segments unchanged + WARNING logged.
- `test_cli_parse_args_pause_split_default_06`
- `test_cli_parse_args_pause_split_custom_value`

**Status**: Not Started

## Stage 3: End-to-end validation on 夜吹 segment
**Goal**: Re-run `video2yt-subtitle` on the 夜吹 mooniron segment, verify the
specific pause that was missed (user-identified) is now split.

**Success criteria**:
- Final SRT has more blocks than the pre-fix version (sanity check).
- User audibly confirms the previously-collapsed-pause now breaks into two
  subtitle blocks.

**Tests**: manual ear/eye test on the 夜吹 output.

**Status**: Not Started

## Scope and non-goals

- Only `subtitle.py` and `subtitle_cli.py` (+ tests). No changes to ASR, the
  cleanup prompt, the char-split, or the burn step.
- Don't touch the existing char-split — `pause_split` runs BEFORE cleanup,
  and the char-split still runs AFTER cleanup, both stages preserved.
- Don't change the alignment model — reuse `transcribe.run_whisperx_alignment`
  as-is.

## Risks

- **Alignment cost**: ~2-3 min on a 17-min segment. Acceptable on top of
  the existing 24-min cold pipeline.
- **Alignment misfires**: if whisperx alignment drops a few words, the
  pause-split might over-split. Mitigation: tolerance of 0.2s on segment
  boundaries; passthrough on alignment failure.
- **Mid-sentence breath pauses**: a 0.6-0.8s breath in the middle of a long
  sentence will trigger an unwanted split. The user can raise the threshold
  via CLI if their streamer pauses a lot mid-sentence. We expose the knob.
