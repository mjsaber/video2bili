# Season 14 Choice Quilboar Understanding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Download the two selected Season 14 Choice Quilboar videos, generate one raw speech transcript per source, identify the actual new or changed 36.2 cards used in the matches, and deliver a verified Traditional Chinese intro draft for review.

**Architecture:** Reuse the existing `video2yt-prefetch`, `video2yt-stems`, and `video2yt-subtitle --skip-cleanup` cache layers. Build the editorial understanding from raw ASR, danmaku, and targeted frame inspection, then verify every intro card against the official 36.2 information and zhTW card art before drafting the intro. Stop at review checkpoint #1; do not produce TTS or body renders.

**Tech Stack:** video2yt CLIs, yt-dlp/Bilibili cookies, song-remover on Modal, Volcengine Seed-ASR, ffmpeg/ffprobe, HearthstoneJSON zhTW card art, Markdown/text artifacts.

---

## File map

- Create: `output/choice_quilboar_s14/WORKFLOW_NOTES.md` — milestone status and source URLs.
- Create: `output/choice_quilboar_s14/content_understanding.md` — evidence-backed explanation of each match and the combined angle.
- Create: `output/choice_quilboar_s14/terms_zhTW.md` — official name/effect/source table for the retained cards.
- Create: `output/choice_quilboar_s14/intro_script.txt` — 100–130 character Traditional Chinese narration draft.
- Create: `assets/cards/<verified-card-slug>_zhTW_bgs_512.png` — only cards retained for the intro.
- Reuse: `temp/<source>/<BVID>.mp4`, danmaku ASS, stems, and raw speech2srt cache files.

### Task 1: Create project tracking and run preflight checks

**Files:**
- Create: `output/choice_quilboar_s14/WORKFLOW_NOTES.md`

- [ ] **Step 1: Create the project folder and workflow notes**

Use `apply_patch` to create the notes with both Bilibili URLs, the design-spec link, and these statuses: Step 0 complete; Steps 1–3 in progress; review checkpoint #1 pending; Steps 4–12 out of scope for this plan.

- [ ] **Step 2: Verify required local tools without exposing secrets**

Run:

```bash
command -v ffmpeg
command -v ffprobe
command -v song-remover
command -v speech2srt
command -v codex
ffmpeg -filters 2>/dev/null | rg ' subtitles '
test -f .env
test -f ~/.modal.toml
```

Expected: every command exits 0, and ffmpeg lists the `subtitles` filter. Do not print `.env` or any credential value.

### Task 2: Download and validate both source videos

**Files:**
- Reuse/Create: `temp/<source>/BV1HYGw6kESm.mp4`
- Reuse/Create: `temp/<source>/BV17NGP6zERB.mp4`
- Reuse/Create: matching `*.danmaku.ass`

- [ ] **Step 1: Prefetch both sources serially through the existing command**

Run:

```bash
uv run video2yt-prefetch \
  'https://www.bilibili.com/video/BV1HYGw6kESm' \
  'https://www.bilibili.com/video/BV17NGP6zERB' \
  -o temp/
```

Expected: exit 0; each source reports a successful cache hit or download and produces its MP4 plus danmaku ASS.

- [ ] **Step 2: Resolve the exact cache paths and reject ambiguity**

Run:

```bash
find temp -type f -name 'BV1HYGw6kESm.mp4' -print
find temp -type f -name 'BV17NGP6zERB.mp4' -print
```

Expected: exactly one path per BVID. If either count differs from one, stop and resolve the cache collision before continuing.

- [ ] **Step 3: Probe dimensions, codec, duration, and audio**

For each resolved MP4, run:

```bash
ffprobe -v error -show_entries stream=index,codec_type,codec_name,width,height,r_frame_rate \
  -show_entries format=duration -of json '<resolved-video-path>'
```

Expected: video is 1920×1080, contains audio, and has a positive duration. A lower resolution blocks the milestone and must be reported rather than silently accepted.

- [ ] **Step 4: Confirm the danmaku inputs are non-empty**

Run for each resolved source directory:

```bash
test -s '<resolved-source-directory>/<BVID>.danmaku.ass'
rg -c '^Dialogue:' '<resolved-source-directory>/<BVID>.danmaku.ass'
```

Expected: both tests pass and each ASS has at least one dialogue line.

### Task 3: Generate speech stems and one raw transcript per source

**Files:**
- Reuse/Create: `temp/<source>/<BVID>/speech.wav`
- Reuse/Create: `temp/<source>/<BVID>/speech.wav.speech2srt.srt`
- Reuse/Create: `temp/<source>/<BVID>/speech.cleaned.srt`

- [ ] **Step 1: Generate or validate the Guo Fenghe speech stem**

Run:

```bash
uv run video2yt-stems '<resolved-BV1HYGw6kESm-path>'
```

Expected: exit 0 and a non-empty sibling `BV1HYGw6kESm/speech.wav`; a valid cache hit is acceptable.

- [ ] **Step 2: Generate or validate the Kimmy speech stem**

Run:

```bash
uv run video2yt-stems '<resolved-BV17NGP6zERB-path>'
```

Expected: exit 0 and a non-empty sibling `BV17NGP6zERB/speech.wav`; a valid cache hit is acceptable.

- [ ] **Step 3: Run raw ASR once for Guo Fenghe**

Run:

```bash
set -a
source .env
set +a
uv run video2yt-subtitle '<resolved-BV1HYGw6kESm-path>' --skip-cleanup
```

Expected: exit 0 and a raw speech2srt SRT cache. Do not use `--force-asr`; a cache hit proves the existing single transcription can be reused.

- [ ] **Step 4: Run raw ASR once for Kimmy**

Run:

```bash
set -a
source .env
set +a
uv run video2yt-subtitle '<resolved-BV17NGP6zERB-path>' --skip-cleanup
```

Expected: exit 0 and a raw speech2srt SRT cache. Do not invoke speech2srt again during this milestone.

- [ ] **Step 5: Validate both raw SRT files**

For each canonical raw SRT, run:

```bash
test -s '<raw-srt-path>'
rg -c '^([0-9]{2}:){1,2}[0-9]{2},[0-9]{3} --> ' '<raw-srt-path>'
tail -12 '<raw-srt-path>'
```

Expected: non-empty file, timestamp count above zero, and the tail contains complete numbered blocks rather than a truncated write.

### Task 4: Build evidence-backed understanding of both matches

**Files:**
- Create: `output/choice_quilboar_s14/content_understanding.md`

- [ ] **Step 1: Extract speech and danmaku evidence around the strategy vocabulary**

Search both SRT and ASS files for:

```bash
rg -n '抉择|抉擇|摩托|宝石|寶石|野猪|野豬|四本|五本|六本|新版本|小饰品|小飾品|黑暗之赐|黑暗贈禮|启动|啟動' \
  '<guo-raw-srt>' '<guo-danmaku-ass>' '<kimmy-raw-srt>' '<kimmy-danmaku-ass>'
```

Expected: a line-numbered evidence set identifying card mentions, decisions, and corrections. Also read the surrounding SRT blocks, not isolated keyword hits.

- [ ] **Step 2: Inspect the full transcript structure**

Read both SRTs from start to finish in chunks and record, for each source: opening route, tier progression, each named Choose One generator/payoff, when the core engine comes online, final board, and streamer conclusions.

- [ ] **Step 3: Inspect targeted source frames**

Use ffmpeg to extract frames at SRT timestamps where a candidate new/changed card is bought, played, or hovered:

```bash
ffmpeg -ss '<timestamp>' -i '<resolved-video-path>' -frames:v 1 -q:v 2 \
  'output/choice_quilboar_s14/frame_<bvid>_<seconds>.jpg'
```

Expected: readable frames that confirm the actual Simplified Chinese card name and visible rules text. Delete no frames during this milestone; they serve as review evidence.

- [ ] **Step 4: Write the understanding document**

Create these concrete sections:

1. `版本定位` — 36.2 is live as of 2026-08-04 10:00 PDT; source footage came from creator early access, so final effects must be checked against live 36.2.
2. `郭楓荷路线` — decisions and card chain with SRT/danmaku timestamps.
3. `Kimmy路线` — decisions and card chain with SRT/danmaku timestamps.
4. `共同机制` — why the two videos form one Choice Quilboar topic.
5. `差异与双视角价值` — what each source uniquely teaches.
6. `卡牌候选证据` — every potential intro card with video/timestamp evidence.

### Task 5: Verify official 36.2 cards and zhTW names

**Files:**
- Create: `output/choice_quilboar_s14/terms_zhTW.md`
- Create: `assets/cards/<verified-card-slug>_zhTW_bgs_512.png`

- [ ] **Step 1: Compare video candidates with official 36.2 information**

Use Blizzard's 36.2 patch notes and Season 14 announcement as the version source. For Quillboar-specific minion details, follow the official minion-list link from the patch notes. Record whether each video candidate is new, changed, returning unchanged, or unrelated to 36.2.

- [ ] **Step 2: Resolve exact card IDs and English names**

Search the local/fresh HearthstoneJSON card dataset for candidate Simplified Chinese names and visible rules text. Confirm that the ID belongs to the 36.2 Battlegrounds pool and that normal/golden variants are not confused.

- [ ] **Step 3: Download zhTW BGS card faces**

For each retained card, run one of:

```bash
uv run video2yt-research-card --name '<exact-enUS-name>' --style bgs \
  -o 'assets/cards/<verified-card-slug>_zhTW_bgs_512.png'
```

or, when the ID is already proven:

```bash
uv run video2yt-research-card --id '<exact-card-id>' --style bgs \
  -o 'assets/cards/<verified-card-slug>_zhTW_bgs_512.png'
```

Expected: exit 0 and a readable 512px zhTW BGS card face for every retained card.

- [ ] **Step 4: Write the verified term table**

For each retained card, record: enUS name, card ID, Simplified video name, official zhTW name read from the card face, live 36.2 effect, new/changed classification, source-video timestamp, and why it belongs in the intro. Limit the retained set to 2–4 cards.

### Task 6: Draft and verify the intro

**Files:**
- Create: `output/choice_quilboar_s14/intro_script.txt`

- [ ] **Step 1: Draft the 100–130 character narration**

Write four beats in continuous narration:

1. Start exactly with `你敢相信？`.
2. Introduce Season 14 through `黑暗贈禮`、`啟動` and the refreshed minion pool.
3. Name only the verified new/changed cards used in the two videos and explain how Choose One becomes midgame economy and late-game board-wide Blood Gem scaling.
4. Close on the complementary Guo Fenghe and Kimmy routes.

- [ ] **Step 2: Run mechanical script checks**

Run:

```bash
python -c "from pathlib import Path; s=Path('output/choice_quilboar_s14/intro_script.txt').read_text().strip(); assert s.startswith('你敢相信？'); assert 100 <= len(s) <= 160; print(len(s))"
rg -n '酒馆|酒館|牌组|牌組|过渡|過渡|畸变|畸變' \
  output/choice_quilboar_s14/intro_script.txt
```

Expected: Python exits 0; `rg` finds no forbidden vocabulary or placeholders. The upper mechanical bound allows punctuation while the editorial target remains 100–130 Chinese characters.

- [ ] **Step 3: Cross-check every named card**

For every card name in `intro_script.txt`, confirm a matching entry exists in `terms_zhTW.md`, a readable zhTW card PNG exists, and at least one timestamped source-video occurrence exists in `content_understanding.md`.

### Task 7: Verify and hand off review checkpoint #1

**Files:**
- Verify: `output/choice_quilboar_s14/content_understanding.md`
- Verify: `output/choice_quilboar_s14/terms_zhTW.md`
- Verify: `output/choice_quilboar_s14/intro_script.txt`

- [ ] **Step 1: Run artifact validation**

Run:

```bash
test -s output/choice_quilboar_s14/content_understanding.md
test -s output/choice_quilboar_s14/terms_zhTW.md
test -s output/choice_quilboar_s14/intro_script.txt
rg -n '^## (版本定位|郭楓荷路线|Kimmy路线|共同机制|差异与双视角价值|卡牌候选证据)$' \
  output/choice_quilboar_s14/content_understanding.md
git diff --check -- output/choice_quilboar_s14 assets/cards
```

Expected: all three artifacts are non-empty, all six understanding sections exist, and diff check reports no whitespace errors.

- [ ] **Step 2: Present the review package and stop**

Send the user the two-source understanding, the 2–4-card version/zhTW table, and the full intro script together. Explicitly state that TTS, dynamic intro, subtitle cleanup, body rendering, merge, thumbnail, upload, and cleanup have not begun and require approval of checkpoint #1.
