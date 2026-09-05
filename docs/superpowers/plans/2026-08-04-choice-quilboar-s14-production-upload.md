# 抉擇野豬 S14 Production and Upload Plan

> **Execution note:** Intro review checkpoint #2 was approved. The user explicitly authorized continuing through automatic public upload.

**Goal:** Finish the two approved Battlegrounds source videos as one upload emphasizing the new-season Quilboar update, publish it publicly, post the subscribe/comment prompt, and run the project cleanup workflow.

**Project:** `output/choice_quilboar_s14/`

**Sources:**
- 郭楓荷 — `BV1HYGw6kESm`
- Kimmy — `BV17NGP6zERB`

---

### Task 1: Lock production decisions

- Mark intro checkpoint #2 approved in `WORKFLOW_NOTES.md`.
- Inspect one representative frame from each source independently.
- If the source already carries bottom hard subtitles, skip the cleaned subtitle overlay for that source and burn with `--no-subtitle`.
- Keep the new-version cards already used by the intro; use `巨力囚犯` as the thumbnail card to visually anchor the update.

### Task 2: Build music beds and burn both battles

Run:

```bash
uv run video2yt-music-mix "temp/炉石郭枫：抉择野猪强势回归，野猪要王朝了——酒馆战棋新版本！/BV1HYGw6kESm.mp4"
uv run video2yt-music-mix "temp/炉石Ki：【单刷对面一整车】摩托猪抉择流 456本流畅战力 预定版本答案/BV17NGP6zERB.mp4"
uv run video2yt-burn "temp/炉石郭枫：抉择野猪强势回归，野猪要王朝了——酒馆战棋新版本！/" --bv BV1HYGw6kESm --no-subtitle -o "output/choice_quilboar_s14/guo/BV1HYGw6kESm_final.mp4"
uv run video2yt-burn "temp/炉石Ki：【单刷对面一整车】摩托猪抉择流 456本流畅战力 预定版本答案/" --bv BV17NGP6zERB --no-subtitle -o "output/choice_quilboar_s14/kim/BV17NGP6zERB_final.mp4"
```

Verify both are 1920×1080, 30 fps, H.264/AAC 48 kHz; decode fully without errors and visually inspect beginning/middle/end frames.

### Task 3: Append CTA and merge

Run:

```bash
scripts/append_cta.sh output/choice_quilboar_s14/guo/BV1HYGw6kESm_final.mp4
uv run video2yt-merge \
  --segment output/choice_quilboar_s14/intro.mp4 --label "開場：新賽季抉擇野豬" \
  --segment output/choice_quilboar_s14/guo/BV1HYGw6kESm_final_cta.mp4 --label "郭楓荷：抉擇野豬王朝" \
  --segment output/choice_quilboar_s14/kim/BV17NGP6zERB_final.mp4 --label "Kimmy：摩托豬一穿全車" \
  --title "新賽季抉擇野豬完整教學" \
  -o output/choice_quilboar_s14/choice_quilboar_s14_final.mp4
```

Verify chapter boundaries, CTA placement between battles, full decode, audio loudness, and representative frames.

### Task 4: Build and inspect the thumbnail

Use the approved intro background, the official zhTW `巨力囚犯` card, and the two-tier text:

- Primary: `抉擇野豬`
- Secondary: `一豬穿車`

Render `output/choice_quilboar_s14/thumbnail.png`, verify 1280×720 and inspect it at full size and reduced preview size.

### Task 5: Build metadata and upload

Create metadata with:

- Title: `「爐石戰記：英雄戰場」新賽季抉擇野豬完整教學 | 郭楓荷 × Kimmy 實戰 [彈幕]`
- Traditional Chinese description, exactly one chapter block, both Bilibili source links, and all generated music credits.
- First hashtags: `#英雄戰場教學 #英雄戰場 #爐石戰記`
- Category 20, language zh-Hant, public visibility.
- Expected channel ID: `UCEgIrCo0pR6DyyrXuSn3wBg`.

Run uploader dry-run first, review the resolved channel/title/description/thumbnail, then run the real upload. Post the required subscribe/comment prompt after the upload.

### Task 6: Verify and clean up

- Confirm the returned public watch URL is reachable and the video is public.
- Confirm the comment call succeeded.
- Run `video2yt-cleanup --project choice_quilboar_s14` as a dry-run, inspect targets, then rerun with `--yes`.
- Preserve the current project output as the one-period buffer and report the public URL plus cleanup result.
