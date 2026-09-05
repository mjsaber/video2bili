# Butcher Undead Video Production Implementation Plan

> **For agentic workers:** Execute this plan task-by-task in the current session. The user explicitly authorized publication on 2026-08-01 after the thumbnail was completed, satisfying the upload gate.

**Goal:** Produce a Season 14 early-access Battlegrounds video explaining the Reborn/Butchering Undead engine from the Guo Fenghe and Kimmy source matches.

**Architecture:** Reuse the downloaded source, stems, raw ASR, and danmaku caches. Lock the verified Traditional Chinese intro first, produce a reviewable dynamic intro, then clean and burn both source matches, add the cold open and CTA, merge, generate metadata and thumbnail, and stop for thumbnail approval before upload.

**Tech Stack:** video2yt CLIs, ffmpeg/ffprobe, Volcengine BigTTS, Hearthstone zhTW card art, existing dynamic-intro and thumbnail tooling.

---

### Task 1: Lock the intro and terminology

**Files:**
- Modify: `output/butcher_undead_review/intro_script.txt`
- Reference: `output/butcher_undead_review/terms_zhTW.md`

- [x] Replace the normal-guide opening with the approved early-access structure.
- [x] Keep the user-requested colloquial hook `新賽季亡靈要崛起了？`.
- [x] Use verified terms `黑暗贈禮`, `啟動`, `不死族`, `復生`, and `屠殺` in the explanatory portion.
- [x] Verify the script is Traditional Chinese, contains no unverified preview-card names, and remains about 100–130 characters.

### Task 2: Produce the dynamic intro for review

**Files:**
- Create: `output/butcher_undead_review/intro.mp3`
- Create: `output/butcher_undead_review/intro.srt`
- Create: `output/butcher_undead_review/intro_image_prompt.txt`
- Create: `output/butcher_undead_review/intro_bg_raw.png`
- Create: `output/butcher_undead_review/intro_bg.png`
- Create: `output/butcher_undead_review/intro_cards.txt`
- Create: `output/butcher_undead_review/intro.mp4`

- [x] Generate narration from the locked script with `video2yt-tts`.
- [x] Align the script to the narration with `video2yt-transcribe`.
- [x] Generate a warm Dalaran/Undead tavern background without text or characters.
- [x] Spotlight the verified zhTW `屠殺` card art.
- [x] Compose the dynamic intro and verify 1920x1080, 30 fps, H.264/AAC, complete narration, and subtitle tail alignment.
- [x] Send `intro.mp4` to the user for review before processing the body.

### Task 3: Prepare and burn both source matches

**Files:**
- Create: `output/butcher_undead_review/subtitle_context.txt`
- Create: cleaned Traditional Chinese SRT/ASS beside each cached source
- Create: two final burned match MP4 files under `output/butcher_undead_review/`

- [x] Split and clean the already-generated raw ASR without rerunning speech2srt.
- [x] Review timestamps and Hearthstone terminology against the source frames.
- [x] Burn danmaku, cleaned subtitles, and the standard 0.12 music bed into each match.
- [x] Verify both outputs meet merge requirements.

### Task 4: Build the viewing structure

**Files:**
- Create: a short cold-open clip from the strongest verified combat payoff
- Create: first-match CTA variant

- [x] Select an 8–15 second high-stat combat payoff that does not require prior explanation.
- [x] Re-encode the cold open to the merge profile.
- [x] Append the channel CTA to the first battle segment.
- [x] Verify timestamps remain monotonic and all clips share the merge profile.

### Task 5: Merge and prepare publishing assets

**Files:**
- Create: final merged MP4
- Create: title/description/chapters draft
- Create: YouTube thumbnail

- [x] Merge cold open, intro, Guo Fenghe, and Kimmy segments with chapters.
- [x] Draft a title that identifies Season 14 early access rather than a finalized meta guide.
- [x] Draft a Traditional Chinese description with source links, music credits, and `#英雄戰場教學` in the first three hashtags.
- [x] Generate the channel-standard thumbnail with `thumbnail_polish.py`.
- [x] Verify final media, metadata, and thumbnail dimensions.
- [x] Send the thumbnail to the user and stop before upload.

### Task 6: Publish only after thumbnail approval

- [x] Upload only after the user explicitly approves the thumbnail and says to publish.
- [x] Add the video to the matching playlist.
- [x] Post the required Traditional Chinese subscribe comment.
- [x] Run `video2yt-cleanup --project butcher_undead_review` as a dry run, inspect the plan, then run with `--yes` only after successful publication.
