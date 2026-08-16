# S14 新賽季海獸流單素材 Evidence and Intro Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Current execution boundary — 2026-08-16:** The user approved a single-source “new invention” experiment using only BV1jnuZ67Epi. Execute inline through source understanding, official terminology, title/thumbnail copy, and the completed Intro script, then stop for review. Do not synthesize TTS, generate imagery, burn body video, upload, comment, or clean caches before that review.

**Goal:** 把郭楓荷的一段 S14 實戰整理成一支以「新賽季海獸流」為主題的單素材嘗鮮影片，先交付可核驗的海盜／野獸分工、官方繁中術語、包裝文案與 Intro。

**Architecture:** 只下載並處理 BV1jnuZ67Epi，沿用 Stage 1–3 cache 且 raw ASR 只執行一次。之後聯合讀取原始語音、彈幕、全片概覽、關鍵幀與最新 HearthstoneJSON zhTW 資料，把「寶箱經濟／海盜永久成長／野獸亡語戰鬥」拆成可追溯證據，再撰寫 45–50 秒 Intro；排除的瓦莉拉龍蝦局不得進入任何製作產物。

**Tech Stack:** `video2yt-prefetch`, `video2yt-stems`, `video2yt-subtitle --skip-cleanup`, ffmpeg/ffprobe, HearthstoneJSON latest zhTW/enUS data and BGS art, Markdown evidence records.

---

## File map

- Create: `output/seabeast_s14/WORKFLOW_NOTES.md` — 唯一來源、排除來源、單素材規則、審核邊界與進度。
- Create: `output/seabeast_s14/content_understanding.md` — 帶時間戳的完整對局與海盜／野獸關聯分析。
- Create: `output/seabeast_s14/terms_zhTW.md` — 官方 ID、繁中名稱、現行規則、卡面 URL 與原片時間點。
- Create: `output/seabeast_s14/subtitle_context.txt` — 後續字幕清理所需別名與官方術語，最多 2 KB。
- Create: `output/seabeast_s14/intro_script.txt` — 等待使用者審核的繁中 Intro。
- Create: `output/seabeast_s14/evidence/guo/` — 全片概覽與必要的全解析度關鍵幀。
- Modify: `docs/superpowers/specs/2026-04-18-video-production-workflow.md` — 記錄人工確認的新發明型內容可採單素材，不修改 `video2yt-topic` 配對算法。
- Do not create yet: Intro TTS/SRT/background/MP4, body renders, thumbnail image, metadata, upload artifacts, or cleanup records.
- Do not modify: `src/video2yt/topic.py`, 瓦莉拉來源 cache、無關髒工作樹檔案、已發布專案輸出或 `assets/topic/done_topics.txt`。

### Task 1: Preflight and initialize the review-bounded project

- [ ] **Step 1: Verify the approved and excluded source records**

Run:

```bash
rg -n 'BV1jnuZ67Epi|BV1sYgA6CEms|新賽季海獸流|兩萬血海盜|亡語野獸' \
  docs/superpowers/specs/2026-08-16-seabeast-s14-production-design.md \
  output/topics/2026-08-16.md
```

Expected: the design identifies BV1jnuZ67Epi as the only source and BV1sYgA6CEms as explicitly excluded; both URLs remain visible for auditability.

- [ ] **Step 2: Verify tools, credentials, disk, and worktree without printing secrets**

Run:

```bash
command -v ffmpeg
command -v ffprobe
uv run which yt-dlp
command -v song-remover
command -v speech2srt
test -s .env
test -s ~/.modal.toml
ffmpeg -hide_banner -filters 2>/dev/null | rg ' subtitles '
df -h .
git status --short
```

Expected: all executables resolve, both protected files exist, ffmpeg exposes libass, free disk exceeds 20 GiB, and unrelated existing changes are recorded but untouched.

- [ ] **Step 3: Initialize only the single-source project**

Create `output/seabeast_s14/evidence/guo/` and `WORKFLOW_NOTES.md` with exactly these facts:

```markdown
# S14 新賽季海獸流 Workflow Notes

- Included source: https://www.bilibili.com/video/BV1jnuZ67Epi
- Excluded source: https://www.bilibili.com/video/BV1sYgA6CEms
- Format: manually approved single-source “new invention” experiment
- Packaging: 新賽季海獸流／兩萬血海盜／亡語野獸
- Public upload authorization: absent for this project

- [ ] Source downloaded and fully decoded
- [ ] Raw ASR completed or valid canonical cache reused
- [ ] Timestamped mechanism evidence completed
- [ ] Official zhTW terminology completed
- [ ] Intro and packaging draft completed
- [ ] User approved Intro and packaging
```

Expected: no file or directory for the excluded BVID is created or downloaded.

### Task 2: Record the single-source rule without changing topic discovery

- [ ] **Step 1: Add the approved exception to the workflow spec**

Modify `docs/superpowers/specs/2026-04-18-video-production-workflow.md` so Step 0 states:

```markdown
Paired topics remain the default. A manually reviewed “new invention” topic may use one source when that single game contains a complete setup-to-payoff arc and a second candidate does not share the same mechanism. This exception is a production decision, not an automatic title-keyword rule: do not change `video2yt-topic` to surface singletons merely because a title says “新发明”.
```

Also change source-count-specific wording in Steps 1–2 from unconditional “both/two sources” to “all approved source(s)”, while preserving the existing evidence, term-check, review, and upload gates.

- [ ] **Step 2: Verify the documentation change is narrow**

Run:

```bash
rg -n 'new invention|single|approved source|新發明|單素材' \
  docs/superpowers/specs/2026-04-18-video-production-workflow.md
git diff --check -- docs/superpowers/specs/2026-04-18-video-production-workflow.md
git diff --stat -- docs/superpowers/specs/2026-04-18-video-production-workflow.md
```

Expected: the rule is discoverable, there are no whitespace errors, and no source code or topic algorithm changes appear.

- [ ] **Step 3: Commit only the workflow-rule change**

Run:

```bash
git add docs/superpowers/specs/2026-04-18-video-production-workflow.md
git commit -m "docs: allow reviewed single-source invention videos"
```

Expected: one tracked documentation file is committed; unrelated dirty files remain uncommitted.

### Task 3: Download and validate the only source

- [ ] **Step 1: Prefetch BV1jnuZ67Epi only**

Run:

```bash
uv run video2yt-prefetch \
  'https://www.bilibili.com/video/BV1jnuZ67Epi' \
  -o temp/
```

Expected: exit 0; BV1jnuZ67Epi yields one MP4, one XML danmaku file, and one converted ASS file under `temp/`; no BV1sYgA6CEms path exists.

- [ ] **Step 2: Resolve exact paths and assert non-empty artifacts**

Run:

```bash
test "$(rg --files temp | rg -c '/BV1jnuZ67Epi\.mp4$')" -eq 1
test "$(rg --files temp | rg -c '/BV1jnuZ67Epi\.danmaku\.xml$')" -eq 1
test "$(rg --files temp | rg -c '/BV1jnuZ67Epi\.danmaku\.ass$')" -eq 1
! rg --files temp | rg -q '/BV1sYgA6CEms'
rg --files temp | rg '/BV1jnuZ67Epi\.(mp4|danmaku\.(xml|ass))$'
```

Expected: exactly three non-empty artifact paths resolve for the approved BVID and zero for the excluded BVID.

- [ ] **Step 3: Verify streams and complete decode**

Run:

```bash
video_path=$(rg --files temp | rg '/BV1jnuZ67Epi\.mp4$')
ffprobe -v error \
  -show_entries stream=codec_type,codec_name,width,height,r_frame_rate,sample_rate \
  -show_entries format=duration -of json "$video_path"
ffmpeg -v error -xerror -i "$video_path" -map 0:v:0 -f null -
ffmpeg -v error -xerror -i "$video_path" -map 0:a:0 -f null -
```

Expected: 1920×1080 video with audio, duration near 24:12, and both full decodes exit 0 without errors.

### Task 4: Generate stems and one raw ASR

- [ ] **Step 1: Separate stems for the exact MP4**

Run:

```bash
video_path=$(rg --files temp | rg '/BV1jnuZ67Epi\.mp4$')
uv run video2yt-stems "$video_path"
```

Expected: the BVID directory contains `speech.wav`, `music.wav`, `sfx.wav`, `no_music.wav`, and `.stems_source_meta.json`; stem durations match the source within one second.

- [ ] **Step 2: Reuse valid canonical ASR or run it exactly once**

Inspect `speech.wav.speech2srt.{srt,json}`. If both exist and the JSON source hash matches the current `speech.wav`, reuse them. Otherwise run:

```bash
set -a
source .env
set +a
uv run video2yt-subtitle "$video_path" --skip-cleanup
```

Expected: no `--force-asr`; one non-empty canonical SRT/JSON pair exists, `cleanup_enabled=false`, and transcript coverage reaches the late game.

### Task 5: Build source-grounded sea-beast evidence

- [ ] **Step 1: Read all raw text evidence**

Read the canonical raw SRT and danmaku XML/ASS from beginning to end. Search both scripts and likely ASR aliases for 逃兵、寶箱、鉤牙、發現、金色、腐鰓、潛力、戈德林、陸行鳥、瑞文、海盜、野獸、亡語、兩萬、+78/+78 and every visible late-game value.

Expected: every retained assertion records BVID, timestamp, evidence type (`speech`, `danmaku`, or `visible UI`), and confidence; danmaku alone never proves a rule or number.

- [ ] **Step 2: Create the complete overview and targeted frames**

Run:

```bash
mkdir -p output/seabeast_s14/evidence/guo
video_path=$(rg --files temp | rg '/BV1jnuZ67Epi\.mp4$')
ffmpeg -y -i "$video_path" \
  -vf 'fps=1/40,scale=480:-2,tile=6x7' -frames:v 1 \
  output/seabeast_s14/evidence/guo/contact.png
```

First extract a fixed full-resolution review sequence covering minutes 9–24:

```bash
for second in 540 600 660 720 780 840 900 960 1020 1080 1140 1200 1260 1320 1380 1440; do
  ffmpeg -y -ss "$second" -i "$video_path" -frames:v 1 \
    "output/seabeast_s14/evidence/guo/review-${second}.png"
done
```

Inspect those frames together with the overview, then use the same command with exact numeric seconds found in the source to capture every escapee/lockbox rule, golden-minion play, Hooktusk rule update, discover trigger, beast pivot, deathrattle trigger, final board, and result. Name each final frame `<numeric-second>-<observed-event>.png`, using only events actually visible at that second.

Expected: the overview covers the complete game and the final targeted images make every Intro-eligible rule, link, and result readable.

- [ ] **Step 3: Resolve current official zhTW records**

Refresh HearthstoneJSON latest zhTW/enUS data, match actual on-screen art to exact IDs, and verify the official 512 px BGS image for every resolved ID under the `art.hearthstonejson.com/v1/bgs/latest/zhTW/512x/` endpoint.

At minimum resolve the official current records corresponding to the source UI names `上进的逃兵`, `上锁宝箱`, `掠夺大师钩牙`, `腐鳃学徒`, `无限潜力`, `巨狼戈德林`, `透亡陆行鸟`, and the actual deathrattle multiplier. Do not infer a Traditional name from Simplified text or a filename alias.

Expected: every named Intro card has an actual source timestamp, exact ID, official zhTW name/current rule, and readable official art.

- [ ] **Step 4: Write the fixed evidence documents**

Create `content_understanding.md` with these sections:

```markdown
# S14 新賽季海獸流單素材內容理解
## 唯一來源：BV1jnuZ67Epi
## 對局時間線
## 寶箱經濟與金色隨從累積
## 海盜永久成長鏈
## 野獸亡語戰鬥鏈
## 海盜與野獸的實際關聯
## 可見終局數值與勝負
## Intro 可展示卡牌
## 排除的第二素材與錯誤摘要
## 排除的未證實說法
```

Create `terms_zhTW.md` with card ID, enUS name, official zhTW name, exact current rule, local/stable art filename, official URL, and source timestamp. Create `subtitle_context.txt` with 郭楓荷, the approved official terms, and concrete Simplified/ASR alias mappings.

- [ ] **Step 5: Run evidence acceptance checks**

Run:

```bash
test -s output/seabeast_s14/content_understanding.md
test -s output/seabeast_s14/terms_zhTW.md
test -s output/seabeast_s14/subtitle_context.txt
test "$(wc -c < output/seabeast_s14/subtitle_context.txt)" -le 2048
rg -n 'BV1jnuZ67Epi|海盜與野獸的實際關聯|排除的第二素材|排除的未證實說法' \
  output/seabeast_s14/content_understanding.md
! rg -n 'T[BB]D|T[OO]DO|待定|龍蝦亡語藏入魚人|穩定T0|百分百' \
  output/seabeast_s14/content_understanding.md \
  output/seabeast_s14/terms_zhTW.md
```

Expected: all required sections exist, subtitle context is within 2 KB, the incorrect report summary is rejected, and no placeholder or unsupported strength claim remains.

### Task 6: Draft packaging and Intro, then stop for review

- [ ] **Step 1: Lock the review copy in `WORKFLOW_NOTES.md`**

Record these approved directions, subject only to evidence-based number correction:

```text
Title: 新賽季海獸流！兩萬血海盜站場，野獸亡語瘋狂觸發
Thumbnail top: 新賽季
Thumbnail main: 海獸流！
Thumbnail left: 兩萬血海盜
Thumbnail right: 亡語野獸
```

Expected: both the title and thumbnail name pirates and beasts and make their two roles visually distinct.

- [ ] **Step 2: Write `intro_script.txt` from verified evidence only**

Requirements:

- Start exactly with `你敢相信？`.
- Use official Traditional Chinese Battlegrounds terminology.
- Target 45–50 seconds, initially about 220–245 Chinese characters.
- Say `新賽季海獸流` and explain the real relationship: pirates convert treasure/discover resources into permanent stats, while beasts add the deathrattle combat layer.
- Show the verified result before explaining the setup; mention two-wan health and +78/+78 only if the targeted frames prove those exact values and ownership.
- Keep the single-game framing explicit through `新發明`, `花活`, or `胡牌上限`; do not call it stable T0, a universal recipe, or guaranteed victory.
- Use objective, direct, highly assertive wording; avoid anthropomorphism and loose metaphors.
- End with a try-it-when-the-pieces-appear CTA, not a promise that viewers can force the comp every game.

- [ ] **Step 3: Run textual acceptance checks**

Run:

```bash
test -s output/seabeast_s14/intro_script.txt
python -c "from pathlib import Path; s=Path('output/seabeast_s14/intro_script.txt').read_text().strip(); assert s.startswith('你敢相信？'); assert 210 <= len(s) <= 255; print(len(s))"
rg -n '新賽季海獸流|海盜|野獸|亡語' output/seabeast_s14/intro_script.txt
! rg -n '酒館|畸變|牌組|套牌|構築|穩定T0|百分百|必定吃雞|T[BB]D|T[OO]DO|待定' \
  output/seabeast_s14/intro_script.txt
```

Expected: opening, length, complete sea-beast relationship, official terminology, and forbidden-claim checks pass.

- [ ] **Step 4: Present the review package and stop**

Mark source decode, raw ASR, evidence, official terms, packaging draft, and Intro draft complete in `WORKFLOW_NOTES.md`, leaving user approval unchecked. Present:

1. the only included source URL and the excluded source URL;
2. the timestamped pirate growth chain;
3. the timestamped beast deathrattle chain;
4. the verified connection between the two;
5. every numerical claim used;
6. the exact title and four thumbnail text lines;
7. the complete Intro script and predicted duration.

Stop here. Do not generate TTS, imagery, Intro video, body render, metadata, comments, cleanup, or upload until the user approves or revises the package.
