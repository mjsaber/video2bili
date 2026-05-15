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
| ASR engine | Alibaba SenseVoice-Small via `funasr` | 2-4 pts lower Mandarin CER than whisper-large; ~5× faster; built-in VAD; mature open-source by 2026 |
| Cleanup | Codex CLI with in-repo glossary | Same auth path as image-gen (ChatGPT subscription); risk profile consistent with current project usage of Codex CLI; preserves option to migrate to direct API later |
| Detection signals | a + b + c (danmaku XML scan + visual OCR sample + manual flag) | User chose comprehensive coverage. "Don't add" is the safe default — any signal saying SKIP triggers SKIP |
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
    # ... existing ...
    "funasr>=1.2",            # SenseVoice-Small runtime
    "rapidocr-onnxruntime>=1.4",
    "pyyaml>=6.0",            # glossary parsing
]

[project.scripts]
video2yt-subtitle = "video2yt.subtitle_cli:main"
```

Rationale for flat layout (not a `subtitle/` subpackage): every other module in the project is a single flat file. Introducing a subpackage here would be the first inconsistency. If `subtitle.py` grows past ~800 lines we revisit; not now.

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
    │   - Output: [(start_s, end_s, text), ...]
    │   - Convert to SRT (sentence-level segments, no further splitting)
    │   - Cache: <segment_stem>.raw.srt next to input
    │   - --force-asr bypasses cache
    │
    ├─[4. Cleanup]
    │   - Load glossary from --glossary (or default packaged yaml)
    │   - Build prompt:
    │       「以下是繁體中文爐石戰記戰棋實況解說的 STT 轉寫，每行一句。
    │        只修正錯字、術語、人名；保持每行字數不變動超過 ±20%；
    │        不改寫語意、不增刪句子、不合併或分割行。
    │        術語表（左 → 右）：
    │        <glossary entries>
    │        輸入：
    │        <numbered transcript lines>
    │        輸出：保持相同行數，每行對應的修正結果。」
    │   - subprocess: codex exec --skip-git-repo-check (or equivalent non-interactive flag) with timeout=30s
    │   - Parse output back to numbered lines, zip with original timestamps
    │   - Sanity check per line: len_delta_ratio ≤ 0.20
    │   - If sanity check fails OR Codex times out OR parsing fails:
    │       → fallback to raw SRT, WARNING log, do not fail
    │   - Cache: <segment_stem>.cleaned.srt
    │   - --force-cleanup bypasses cache; --skip-cleanup short-circuits to raw
    │
    └─[5. Burn]
        - compose.srt_to_ass(srt, w, h, font_face, font_size,
                              position="bottom", outline_px=4, shadow_px=2)
        - Write ASS to temp inside same directory as input
        - ffmpeg -i segment.mp4 -vf "subtitles=f='<ass_basename>'"
          -c:a copy -c:v libx264 -preset medium -crf 20 -pix_fmt yuv420p -r 30
          <output>
          (cwd=temp dir, same trick as burn.py for path-escaping)
        - Validate output: ffprobe duration within ±1s of input

OUTPUT: segment_subbed.mp4 (or input copy/hardlink if skipped)
        Persisted intermediates: <stem>.raw.srt, <stem>.cleaned.srt
```

### 5.1 Deliberate design choices to call out

- **Short-circuit decision, not voting**: any single signal saying SKIP triggers SKIP. Rationale: "don't add subtitles" is the safe undo-able state. Adding subtitles and getting them wrong (overlapping with existing burnt subs) is much harder to fix than realizing later you missed an opportunity.
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

**ASR-result → SRT conversion**
- Mock FunASR returns [(0.0, 2.5, "你好"), (2.5, 5.0, "世界")] → valid SRT
- Chinese punctuation at segment boundaries preserved

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
