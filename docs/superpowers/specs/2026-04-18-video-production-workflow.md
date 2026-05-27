# YouTube Video Production Workflow

**Date**: 2026-04-18
**Status**: Validated end-to-end on `back2back` project (S13 炉石战棋 教程)
**Target audience**: Future Claude agents and the user, when producing similar topical YouTube videos from Bilibili source material.

## 1. Goal

Take a topical brief (e.g. "S13 最強輪椅 背靠背流派 教程") and produce a publish-ready YouTube video with:

- A short (~30s) original spoken intro
- One or more burnt-in Bilibili source segments (with danmaku) as the body
- A concatenated final MP4 with chapter markers + loudness normalization
- A YouTube thumbnail
- Localized title / description / tags
- Uploaded to YouTube via API with all metadata pre-filled

The pipeline is implemented as a sequence of 9 steps, each backed by an existing CLI command (`video2yt-*`) or a one-off script in `scripts/`.

## 2. Per-project folder convention

**Every artifact for a project MUST live under `output/<project>/`.** Use a short, lowercase, ASCII project name (e.g. `back2back`).

Pass `-o output/<project>/` to every `video2yt`, `video2yt-compose`, and `video2yt-merge` invocation. CLAUDE.md documents this convention in the "Project folder convention" section.

Final layout for `back2back/`:

```
output/back2back/
├── intro_script.txt              # Step 1 source
├── intro_script_prompt.txt       # (optional, if generated)
├── intro_image_prompt.txt        # Step 3 source
├── thumbnail_bg_prompt.txt       # Bonus step source
├── intro.mp3                     # Step 2 output
├── intro.srt                     # Step 4 output
├── intro_bg.png                  # Step 3 output (1920x1080, fitted)
├── intro_bg_raw.png              # Step 3 raw (1024x1024 from Gemini)
├── intro.mp4                     # Step 5 output (intro video)
├── thumbnail_bg.png              # Bonus step bg
├── thumbnail.png                 # Bonus step composed thumbnail (1280x720)
├── <uploader>：<title>/          # Step 6 burnt segment 1
│   └── BV...._final*.mp4
├── <uploader>：<title>/          # Step 6 burnt segment 2
│   └── BV...._final*.mp4
├── back2back_final.mp4           # Step 7 merged final video
├── back2back_final_chapters.txt  # Step 7 YouTube chapters (description paste)
├── back2back_final_ffmeta.txt    # Step 7 ffmetadata embedded into the MP4
├── youtube_metadata.txt          # Step 8 human-readable
├── youtube_metadata.json         # Step 8 machine-readable (for Step 9)
└── (uploaded video URL)          # Step 9 stdout
```

## 3. External dependencies and credentials

| Component | Where | Setup |
|---|---|---|
| `ffmpeg`, `ffprobe` | system PATH | `brew tap homebrew-ffmpeg/ffmpeg && brew install homebrew-ffmpeg/ffmpeg/ffmpeg` (must include libass) |
| Volcengine BigTTS | API key | Volcano Ark console → API Key 管理 → create. Stored as `VOLCENGINE_API_KEY` in `.env`. Only the new (single-key) auth style works; legacy v1 endpoints need separate AppID. |
| Codex CLI (default for image gen + Stage 3 subtitle cleanup + Step 4 intro alignment) | `codex` in PATH, logged in | `brew install codex` then `codex login`. Uses ChatGPT auth; no separate API key required. |
| `speech2srt` CLI (Stage 3 subtitle backbone — Volcengine 火山 Seed-ASR) | `speech2srt` in PATH | One-time: `cd ~/code/speech2srt && uv tool install . --force`. Requires `VOLCENGINE_API_KEY` (same env var as BigTTS — single key works for both Volcano services if scoped right; otherwise create a separate key under 语音技术 → 豆包录音文件识别模型2.0). Cost ~¥0.0003/char, ≈ ¥0.1 per 4-min segment. |
| `song-remover` CLI (Stage 2 stems backbone — Bandit-v2 multilingual separator) | `song-remover` in PATH | One-time: `cd ~/code/song-remover && uv tool install '.[remote]'` (the `[remote]` extra bakes the `modal` SDK in). Default `--device remote` needs `uv run modal token new` + Modal app deploys per `song-remover` README. |
| Google Gemini (image-gen fallback) | API key | Google AI Studio → API key. Image-generation model requires a paid/billed key (free tier limit = 0). Stored as `GEMINI_API_KEY` in `.env`. Only needed when running `image_quick.py --backend gemini`. |
| YouTube Data API v3 | OAuth client | Google Cloud Console → enable YouTube Data API v3 → create OAuth client (desktop app). Save JSON as `client_secret.json` (gitignored). First run opens browser for consent (test users must be allow-listed during testing mode). Token cached in `youtube_token.json` (gitignored). |
| Hearthstone Battlegrounds logo | `assets/hsbg_logo.png` | One-time download from Fandom wiki (RGBA, 4098x2146). |

`.env` and all secrets live in repo root, gitignored via `.gitignore` (`.env`, `client_secret*.json`, `youtube_token.json`).

## 4. The 9-step pipeline

### Step 1 — Write a 30-second script

**Input**: brief outline (sentence or two), target length (~30s).
**Output**: `output/<project>/intro_script.txt` (UTF-8 plain text, ~110 chars for 30s at 1.0x speed).

Hand-write or LLM-draft the script. Length rule of thumb: **3.7 chars/sec at speech_rate=0** (1.0x). For a 30s intro, aim for 100–120 Chinese chars.

**Before drafting (HARD RULE — added after `ringnaga` mistake)**: when the topic involves a Hearthstone Battlegrounds 流派/阵容/卡牌, FIRST verify the terminology before writing any script. Steps:
1. `WebFetch https://search.bilibili.com/all?keyword=<策略名>` to find the UP 主's video on the topic. Read the first few titles + descriptions.
2. Confirm what the 流派 actually pivots on — usually a specific 6-7星核心隨從 or hero. The Chinese name often differs from the English mechanic ("護戒" = the card 戒指龍 = Ring Bearer, NOT a Spellcraft "ring" buff).
3. Only after confirming with the user (or matching the source video) should you draft the script.

**Battlegrounds vocabulary (use these, NOT constructed-mode terms)**:

| Use | Don't use | Notes |
|---|---|---|
| 阵容 / 流派 / 體系 | 牌組 / 套牌 / 構築 | "牌组" is constructed-only |
| 隨從 / 小弟 | 法術 (rare in BG) | The board is mostly minions |
| 酒館 / 卡池 / 升級 | 抽牌 / 牌庫 | BG has a tavern, not a deck |
| 站位 / 排位 | 起手 / mulligan | "起手" is constructed |
| 餵 / 養 / 疊屬性 | 過渡 | "過渡" sounds like deck-building |
| 開局 / 中期 / 後期 / 終局 | 早期 / 後期 alone | OK in moderation |
| 吃雞 / 吃八雞 / 上分 | — | BG ranking jargon |
| 種族羈絆 (海盜 / 元素 / 機械 / 食屍鬼 / 娜迦 / 龍 / 野獸 / 惡魔 / 任務小隊) | 種族特性 | Use the official族群 names |
| 三聯 / 三合一 / 三星 | — | Combine 3 same minions |
| 法術強化 (Spellcraft) | — | Tavern spells with a cost-modifier mechanic |
| 加buff / 加屬性 | 增益 | More natural in BG context |

### Step 2 — TTS via Volcengine BigTTS

**Input**: `intro_script.txt`, voice ID, speech rate.
**Output**: `output/<project>/intro.mp3`.
**Script**: `scripts/tts_quick.py`.
**API**: HTTP Chunked unidirectional (`POST https://openspeech.bytedance.com/api/v3/tts/unidirectional`).

```bash
uv run python scripts/tts_quick.py \
  --text-file output/<project>/intro_script.txt \
  --output    output/<project>/intro.mp3 \
  --speech-rate 0
```

Auth: `X-Api-Key: $VOLCENGINE_API_KEY` + `X-Api-Resource-Id: seed-tts-2.0`.
Default voice: `zh_female_vv_uranus_bigtts`.
Speech rate range: `[-50, 100]`; `0` = 1.0x, `100` = 2.0x, `-50` = 0.5x.

### Step 3 — Background image via Codex `image_gen` (default) or Gemini (fallback)

**Input**: detailed art-direction prompt, target size.
**Output**: `output/<project>/intro_bg.png` (1920x1080, center-cropped).
**Script**: `scripts/image_quick.py`.

```bash
# Default: Codex backend (ChatGPT auth, no separate API key, no billing).
uv run python scripts/image_quick.py \
  --prompt-file output/<project>/intro_image_prompt.txt \
  --output      output/<project>/intro_bg.png \
  --save-raw    output/<project>/intro_bg_raw.png \
  --target-size 1920x1080 \
  --fit cover

# Fallback: Gemini (requires GEMINI_API_KEY with billing enabled).
uv run python scripts/image_quick.py --backend gemini ...
```

Codex backend (default) calls `codex exec` with the `image_gen` tool; native output is 1536x1024 (3:2). Gemini backend always returns 1024x1024 (1:1). In both cases the script center-crops or letterboxes to the target. Prompts should explicitly say "no text, no logos, no watermarks" — both models hallucinate text/logos otherwise.

Codex invocation gotchas (validated on `ringnaga`):
- Do NOT pass `writable_roots`. The default `--sandbox workspace-write` already allows writing inside cwd; adding `writable_roots` once caused an 11+ minute hang.
- Keep the instruction concise. Multi-step checklists trigger an approval/thinking loop. The script wraps the user prompt with a single-sentence "use image_gen, save to <path>" preamble.
- First-time setup: `brew install codex && codex login`.

### Step 4 — Forced-alignment SRT

**Input**: `intro.mp3` + `intro_script.txt`.
**Output**: `output/<project>/intro.srt`.
**Tool**: existing `video2yt-transcribe` (whisperx + wav2vec2, CPU).

```bash
uv run video2yt-transcribe \
  --audio  output/<project>/intro.mp3 \
  --script output/<project>/intro_script.txt \
  --max-block-chars 30 \
  -o       output/<project>/intro.srt
```

Text comes from the script (preserves correct terms / punctuation); whisperx provides only timestamps. Splits by Chinese sentence punctuation (`。`, `！`, `？`). Pass `--max-block-chars N` to additionally split sentences longer than N chars at semicolons/commas (`；，、;,`) — useful when the script uses commas/semicolons instead of periods in long sentences (the `ringnaga` script had a 60-char block that ran 12 seconds before this flag existed).

### Step 5 — Compose the intro MP4

**Input**: `intro.mp3` + `intro_bg.png` + `intro.srt`.
**Output**: `output/<project>/<title>/<title>.mp4` (1080p, 30fps, h264 + aac).
**Tool**: existing `video2yt-compose`.

```bash
uv run video2yt-compose \
  --audio  output/<project>/intro.mp3 \
  --image  output/<project>/intro_bg.png \
  --srt    output/<project>/intro.srt \
  --title  back2back_intro \
  -o       output/<project>/
```

Then move/rename the result to `output/<project>/intro.mp4` so Step 7 can reference it cleanly.

`compose.render` was patched in this session to probe the audio and pass `-t <audio_duration>` to ffmpeg, working around `-shortest` not stopping the looped image stream when AAC flushes. Output now matches the audio within ~80ms.

### Step 6 — Burn N Bilibili segments (five-stage pipeline)

**Input**: Bilibili URL + optional `--cut START~END` ranges + optional `--speed`.
**Output**: `output/<project>/<uploader>：<title>/<bv>_final[_cut][_<speed>x][_preview].mp4` + sidecar `<bv>_final_music_credits.txt`.
**Tool**: `video2yt` (one CLI that orchestrates 5 stages).

```bash
uv run video2yt "<bilibili_url>" \
  [--cut 0~6]      \
  [--speed 1.25]   \
  [--no-subtitle]  \
  [--no-music-swap] \
  -o output/<project>/
```

The five stages, all gated by the right skip flags (full details in `docs/superpowers/specs/2026-05-24-step6-restructure.md`):

1. **fetch** — yt-dlp downloads the raw mp4 + danmaku XML; biliass converts to ASS. Raw artifacts cached under `temp/<uploader>：<title>/<bv>.*`.
2. **stems** — `song-remover` (Bandit-v2, default `--device remote` = Modal cloud GPU, ~7.2× faster than local CPU) writes 4 stems to `<bv>/{speech,music,sfx,no_music}.wav`. Only `speech.wav` is consumed downstream; the others stay on disk. Cache: `<bv>/.stems_source_meta.json`.
3. **subtitle** — `speech2srt` subprocess (out-of-tree at `~/code/speech2srt`) runs Volcengine 豆包 Seed-ASR on `speech.wav` with word-level timing, then codex cleanup using a per-project free-form `--context-file` (authored at `output/<project>/subtitle_context.txt`, ≤ 2 KB). speech2srt owns its own cache at `<bv>/speech.wav.speech2srt.{json,srt}`; video2yt converts the SRT → `<bv>/speech.cleaned.ass` (Stage 5 contract). Cost ~¥0.0003/char (≈ ¥0.1 per 4-min segment).
4. **music-mix** — CC0 bed stitched from `~/.cache/video2yt/music/` (Kevin MacLeod, CC BY 3.0 by default — attribution required, written to `<bv>.music_credits.txt`). Cache: `<bv>.music_bed_meta.json`.
5. **burn** — ONE ffmpeg `-filter_complex` invocation: danmaku ASS + cleaned subtitle ASS burned together; speech + bed sidechain-ducked amix replaces source audio; optional cuts and speed applied last. Output: `-pix_fmt yuv420p -r 30 -ar 48000` for downstream merge compatibility.

Each stage has its own per-CLI for partial reruns:

```bash
uv run video2yt-fetch "<url>" -o temp/
uv run video2yt-stems temp/<dir>/<bv>.mp4
uv run video2yt-subtitle temp/<dir>/<bv>.mp4 --context-file output/<project>/subtitle_context.txt
uv run video2yt-music-mix temp/<dir>/<bv>.mp4
uv run video2yt-burn temp/<dir>/ --bv <bv> -o output/<project>/<dir>/<bv>_final.mp4
```

The orchestrator skip flags:

| Flag combination | Stages run |
|---|---|
| (no flags) | 1+2+3+4+5 — full pipeline |
| `--no-subtitle` | 1+2+4+5 (stems still runs; music-swap needs `speech.wav`) |
| `--no-music-swap` | 1+2+3+5 (stems still runs; subtitle needs `speech.wav`; Stage 5 maps source audio) |
| `--no-subtitle --no-music-swap` | 1+5 (legacy danmaku-only path) |

**Per-streamer skip-flag matrix:**

| Streamer | Burnt-in subs? | Recommended flags |
|---|---|---|
| 炉石郭枫荷 (郭楓荷) | YES — source already has subs at the bottom | `--no-subtitle` |
| 炉石传说瓦莉拉 | NO | (default — run subtitle) |
| 炉石Kimmy | NO | (default) |
| 高冷难神衣锦夜行 (夜吹) | NO | (default) |

For any new streamer, eyeball the source video once before committing — if the streamer's stream has a bottom subtitle track (most Bilibili UP 主 add their own), pass `--no-subtitle` to save the ~3-6 min subtitle pipeline cost AND avoid double-subtitle visual mess.

**Authoring the per-project subtitle context (Stage 3):** speech2srt's `--cleanup` reads `output/<project>/subtitle_context.txt` (≤ 2 KB UTF-8 free-form text). Write one per project describing:
- Streamer name(s) (e.g. `B站UP主炉石郭枫荷`, `瓦莉拉`)
- 流派 / 策略 + key 卡牌/隨從 names (繁體 OR 简体 — speech2srt's codex prompt handles both)
- Streamer-specific 口頭禪 / 黑話
- Known ASR error patterns (e.g. `'升过级'常被识别成'升过几'`)

Pass via `video2yt --subtitle-context-file output/<project>/subtitle_context.txt`. NO sibling-file fallback — if the flag is omitted, a stderr WARNING fires and speech2srt runs context-less (quality drops; usable but not great).

**Performance** (17 min source segment):

| Phase | Cold | Warm cache |
|---|---|---|
| Stage 1 fetch | ~30s | ~0s (cache hit) |
| Stage 2 stems (`--device remote`) | ~12–15 min | ~0s |
| Stage 2 stems (`--device cpu`) | ~3 hr | ~0s |
| Stage 3 subtitle | **~3–6 min (provisional)** — extrapolated from a 4-min smoke at 4:43; T7 production verification on a 17-min segment is the canonical measurement | <5s (speech2srt cache hit) |
| Stage 4 music-mix | ~30s | ~0s |
| Stage 5 burn | ~3 min | ~3 min (no cache) |
| **Total cold (remote)** | **~18–24 min (provisional)** | — |
| **Total warm** | — | **~3 min** |

Modal cost: ~$0.10 per 17-min segment, within Modal's $30/mo free tier for personal use.

**Migration note (2026-05-24)**: The old three-step pipeline (`video2yt` → `video2yt-music-swap` → `video2yt-subtitle`) was collapsed into this five-stage pipeline by the step6-restructure plan. The legacy `_with_danmaku.mp4`, `_clean.mp4`, `_subbed.mp4` intermediates are gone — the only segment output is `<bv>_final.mp4`. `video2yt-music-swap` was deleted; its bed-build logic moved into `video2yt-music-mix`, its Demucs separation was replaced by song-remover, and its mix step moved into Stage 5's `-filter_complex`.

### Step 7 — Merge into final video

**Input**: ordered list of `--segment` + `--label` pairs (intro first), plus a working title.
**Output**: `output/<project>/<title>.mp4` + `<title>_chapters.txt` + `<title>_ffmeta.txt`.
**Tool**: existing `video2yt-merge`.

```bash
uv run video2yt-merge \
  --segment output/<project>/intro.mp4                            --label "intro" \
  --segment output/<project>/<uploader1>：.../<bv1>_final_cut.mp4 --label "教程" \
  --segment output/<project>/<uploader2>：.../<bv2>_final_1.25x.mp4 --label "郭楓荷實戰" \
  --title   "<working_title>" \
  -o        output/<project>/<project>_final.mp4
```

All `--segment` inputs MUST be 1920x1080 30fps h264 (strict) AND ≥10s long, with at least 3 segments total (those rules mirror YouTube's chapter requirements; see Step 8). Output: concat + per-segment loudnorm to -14 LUFS. There is no burned-in progress bar — segmentation must be delivered through the description chapter block written in Step 8. merge writes `<title>_chapters.txt` for that paste, and also embeds the same chapters into the MP4 via `<title>_ffmeta.txt` + `-map_metadata`/`-map_chapters` as a best-effort extra (YouTube does not officially document reading embedded chapter atoms, so this is NOT a safety net for a missing description block).

### Step 8 — Generate YouTube metadata

**Output**: two files in `output/<project>/`:

- `youtube_metadata.txt` — human-readable; sections separated by `===` headers; contains title, two description variants (繁體 Taiwan + 简体), tags, chapters.
- `youtube_metadata.json` — structured for Step 9. Fields:

```json
{
  "title": "...",
  "description": "...",
  "tags": ["..."],
  "category_id": "20",
  "default_language": "zh-Hant",
  "default_audio_language": "zh-Hant",
  "privacy_status": "public",
  "made_for_kids": false,
  "expected_channel_id": "UC...",
  "video_path": "output/<project>/<project>_final.mp4",
  "thumbnail_path": "output/<project>/thumbnail.png"
}
```

**Title format (locked):**

```
「英雄戰場」S<season><topic>完整教學 | <streamer1> × <streamer2> 實戰 [彈幕]
```

Examples:
- `「英雄戰場」S13龍族崛起！紅龍滾雪球完整教學 | 郭楓荷 × 瓦莉拉 實戰 [彈幕]`
- `「英雄戰場」S13宰割亡靈完整教學 | 郭楓荷 × 夜吹 實戰 [彈幕]`

Rules:
- Prefix is the player-口語 short name `「英雄戰場」` with Japanese-style 「」 brackets (NOT `[]`, NOT `《》`). The official full name 「爐石戰記：英雄戰場」 is too long for the title slot — keep it for the description body's first paragraph as a branding cue.
- **No space** between `」` and the season number; no space between season number and topic — compact CJK style.
- Season prefix is **uppercase `S`** (e.g. `S13`).
- Hook phrases (e.g. `龍族崛起！`) can be embedded as part of the `<topic>` slot when a catchier title is needed.
- Topic + `完整教學`, pipe `|` with single spaces on both sides.
- Streamer names in 繁體, joined by ` × ` (with spaces) when multiple.
- Final tag `[彈幕]` with half-width brackets.
- DO NOT use `[爐石戰棋]` (China/B站 用法), `[Hearthstone Battlegrounds]` (global English), or 简体字 anywhere in the title.

For Taiwan audience, primary description is 繁體 with TW grammar; append 简体 below as secondary. The first paragraph of the 繁體 description should mention `「爐石戰記：英雄戰場」` once so the channel branding stays connected to Blizzard's Taiwan localization.

**Required hashtags in the description body (locked):** every video's description MUST end with a hashtag line that includes **`#英雄戰場教學`** as a channel-wide tag. Put it among the first three hashtags so YouTube renders it above the title (YouTube only surfaces the first 3 hashtags as the above-title link). Recommended pattern:

```
#英雄戰場教學 #英雄戰場 #爐石戰記 #<策略名> #<核心隨從> #戰棋 #Hearthstone #Battlegrounds
```

The remaining hashtags (策略名 / 核心隨從 / 其他) vary per video, but `#英雄戰場教學` is the cross-video channel anchor and is NOT optional.

**Chapter timestamps in the description — required, exactly one ascending block.** The description is the **only officially-supported** way to get the YouTube progress-bar segmentation. Rules YouTube enforces:

1. At least 3 timestamps.
2. First timestamp is `00:00`.
3. All timestamps strictly ascending, on their own lines.
4. Each chapter ≥10 seconds.
5. The whole list lives in **one** block — there must not be a second block that resets to `00:00`.

A duplicated block (e.g. one under 繁體, another under 简体) makes the sequence jump backwards to `00:00` and YouTube discards the whole list — that is the `back2back`/`ringnaga`/`chickenking` bug. So put the `時間軸：` block **once** and do **not** repeat it inside the 简体 section. Copy directly from `<title>_chapters.txt` produced by merge — that file is already formatted correctly. merge also embeds the same chapters into the MP4 itself as a best-effort extra, but YouTube does NOT officially support reading embedded chapter atoms, so don't rely on it as a fallback — get the description block right.

### Bonus — YouTube thumbnail

**Input**: bg image (Step 3 style), logo PNG, **zhTW BGS** card art PNG, 8-char two-tier title.
**Output**: `output/<project>/thumbnail.png` (1280x720).
**Tools**: `video2yt-research-card` (download card art), `video2yt-thumbnail` (base render), `scripts/thumbnail_polish.py` (committed polish pass — vignette + 8-char two-tier title).

**Locked layout (2026-05-10, supersedes earlier `ringnaga` vertical-4-char recipe):**

- Canvas: **1280x720**.
- **Top-left**: HSBG logo (`assets/hsbg_logo.png`), `--logo-target-w 180`, `--logo-margin 16`.
- **Left half (below logo)**: **8-char two-tier title** (formula below).
- **No season text** (S13 etc) — removed because it competed with the card.
- **Right side**: card art bleeds off right + top + bottom. `--card-target-h 1100`, `--card-right-inset -180`, `--card-tilt-deg -18`, `--card-glow-expand 50`. Card supports the title; title is the primary message.
- **Vignette**: radial darken corners ~30% in the polish pass.

**Title formula — 8-char two-tier:**

- **Top row (4 chars, primary):** the 流派 canonical 4-char name (e.g. `護戒娜迦`, `紅龍滾雪`).
- **Bottom row (4 chars, secondary):** quantifiable / promise payoff. Pick from 5 directions:
  - **Numbers** (preferred, most click-worthy) — `兩千攻擊` style absolute-value.
  - **Hyperbole** — `太超模了` / `根本崩盤`.
  - **Tutorial promise** — `必學陣容`.
  - **Mechanic teaser** — 4-char strategy explainer.
  - **Action / emotion** — visceral verb-driven phrase.

Always present the 5 directions to the user with examples drawn from the source-video titles, then propose 3–4 concrete 4-char picks under the chosen direction. **Do not pick alone.**

**Visual params for the title (rendered in the polish pass, NOT the CLI — the CLI only supports single-row titles):**

```
row 1 (primary):    text=<流派 4 字>
                    font=Hiragino Sans GB W6, font_size=180
                    fill=pure white (255,255,255), stroke=black 16px
                    drop-shadow: offset (10,14), blur 12, alpha 235
                    char_gap=-10  (slight overlap, "stamp" feel)
                    position: x=20, y=140

row 2 (secondary):  text=<4 字 payoff>
                    font=Hiragino Sans GB W6, font_size=130
                    fill=saturated gold (245,195,75), stroke=dark brown (70,25,0) 12px
                    drop-shadow: offset (7,10), blur 10, alpha 220
                    char_gap=-6
                    position: x=30, y=380
```

**Card art**: use the **zhTW BGS art** for any BG card (繁體 card name matches the Taiwan audience). `video2yt-research-card` currently downloads enUS only — manually `curl https://art.hearthstonejson.com/v1/bgs/latest/zhTW/512x/<id>.png` into `assets/cards/<slug>_zhTW_bgs_512.png` until the CLI grows a `--locale` flag.

**Background**: Codex `image_gen` via `video2yt-image --backend codex` (default), 16:9 atmospheric tavern/scene matched to topic. **No figures, characters, text, or logos** in the prompt. Keep top-left, top-right, far-left, and far-right bands darker so logo + title + card overlay cleanly.

**Invocation pattern:**

```bash
# 1. Background
uv run video2yt-image --backend codex \
  --prompt-file output/<project>/thumbnail_bg_prompt.txt \
  --output      output/<project>/thumbnail_bg.png \
  --save-raw    output/<project>/thumbnail_bg_raw.png \
  --target-size 1280x720 --fit cover

# 2. zhTW card art (manual curl until --locale lands)
curl -o assets/cards/<slug>_zhTW_bgs_512.png \
  https://art.hearthstonejson.com/v1/bgs/latest/zhTW/512x/<id>.png

# 3. Base render — title pushed offscreen so CLI's vertical-title rendering doesn't paint
uv run video2yt-thumbnail \
  --bg     output/<project>/thumbnail_bg.png \
  --logo   assets/hsbg_logo.png \
  --card   assets/cards/<slug>_zhTW_bgs_512.png \
  --title  "X" --season "" \
  --orientation card-tilt-right \
  --logo-target-w 180 --logo-margin 16 \
  --font-size 1 --stroke-width 0 \
  --title-anchor-x-abs 9000 \
  --shared-top-y 30 \
  --card-target-h 1100 --card-right-inset -180 \
  --card-glow-expand 50 --card-tilt-deg -18 \
  --output output/<project>/thumbnail_pre_polish.png

# 4. Polish pass (vignette + 8-char two-tier title)
uv run python scripts/thumbnail_polish.py \
  --input     output/<project>/thumbnail_pre_polish.png \
  --output    output/<project>/thumbnail.png \
  --primary   "<4 字流派>" \
  --secondary "<4 字 payoff>"
```

`thumbnail_compose.py` still supports three orientations (`card-tilt-right` default, plus `vertical-left` and `horizontal-bottom` legacy), but **all new projects MUST use `card-tilt-right` + the 2-tier polish-pass title**. Do not invent a new layout per project.

`video2yt-research-card` queries `api.hearthstonejson.com/v1/latest/enUS/cards.json` (cached at `~/.cache/video2yt/`, 7-day TTL). `--style auto` picks `bgs` for BATTLEGROUND-set cards, `render` for constructed.

### Step 9 — Upload to YouTube

**Input**: `youtube_metadata.json`, `client_secret.json`, cached `youtube_token.json` (or fresh OAuth flow on first run).
**Output**: published video URL printed to stderr.
**Script**: `scripts/youtube_upload.py`.

```bash
# First time: OAuth dry-run to verify channel
uv run python scripts/youtube_upload.py \
  --metadata output/<project>/youtube_metadata.json \
  --dry-run

# Real upload
uv run python scripts/youtube_upload.py \
  --metadata output/<project>/youtube_metadata.json
```

Behavior:

1. OAuth via `InstalledAppFlow.run_local_server(port=0)`. Browser opens for consent on first run; token cached to `youtube_token.json` after.
2. Lists authenticated channels via `channels.list(mine=True)`. **Aborts** if `expected_channel_id` from metadata is not in the list (catches wrong-account auth). All uploads from this repo go to channel **`UCEgIrCo0pR6DyyrXuSn3wBg`** — use it as `expected_channel_id`.
3. Resumable upload via `MediaFileUpload` with 8 MB chunks. Progress logged every ≥5%.
4. Uploads thumbnail via `thumbnails().set()` after video upload completes.
5. Prints watch URL + studio URL.

OAuth gotchas:

- App in "Testing" status only allows allow-listed test users (add at OAuth consent screen → test users).
- Test-mode refresh tokens expire after 7 days. **`get_credentials` auto-recovers**: if `creds.refresh()` raises `RefreshError`, the cached `youtube_token.json` is deleted and `run_local_server` is invoked to mint a fresh token. The browser will pop again on day 8+.
- Brand channels require signing in to that brand account during the OAuth consent flow.

## 5. Scripts added by this workflow

All under `scripts/` (untracked by default — they're project-specific tooling, but useful enough to be reused; promote to `src/video2yt/` if formalizing into proper CLIs).

| File | Purpose | Key deps |
|---|---|---|
| `scripts/tts_quick.py` | Volcengine BigTTS HTTP Chunked client | `requests`, `python-dotenv` |
| `scripts/image_quick.py` | Image-gen via Codex (default) or Gemini, then crop/letterbox to target | `google-genai`, `Pillow`, `python-dotenv`, `codex` CLI |
| `scripts/thumbnail_compose.py` | Pillow composite: bg + logo + (season + tilted card +) vertical/horizontal title with auto-shrink | `Pillow` |
| `video2yt-research-card` (`src/video2yt/research_card{,_cli}.py`) | Look up Hearthstone card on hearthstonejson.com and download 512px art | `requests` |
| `scripts/youtube_upload.py` | YouTube Data API v3 OAuth + resumable upload + thumbnail set | `google-api-python-client`, `google-auth-oauthlib`, `google-auth-httplib2` |

`pyproject.toml` got these new deps added during this session:

- `google-genai>=1.73.1`
- `google-api-python-client>=2.194.0`
- `google-auth-oauthlib>=1.3.1`
- `google-auth-httplib2>=0.3.1`
- `python-dotenv>=1.2.2`
- `requests>=2.33.1`

## 6. Tech debt and follow-ups

| Area | Status | Notes |
|---|---|---|
| `compose -shortest` bug | **Fixed** in this session | `compose.render` now probes audio duration and adds `-t <audio_duration>` as an output-side clamp. |
| Promote `scripts/*.py` to CLIs | Pending | User originally chose option (A) — formalize as `video2yt-tts`, `video2yt-image`, `video2yt-thumbnail`, `video2yt-upload` with TDD. Current scripts are working but lack tests and are not installed as console scripts. |
| Image fit aspect ratio | Improved (Codex 3:2) | Gemini outputs 1024x1024 (44% vertical loss to 16:9). Codex `image_gen` outputs 1536x1024 (3:2 — only ~16% loss). The `image_quick.py --backend codex` default benefits from this; can switch back via `--backend gemini`. |
| Thumbnail font auto-fit | **Fixed** | Both `vertical-left` and `card-tilt-right` orientations now auto-shrink the title font in 4-pt steps when the stacked rows would overflow the available height. Logged to stderr when shrink fires. |
| OAuth app publishing | Pending (user-side) | While in Testing status, tokens expire in 7 days. To upload reliably long-term, publish the OAuth consent screen (or rotate tokens). |

## 7. Verification log — projects that have shipped through this pipeline

| Project | Date | Video ID | Notes |
|---|---|---|---|
| `back2back` | 2026-04-17 | [`DuglxlhKbzw`](https://www.youtube.com/watch?v=DuglxlhKbzw) | First end-to-end run. `intro.mp3` 21.89s → `intro.mp4` 21.97s (Δ < 0.1s). Final 21:55, 847 MB. 8m 24s upload. Originated the `compose -shortest` fix. |
| `ringnaga` | 2026-05-02 | [`hP27PqfL6zY`](https://www.youtube.com/watch?v=hP27PqfL6zY) | First `card-tilt-right` thumbnail. Validated Codex `image_gen` as Gemini fallback. Surfaced 6 workflow improvements (term research, BG glossary, thumbnail formalization, transcribe multi-separator, OAuth auto-refresh, image backend), all batched after ship and folded into this spec on 2026-05-03. |
| `redchroma` | 2026-05-23 | [`QwzUGIE3C6s`](https://www.youtube.com/watch?v=QwzUGIE3C6s) | First end-to-end run of `video2yt-music-swap` (Step 6.5). 22 Kevin MacLeod CC BY 3.0 tracks auto-downloaded from Internet Archive on first invocation. Demucs MPS path ~10 min per ~18-min segment. Hit a torchaudio backend bug on first attempt; fixed by `uv add soundfile` mid-pipeline. 瓦莉拉's source was VIP-locked at 480p, so the burnt segment had to be upscaled to 1920x1080 via ffmpeg before music-swap to meet merge's strict resolution rule. Final 36:37, 1.26 GB. 4m 43s upload. |
| `mooniron` | 2026-05-24 | [`O5tkP2YAFhY`](https://www.youtube.com/watch?v=O5tkP2YAFhY) | Last segment shipped under the old 3-step pipeline (`video2yt` → `video2yt-music-swap` → `video2yt-subtitle`). Surfaced the merge audio-truncation gotcha (initial upload `RrR9lqn3M3s` lost 27 min of audio from the 夜吹 segment) — root cause was yt-dlp merger truncation on cached download; fixed by quarantining `.broken` files and validating AV duration match in `download.fetch`. |
| `dragon_snip_4m50_to_9m` A/B | 2026-05-25 | — | T11 regression run for the step6-restructure (new five-stage pipeline). Source: 4:10 mooniron sub-clip (1920×1080 h264, 250.1s, 143 MB). New pipeline outputs an identical 1920×1080 30fps h264 yuv420p file (136.5 MB / 4577 kbps / **duration 250.10s, exact match** vs OLD pipeline's 250.07s drift). Audio sample-rate flipped 44.1k → **48k** (T6 design: aligns with song-remover speech.wav). Wall-clock: stems 1:57 (Modal T4) + ASR 2:03 + cleanup 0:18 + music-mix 0:01 + burn 1:00 = **5:21 cold** (≈ 1.28× realtime). Old pipeline same clip estimated 30–50 min (Demucs CPU + two video re-encodes) → **~6–10× speedup**. Artifacts: `output/regression-ab/dragon_snip_NEW_final.mp4`; A/B baseline `output/mooniron/dragon_snip_4m50_to_9m_b_subbed.mp4`. |

## 8. Per-project workflow template

Every new project starts by creating `output/<project>/` and copying this checklist into a project-local `WORKFLOW_NOTES.md`. Track step status as you go, and **log every awkward bit / spec gap into the "Issues to fix later" section without breaking flow** — fix in a batch after the video ships.

```markdown
# <Project> Workflow Notes

**Project**: `<project>` (<one-line topic>)
**Channel**: `UCEgIrCo0pR6DyyrXuSn3wBg`
**Started**: <YYYY-MM-DD>

Running through `docs/superpowers/specs/2026-04-18-video-production-workflow.md`.
Anything that should be fixed in the scripts / CLIs / spec gets logged below as
we hit it. Address them in a batch after the video ships.

## Step status

- [ ] Step 1 — write intro script (term-research first if BG topic; see spec Step 1)
- [ ] Step 2 — TTS via `tts_quick.py`
- [ ] Step 3 — bg image via `image_quick.py` (Codex backend default)
- [ ] Step 4 — forced-alignment SRT via `video2yt-transcribe`
- [ ] Step 5 — compose intro via `video2yt-compose`
- [ ] Step 6 — burn N Bilibili segments via `video2yt`
- [ ] Step 6 covers the full per-segment pipeline (fetch → stems → subtitle → music-mix → burn) in one `video2yt` invocation. Per-segment skip flags `--no-subtitle` / `--no-music-swap` replace the old Step 6.5 / 6.6 sub-steps. See the table in §"Step 6 — Burn N Bilibili segments (five-stage pipeline)" above.
- [ ] Step 7 — merge via `video2yt-merge`
- [ ] Bonus — thumbnail (`video2yt-research-card` → `image_quick.py` for bg → `thumbnail_compose.py --orientation card-tilt-right`)
- [ ] Step 8 — write `youtube_metadata.{txt,json}`
- [ ] Step 9 — upload via `youtube_upload.py`

## Issues to fix later

<!-- Format per item:
### N. <short title>
- **Step**: which workflow step / which script
- **Symptom**: what went wrong / what was awkward
- **Proposed fix**: what to change
-->
```

After the video ships:
1. Review the per-project `WORKFLOW_NOTES.md` "Issues to fix later" section.
2. Implement fixes in the scripts / CLIs / this spec, in priority order (blockers > frequency > cost).
3. Once all items in a project's notes are addressed, the file can be deleted (its lessons live in the spec now). Keep it temporarily if a future project still relies on quirks documented there.
