# video2yt-subtitle — Auto-Subtitle for Bilibili Segments with Pre-Existing Subtitle Detection

**Date**: 2026-05-14
**Status**: Design approved, awaiting user review before implementation plan
**Target audience**: Future Claude agents implementing this CLI; the user reviewing approach before code is written.

## 1. Goal

Produce a new CLI `video2yt-subtitle` that takes a single Bilibili segment MP4 (typically the output of `video2yt` with danmaku already burnt in) and adds bottom Chinese subtitles via STT — but skips the addition entirely if the segment already has subtitle-like content visible at the bottom (either burned into the source video, or in the form of bottom-fixed danmaku that already serves the subtitle function).

The CLI slots into the existing per-project workflow as a new step between `video2yt` (segment burn) and `video2yt-merge` (concat):

```
video2yt URL                            → seg_with_danmaku.mp4
video2yt-subtitle seg_with_danmaku.mp4  → seg_with_danmaku_subbed.mp4   (or passthrough)
video2yt-merge --segment seg1_subbed.mp4 --segment seg2_subbed.mp4 ...
```

It is invoked per-segment, not on the merged output, because detection signals only make sense per-source-segment.

## 2. Non-goals

- This is NOT for the scripted intro. The existing `video2yt-transcribe` flow (script + audio → SRT via whisperx forced alignment) stays as-is for intros.
- This does NOT modify `video2yt`, `video2yt-merge`, or `video2yt-compose`. The only existing-file change is a minimal extension of `compose.srt_to_ass` to accept `outline_px` / `shadow_px` parameters (default values preserve current behavior).
- This does NOT attempt to translate or summarize. The output is a verbatim STT transcript with terminology corrections only.

## 3. Locked design decisions

| Dimension | Decision | Rationale |
|---|---|---|
| Form factor | Independent CLI `video2yt-subtitle` | Single-responsibility, matches existing flat module pattern (compose/compose_cli, merge/merge_cli); cacheable per-segment; parallelizable; doesn't bloat merge.py |
| Dependency gating | ML deps (`funasr`, `rapidocr-onnxruntime`) live in `[project.optional-dependencies] subtitle`, NOT top-level | These deps pull in PyTorch + ONNX runtime (~1.5-2GB). Other CLIs in this repo shouldn't be forced to install them. Install via `uv sync --extra subtitle`; lazy import + preflight check matches existing whisperx pattern |
| ASR engine | Alibaba SenseVoice-Small via `funasr` | 2-4 pts lower Mandarin CER than whisper-large; ~5× faster; built-in VAD; mature open-source by 2026 |
| Cleanup | Codex CLI with in-repo glossary | Same auth path as image-gen (ChatGPT subscription); risk profile consistent with current project usage of Codex CLI; preserves option to migrate to direct API later |
| Detection signals | a + b + c (danmaku XML scan + visual OCR sample + manual flag); **OCR is opt-in via `--enable-ocr`** (revised 2026-05-15) | Initial design enabled all three by default. First end-to-end test on a Hearthstone Battlegrounds segment exposed that the bottom-band OCR sample fires on the game's hand-card UI (always-on stable text at ~0.85-0.95 of frame height). OCR detection is now off by default; the danmaku XML scan and manual `--force-add`/`--force-skip` cover the normal BG workflow. Enable OCR for talking-head streams or other source material with a plain bottom band |
| Subtitle style | Reuse `compose.srt_to_ass`, position="bottom", stronger outline (4px) + shadow (2px) | Game video background is busy; current intro style (2px outline, no shadow) is too weak for overlay on dynamic backgrounds; bottom is the conventional subtitle position |
| Glossary | In-repo at `src/video2yt/data/bg_glossary.yaml`, error→correction map | Reproducible across machines; PR-able; the ringnaga 護戒/戒指龍 incident memory is exactly the kind of entry this is for. New file, curated fresh as part of this implementation |
| OCR library | RapidOCR (ONNX runtime) | ~50MB package vs PaddleOCR's ~200MB+; CPU-only fine for yes/no detection |

## 4. Module structure

```
src/video2yt/
├── subtitle.py              # NEW — detection + ASR + cleanup + burn orchestration
├── subtitle_cli.py          # NEW — video2yt-subtitle entry point
├── data/
│   └── bg_glossary.yaml     # NEW — error→correction map for HS Battlegrounds terminology
└── compose.py               # MODIFIED — srt_to_ass gains optional outline_px, shadow_px params

tests/
└── test_subtitle.py         # NEW — mocks subprocess at the FunASR / Codex / ffmpeg / OCR boundaries
```

`pyproject.toml` additions:

```toml
dependencies = [
    # ... existing top-level deps unchanged ...
    "pyyaml>=6.0",            # glossary parsing — lightweight, top-level
]

[project.optional-dependencies]
subtitle = [
    "funasr>=1.2",            # SenseVoice-Small runtime + PyTorch transitively
    "rapidocr-onnxruntime>=1.4",  # ONNX runtime for OCR detection
]

[project.scripts]
video2yt-subtitle = "video2yt.subtitle_cli:main"
```

**Dependency gating**: `funasr` and `rapidocr-onnxruntime` together pull in PyTorch + ONNX runtime, easily 1.5-2GB on disk. Users who only run `video2yt` / `video2yt-merge` / `video2yt-compose` should not be forced to install this stack. Therefore:

- Heavy deps live in `[project.optional-dependencies] subtitle = [...]`
- Install via `uv sync --extra subtitle` (or `uv add --extra subtitle video2yt`)
- `subtitle.py` uses lazy imports (`import funasr` / `import rapidocr_onnxruntime` inside the functions that need them), matching the existing `transcribe.py` pattern with `whisperx`
- `subtitle_cli.preflight()` does `try: import funasr; import rapidocr_onnxruntime; except ImportError → raise RuntimeError("subtitle extras not installed. Run: uv sync --extra subtitle")`
- README documents this extra in the install section

Rationale for flat module layout (not a `subtitle/` subpackage): every other module in the project is a single flat file. Introducing a subpackage here would be the first inconsistency. If `subtitle.py` grows past ~800 lines we revisit; not now.

## 5. Data flow (per segment)

```
INPUT: segment.mp4 + [--danmaku raw.xml] + [--force-add|--force-skip] + [--glossary path]

│
├─[1. Decide]─────────────────────────────────────────────────
│   Priority (short-circuit evaluation):
│   a. --force-add / --force-skip      → final decision, skip b/c
│   b. Danmaku XML scan (if --danmaku given):
│        - Parse <d> tags, extract type field (2nd CSV column of `p` attr)
│        - Count type=4 (bottom-fixed) danmaku
│        - Compute coverage = union of [start, start+duration_floor) intervals
│        - Threshold: ≥ --danmaku-min-fixed AND coverage ≥ --danmaku-min-coverage%
│        - Hit → SKIP with reason
│   c. OCR sample (CPU fallback):
│        - ffmpeg sample one frame every --ocr-interval seconds to memory (numpy)
│        - Crop bottom 12–18% horizontal band
│        - RapidOCR pass; count frames with detected text
│        - Stability check: cluster detected text by position; require ≥1 cluster
│          appearing in ≥30% of sampled frames (rules out floating danmaku that
│          happens to pass through the crop band)
│        - Hit → SKIP with reason
│
├─[2a. SKIP path]
│   - hardlink (or copy if cross-device) input → output
│   - stderr log: which signal triggered + threshold values
│   - exit 0
│
└─[2b. ADD path]──────────────────────────────────────────────
    ├─[3. ASR]
    │   - ffmpeg extract mono 16kHz wav to temp
    │   - funasr.AutoModel(model="SenseVoiceSmall", vad_model="fsmn-vad", trust_remote_code=True)
    │   - Output: [(start_s, end_s, text), ...] at FunASR-segment granularity
    │   - Write directly to SRT format (one SRT entry per FunASR segment,
    │     NO splitting yet — splitting happens at step 5)
    │   - Cache: <segment_stem>.raw.srt next to input
    │   - --force-asr bypasses cache
    │
    ├─[4. Cleanup]
    │   - Load glossary from --glossary (or default packaged yaml)
    │   - Read .raw.srt; extract M numbered text lines (timestamps preserved separately)
    │   - Build prompt:
    │       「以下是繁體中文爐石戰記戰棋實況解說的 STT 轉寫，每行一句。
    │        只修正錯字、術語、人名；
    │        每行修正後的字數必須與原文相差不超過 ±20%；
    │        不改寫語意、不增刪句子、不合併或分割行。
    │        術語表（左 → 右）：
    │        <glossary entries>
    │        輸入（共 M 行，已編號）：
    │        <numbered transcript lines>
    │        輸出：M 行修正結果，順序對應，不加編號。」
    │   - subprocess: codex exec (non-interactive) with timeout=30s
    │   - Parse output: M lines expected; zip text-only with original timestamps
    │   - Sanity check (§5.1 B):
    │       · line count == M
    │       · per line: 0.8 ≤ len(cleaned) / max(len(raw), 1) ≤ 1.2
    │     ANY violation → fallback to raw, WARNING log, do not fail
    │   - Cache: <segment_stem>.cleaned.srt (still at FunASR-segment granularity)
    │   - --force-cleanup bypasses cache; --skip-cleanup short-circuits to raw
    │
    ├─[5. Split]                                          (NEW — pure Python, no LLM)
    │   - Read cleaned.srt (M segments)
    │   - For each segment, apply punctuation/midpoint split (§5.1 C) using
    │     style-dependent MAX_LINE_CHARS = compose._effective_chars_per_line(
    │         font_size, video_width, margin_l=80, margin_r=80)
    │   - Reallocate timestamps proportionally by effective-CJK-char weights
    │   - Apply hard floor (0.8s) per piece
    │   - Output: in-memory list of K ≥ M final SRT entries
    │   - NOT cached separately (style-dependent; cheap to recompute from .cleaned.srt)
    │
    └─[6. Burn]
        - compose.srt_to_ass(final_srt, w, h, font_face, font_size,
                              position="bottom", outline_px=4, shadow_px=2)
        - Write ASS to temp inside same directory as input
        - ffmpeg -i segment.mp4 -vf "subtitles=f='<ass_basename>'"
          -c:a copy -c:v libx264 -preset medium -crf 20 -pix_fmt yuv420p -r 30
          <output>
          (cwd=temp dir, same trick as burn.py for path-escaping)
        - Validate output: ffprobe duration within ±1s of input

OUTPUT: segment_subbed.mp4 (or input copy/hardlink if skipped)
        Persisted intermediates: <stem>.raw.srt, <stem>.cleaned.srt
                                 (both at FunASR-segment granularity — split is style-dependent)
```

### 5.1 Timeline handling — explicit contract

This is the load-bearing part: subtitles only work if text and timestamps stay aligned. Three timeline concerns, each handled explicitly:

**A. Stage ordering: cleanup BEFORE split**

The pipeline has two text-mutating stages: Codex cleanup (Latin/Han character substitution) and post-split (one FunASR segment → one or more SRT entries). They must happen in a fixed order; the order is **cleanup first, split second**.

```
FunASR raw segments:    [(t0, t1, raw_text_0), (t1, t2, raw_text_1), ..., (t_{M-1}, t_M, raw_text_{M-1})]   (M segments)
                              ↓ cleanup (preserves M, N-out == N-in invariant)
Cleaned segments:       [(t0, t1, clean_text_0), ..., (t_{M-1}, t_M, clean_text_{M-1})]                    (M segments)
                              ↓ split each segment by punctuation + caps
Final SRT entries:      [(s0, e0, line_0), (s1, e1, line_1), ..., (s_{K-1}, e_{K-1}, line_{K-1})]          (K ≥ M entries)
```

Rationale: Codex disambiguates terminology better with longer context (FunASR-segment granularity ≈ 1 sentence). Splitting first would feed Codex short fragments and hurt cleanup quality. Splitting happens on cleaned text and is pure-Python deterministic — no LLM in the loop after cleanup.

The "N lines" invariant in cleanup (§B below) operates on FunASR segments, NOT on post-split SRT entries. The number of post-split SRT entries (K) is determined by the splitter after cleanup.

**B. Cleanup preserves alignment by construction, not by sanity check**

Codex receives a numbered list of M FunASR segments and is instructed to return exactly M lines. The cleanup step re-zips:

```
raw:     [(t0,t1,raw_text_0), ..., (t_{M-1},t_M,raw_text_{M-1})]
cleaned: [(t0,t1,clean_text_0), ..., (t_{M-1},t_M,clean_text_{M-1})]
```

Timestamps come from raw and never change. Cleanup output is line-aligned text only.

Sanity checks (any failure → fallback to raw, WARNING log, run still succeeds):
- Codex output line count must equal M
- Each line's effective-CJK-char length must satisfy `0.8 ≤ len(clean_i) / max(len(raw_i), 1) ≤ 1.2`

These are defense-in-depth: if Codex violates the N-in/N-out contract or wildly rewrites a line, we no longer trust the re-zip is semantically meaningful and we revert.

**C. Post-cleanup split — exact algorithm**

Input to splitter: one cleaned FunASR segment `(start, end, text)`. Output: 1+ SRT entries with timestamps inside `[start, end)`.

**Single trigger condition** — splitting happens only on **char-oversize**:

```
MAX_LINE_CHARS = compose._effective_chars_per_line(
    font_size=args.font_size,        # CLI flag, default 42
    video_width=video_width,         # 1920
    margin_l=80, margin_r=80,        # same as compose.py
)
# Default ≈30 for font_size=42, ≈22 for font_size=56.

is_char_oversize(s) := effective_cjk_chars(s) > MAX_LINE_CHARS
```

Duration is NOT a split trigger. A long-duration, char-OK segment (e.g., 25 chars over 9 seconds) is emitted as a single SRT entry. Rationale: text fits on screen; the speaker just paused mid-sentence; cutting at an artificial boundary would create flicker. The natural fix for prolonged on-screen subtitles is a future whisperx alignment pass, not synthetic mid-text cuts.

**Algorithm** (deterministic, provably terminates):

```python
def split_segment(start: float, end: float, text: str) -> list[Entry]:
    if not is_char_oversize(text):
        return [Entry(start, end, text)]   # base case

    # Try passes in order; ACCEPT a pass only if it produces a useful split.
    # A useful split has ≥2 non-empty pieces, EACH strictly shorter than the
    # parent. This is the load-bearing invariant for termination.
    pieces = _pieces_from(text, SENTENCE_PUNCT)        # 。！？
    if not _is_useful_split(pieces, text):
        pieces = _pieces_from(text, CLAUSE_PUNCT)      # ；，、
    if not _is_useful_split(pieces, text):
        pieces = _split_at_effective_midpoint(text)    # Pass 3 — always useful

    timed = _allocate_time_proportionally(start, end, pieces)
    result = []
    for (s_i, e_i, t_i) in timed:
        result.extend(split_segment(s_i, e_i, t_i))    # recursion
    return _apply_hard_floor(result)


def _is_useful_split(pieces: list[str] | None, parent: str) -> bool:
    """True iff pieces has ≥2 non-empty entries, EACH strictly shorter than parent."""
    if not pieces or len(pieces) < 2:
        return False
    parent_len = len(parent)
    return all(0 < len(p) < parent_len for p in pieces)


def _split_at_effective_midpoint(text: str) -> list[str]:
    """Split into TWO pieces at the index closest to the effective-CJK-char midpoint.
    Pieces are non-empty and strictly shorter than parent (parent has length ≥ 2,
    guaranteed by the is_char_oversize precondition + MAX_LINE_CHARS ≥ 1)."""
    ...
```

Three pass strategies:

1. **Pass 1 — sentence punctuation `。！？`**: split after each occurrence (punctuation stays on the preceding piece). Accept only if `_is_useful_split` returns True. Rejected when, e.g., the only punctuation is at the very end and `_pieces_from` returns `[text]` unchanged.
2. **Pass 2 — clause punctuation `；，、`**: same procedure with clause-level punctuation. Tried only if Pass 1 was not useful.
3. **Pass 3 — effective-CJK-char midpoint**: produces exactly two non-empty pieces, each strictly shorter than parent. Always useful by construction. Reached only when neither punctuation pass produces a useful split.

**Termination proof**:
- `is_char_oversize` precondition + MAX_LINE_CHARS ≥ 1 implies `len(text) ≥ 2` whenever recursion is considered (a 1-char text can never exceed the threshold).
- Whichever pass is accepted, every produced piece has `len(piece) < len(parent)` strictly.
- Therefore every recursive call has strictly fewer characters than its parent.
- Recursion depth is bounded by `len(initial_text)` (worst case: degenerates to 1-char pieces; impossible in practice since base case fires once a piece drops below MAX_LINE_CHARS).
- In practice, depth ≤ `log2(len / MAX_LINE_CHARS) + small constant` for Pass 3, and shallower when punctuation is present.

**Edge cases that previously could have looped forever** (now correctly handled by `_is_useful_split`):
- Text ending in the only punctuation: `"AAAA...A。"` → Pass 1 yields `["AAAA...A。"]` (single piece, NOT useful) → Pass 2 yields same (no clause punctuation) → Pass 3 midpoint splits.
- Punctuation only at the start: `"。AAAA...A"` → Pass 1 yields `["。", "AAAA...A"]` — both pieces non-empty AND strictly shorter than parent → useful, accepted. The `"AAAA...A"` piece recurses with no punctuation and goes to Pass 3.
- All punctuation at one end clustered: `"AAAAA。。。"` → Pass 1 yields `["AAAAA。", "。", "。"]` if implementation splits at every occurrence, or `["AAAAA。。。"]` if implementation only splits between non-empty pieces — the former is useful, the latter is not and falls through. Implementations should use the former; the spec MUST cover this in tests.

**Time allocation** — `allocate_time_proportionally(start, end, pieces)`:
- `w_i = effective_cjk_chars(p_i)` (whitespace excluded, ASCII counted as 0.5, CJK as 1.0 — matches `compose._count_effective_chars`)
- `r_i = (Σ_{j ≤ i} w_j) / (Σ w)`
- Piece `i` gets `[start + r_{i-1} * (end - start), start + r_i * (end - start))` with `r_{-1} = 0`

**Hard floor (0.8s minimum display)** — `apply_hard_floor(entries)`:
- Walk entries left-to-right; for each entry `e` shorter than 0.8s, extend `e.end` forward by `0.8 - (e.end - e.start)` and push the next entry's `start` forward by the same amount.
- The cascade may reach the final entry; if extending it would push past the segment's overall `end`, the cascade stops at the segment boundary and the final entry is emitted with whatever duration remains (may still be < 0.8s — rare; only happens when the segment itself is too short to fit floor-padded pieces, in which case the splitter shouldn't have been invoked anyway).
- Overlaps are NOT introduced; the cascade pushes forward instead of overlapping.

This isn't word-aligned (SenseVoice doesn't give word timestamps); proportional-by-char-weight is the best we can do without a second alignment pass. A future enhancement: pipe the cleaned text + audio through whisperx's wav2vec2 aligner to get true word timestamps and reissue piece boundaries — out of scope for v1.

**D. Danmaku coverage formula (detection signal)**

For type=4 (bottom-fixed) danmaku, Bilibili's standard renderer displays each entry for **5 seconds**. There is no duration field in the XML; the 5s window is a renderer convention, not metadata.

Coverage formula:
```
intervals = [(start_i, start_i + 5.0) for each type=4 danmaku i]
coverage_seconds = total length of UNION of intervals
coverage_ratio = coverage_seconds / segment_duration
```

Threshold (defaults, tunable via flags):
```
hit if (count(type=4) >= --danmaku-min-fixed) AND (coverage_ratio >= --danmaku-min-coverage / 100)
```

The 5.0 second assumption is documented as a constant `BILIBILI_FIXED_DANMAKU_SECONDS = 5.0` in the source, with a comment pointing to this spec. Future Bilibili renderer changes would require updating the constant.

### 5.2 Deliberate design choices to call out

- **Short-circuit decision, not voting**: any single signal saying SKIP triggers SKIP. Rationale: "don't add subtitles" is the safe undo-able state. Adding subtitles and getting them wrong (overlapping with existing burnt subs) is much harder to fix than realizing later you missed an opportunity.
- **Cleanup before split (not after)**: the N-line invariant operates on FunASR-segment-granularity text (longer context → better terminology disambiguation by Codex). Splitting is purely mechanical (no LLM) and runs on cleaned text. See §5.1 A.
- **Char-oversize is the SOLE split trigger**: duration is not a trigger. A 25-char, 9-second segment stays as one entry; the speaker just paused mid-sentence and a synthetic cut would cause flicker. There is no `MAX_DURATION` constant; the spec is intentionally simpler. See §5.1 C.
- **Last-resort midpoint split for punctuation-free oversized text**: ugly but bounded; Pass 3 is guaranteed to terminate because each recursive call strictly halves character count. Acceptable failure mode: a clause boundary that doesn't match prosody. See §5.1 C Pass 3.
- **Split is style-dependent and NOT cached**: `.raw.srt` and `.cleaned.srt` are stored at FunASR-segment granularity (the expensive-to-recompute level). Splitting is fast pure Python keyed on `--font-size`, so changing font size doesn't invalidate the ASR or cleanup caches.
- **Cleanup is "quality bonus", not "correctness path"**: Codex failures fall back to raw ASR without failing the run. Better to ship slightly imperfect terminology than to block the pipeline.
- **OCR failures fall open (toward "no text detected")**: opposite of fail-closed — we'd rather over-subtitle a clean segment than miss subtitling because an OCR bug crashed. The danmaku-XML path is the high-confidence signal; OCR is the fallback for the "原视频烧录" case.
- **Cached SRT artifacts are SRT, not JSON**: makes them inspectable / hand-editable by the user. If `--force-cleanup` is rerun after the user manually fixes a few lines in `.cleaned.srt`, the user fix gets blown away — accept this; the user can move/rename the file to protect it.
- **type=5 (top-fixed danmaku) does NOT count toward the danmaku detection signal**: those serve a different purpose (announcements, marquee), not bottom subtitles. Only type=4 (bottom-fixed) implies "subtitle role".

## 6. CLI interface

```
video2yt-subtitle SEGMENT.mp4 [options]

Required:
  SEGMENT.mp4                        Positional; 1920x1080 30fps h264 MP4

Optional inputs:
  --danmaku PATH                     Source danmaku XML (enables danmaku detection)
                                     Omit → skip danmaku detection, go straight to OCR
  --glossary PATH                    Override packaged glossary
                                     (default: src/video2yt/data/bg_glossary.yaml in this repo)

Decision override (mutually exclusive):
  --force-add                        Skip all detection, force-burn subtitles
  --force-skip                       Skip all detection, passthrough as-is

Detection tuning (rarely needed):
  --ocr-interval SECONDS             Default 5.0
  --danmaku-min-fixed N              Default 10  (type=4 count threshold)
  --danmaku-min-coverage PERCENT     Default 30  (coverage threshold)

Cache control:
  --force-asr                        Re-run ASR ignoring <stem>.raw.srt cache
  --force-cleanup                    Re-run Codex cleanup ignoring <stem>.cleaned.srt cache
  --skip-cleanup                     Skip Codex entirely; use raw ASR

Style (consistent naming with video2yt):
  --font-face NAME                   Default "Hiragino Sans GB"
  --font-size N                      Default auto (height * 25/540, matching video2yt)
  --outline-px N                     Default 4
  --shadow-px N                      Default 2

Output:
  -o, --output PATH                  Default: <SEGMENT_stem>_subbed.mp4 in same dir
```

### 6.1 Exit codes

| Code | Meaning |
|---|---|
| 0 | Success — subtitles added, OR detection said SKIP and passthrough succeeded |
| 1 | Preflight failure (ffmpeg, ffprobe, codex, or funasr unavailable) |
| 2 | Input validation failure (file missing, not 1080p, mutex flag conflict, malformed danmaku XML) |
| 3 | Runtime subprocess failure (ASR crash, ffmpeg burn failure) |

### 6.2 Example log output

SKIP path (existing subs detected):
```
[video2yt-subtitle] preflight OK (ffmpeg, ffprobe, codex, funasr)
[video2yt-subtitle] input: seg1_with_danmaku.mp4 (1920x1080 30fps, 487.32s)
[video2yt-subtitle] danmaku scan: 47 type=4 fixed danmaku, 38.2% coverage → SKIP
[video2yt-subtitle] passthrough -> seg1_with_danmaku_subbed.mp4
[video2yt-subtitle] done in 0.04s
```

ADD path (no existing subs):
```
[video2yt-subtitle] danmaku scan: 2 type=4 fixed, 1.4% coverage → continue
[video2yt-subtitle] OCR sample: 12% frames with stable bottom text → continue
[video2yt-subtitle] ASR: SenseVoice-Small on 487.32s audio... (cached -> seg1.raw.srt)
[video2yt-subtitle] cleanup: codex exec with glossary (87 lines, 2.1s)
[video2yt-subtitle] burn: subtitles=seg1.cleaned.ass ...
[video2yt-subtitle] done in 47.3s -> seg1_with_danmaku_subbed.mp4
```

## 7. Error handling

| Failure | Behavior | Exit |
|---|---|---|
| `ffmpeg` / `ffprobe` not in PATH | preflight error, print install command | 1 |
| `codex` CLI not in PATH | preflight error (still required even with --skip-cleanup, matches project convention) | 1 |
| `funasr` / `rapidocr_onnxruntime` not importable | preflight error: `subtitle extras not installed. Run: uv sync --extra subtitle` | 1 |
| FunASR model not downloaded | Let FunASR auto-download on first run, log one line `[downloading SenseVoice-Small ~600MB...]`. Network failure during download surfaces as ASR runtime failure | 0 on success / 3 on network failure |
| Input file missing / not 1080p | error with actual resolution | 2 |
| `--danmaku` XML corrupted | error (fail fast — user passed bad input) | 2 |
| `--force-add` + `--force-skip` both given | argparse mutex group rejects | 2 |
| ASR failure (audio extract / model crash) | error with FunASR exception | 3 |
| **Codex failure / 30s timeout** | **WARNING + fallback to raw ASR**, overall success | 0 |
| **Codex output sanity check fails** (±20% length change) | **WARNING + fallback to raw ASR**, overall success | 0 |
| OCR failure (RapidOCR exception) | WARNING + treat as "no text detected" (fail-open), continue | 0 |
| ffmpeg burn failure | error with ffmpeg stderr | 3 |

## 8. Testing strategy

New file `tests/test_subtitle.py`, following the existing pattern of mocking at the `subprocess.run` boundary (no real ffmpeg / FunASR / Codex / OCR network calls).

**Decision logic (pure function, highest priority)**
- `decide(danmaku_xml=None, ocr_signal=None, force=None)` truth table
- Priority: force > danmaku > OCR
- Threshold edges: exactly 10 type=4 + 30% coverage → hit; 9 type=4 → miss; 10 + 29.9% coverage → miss
- No --danmaku given → OCR only
- No OCR signal computable → danmaku only

**Danmaku XML parsing**
- type=1 (rolling) ignored
- type=4 (bottom-fixed) counted
- type=5 (top-fixed) ignored
- Overlapping intervals merged correctly for coverage
- Corrupt XML raises ValueError with helpful message

**Pipeline stage ordering (timeline-critical, §5.1 A)**
- Given FunASR returns 5 segments → cleanup is invoked with M=5 lines, split is invoked AFTER cleanup
- Codex mock returning a different number of lines (M=5 in, M=4 out) → fallback to raw + WARNING
- Codex mock returning 5 lines with line 2 length-blown (raw=20 chars → cleaned=40 chars) → fallback to raw + WARNING
- Verify split() receives cleaned text, not raw text (mock cleanup to return distinguishable text)

**Cleanup re-zip + sanity check (§5.1 B)**
- Codex returns clean text with N=M and all len ratios in [0.8, 1.2] → use cleaned, timestamps preserved
- Codex returns 1 line at exactly len ratio 0.8 → accept (closed boundary)
- Codex returns 1 line at len ratio 0.79 → reject, fallback

**Post-cleanup split — exact algorithm (§5.1 C)**
- Char-OK (15 chars, 3s) → 1 entry, unchanged regardless of duration
- Char-OK long duration (25 chars, 9s, no punctuation) → 1 entry, NOT split (duration is not a trigger)
- Char-oversize (45 chars, 3s) with `。` mid-text → Pass 1, all sub-pieces char-OK after recursion
- Char-oversize (45 chars, 3s) with only `，` (no 。) → Pass 1 not useful, Pass 2 used
- Char-oversize (45 chars, 3s) with zero punctuation → Pass 1+2 not useful, Pass 3 midpoint
- **Termination edge (was the bug)**: text = "A" * 99 + "。" with MAX=30 → Pass 1 yields single piece `[text]` → `_is_useful_split` returns False → Pass 2 yields same → False → Pass 3 splits at midpoint → recursion progresses. Final result: ≤4 entries.
- **Punctuation at start**: text = "。" + "A" * 99 → Pass 1 yields ["。", "AAAA..."] → useful; recursion into "AAAA..." goes to Pass 3
- **Multiple trailing punctuation**: "AAAAA。。。" → Pass 1 yields ["AAAAA。", "。", "。"] → useful (3 non-empty pieces, all strictly shorter)
- Pass 3 termination property: 100-char no-punctuation text splits to ≤32 chars in ≤3 levels of recursion (default MAX_LINE_CHARS=30)
- Char threshold uses strict `>` (exactly 30 chars at default → no split)
- Proportional time allocation: pieces with weights [40, 30, 20] inside (0.0, 12.0) → boundaries at (0.0, 5.33), (5.33, 9.33), (9.33, 12.0)
- Hard floor cascade: pieces (5.0, 5.3) → (5.6, 5.9) → ... walks forward, never overlaps. Final-entry-clipped-by-segment-end behavior verified
- MAX_LINE_CHARS is style-dependent: --font-size 56 produces a smaller threshold than --font-size 42

**Danmaku coverage (§5.1 D)**
- Single type=4 at t=10 → coverage interval [10, 15] = 5s
- Two type=4 at t=10, t=12 (overlapping) → union [10, 17] = 7s (NOT 10s)
- Type=4 at t=segment_end-2 → clipped to [end-2, end] = 2s (the 5s window can extend past end conceptually, but coverage caps at segment_duration)

**Cleanup sanity check**
- Mock Codex normal response → use cleaned
- Mock Codex returns 87 chars rewritten to 120 → fallback raw + WARNING
- Mock Codex `subprocess.TimeoutExpired` → fallback raw
- Mock Codex unparseable response → fallback raw

**ffmpeg burn command construction**
- subtitles= filter uses basename + cwd (same path-escape avoidance as burn.py)
- outline_px / shadow_px propagate to ASS style block
- audio is `-c:a copy` (we're not modifying audio)

**CLI**
- `--force-add` + `--force-skip` rejected by argparse
- Default output path is `<input_stem>_subbed.mp4` in input's directory
- SKIP path produces output file (either hardlink or copy, either is OK)
- Preflight failure when `codex` not on PATH

**Explicitly NOT tested**
- FunASR transcription accuracy (that's FunASR's problem)
- Codex CLI actual behavior (mocked)
- RapidOCR detection accuracy (mocked)
- End-to-end with real media (manual smoke during dev)

## 9. Glossary v0

A starter `bg_glossary.yaml` is part of this implementation. Format:

```yaml
# Error → correction. Left-hand side is what whisper/SenseVoice tends to mis-hear;
# right-hand side is the canonical Traditional Chinese form for the channel.
# Add entries as new project topics surface new error patterns.
corrections:
  戰旗: 戰棋               # 战棋 = HS Battlegrounds (not 战旗, which is a different game)
  护戒: 戒指龍              # ringnaga incident; "护戒"/"護戒" mistranscription for 戒指龍 / Ring Bearer
  拉法母: 拉法姆            # Rafaam, proper-noun mishearing
  加拉克朗: 加拉克隆        # Galakrond, proper-noun mishearing

# Canonical terms (no left-hand error; just declared as "preferred forms"
# for Codex to bias toward when it sees ambiguous transcription)
canonical:
  - 酒館
  - 隨從
  - 餵牌
  - 三星
  - 吃雞
  - 加血
  - 上分
  - 開酒館
```

The v0 list will be seeded from the existing CLAUDE.md "Battlegrounds workflow rule" glossary and the ringnaga memory. The user is expected to extend this file as new topics produce new mistranscription patterns; the file is checked into git so corrections compound across projects.

## 10. Integration with existing workflow spec

The 9-step workflow in `2026-04-18-video-production-workflow.md` gets a new optional substep between Step 6 (burn Bilibili segments) and Step 7 (merge). The workflow spec will be updated in a follow-up commit once this CLI is implemented and validated end-to-end; not part of this design doc's scope.

Step 6.5 (new) — per segment:
```bash
uv run video2yt-subtitle \
  output/<project>/<seg_folder>/BV..._with_danmaku.mp4 \
  --danmaku temp/<bv>/<bv>*.xml
```

Then Step 7 consumes the `_subbed.mp4` outputs.

## 11. Open implementation questions (decide during writing-plans)

These were left to implementation time rather than design time because they're not user preference calls — they're tactical:

- Exact Codex CLI invocation syntax (`codex exec` vs `codex` with stdin; the right flag combo for non-interactive structured output)
- FunASR model load caching (load once per process for batch use; the current per-segment CLI invokes a fresh process each time — first run will pay ~3s model load on top of inference)
- Whether to extract audio with ffmpeg into an in-memory pipe vs. a tempfile (memory: cleaner; tempfile: easier to debug)
- RapidOCR's exact API for ONNX-runtime mode + how to feed it numpy arrays from ffmpeg

These are tactical and will be resolved when writing the implementation plan and the first lines of code.
