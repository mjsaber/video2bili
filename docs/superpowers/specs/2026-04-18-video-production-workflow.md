# YouTube Video Production Workflow

**Date**: 2026-04-18 (workflow reordered 2026-06-24)
**Status**: Validated end-to-end; current step order shipped on `midas_arrow` (黃金箭異變).
**Target audience**: Future Claude agents and the user, when producing similar topical YouTube videos from Bilibili source material.

## 1. Goal

Take a topic (normally two streamers on the same 流派/英雄/饰品, or one manually approved “new invention” source) and produce a publish-ready YouTube video with:

- A short original spoken intro **derived from the actual content of all approved source videos** (not guessed from the topic title)
- One or more burnt-in Bilibili source segments (danmaku + cleaned 繁體 subtitle) as the body
- A concatenated final MP4 with chapter markers + loudness normalization
- A YouTube thumbnail
- Localized title / description / tags
- Uploaded to YouTube via API with all metadata pre-filled

**Key ordering principle (2026-06-24 redesign):** download and *understand the real content first*, then write the intro from all approved sources' actual 思路; verify terminology against the in-game card art; only then finish the body. The old "write the intro script first from the topic guess" order is retired.

The pipeline is a sequence of steps, each backed by an existing CLI command (`video2yt-*`) or a one-off script in `scripts/`. Only Step 5's per-segment work is partly automated (`video2yt-burn` etc.); the rest is an agent following this SOP and invoking CLIs in order.

## 2. Per-project folder convention

**Every artifact for a project MUST live under `output/<project>/`.** Use a short, lowercase, ASCII project name (e.g. `midas_arrow`).

Pass `-o output/<project>/` to every `video2yt`, `video2yt-intro`, `video2yt-merge` invocation. CLAUDE.md documents this convention in the "Project folder convention" section.

Final layout for `<project>/`:

```
output/<project>/
├── content_understanding.md      # Step 2 — the two videos' 思路 + combined intro angle
├── intro_script.txt              # Step 2 output (the narration; corrected in Step 3)
├── intro_image_prompt.txt        # Step 4 source (subjectless, warm mid-key — see Step 4)
├── intro_cards.txt               # Step 4 source (<png> | <中文卡名> [| start end])
├── intro.mp3                     # Step 4 output (TTS)
├── intro.srt                     # Step 4 output (forced-aligned)
├── intro_bg.png                  # Step 4 output (1920x1080, fitted)
├── intro_bg_raw.png              # Step 4 raw (1536x1024 from Codex image_gen)
├── intro.mp4                     # Step 4 output (dynamic intro: mascot + card spotlight)
├── subtitle_context.txt          # Step 5 — term table fed to the cleanup subagents
├── thumbnail_bg.png / thumbnail.png  # Step 8
├── <uploader>：<title>/          # Step 5 burnt segment 1 (+ _cta in Step 6)
│   └── BV..._final.mp4
├── <uploader>：<title>/          # Step 5 burnt segment 2
│   └── BV..._final.mp4
├── <title>.mp4                   # Step 7 merged final video
├── <title>_chapters.txt          # Step 7 YouTube chapters (description paste)
├── <title>_ffmeta.txt            # Step 7 ffmetadata embedded into the MP4
├── youtube_metadata.json         # Step 9 (for Step 10 upload)
└── subscribe_comment.txt         # Step 11 source
```

## 3. External dependencies and credentials

| Component | Where | Setup |
|---|---|---|
| `ffmpeg`, `ffprobe` | system PATH | `brew tap homebrew-ffmpeg/ffmpeg && brew install homebrew-ffmpeg/ffmpeg/ffmpeg` (must include libass) |
| Volcengine BigTTS (Step 4 intro voice) | API key | Volcano Ark console → API Key 管理 → create. Stored as `VOLCENGINE_API_KEY` in `.env`. `video2yt-tts` reads it. |
| `speech2srt` CLI (Step 2 ASR — Volcengine 火山 Seed-ASR) | `speech2srt` in PATH | One-time: `cd ~/code/speech2srt && uv tool install . --force`. Requires `VOLCENGINE_API_KEY`. Cost ~¥0.0003/char, ≈ ¥0.1 per 4-min segment. **Called exactly ONCE per segment now** (Step 2, `--skip-cleanup`); the subtitle cleanup no longer goes through speech2srt's codex path (see Step 5). |
| `song-remover` CLI (Step 2 stems — Bandit-v2 multilingual separator) | `song-remover` in PATH | One-time: `cd ~/code/song-remover && uv tool install '.[remote]'` (the `[remote]` extra bakes the `modal` SDK in). Default `--device remote` needs `uv run modal token new` + Modal app deploys per `song-remover` README. |
| Codex CLI (Step 4 image gen only) | `codex` in PATH, logged in | `brew install codex` then `codex login`. Uses ChatGPT auth; no separate API key. **No longer used for subtitle cleanup** — that moved to Claude subagents (Step 5). NOT used by Step 4 intro alignment (pure ffmpeg silencedetect since 2026-07-04). |
| Google Gemini (image-gen fallback) | API key | Google AI Studio → API key (paid/billed). `GEMINI_API_KEY` in `.env`. Only for `video2yt-image --backend gemini`. |
| YouTube Data API v3 | OAuth client | Google Cloud Console → enable YouTube Data API v3 → desktop OAuth client. Save JSON as `client_secret.json` (gitignored). Token cached in `youtube_token.json` (gitignored, testing-mode expiry ~7 days). |
| Hearthstone Battlegrounds logo | `assets/hsbg_logo.png` | One-time download from Fandom wiki (RGBA). |

`.env` and all secrets live in repo root, gitignored (`.env`, `client_secret*.json`, `youtube_token.json`).

## 4. The pipeline (Steps 0–12)

> **Reorder note (2026-06-24):** the intro is now built *after* downloading and understanding every approved source video (Steps 1–2) and *after* verifying terminology (Step 3). speech2srt runs only once per segment (Step 2); the burnt 繁體 subtitle is cleaned by Claude subagents in Step 5, not by a second speech2srt call.

### Step 0 — 选题 (topic discovery)

**Tool**: `uv run video2yt-topic` → prints the full link-bearing report between `===== CHAT-READY REPORT … =====` markers to stdout, and writes `output/topics/<YYYY-MM-DD>.md`.

It pairs two whitelisted streamers along **three axes** — same 核心卡 (流派), same 英雄, same 饰品 — and marks each pair 新 / 已做过. A topic can be a comp, a hero tutorial, or a trinket tutorial.

Paired topics remain the default. A manually reviewed “new invention” topic may use one source when that single game contains a complete setup-to-payoff arc and a second candidate does not share the same mechanism. This exception is a production decision, not an automatic title-keyword rule: do not change `video2yt-topic` to surface singletons merely because a title says “新发明”.

**HARD RULE — every candidate surfaced in chat MUST carry BOTH streamers' Bilibili links.** Relay the stdout report block **verbatim**, `SendUserFile output/topics/<date>.md`, and layer your done/补丁 annotations *on top* — never re-author a condensed table (that is how links get dropped). This applies to ALL candidates you mention, including ones you do NOT recommend. **Never name-drop a candidate without its two URLs** — and that includes the 推荐/跳过 section you write after the verbatim block (the script only protects the verbatim block; any sentence you add naming a candidate is a fresh chance to drop links). See memory `feedback_topic_summary_include_links`.

**Auto-annotation is a hint, not ground truth.** It matches core-card substrings, so it misses cross-script names and same-comp/different-core cases, and it can mis-bucket (e.g. it filed 黃金箭, an **異變/Anomaly**, under the 饰品 axis). Eyeball every 新-marked pick against `assets/topic/done_topics.txt`.

### Step 1 — 下载所有已批准来源 (download all approved sources)

**Input**: all approved Bilibili URL(s).
**Output**: `temp/<uploader>：<title>/<bv>.mp4` + `<bv>.danmaku.ass` (Stage 1 cache).
**Tool**: `video2yt-prefetch`.

```bash
uv run video2yt-prefetch "<approved-url>"... -o temp/
```

`video2yt-prefetch` serial-downloads every approved source into the Stage 1 cache (truncation retry + low-res quarantine + fail-fast). **Note the `-o temp/`**: prefetch's `-o` is the *temp* dir and MUST match where Step 5 reads its cache (`./temp`), NOT `output/<project>/`.

**Pre-flight resolution check**: eyeball the prefetch log — each line reports `<W>x<H>`. Every approved source must be 1920x1080 (merge is strict). A VIP-locked 480p/360p source must be swapped or upscaled before Step 5. (Bilibili download robustness — sequential not parallel, aria2c for the video stream, `--codec h265` fallback if the avc1 copy is truncated — see CLAUDE.md "yt-dlp / Bilibili".)

### Step 2 — 抽 speech + 内容理解 → intro 稿 (understand, then write the intro)

**Input**: all approved cached segment(s).
**Output**: `content_understanding.md` + `intro_script.txt`.
**Tools**: `video2yt-stems`, `video2yt-subtitle --skip-cleanup`, then Claude reads + writes.

This is where speech2srt runs — **exactly once per segment**, raw:

```bash
# per segment:
uv run video2yt-stems     "temp/<dir>/<bv>.mp4"                 # Stage 2: speech.wav (Modal GPU, ~5 min)
uv run video2yt-subtitle  "temp/<dir>/<bv>.mp4" --skip-cleanup  # Stage 3 ASR, RAW (no codex, no context)
```

Then build understanding from two evidence types for every approved source:
1. **Speech → text**: the raw `<bv>/speech.wav.speech2srt.srt` from the command above (Simplified, ASR errors — fine for understanding).
2. **Danmaku → text**: extract the dialogue lines from `temp/<dir>/<bv>.danmaku.ass` (Stage 1 / biliass output) — independent of speech2srt.

Read both evidence types for each approved video, write up each video's 思路 (what the comp/line actually does, key turns, the streamer's angle), then **combine the approved source material into one intro angle**. For a single-source new invention, explain the complete setup-to-payoff arc and why no second source was paired. Capture this in `content_understanding.md`, and draft the narration in `intro_script.txt` (繁體, hook first; use the current project spec for target duration).

**Review checkpoint #1**: show the user the content understanding + the intro script together before moving on (the user asked to see both).

**Battlegrounds vocabulary (use these in the script, NOT constructed-mode terms)**:

| Use | Don't use | Notes |
|---|---|---|
| 阵容 / 流派 / 體系 | 牌組 / 套牌 / 構築 | "牌组" is constructed-only |
| 隨從 / 小弟 | 法術 (rare in BG) | The board is mostly minions |
| 酒館 / 卡池 / 升級(跳本) | 抽牌 / 牌庫 | BG has a tavern, not a deck |
| 站位 / 排位 | 起手 / mulligan | "起手" is constructed |
| 餵 / 養 / 疊屬性 | 過渡 | "過渡" sounds like deck-building |
| 開局 / 中期 / 後期 / 終局 | — | |
| 吃雞 / 吃八雞 / 上分 | — | BG ranking jargon |
| 種族羈絆 (海盜 / 元素 / 機械 / 食屍鬼 / 娜迦 / 龍 / 野獸 / 惡魔 / 任務小隊) | 種族特性 | Use official 族群 names |
| 三聯 / 三合一 / 三星 | — | Combine 3 same minions |
| 異變 (Anomaly) | 畸變 / 機變 | 简中=畸变; 繁中(台服)=異變 |

> **The raw ASR from this step is for understanding only.** It is NOT reused as the burnt subtitle — Step 5 cleans it into 繁體 separately (so speech2srt's flaky Volcengine upload runs once, not twice). The single speech2srt call here is the only transcription cost.

### Step 3 — 术语核对 (terminology verification — HARD RULE)

**Input**: the cards / heroes / anomaly / 流派 named in `intro_script.txt`.
**Output**: a verified zhTW term list; corrected `intro_script.txt`.

For any Hearthstone Battlegrounds term, **verify against the in-game zhTW card art before finalizing the intro** (added after the `ringnaga` mistake; reinforced by `midas_arrow` where 简中「点金箭」turned out to be 台服「黃金箭」). Order of attack, cheapest first:

1. **Danmaku + topic first.** The danmaku usually names the key cards already (`midas_arrow`'s danmaku said 点金箭/金铜须 outright), so you can often confirm terms without the speech. Prefer this — it lets the term-check precede heavy work.
2. **Download the official zhTW card art and read the name off it.** `video2yt-research-card --name "<enUS>"` to resolve the card id, then `curl https://art.hearthstonejson.com/v1/bgs/latest/zhTW/512x/<id>.png` (anomalies: the same path works with the `BG..._Anomaly_...` id). The card face is the source of truth — Blizzard's zh-tw card *library* is JS-rendered (WebFetch can't read it) and fan wikis 403. This is how `黃金箭` / `金銅鬚` / `卡雷苟斯` were locked.
3. Only `WebSearch` for the enUS name → confirm the mechanic; do NOT trust fan-site Chinese names (often OCR-blocked images).

Fix every term in `intro_script.txt` to the verified zhTW form **before** Step 4 (TTS), so you don't TTS a wrong term and redo it. The same verified terms seed `subtitle_context.txt` in Step 5.

### Step 4 — 生成 intro.mp4 (build the dynamic intro)

**Input**: the corrected `intro_script.txt`.
**Output**: `intro.mp4` (1920×1080, 30fps, h264 + aac).
**Tools**: `video2yt-tts` → `video2yt-transcribe` → `video2yt-image` → `video2yt-intro`.

```bash
# 1. TTS (女老板 voice). Default speaker zh_female_vv_uranus_bigtts, rate 0 (1.0x).
uv run video2yt-tts --text-file output/<project>/intro_script.txt -o output/<project>/intro.mp3

# 2. Alignment SRT (text from the script; timestamps = ffmpeg silencedetect span, proportional slicing).
uv run video2yt-transcribe --audio output/<project>/intro.mp3 \
  --script output/<project>/intro_script.txt --max-block-chars 22 \
  -o output/<project>/intro.srt

# 3. Background (subjectless warm mid-key tavern; the mascot overlays separately).
uv run video2yt-image --backend codex \
  --prompt-file output/<project>/intro_image_prompt.txt \
  -o output/<project>/intro_bg.png --save-raw output/<project>/intro_bg_raw.png

# 4. Compose: bg + scrim + SRT-timed card spotlight + 女老板 mascot + burned subtitle.
uv run video2yt-intro --audio output/<project>/intro.mp3 --bg output/<project>/intro_bg.png \
  --srt output/<project>/intro.srt --cards output/<project>/intro_cards.txt \
  -o output/<project>/intro.mp4
```

**Card art for the spotlight**: download the zhTW BGS art for each card the script names (same `art.hearthstonejson.com/.../zhTW/...` source as Step 3), into `assets/cards/<slug>_zhTW_bgs_512.png`. Author `intro_cards.txt`, one card per line in display order; the `中文卡名` must be a substring that appears in `intro.srt`:

```
# <png in assets/cards> | <中文卡名 matched in intro.srt> [| <start> <end>]
golden_arrow_zhTW_bgs_512.png | 黃金箭
brann_zhTW_bgs_512.png        | 銅鬚
```

Each card shows from the SRT block where its name first appears (forward cursor) to the next card; a name matching no block fails fast.

**Image-prompt art direction** (subjectless ENVIRONMENT, no figure/text/logo; warm amber/honey-gold/candle palette; keep the **lower-left subtitle area** and the **entire right mascot area** locally dimmer so white subs + the warm-gold mascot read; darker right half + bottom-left + top strip; brightest focal glow low-center; gentle vignette). Per-theme motif slot (e.g. 黃金箭 → "stacks of gold coins / gilded goblets catching firelight"). Codex gotchas: do NOT pass `writable_roots` (caused an 11-min hang); keep the prompt one concise paragraph.

**Review checkpoint #2**: send the user `intro.mp4`.

> The legacy static composer `video2yt-compose` (one still image + SRT, no mascot) still exists for non-BG/simple intros.

### Step 5 — 烧录两条正片 (burn the two body segments)

**Input**: the two cached segments + `subtitle_context.txt`.
**Output**: two `output/<project>/<uploader>：<title>/<bv>_final.mp4` (+ `<bv>_final_music_credits.txt`).

Stages 1–2 (fetch, stems) are already done from Steps 1–2 and cache-hit. The per-segment work here is **three things** — note that the subtitle is cleaned by Claude, NOT by a second speech2srt call:

#### 5a. Build the CC0 music bed (Stage 4)

```bash
uv run video2yt-music-mix "temp/<dir>/<bv>.mp4"
```

`music_mix.render` → `music_library.select_sequence` greedily picks CC0 tracks from `~/.cache/video2yt/music/` (Kevin MacLeod, CC BY 3.0) until the stitched length (`Σ duration − (N−1)·crossfade`) ≥ the video duration → `_build_music_bed` joins consecutive tracks with a 2s `acrossfade`, trims to **exactly** the video duration with `-t`, applies a 2s `afade` out → `<bv>.music_bed.wav` + `<bv>.music_credits.txt` (attribution — required in the description). Cache key: `<bv>.music_bed_meta.json` (duration ±0.5s).

#### 5b. Clean the raw SRT into 繁體 myself (replaces the old speech2srt cleanup)

speech2srt is NOT called again. Take the raw `<bv>/speech.cleaned.srt` (= the Step 2 raw ASR; `--skip-cleanup` wrote it there) and clean it deterministically:

1. **Dump + split** the raw SRT into N chunks at block boundaries (~30 blocks each).
2. **Parallel cleanup subagents** — one per chunk — each rewrites ONLY the text lines to 繁體 + corrected terms (from `subtitle_context.txt`), copying every block number and timestamp **verbatim** (same block count out as in). Keep the streamer's spoken/roast tone; don't summarize.
3. **Splice** the chunks back and verify block-count + timestamps match the raw exactly.
4. **Review subagent** (per `feedback_subagent_review_loop`): check 100% 繁體, term correctness, no meaning drift, block count.
5. **Convert to ASS**: `compose.srt_to_ass(srt, 1920, 1080, font_face="Hiragino Sans GB", font_size=50, position="bottom", outline_px=4, shadow_px=2, margin_v=80)` → write `<bv>/speech.cleaned.ass`.

`subtitle_context.txt` (≤2 KB) is the **term table fed to these subagents** (streamers, 流派, key cards with verified zhTW names, 口頭禪, ASR-error→correct mappings). It seeds from the Step 3 verified terms.

> Why this replaces speech2srt's cleanup: the old codex-via-speech2srt cleanup (a) re-ran the slow/flaky Volcengine transcription a second time, and (b) had a length-drift guard that silently fell back to raw 简体 subs (`cleanup: applied=false` — hit on `futurefish`, `handfish`, `midas_arrow`/Kimmy). Doing the cleanup in subagents is deterministic, runs no second transcription, and has no guard to trip.

#### 5c. Burn (Stage 5 — one ffmpeg pass)

```bash
uv run video2yt-burn "temp/<dir>/" --bv <bv> \
  -o "output/<project>/<dir>/<bv>_final.mp4"
# default: subtitle layer ON + music-swap ON. --no-subtitle / --no-music-swap to skip.
```

`burn._build_filter_complex` chains, in one `-filter_complex`:
- **Two subtitle layers**: `[cv]subtitles=f='<bv>.danmaku.ass'[sv1]; [sv1]subtitles=f='<bv>.cleaned.ass'[sv]` — danmaku (Stage 1 biliass, floats top→mid) then the cleaned 繁體 subtitle (5b, bottom). Burned BEFORE the `setpts`/`atempo` speed stage so the ASS timeline matches the original. (Pre-flight symlinks `<bv>/speech.cleaned.ass` to a flat `<bv>.cleaned.ass` sibling for the cwd-with-basename escaping trick.)
- **Audio**: `speech.wav` (the **reused** Stage 2 stem — the dry voice) + `music_bed.wav`; the bed is `volume`-scaled then `sidechaincompress` (`threshold=0.05:ratio=8:attack=5:release=300`) keyed by the speech so it ducks under the voice, then `amix`. The original music+SFX are discarded by design (CC0 risk reduction).

Output args: `-pix_fmt yuv420p -r 30 -ar 48000 -c:v libx264 -c:a aac` (satisfies merge strict mode).

#### Data flow

```
Stage1 danmaku.ass ─────────────────────────────────────────────┐
Stage2 speech.wav (cached, reused) ─┬─→ Step2 raw ASR ─→ 5b 我清洗 → speech.cleaned.ass ─┤
                                    └──────────────────────────→ (dry voice) ───┐        │
5a select CC0 → stitch to length → music_bed.wav ─────────────────→ (bed) ──────┴ sidechain+amix ─┐
                                                                                                   ↓
                                        5c burn: chain 2 subtitle layers + ducked amix → <bv>_final.mp4
```

**Per-streamer subtitle note**: if a streamer's source already has burnt-in bottom subs (e.g. 郭楓荷 sometimes), pass `--no-subtitle` to `video2yt-burn` and skip 5b for that segment (avoids double subs). Eyeball each source once.

### Step 6 — Append the subscribe CTA to battle 1

**Input**: the first **battle** segment from Step 5 (NOT the intro).
**Output**: `<battle1>_final_cta.mp4`.
**Tool**: `scripts/append_cta.sh` + `assets/cta/subscribe_cta.mp4`.

```bash
scripts/append_cta.sh output/<project>/<uploader1>：.../<bv1>_final.mp4
# -> ..._final_cta.mp4
```

The ~5s faceless-mascot CTA (beat A 「訂閱馬哥！」 click sequence + bell ding; beat B spoken「想看什麼陣容？留言告訴我！」) is **re-encode** concatenated onto battle 1 so it plays **mid-roll between battles 1 and 2, inside battle 1's chapter** (each chapter still ≥10s; no stray chapter). Re-encode, not stream copy — a stream-copy join once emitted a backward-pts reset that made merge silently drop the segment tail + CTA. Never pass the CTA to merge as its own `--segment`.

### Step 7 — Merge into final video

**Input**: ordered `--segment`/`--label` pairs (intro first; battle 1 is the `_cta` clip), a working title.
**Output**: `output/<project>/<title>.mp4` + `<title>_chapters.txt` + `<title>_ffmeta.txt`.
**Tool**: `video2yt-merge`. **`-o` is a full output MP4 file path, not a directory.**

```bash
uv run video2yt-merge \
  --segment output/<project>/intro.mp4                              --label "開場：<topic>" \
  --segment output/<project>/<uploader1>：.../<bv1>_final_cta.mp4   --label "<streamer1>：<打法>" \
  --segment output/<project>/<uploader2>：.../<bv2>_final.mp4       --label "<streamer2>：<打法>" \
  --title   "<working_title>" \
  -o        "output/<project>/<title>.mp4"
```

All `--segment` inputs MUST be 1920x1080 30fps h264 (strict) AND ≥10s, with ≥3 segments (mirrors YouTube's chapter rules). Output: concat + per-segment loudnorm to -14 LUFS, CFR-normalized (`fps=30,setpts=PTS-STARTPTS`) before concat. Segmentation is delivered via the description chapter block (Step 9) from `<title>_chapters.txt`; the `_ffmeta` embed is best-effort only.

### Step 8 — YouTube thumbnail (confirm with the user)

**Input**: bg image (Step 4 style), logo, **zhTW BGS** card art, 8-char two-tier title.
**Output**: `output/<project>/thumbnail.png` (1280x720).
**Tool**: `scripts/thumbnail_polish.py` (the ONLY thumbnail tool — warm-tavern compositor: bg lift + edge vignette + tilted card right + left scrim + 女老板 mascot + two-tier title). All visual params are locked constants — do NOT tweak per-project.

**Title formula — 8-char two-tier** (present the 5 directions with examples from the source titles, then propose 3–4 concrete 4-char picks; **do not pick alone**):
- **Top row (4 chars, primary)**: the 流派 canonical 4-char name.
- **Bottom row (4 chars, secondary)**: payoff — pick a direction: **Numbers** (preferred, e.g. `二八萬攻`) / **Hyperbole** / **Tutorial promise** / **Mechanic teaser** / **Action-emotion**.

```bash
# bg can reuse intro_bg.png (same warm tavern) or a fresh video2yt-image render.
uv run python scripts/thumbnail_polish.py \
  --bg output/<project>/intro_bg.png \
  --card assets/cards/<slug>_zhTW_bgs_512.png \
  --output output/<project>/thumbnail.png \
  --primary "<4 字流派>" --secondary "<4 字 payoff>"
# --logo / --mascot default to assets/hsbg_logo.png and assets/cta/src/mascot_raw.png
```

**Review checkpoint #3**: send the user `thumbnail.png` and confirm before upload.

### Step 9 — Generate YouTube metadata

**Output**: `output/<project>/youtube_metadata.json` for Step 10. Fields:

```json
{
  "title": "...", "description": "...", "tags": ["..."],
  "category_id": "20", "default_language": "zh-Hant", "default_audio_language": "zh-Hant",
  "privacy_status": "public", "made_for_kids": false,
  "expected_channel_id": "UCEgIrCo0pR6DyyrXuSn3wBg",
  "video_path": "output/<project>/<title>.mp4",
  "thumbnail_path": "output/<project>/thumbnail.png"
}
```

**Title format (locked — feina style):**

```
「爐石戰記：英雄戰場」新賽季<topic>完整教學 | <streamer1> × <streamer2> 實戰 [彈幕]
```

Example: `「爐石戰記：英雄戰場」新賽季黃金箭異變完整教學 | 郭楓荷 × Kimmy 實戰 [彈幕]`

Rules: use the **full game name** 「爐石戰記：英雄戰場」 with 「」 brackets and **新賽季** (NOT `S13`); `完整教學`; pipe `|` with single spaces; streamer names in 繁體 joined by ` × `; final `[彈幕]` half-width. No 简体字 in the title. (The earlier `「英雄戰場」S13…` form is retired — `mirrorbox` had to be deleted + re-uploaded over it.)

**Description**: 繁體 primary (first paragraph mentions 「爐石戰記：英雄戰場」 once), then the **single** `時間軸：` chapter block copied verbatim from `<title>_chapters.txt`, then 原片來源 links, then the 🎵 music credits (every line from the `_music_credits.txt` files — CC BY 3.0 requires it), then the hashtag line, then a short 简体 summary (NO second chapter block — a duplicate block resets to 00:00 and YouTube discards the whole list).

**Required hashtags (locked):** put `#英雄戰場教學` among the **first three** (YouTube only links the first 3 above the title):
```
#英雄戰場教學 #英雄戰場 #爐石戰記 #<策略名> #<核心隨從> #戰棋 #Hearthstone #Battlegrounds
```

**Chapter block rules** (YouTube-enforced): ≥3 timestamps, first is `00:00`, strictly ascending, each chapter ≥10s, exactly ONE block.

### Step 10 — Upload to YouTube

**Input**: `youtube_metadata.json`, `client_secret.json`, cached `youtube_token.json`.
**Tool**: `video2yt-upload`.

```bash
uv run video2yt-upload --metadata output/<project>/youtube_metadata.json --dry-run   # auth + channel check
uv run video2yt-upload --metadata output/<project>/youtube_metadata.json             # real upload
```

Aborts unless `expected_channel_id` is among the authenticated channels (catches wrong-account auth). Resumable upload + thumbnail set; prints watch + studio URLs.

**OAuth re-auth (testing-mode tokens expire ~7 days; a failed refresh auto-deletes `youtube_token.json`):** surface the consent URL by running the `--dry-run` UNBUFFERED to a log, not through `tail` (which buffers):
```bash
PYTHONUNBUFFERED=1 uv run video2yt-upload --metadata <meta> --dry-run > /tmp/auth.log 2>&1 &
grep accounts.google.com /tmp/auth.log   # the auth URL; redirect_uri=http://localhost:<PORT>
```
**Claude-in-Chrome CANNOT drive the Google consent page** — `navigate` to `accounts.google.com` is refused ("Permission denied by user", a sensitive auth domain). Hand the user the URL; they only click "Allow" (no password). The local server on `localhost:<PORT>` catches the redirect and saves the token. (See `feedback_oauth_via_claude_in_chrome` — the self-drive path documented there no longer works for the consent page itself.)

### Step 11 — Post the subscribe comment (MANDATORY)

**Input**: the uploaded `video_id`, `output/<project>/subscribe_comment.txt`.
**Tool**: `scripts/post_comment.py` (uses `youtube_token.json`; `youtube.force-ssl` scope).

```bash
uv run python scripts/post_comment.py --video-id <ID> \
  --text-file output/<project>/subscribe_comment.txt \
  --expected-channel-id UCEgIrCo0pR6DyyrXuSn3wBg
```

繁體, one top-level comment: (a) one line recapping the 核心卡/combo so it reads as content, (b) 按讚 / 訂閱 / 開小鈴鐺, (c) invite 留言許願.

### Step 12 — Reclaim disk (`video2yt-cleanup`)

**Run last, once the upload is confirmed.**

```bash
uv run video2yt-cleanup --project <project>          # DRY-RUN: plan + reclaimable bytes
uv run video2yt-cleanup --project <project> --yes     # delete
```

Policy: delete the CURRENT project's `temp/<source>/` caches (regenerable) but KEEP `output/<project>/` as a one-period buffer; delete the PREVIOUS shipped project's entire `output/<project>/`. A "shipped project" = an `output/` subfolder with `youtube_metadata.json`. Every delete passes `cleanup.assert_within`. NEVER hand-roll `rm -rf temp/*<glob>*`. Flags: `--all-previous`, `--no-prev`, `--no-temp`.

## 5. Scripts and CLIs used by this workflow

| File | Purpose | Key deps |
|---|---|---|
| `video2yt-topic` | Pair streamers along 流派/英雄/饰品, emit link-bearing report | — |
| `video2yt-prefetch` | Serial pre-download of sources into the Stage 1 cache | `yt-dlp` |
| `video2yt-stems` / `video2yt-subtitle` | Stage 2 stems / Stage 3 ASR (`--skip-cleanup` in Step 2) | `song-remover`, `speech2srt` |
| `video2yt-tts` | Volcengine BigTTS narration | `VOLCENGINE_API_KEY` |
| `video2yt-transcribe` | ffmpeg-span alignment SRT | ffmpeg+ffprobe |
| `video2yt-image` | Image-gen via Codex (default) or Gemini, crop/letterbox | `codex` CLI / `google-genai`, `Pillow` |
| `video2yt-intro` | Dynamic intro compositor (mascot + card spotlight + scrim) | `ffmpeg`+libass |
| `video2yt-research-card` | Resolve HS card id on hearthstonejson.com + download art | `requests` |
| `video2yt-music-mix` / `video2yt-burn` | Stage 4 CC0 bed / Stage 5 burn | `ffmpeg`+libass |
| `video2yt-merge` | Concat + loudnorm + chapters | `ffmpeg` |
| `scripts/thumbnail_polish.py` | The ONLY thumbnail compositor (`--primary`/`--secondary`) | `numpy`, `Pillow` |
| `video2yt-upload` | YouTube Data API v3 OAuth + resumable upload + thumbnail | `google-api-python-client`, `google-auth-oauthlib` |
| `scripts/post_comment.py` | Post the subscribe comment | `google-api-python-client` |
| `video2yt-cleanup` | Post-ship disk reclaim | — |

## 6. Tech debt and follow-ups

| Area | Status | Notes |
|---|---|---|
| speech2srt: split raw-transcription cache from cleanup | Pending (out-of-repo) | The cleanest fix would let the slow/flaky Volcengine transcription cache independently of cleanup, so changing context re-runs only the cheap part. Until then, we run speech2srt once (`--skip-cleanup`, Step 2) and do cleanup ourselves (Step 5b). |
| OAuth app publishing | Pending (user-side) | Testing-status tokens expire ~7 days → weekly re-consent (Step 10). Publishing the consent screen would fix it. |
| Image fit aspect ratio | Improved (Codex 3:2) | Codex `image_gen` outputs 1536x1024 (~16% loss to 16:9) vs Gemini 1024x1024 (44%). |

## 7. Verification log — projects shipped through this pipeline

| Project | Date | Video ID | Notes |
|---|---|---|---|
| `back2back` | 2026-04-17 | [`DuglxlhKbzw`](https://www.youtube.com/watch?v=DuglxlhKbzw) | First end-to-end run (old order). Originated the `compose -shortest` fix. |
| `ringnaga` | 2026-05-02 | [`hP27PqfL6zY`](https://www.youtube.com/watch?v=hP27PqfL6zY) | First `card-tilt-right` thumbnail; validated Codex `image_gen`. Surfaced the term-research HARD RULE. |
| `mirrorbox` | 2026-05-31 | [`qvyZtPh_36Y`](https://www.youtube.com/watch?v=qvyZtPh_36Y) | Title-format lesson: must be feina-style 「爐石戰記：英雄戰場」新賽季… (deleted+re-uploaded over the `S13` form). Term-check needs in-game source, not fan sites. |
| `midas_arrow` | 2026-06-24 | [`nY2u4ZPx6Mo`](https://www.youtube.com/watch?v=nY2u4ZPx6Mo) | First run of the **reordered** workflow (download→understand→intro→term-check→burn). Term trap: 简中「点金箭」= 台服「黃金箭」 (an 異變, not a 饰品; topic tool mis-bucketed it), locked from the zhTW card art. First run with **speech2srt-once + subagent cleanup** as the default (not fallback) — Kimmy's segment would have failed the old codex guard. OAuth: Claude-in-Chrome refused the Google consent page; user clicked the URL. |

## 8. Per-project workflow checklist

Copy into a project-local `WORKFLOW_NOTES.md`; track status and log spec gaps as you hit them (fix in a batch after ship).

```markdown
# <Project> Workflow Notes — `<project>` (<topic>)
**Channel**: UCEgIrCo0pR6DyyrXuSn3wBg | **Started**: <YYYY-MM-DD>
Running through docs/superpowers/specs/2026-04-18-video-production-workflow.md.

- [ ] Step 0 — 选题 via video2yt-topic (relay verbatim; EVERY pick carries both links incl. in 推荐/跳过)
- [ ] Step 1 — download both sources via video2yt-prefetch -o temp/ (check 1080p)
- [ ] Step 2 — stems + video2yt-subtitle --skip-cleanup (speech2srt ONCE) → read raw ASR + danmaku → content_understanding.md + intro_script.txt  [REVIEW #1: understanding + script]
- [ ] Step 3 — term-check (danmaku/topic first, then zhTW card art) → correct intro_script.txt
- [ ] Step 4 — TTS → transcribe → image → video2yt-intro → intro.mp4  [REVIEW #2: intro.mp4]
- [ ] Step 5 — per segment: music-mix + clean raw SRT MYSELF (subagents → speech.cleaned.ass) + video2yt-burn
- [ ] Step 6 — append_cta.sh on battle 1 → _cta.mp4
- [ ] Step 7 — video2yt-merge (-o is a FILE path) → final + chapters
- [ ] Step 8 — thumbnail_polish.py (8-char two-tier, 5 directions, don't pick alone)  [REVIEW #3: thumbnail]
- [ ] Step 9 — youtube_metadata.json (feina title; one chapter block; #英雄戰場教學 in first 3)
- [ ] Step 10 — video2yt-upload (dry-run then real; OAuth URL → user clicks Allow)
- [ ] Step 11 — post_comment.py (MANDATORY: recap + 按讚/訂閱/小鈴鐺)
- [ ] Step 12 — video2yt-cleanup --project <project> --yes (dry-run first)

## Issues to fix later
<!-- ### N. <title> — Step / Symptom / Proposed fix -->
```
