# transcribe: replace whisperx with ffmpeg-derived speech span

**Status**: APPROVED (codex review 2026-07-04: APPROVE-WITH-CHANGES, all changes folded in below)
**Date**: 2026-07-04
**Owner**: video2yt-transcribe (Step 4 intro forced-alignment)

## Problem

`video2yt-transcribe` aligns the authoritative intro script to the TTS
narration (`intro.mp3`) and emits `intro.srt`. Today it runs a full whisperx
pipeline (Whisper ASR + pyannote VAD + phoneme alignment) to obtain word-level
timestamps — but `align_script_to_words()` consumes **only two numbers** from
that output:

```python
total_start = word_timestamps[0][1]   # first word start
total_end   = word_timestamps[-1][2]  # last word end
# script sentences are then sliced proportionally by char weight
```

Every intermediate word timestamp is discarded. whisperx exists in this repo
solely to estimate the speech span `[total_start, total_end]`.

It estimates it badly. In two consecutive productions the whisperx transcription
**dropped the audio tail**, so `total_end` came in short and the whole SRT was
compressed toward the front (subtitles run ahead; tail has voice but no text):

- `tiger` 2026-06-30: 41.86s mp3 aligned to 31.9s (−10.0s, 24% of the audio)
- `leapfrog` 2026-07-03: 45.53s mp3 aligned to 42.2s (−3.4s)

Re-running whisperx does not help (deterministic miss); converting mp3→wav does
not help. Both times the manual fix was a *linear rescale* of the SRT timeline
to the real audio duration — which worked immediately, confirming that the
proportional model is fine and only the span was wrong.

Cost of the status quo: a recurring silent quality bug (needs manual
detection each run), ~60s wall-clock per intro, and a heavyweight dependency
subtree (whisperx → torch, pyannote, transformers, lightning ≈ 2+ GB in the
venv) kept alive for two numbers.

## Proposal

Derive the speech span with ffmpeg/ffprobe instead of whisperx:

- **`total_end`**: `ffprobe` container duration **minus trailing silence**
  detected by `silencedetect`. Container duration cannot under-report — the
  class of "dropped tail" bugs disappears structurally.
- **`total_start`**: end of the leading silence run from the same
  `silencedetect` pass (0.0 if the file starts with speech).

Everything else (`strip_markdown`, `split_into_sentences`,
`split_long_sentences`, `align_script_to_words`, `segments_to_srt`) is
unchanged. The proportional model is **sufficient for current BigTTS intros**
(constant-pace single-speaker narration, no music bed): the two shipped
linear-rescale fixes behaved acceptably (±1–1.5s mid-audio drift) — evidence
of adequacy for this input class, not proof for arbitrary audio.

### New span function

```python
def detect_speech_span(audio_path: Path,
                       noise_db: float = -35.0,
                       min_silence: float = 0.35) -> tuple[float, float]:
    """Return (speech_start, speech_end) via ffmpeg silencedetect.

    - one ffmpeg pass:
        -af aformat=channel_layouts=mono,silencedetect=n=<noise_db>dB:d=<min_silence>
        -f null -
      (explicit mono downmix so stereo channel imbalance cannot skew detection)
    - duration from validate.probe() (ffprobe), NOT from decoding
    - speech_start = end of a leading silence run that starts at ~0.0, else 0.0
    - speech_end   = start of a trailing silence run that reaches EOF, else
                     duration
    - guard: if speech_end - speech_start < 0.5s (e.g. silencedetect claims the
      whole file is silence), raise ValueError("audio appears to be silent")
    - logs the detected span + noise_db/min_silence to stderr (observability
      escape hatch while the thresholds are internal constants)
    """
```

Parsing: `silencedetect` writes `silence_start: X` / `silence_end: Y` lines to
stderr. A leading run is one with `silence_start <= 0.1`; a trailing run is
one whose matching `silence_end` is absent (file ends silent) or within
**`EOF_TOLERANCE = 0.25s`** of the container duration. The wide tolerance is
deliberate: VBR MP3 header duration and MP3 encoder/decoder padding can
disagree with the decoded stream by well over 50ms, and silencedetect
timestamps come from the decode while `probe()` reads `format.duration` —
the two must not be compared at millisecond precision. Interior silence runs
are ignored — proportional allocation already absorbs inter-sentence pauses,
same as today.

If the parsed `speech_end` lands *beyond* `duration` (metadata under-reports
vs decode), clamp to the larger of the two: the span may exceed the probed
duration but must never be truncated by it.

### Call-site changes

`transcribe.transcribe_script()`:

```python
# before
word_timestamps = run_whisperx_alignment(...)
segments = align_script_to_words(sentences, word_timestamps)

# after
speech_start, speech_end = detect_speech_span(audio_path)
segments = align_script_to_span(sentences, speech_start, speech_end)
```

`align_script_to_span(sentences, start, end)` carries the (unchanged)
proportional math; `align_script_to_words` stays as a **deprecated shim** over
it for one release (existing unit tests target it directly).
`run_whisperx_alignment` is deleted outright. `transcribe_script()` keeps
`language` / `model_name` / `device` as **accepted-but-ignored kwargs** for one
release (current API compatibility), documented as deprecated in the
docstring.

`transcribe_cli.py`:

- `preflight()`: drop the whisperx import check; require **both** `ffmpeg`
  and `ffprobe` on PATH (the span function shells out to both — ffprobe via
  `validate.probe()`).
- `--language` / `--model` / `--device` flags: keep parsing but mark
  deprecated in help text and ignore (callers in the workflow spec pass none
  of them except defaults). Log a one-line notice if a non-default value is
  passed.

`pyproject.toml`: remove `whisperx` dependency (`uv remove whisperx`).
No other module imports it (verified by grep).

Docs: update the Step 4 section of
`docs/superpowers/specs/2026-04-18-video-production-workflow.md` and the
CLAUDE.md external-dependencies bullet that says transcribe is whisperx-only.

## Why not the alternatives

- **Volcengine (speech2srt) timestamps**: the API does return utterance/word
  timestamps, but it adds a network upload + API-key dependency + latency to a
  step that needs exactly two numbers, and speech2srt's CLI surface only emits
  utterance SRT (would need a new flag or JSON output). Rejected: strictly
  more moving parts than ffmpeg, for accuracy we don't need.
- **Keep whisperx + auto-rescale patch**: treats the symptom; keeps the 2 GB
  dependency subtree and the 60s model run; the mid-audio anchors whisperx
  could theoretically provide are unused by the current algorithm anyway.
- **Real per-sentence anchoring (use intermediate timestamps)**: would improve
  mid-audio drift (±1–1.5s observed) but requires trusting ASR text matching —
  the exact thing that failed twice. Current drift is acceptable for intro
  subtitles and card gates (spotlight granularity is multi-second). Not worth
  the risk now; can be revisited independent of this change.

## Behavior deltas (accepted)

1. Mid-audio timing quality is **unchanged** (proportional then, proportional
   now). Only the span source changes, strictly for the better on the two
   observed failure modes.
2. If a future intro audio is NOT constant-pace TTS (e.g. human narration with
   long dramatic pauses), proportional drift grows. That risk exists today
   too; noted in the module docstring.
3. `video2yt-transcribe` output for a *correctly*-aligned whisperx run will
   differ by ≤ a few hundred ms at the edges (silencedetect boundaries vs
   whisper word boundaries). Card-gate matching is unaffected (name → block
   lookup, not absolute time).

## Test plan

All new tests are pure-Python with mocked subprocess (repo convention:
external tools mocked at the `subprocess.run` boundary; no real ffmpeg in CI).

1. `detect_speech_span` parsing: leading + trailing + interior silence runs;
   no-silence-at-all file → (0.0, duration); file ending in silence with
   unmatched final `silence_start`; all-silence file → ValueError.
2. **Duration-disagreement cases**: trailing `silence_end` at
   `duration − 0.2` (within EOF tolerance → treated as trailing); parsed
   `speech_end > probed duration` (VBR under-report → clamp UP, never
   truncate); trailing run just outside tolerance (`duration − 0.4`) →
   treated as interior, span ends at duration.
3. `transcribe_script` end-to-end with `detect_speech_span` monkeypatched:
   SRT last block end == speech_end (regression test for the tail-drop class).
4. CLI: deprecated-flag notice; preflight no longer requires whisperx but
   fails without ffprobe.
5. Keep existing `align_script_to_words` unit tests as-is (they exercise the
   deprecated shim + unchanged math); add mirror tests for
   `align_script_to_span`.
6. One opt-in real-ffmpeg test (skipped unless ffmpeg+ffprobe on PATH,
   mirroring `test_burn_real_ffmpeg.py`): generate fixtures via ffmpeg itself
   — (a) mono `sine` with known leading/trailing silence, (b) a **stereo**
   fixture with silence on one channel only (mono-downmix regression), (c) a
   **VBR MP3** re-encode of (a) — assert span within ±0.15s.

Manual validation before shipping: re-run against the two archived intro mp3s
(tiger 41.86s, leapfrog 45.53s — if still on disk; else regenerate one via
TTS) and diff the SRT against the shipped (rescaled) versions; expect ≤0.5s
deltas per block.

## Resolved questions (per codex review 2026-07-04)

1. **Delete `run_whisperx_alignment`; keep `align_script_to_words` as a
   deprecated shim** over `align_script_to_span` for one release (existing
   unit tests target it directly; math unchanged).
2. **Keep `--language/--model/--device` as ignored-deprecated CLI flags**
   with a stderr notice on non-default values; `transcribe_script()` likewise
   keeps them as ignored kwargs for one release. Remove both later.
3. **`noise_db=-35dB, min_silence=0.35s` stay internal constants**, but the
   detected span and the parameters are logged to stderr on every run (the
   observability escape hatch — the −35dB floor is inferred from bed-free
   speech at ≈ −21dB mean, not from measured TTS room tone, so make it
   visible during the manual validation pass).
