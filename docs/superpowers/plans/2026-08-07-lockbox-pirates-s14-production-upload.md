# S14 鎖箱海盜 Production and Upload Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Execution authorization — 2026-08-07:** The user approved content review #1, selected the urgent ending below, chose multi-agent execution, and explicitly authorized continuing through direct public upload. Remaining review packages still receive independent internal verification, but execution does not pause again unless a concrete defect or external authentication blocker requires user action.

**Goal:** 把郭楓荷与瓦莉拉的两条 S14 海盗实战制作成一支完整教学视频，以「新經濟循環」为封面卖点，并在 Intro 中完整解释实际出现的新经济卡、成长卡与终局卡机制。

**Architecture:** 复用仓库既有 Stage 1–5 缓存管线：串行下载两条 Bilibili 素材，每条只做一次 raw ASR，再以 speech、弹幕和关键帧建立逐卡证据表。审核通过内容理解与 Intro 文案后，核对官方 zhTW 卡面、制作高对比锁箱 Intro、烧录两条正片、合并并制作缩略图和元数据；公开上传作为独立最终状态变更，必须再次获得明确授权，并验证只加入 S14 播放列表。

**Tech Stack:** `video2yt-prefetch`, `video2yt-stems`, `video2yt-subtitle`, `video2yt-research-card`, HearthstoneJSON zhTW card art, `video2yt-tts`, `video2yt-transcribe`, `video2yt-image`, `video2yt-intro`, `video2yt-music-mix`, `video2yt-burn`, `video2yt-merge`, `video2yt-upload`, ffmpeg/ffprobe.

---

## File map

- Create: `output/lockbox_pirates_s14/WORKFLOW_NOTES.md` — 两次审核、最终上传授权与逐步完成状态。
- Create: `output/lockbox_pirates_s14/content_understanding.md` — 两局内容理解、逐卡机制证据表与数值证据。
- Create: `output/lockbox_pirates_s14/intro_script.txt` — 约 45–50 秒、经过实战证据约束的繁体 Intro 文案。
- Create: `output/lockbox_pirates_s14/terms_zhTW.md` — 官方卡面 ID、繁中名、规则文本和来源 URL。
- Create: `output/lockbox_pirates_s14/subtitle_context.txt` — 字幕清理词表，UTF-8 且不超过 2 KB。
- Create: `output/lockbox_pirates_s14/intro_image_prompt.txt` — 深蓝海盗金库与熔金锁箱背景 Prompt。
- Create: `output/lockbox_pirates_s14/intro_cards.txt` — Intro 实际念到的新卡卡面与 SRT 匹配词。
- Create: `output/lockbox_pirates_s14/intro.{mp3,srt,mp4}` and `intro_bg{,_raw}.png` — 动态 Intro 工件。
- Create: `output/lockbox_pirates_s14/guo/` and `output/lockbox_pirates_s14/vala/` — 两条烧录正片。
- Create: `output/lockbox_pirates_s14/lockbox_pirates_s14_final.mp4` — 最终合并视频。
- Create: `output/lockbox_pirates_s14/thumbnail.png` and `thumbnail_preview_640.png` — 完整与缩小预览缩略图。
- Create: `output/lockbox_pirates_s14/youtube_metadata.json` — YouTube 标题、说明、章节、来源、音乐署名与标签。
- Create: `output/lockbox_pirates_s14/subscribe_comment.txt` — 上传后的繁体订阅评论。
- Modify: `assets/topic/done_topics.txt` — 仅在上传成功后登记本题，避免未发布项目被提前判重。
- Do not modify: 当前工作树中与本项目无关的用户文件、旧项目输出和已有卡牌素材。

### Task 1: Preflight and initialize the project

- [ ] **Step 1: Read the current workflow memory before production**

Run:

```bash
sed -n '1,240p' ~/.claude/projects/-Users-jun-code-video2yt/memory/MEMORY.md
sed -n '60,130p' CLAUDE.md
sed -n '1,220p' docs/superpowers/specs/2026-08-07-lockbox-pirates-production-design.md
```

Expected: the current S14 workflow, one-ASR rule, two review checkpoints, objective Intro style, and S14 playlist isolation are visible before any media work.

- [ ] **Step 2: Verify required tools and credentials without printing secrets**

Run:

```bash
command -v ffmpeg
command -v ffprobe
command -v song-remover
command -v speech2srt
command -v codex
test -s .env
test -s client_secret.json
test -s ~/.modal.toml
ffmpeg -hide_banner -filters 2>/dev/null | rg ' subtitles '
```

Expected: every path lookup prints one executable, all three file checks exit 0, and ffmpeg lists the `subtitles` filter.

- [ ] **Step 3: Create only the current project directories and workflow record**

Run:

```bash
mkdir -p output/lockbox_pirates_s14/guo output/lockbox_pirates_s14/vala output/lockbox_pirates_s14/evidence
```

Create `output/lockbox_pirates_s14/WORKFLOW_NOTES.md` with the approved source BVIDs, the approved cover titles `鎖箱海盜` / `新經濟循環`, and unchecked entries for content review #1, Intro review #2, final media review, and upload authorization.

Expected: only the current project directory is initialized; no previous output is removed.

### Task 2: Download and validate both source videos

- [ ] **Step 1: Prefetch the selected sources serially**

Run:

```bash
uv run video2yt-prefetch \
  'https://www.bilibili.com/video/BV1Lw3U6xEJp' \
  'https://www.bilibili.com/video/BV1uSMU6kEzB' \
  -o temp/
```

Expected: exit 0; both BVIDs report completed 1080p H.264 downloads and non-empty danmaku files. The command remains serial because parallel Bilibili downloads can produce truncated merges.

- [ ] **Step 2: Resolve one exact cached video and danmaku file per BVID**

Run:

```bash
test "$(rg --files temp | rg -c '/BV1Lw3U6xEJp\.mp4$')" -eq 1
test "$(rg --files temp | rg -c '/BV1uSMU6kEzB\.mp4$')" -eq 1
test "$(rg --files temp | rg -c '/BV1Lw3U6xEJp\.danmaku\.(ass|xml)$')" -eq 2
test "$(rg --files temp | rg -c '/BV1uSMU6kEzB\.danmaku\.(ass|xml)$')" -eq 2
rg --files temp | rg '/(BV1Lw3U6xEJp|BV1uSMU6kEzB)\.(mp4|danmaku\.(ass|xml))$'
```

Expected: all four assertions pass and six non-empty paths print: one MP4 plus one raw XML and one converted ASS per BVID.

- [ ] **Step 3: Verify media dimensions, streams, duration, and decode health**

Run:

```bash
guo_video=$(rg --files temp | rg '/BV1Lw3U6xEJp\.mp4$')
vala_video=$(rg --files temp | rg '/BV1uSMU6kEzB\.mp4$')
ffprobe -v error -show_entries stream=codec_type,codec_name,width,height,r_frame_rate,sample_rate -show_entries format=duration -of json "$guo_video"
ffprobe -v error -show_entries stream=codec_type,codec_name,width,height,r_frame_rate,sample_rate -show_entries format=duration -of json "$vala_video"
ffmpeg -v error -i "$guo_video" -f null -
ffmpeg -v error -i "$vala_video" -f null -
```

Expected: both sources are 1920×1080 with video and audio streams; durations are plausibly near 23:31 and 17:52; both full-decode commands exit 0 without errors.

### Task 3: Extract speech exactly once and validate transcript coverage

- [ ] **Step 1: Generate speech stems for both sources**

Run:

```bash
guo_video=$(rg --files temp | rg '/BV1Lw3U6xEJp\.mp4$')
vala_video=$(rg --files temp | rg '/BV1uSMU6kEzB\.mp4$')
uv run video2yt-stems "$guo_video"
uv run video2yt-stems "$vala_video"
```

Expected: each BVID cache directory contains non-empty `speech.wav`, `music.wav`, `sfx.wav`, `no_music.wav`, and `.stems_source_meta.json`.

- [ ] **Step 2: Run raw ASR exactly once per source**

Run:

```bash
set -a
source .env
set +a
guo_video=$(rg --files temp | rg '/BV1Lw3U6xEJp\.mp4$')
vala_video=$(rg --files temp | rg '/BV1uSMU6kEzB\.mp4$')
uv run video2yt-subtitle "$guo_video" --skip-cleanup
uv run video2yt-subtitle "$vala_video" --skip-cleanup
```

Expected: both calls exit 0 and each cache contains non-empty `speech.wav.speech2srt.srt` and `speech.wav.speech2srt.json`. Do not use `--force-asr` and do not invoke subtitle ASR again later.

- [ ] **Step 3: Verify transcript coverage reaches each video's late game**

Run:

```bash
for bvid in BV1Lw3U6xEJp BV1uSMU6kEzB; do
  video_path=$(rg --files temp | rg "/${bvid}\\.mp4$")
  srt_path="$(dirname "$video_path")/$bvid/speech.wav.speech2srt.srt"
  test -s "$srt_path"
  ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 "$video_path"
  tail -16 "$srt_path"
done
```

Expected: both transcripts contain dialogue blocks from the late game; neither ends near the opening or middle due to truncation.

### Task 4: Build the actual new-card mechanism evidence table

- [ ] **Step 1: Extract searchable speech and danmaku evidence**

Read both raw SRT files and both danmaku files. Search for spoken or on-screen aliases related to escapee, lockbox, Golden minions, Discover, Hooktusk, extortionist, Hogg, triple avoidance, APM, and visible end-board numbers. For each match, retain the exact timestamp and source BVID; do not infer a mechanism from the Bilibili title alone.

- [ ] **Step 2: Inspect evenly sampled and targeted keyframes**

Run:

```bash
guo_video=$(rg --files temp | rg '/BV1Lw3U6xEJp\.mp4$')
vala_video=$(rg --files temp | rg '/BV1uSMU6kEzB\.mp4$')
ffmpeg -y -i "$guo_video" -vf 'fps=1/60,scale=480:-2,tile=5x5' -frames:v 1 output/lockbox_pirates_s14/evidence/guo_contact_00.png
ffmpeg -y -ss 00:20:00 -i "$guo_video" -vf 'fps=1/12,scale=480:-2,tile=5x5' -frames:v 1 output/lockbox_pirates_s14/evidence/guo_late_contact.png
ffmpeg -y -i "$vala_video" -vf 'fps=1/45,scale=480:-2,tile=5x5' -frames:v 1 output/lockbox_pirates_s14/evidence/vala_contact_00.png
ffmpeg -y -ss 00:14:00 -i "$vala_video" -vf 'fps=1/10,scale=480:-2,tile=5x5' -frames:v 1 output/lockbox_pirates_s14/evidence/vala_late_contact.png
```

Expected: four readable contact sheets cover setup and late game. Additionally extract single full-resolution PNGs at every speech/danmaku timestamp that supports a new card, a trigger, a Golden-minion counter, or a terminal number.

- [ ] **Step 3: Identify every BG36 Pirate that materially appears in either match**

Start with the source-proven IDs `BG36_523`, `BG36_520t`, `BG36_344`, `BG36_521`, `BG36_343`, `BG36_760`, and `BG36_763`, then inspect both boards, hands, Discover choices, and triggered UI for other actual BG36 Pirates. A card enters the evidence table only when a timestamped source frame proves it appears; cards merely mentioned in commentary go in a separate “spoken but not shown” note and cannot appear in the Intro card timeline. Record `BG36_524` only in the excluded/unverified section because neither source provides a reliable frame.

- [ ] **Step 4: Write `content_understanding.md` with a fixed mechanism table**

Use these sections and columns:

```markdown
# S14 鎖箱海盜內容理解

## 郭楓荷：BV1Lw3U6xEJp
## 瓦莉拉：BV1uSMU6kEzB
## 實際新卡機制表
| Card ID | 官方繁中名 | 類型 | 規則機制 | 實戰作用 | 來源 | 時間點 | 畫面 / speech / 彈幕證據 |
|---|---|---|---|---|---|---|---|
## 完整機制鏈
## 兩局啟動差異
## 可見終局數值
## Intro 可展示卡牌
## 排除的未證實說法
```

Fill both streamer sections with hero, economy source, new cards, turn-by-turn pivot, triple/discover handling, terminal board, and exact evidence. The complete chain must distinguish: spending Gold; escapee/mutineer Lockbox generation and acceleration; deliverer/parrot Golden creation; Cookie Captain same-type resource replacement; actually playing a Golden minion; Hooktusk Discover triggers that scale other Pirates; hero-provided Gold. Do not describe Lockbox itself as direct Gold refund.

- [ ] **Step 5: Run evidence acceptance checks**

Run:

```bash
test -s output/lockbox_pirates_s14/content_understanding.md
rg -n 'BV1Lw3U6xEJp|BV1uSMU6kEzB|BG36_523|BG36_520t|BG36_344|BG36_521|BG36_343|BG36_760|BG36_763|BG36_524' output/lockbox_pirates_s14/content_understanding.md
rg -n '花費|鎖箱|金卡|發現|其他海盜|主廚精選|黃金之觸|霍格' output/lockbox_pirates_s14/content_understanding.md
! rg -n 'T[BB]D|T[OO]DO|待[定]|自動返金' output/lockbox_pirates_s14/content_understanding.md
```

Expected: both sources and every verified core ID occur, the mechanism-chain terms occur, and no placeholder or false direct-Gold-refund claim occurs.

### Task 5: Draft the detailed mechanism Intro and stop at review #1

- [ ] **Step 1: Draft `intro_script.txt` from the verified evidence only**

Requirements:

- Start exactly with `你敢相信？`.
- Use Traditional Chinese and BG vocabulary such as `旅店`, `隨從`, `陣容`, and `異變` when applicable.
- Target 45–50 seconds of narration, approximately 220–250 Chinese characters before TTS timing verification; the user-requested auxiliary new-card mechanisms and fixed urgent ending take priority over an artificially shorter script. Actual synthesized duration remains the hard timing check.
- Explain the mechanism in this order: spending Gold → escapee/mutineer Lockbox production or acceleration → deliverer/parrot Golden creation plus Cookie Captain same-type resources → actually playing a Golden minion → Discover-triggered scaling of other Pirates → the two hero/operation startup differences → visible thousands/near-ten-thousand result.
- Name or show only update cards proven in Task 4. Do not list every new card if it does not materially help explain the actual match.
- Use objective, direct, highly assertive wording; avoid anthropomorphism and metaphors such as `咬一口`, `起飛`, and `引擎`.
- End exactly with: `這套絕對是賽季初期斷層 T0，後續很可能被調整，趁改動前趕緊爽起來！`. This creates urgency without claiming an officially announced deletion or nerf.

- [ ] **Step 2: Run textual acceptance checks**

Run:

```bash
test -s output/lockbox_pirates_s14/intro_script.txt
python -c "from pathlib import Path; s=Path('output/lockbox_pirates_s14/intro_script.txt').read_text().strip(); assert s.startswith('你敢相信？'); assert 220 <= len(s) <= 250; print(len(s))"
rg -n '積極的逃脫者|帶鎖箱|被關押的叛亂者|沉默送貨人|寶藏鸚鵡|餅乾船長|金卡|發現|其他海盜|斷層 T0|趕緊學' output/lockbox_pirates_s14/intro_script.txt
! rg -n '酒館|畸變|牌組|套牌|構築|咬一口|起飛|引擎|T[BB]D|T[OO]DO|待[定]' output/lockbox_pirates_s14/intro_script.txt
```

Expected: the opening, length, mechanism coverage, verdict, CTA, and forbidden-language checks all pass.

- [ ] **Step 3: Review checkpoint #1**

Present the complete two-video understanding, the actual new-card mechanism table, the exact Intro script, and the predicted spoken duration together. The user approved this checkpoint on 2026-08-07 and then requested the fixed urgent ending; record both decisions in `WORKFLOW_NOTES.md` before TTS.

### Task 6: Verify official zhTW names and rules before TTS

- [ ] **Step 1: Download official zhTW BGS art for every Intro card**

Run the research helper for every source-proven new-card English name:

```bash
uv run video2yt-research-card --name 'Enterprising Escapee'
uv run video2yt-research-card --name 'Lockbox'
uv run video2yt-research-card --name 'Hooktusk, Master Marauder'
uv run video2yt-research-card --name 'Locked-up Mutineer'
uv run video2yt-research-card --name 'Silent Deliverer'
uv run video2yt-research-card --name 'Cookie Captain'
uv run video2yt-research-card --name 'Treasure Parrot'
```

For every card retained in the approved Intro, use its resolved official ID to download:

```text
https://art.hearthstonejson.com/v1/bgs/latest/zhTW/512x/<official-card-id>.png
```

Save the seven proven images as `assets/cards/enterprising_escapee_zhTW_bgs_512.png`, `assets/cards/lockbox_zhTW_bgs_512.png`, `assets/cards/hooktusk_master_marauder_zhTW_bgs_512.png`, `assets/cards/locked_up_mutineer_zhTW_bgs_512.png`, `assets/cards/silent_deliverer_zhTW_bgs_512.png`, `assets/cards/cookie_captain_zhTW_bgs_512.png`, and `assets/cards/treasure_parrot_zhTW_bgs_512.png`. Give any additional verified card the same lowercase English-slug convention ending in `_zhTW_bgs_512.png`. Open every PNG and read the zhTW name and rule text directly from the card face.

- [ ] **Step 2: Record exact term evidence**

Create `terms_zhTW.md` with columns: Card ID, enUS name, official zhTW name, official zhTW rule text, image path, official image URL, and video timestamp. Include every gameplay term spoken in the Intro, not only the four initial IDs.

- [ ] **Step 3: Correct the approved Intro before synthesis**

Replace every guessed English, simplified, colloquial, or unofficial card name with the official zhTW card-face name. If the official rules contradict the draft explanation, correct `content_understanding.md` and `intro_script.txt`, then re-present the changed sentence before producing TTS.

- [ ] **Step 4: Seed subtitle cleanup context and validate terms**

Create `subtitle_context.txt` containing both streamer names, verified card terms, common spoken aliases, and concrete ASR-error-to-official-name mappings.

Run:

```bash
test -s output/lockbox_pirates_s14/terms_zhTW.md
test -s output/lockbox_pirates_s14/subtitle_context.txt
test "$(wc -c < output/lockbox_pirates_s14/subtitle_context.txt)" -le 2048
! rg -n 'T[BB]D|T[OO]DO|待[定]' output/lockbox_pirates_s14/terms_zhTW.md output/lockbox_pirates_s14/subtitle_context.txt
```

Expected: all spoken gameplay terms have official card-face evidence and the context file stays within the size limit.

### Task 7: Generate the high-impact background and dynamic Intro

- [ ] **Step 1: Write the approved background Prompt**

Write this complete Prompt to `intro_image_prompt.txt`:

```text
A cinematic high-impact fantasy game key art scene inside a dark pirate ship vault, no people and no creatures, one single molten-gold lockbox glowing intensely at the lower center as the unmistakable focal point, bright gold coins, chain links, and concentrated magical energy forming one clean closed circular loop around the lockbox to visually communicate a repeatable economy cycle, deep navy-blue and saturated teal environmental lighting against vivid molten orange-gold, dramatic volumetric beams, sharp highlights, rich depth, polished dark wood and aged metal, premium fantasy battlegrounds atmosphere, locally darker and low-detail across the entire right side for the mascot, the lower-left area for subtitles, and the top strip for title text, no cards, no text, no letters, no numbers, no logos, no interface, no extra treasure chest, no competing bright focal object, 16:9 composition.
```

- [ ] **Step 2: Generate TTS and verify the actual 45–50 second duration**

Run:

```bash
set -a
source .env
set +a
uv run video2yt-tts --text-file output/lockbox_pirates_s14/intro_script.txt -o output/lockbox_pirates_s14/intro.mp3
uv run video2yt-transcribe \
  --audio output/lockbox_pirates_s14/intro.mp3 \
  --script output/lockbox_pirates_s14/intro_script.txt \
  --max-block-chars 22 \
  -o output/lockbox_pirates_s14/intro.srt
ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 output/lockbox_pirates_s14/intro.mp3
```

Expected: the spoken duration is 45–50 seconds and the final SRT timestamp reaches the audio tail. If duration is outside the range, adjust sentence density without removing any required mechanism link, regenerate only the Intro TTS/SRT, and recheck.

- [ ] **Step 3: Generate and inspect the background**

Run:

```bash
uv run video2yt-image --backend codex \
  --prompt-file output/lockbox_pirates_s14/intro_image_prompt.txt \
  -o output/lockbox_pirates_s14/intro_bg.png \
  --save-raw output/lockbox_pirates_s14/intro_bg_raw.png
ffprobe -v error -show_entries stream=width,height -of csv=p=0 output/lockbox_pirates_s14/intro_bg.png
ffmpeg -y -i output/lockbox_pirates_s14/intro_bg.png -vf 'scale=640:-2' output/lockbox_pirates_s14/intro_bg_preview_640.png
```

Expected: fitted output is 1920×1080. At full size and 640px width, one molten-gold lockbox and one closed gold cycle dominate; there are no characters, creatures, cards, text, logos, UI, extra chests, or bright distractions in the right/top/lower-left safe zones.

- [ ] **Step 4: Build the verified card timeline and Intro**

Write one `assets/cards/*.png | 官方繁中卡名` line per card spoken in the approved SRT to `intro_cards.txt`, preserving first-mention order. Every line must correspond to a Task 4 video timestamp and a Task 6 official card image.

Run:

```bash
uv run video2yt-intro \
  --audio output/lockbox_pirates_s14/intro.mp3 \
  --bg output/lockbox_pirates_s14/intro_bg.png \
  --srt output/lockbox_pirates_s14/intro.srt \
  --cards output/lockbox_pirates_s14/intro_cards.txt \
  -o output/lockbox_pirates_s14/intro.mp4
ffprobe -v error -show_entries stream=codec_name,width,height,r_frame_rate,sample_rate -show_entries format=duration -of json output/lockbox_pirates_s14/intro.mp4
ffmpeg -v error -i output/lockbox_pirates_s14/intro.mp4 -f null -
```

Expected: 1920×1080, 30 fps, H.264/AAC; complete decode succeeds; every card appears after its spoken name and remains long enough to read its mechanism.

- [ ] **Step 5: Review checkpoint #2**

Run an independent visual review of `intro.mp4`, `intro_bg_preview_640.png`, and the final card timeline. Record the result in `WORKFLOW_NOTES.md`; because the user authorized continuous execution through upload, continue automatically when the review passes and stop only for a concrete defect that cannot be corrected within the approved design.

### Task 8: Prepare subtitles, music, and both body segments

- [ ] **Step 1: Inspect each source for existing hard subtitles**

Extract full-resolution frames at the beginning, middle, and late game of each source. If a source already contains adequate bottom hard subtitles, record `--no-subtitle` for that source; otherwise clean the raw SRT manually. Do not rerun speech2srt.

- [ ] **Step 2: Clean only dialogue text while preserving timing**

For every source that needs subtitles, convert raw speech text to Traditional Chinese and apply `subtitle_context.txt`. Preserve every SRT block number and timestamp byte-for-byte. Compare raw and cleaned block counts plus timestamp lists and fail on any mismatch. Convert the cleaned SRT to `<BVID>/speech.cleaned.ass` using `compose.srt_to_ass` at 1920×1080, font size 50, bottom position, outline 4, shadow 2, and margin 80.

- [ ] **Step 3: Generate copyright-safe music beds**

Run:

```bash
guo_video=$(rg --files temp | rg '/BV1Lw3U6xEJp\.mp4$')
vala_video=$(rg --files temp | rg '/BV1uSMU6kEzB\.mp4$')
uv run video2yt-music-mix "$guo_video"
uv run video2yt-music-mix "$vala_video"
```

Expected: each source directory contains a non-empty music bed, metadata sidecar, and attribution file; each bed duration matches its video within 0.5 seconds.

- [ ] **Step 4: Burn both body segments**

Run with `--no-subtitle` appended only for a source proven in Step 1 to have adequate hard subtitles:

```bash
guo_video=$(rg --files temp | rg '/BV1Lw3U6xEJp\.mp4$')
vala_video=$(rg --files temp | rg '/BV1uSMU6kEzB\.mp4$')
uv run video2yt-burn "$(dirname "$guo_video")" --bv BV1Lw3U6xEJp -o output/lockbox_pirates_s14/guo/BV1Lw3U6xEJp_final.mp4
uv run video2yt-burn "$(dirname "$vala_video")" --bv BV1uSMU6kEzB -o output/lockbox_pirates_s14/vala/BV1uSMU6kEzB_final.mp4
```

Expected: both outputs are 1920×1080, 30 fps, H.264/yuv420p, AAC 48 kHz; full decode succeeds; speech is clear, music is ducked, and subtitles do not collide with danmaku.

### Task 9: Append CTA, merge, and verify the final media

- [ ] **Step 1: Append CTA to the first battle only**

Run:

```bash
scripts/append_cta.sh output/lockbox_pirates_s14/guo/BV1Lw3U6xEJp_final.mp4
```

Expected: `BV1Lw3U6xEJp_final_cta.mp4` is longer than the source render by the CTA duration and fully decodes.

- [ ] **Step 2: Merge the fixed three-part sequence**

Run:

```bash
uv run video2yt-merge \
  --segment output/lockbox_pirates_s14/intro.mp4 --label '開場：S14 鎖箱海盜' \
  --segment output/lockbox_pirates_s14/guo/BV1Lw3U6xEJp_final_cta.mp4 --label '郭楓荷：極限新經濟循環' \
  --segment output/lockbox_pirates_s14/vala/BV1uSMU6kEzB_final.mp4 --label '瓦莉拉：穩定鎖箱海盜' \
  --title 'S14 鎖箱海盜完整教學' \
  -o output/lockbox_pirates_s14/lockbox_pirates_s14_final.mp4
```

Expected: final MP4 and chapter files exist; chapters are strictly ascending from 00:00 and each body chapter exceeds 10 seconds.

- [ ] **Step 3: Verify final media and representative frames**

Run:

```bash
ffprobe -v error -show_entries stream=codec_name,width,height,pix_fmt,r_frame_rate,sample_rate,channels -show_entries format=duration -of json output/lockbox_pirates_s14/lockbox_pirates_s14_final.mp4
ffmpeg -v error -i output/lockbox_pirates_s14/lockbox_pirates_s14_final.mp4 -f null -
sed -n '1,20p' output/lockbox_pirates_s14/lockbox_pirates_s14_final_chapters.txt
```

Expected: 1920×1080, 30 fps, H.264/yuv420p, AAC 48 kHz stereo, clean full decode, exactly three valid chapters, and no visual/audio break at either boundary.

### Task 10: Build the fixed-message thumbnail and metadata

- [ ] **Step 1: Render the channel-standard thumbnail**

Choose the official zhTW `積極的逃脫者` or `帶鎖箱` card that remains most legible at 640px. If one card cannot communicate the chain, use the compositor's `--card2` dual-card arrangement without covering either official card name.

For the single-card path, run:

```bash
uv run python scripts/thumbnail_polish.py \
  --bg output/lockbox_pirates_s14/intro_bg.png \
  --card assets/cards/enterprising_escapee_zhTW_bgs_512.png \
  --output output/lockbox_pirates_s14/thumbnail.png \
  --primary '鎖箱海盜' \
  --secondary '新經濟循環'
ffmpeg -y -i output/lockbox_pirates_s14/thumbnail.png -vf 'scale=640:-2' output/lockbox_pirates_s14/thumbnail_preview_640.png
ffprobe -v error -show_entries stream=width,height -of csv=p=0 output/lockbox_pirates_s14/thumbnail.png
stat -f '%z' output/lockbox_pirates_s14/thumbnail.png
```

Expected: 1280×720 and below 2,000,000 bytes; both title tiers remain instantly readable at 640px, the selected card name is unobscured, the lockbox/gold loop is obvious, and the mascot has a dark uncluttered zone.

For the dual-card path, replace the render command above with:

```bash
uv run python scripts/thumbnail_polish.py \
  --bg output/lockbox_pirates_s14/intro_bg.png \
  --card assets/cards/enterprising_escapee_zhTW_bgs_512.png \
  --card2 assets/cards/lockbox_zhTW_bgs_512.png \
  --output output/lockbox_pirates_s14/thumbnail.png \
  --primary '鎖箱海盜' \
  --secondary '新經濟循環'
```

- [ ] **Step 2: Create `youtube_metadata.json`**

Use this exact title pattern:

```text
「爐石戰記：英雄戰場」S14 鎖箱海盜新經濟循環完整教學 | 郭楓荷 × 瓦莉拉實戰 [彈幕]
```

The Traditional Chinese description must explain both economy and new-card scaling mechanisms, contain exactly one chapter block from the merge output, both Bilibili source URLs, and every generated CC BY music credit. The first hashtags must be `#英雄戰場教學 #英雄戰場 #爐石戰記`. Set `season` to 14, category 20, language and audio language to `zh-Hant`, public visibility, `made_for_kids` false, expected channel ID `UCEgIrCo0pR6DyyrXuSn3wBg`, final video path, and thumbnail path.

- [ ] **Step 3: Create the subscribe comment**

Write a short Traditional Chinese recap that distinguishes the Lockbox economy loop, auxiliary new-card resource roles, and Hooktusk's other-Pirate scaling, followed by a natural request to like, subscribe, enable notifications, and comment the next desired composition.

### Task 11: Final review, authorized upload, playlist verification, and cleanup

- [ ] **Step 1: Present the final review package**

Assemble the final MP4, 640px thumbnail preview, exact title, complete description, chapters, tags, both source URLs, all music credits, and the uploader's expected S14 playlist classification. Run independent internal verification and record it in `WORKFLOW_NOTES.md`. The user already gave explicit authorization on 2026-08-07 to proceed directly to public upload, so do not pause again when the package passes.

- [ ] **Step 2: Run uploader dry-run after final review**

Run:

```bash
uv run video2yt-upload --metadata output/lockbox_pirates_s14/youtube_metadata.json --dry-run
```

Expected: authentication succeeds and the resolved channel ID exactly matches `UCEgIrCo0pR6DyyrXuSn3wBg`; title, privacy, thumbnail, description, video path, and season classification are correct; no video is uploaded.

- [ ] **Step 3: Upload publicly under the recorded explicit authorization**

Run:

```bash
uv run video2yt-upload --metadata output/lockbox_pirates_s14/youtube_metadata.json
```

Expected: upload and processing succeed, a public YouTube watch URL is returned, and the URL is reachable.

- [ ] **Step 4: Verify S14-only playlist placement and post the comment**

Confirm the new video is present in the S14 playlist and absent from the S13 playlist. Assign the uploader's returned ID to `uploaded_video_id`, then run:

```bash
uv run python scripts/post_comment.py \
  --video-id "$uploaded_video_id" \
  --text-file output/lockbox_pirates_s14/subscribe_comment.txt \
  --expected-channel-id UCEgIrCo0pR6DyyrXuSn3wBg
```

Expected: the helper reports a new comment ID on the same video ID.

- [ ] **Step 5: Register the shipped topic and preview cleanup**

Append one concise normalized line for `S14 鎖箱海盜／新經濟循環` to `assets/topic/done_topics.txt`, including both source BVIDs if the file's current format supports them. Then run:

```bash
uv run video2yt-cleanup --project lockbox_pirates_s14
```

Expected: the dry run targets only this project's disposable caches and the workflow-defined stale project; it preserves `output/lockbox_pirates_s14/` as the current one-period buffer.

- [ ] **Step 6: Execute cleanup after target review**

Run:

```bash
uv run video2yt-cleanup --project lockbox_pirates_s14 --yes
```

Expected: only reviewed targets are removed, the current project output remains, and the public YouTube URL stays available.
