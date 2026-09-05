# Subscribe + comment CTA clip

`subscribe_cta.mp4` — a ~5s faceless 2-beat call-to-action (redesigned
2026-06-11 to the 4-6s industry norm after CTA best-practice research):

- **Beat A (subscribe, visual-secondary)**: the mascot (二次元 tavern-keeper
  girl) bounces while BigTTS says 「訂閱馬哥！」; the canonical click sequence
  plays — arrow clicks the red 訂閱 button → it turns grey 已訂閱 → a gold bell
  pops in with a decaying shake, synced to the clip's ONLY sound effect, a
  Mixkit bell ding (`src/bell_ding.wav`, Mixkit Free License, no attribution).
- **Beat B (comment, spoken PRIMARY ask)**: BigTTS asks
  「想看什麼陣容？留言告訴我！」 while a blue speech bubble pops beside the
  mascot. This is a historical creative choice; measure its conversion rather than assuming it performs best for this channel.

Output spec matches burn (1920x1080 30fps h264 yuv420p + AAC 48k) so it
satisfies merge strict mode after the append.

## How it's used (per video)

Since the approved 2026-09-05 growth review, the default is a contextual text overlay after the first useful decision, using `video2yt-cta` (see `docs/growth-workflow.md`). It keeps gameplay and audio running. Select and record the timestamp per video, and inspect nearby audience retention.

This full-screen clip is an optional experiment. The helper below appends it after a chosen segment; it is no longer mandatory after the first battle. Short media segments are supported by merge; use independent editorial chapters instead of assigning a short CTA its own chapter.

```bash
scripts/append_cta.sh output/<project>/<battle1>_final.mp4   # -> <battle1>_final_cta.mp4
# then use <battle1>_final_cta.mp4 as that --segment in video2yt-merge
```

`append_cta.sh` re-encodes (filter-level concat, ~5 min for a 24-min segment).
Stream copy was abandoned 2026-06-11: it once emitted a backward-pts join that
made merge's concat silently drop the segment tail + the CTA.

When using the appended variant, define chapters on the final timeline. YouTube chapter limits apply to chapter spans, not input clip duration.

**Comment tie-in**: if explicitly authorized to post, open the post-upload comment with the same question
(「想看什麼陣容？留言告訴我！」) so latecomers see the ask too.

## Regenerating / editing (`src/`)

1. `src/make_assets.sh` — background, red/grey buttons, arrow, bell, comment
   bubble (ImageMagick).
2. `src/gen_char.py` — mascot via codex `image_gen` (transparent PNG). Edit the
   prompt to restyle the character.
3. Voices (project TTS voice `zh_female_vv_uranus_bigtts`):
   ```bash
   cd src
   uv run video2yt-tts --text "訂閱馬哥！" -o voice_cta.mp3
   uv run video2yt-tts --text "想看什麼陣容？留言告訴我！" --speech-rate 15 -o voice_comment.mp3
   # --speech-rate 15~30 for more energy; --speaker <id> for a different voice
   ```
4. `src/build_tts.sh` — measures the voices, auto-fits the 2-beat timeline,
   writes `slogan_tts.ass`, composites, and copies the result to
   `../subscribe_cta.mp4` (the canonical file).

Known build gotcha: do NOT add `apad` before the final `atrim` in the audio
filter chain — with this 4-input amix graph it hangs ffmpeg in an infinite
EOF loop (the lavfi pad input already spans the full duration, so apad is
redundant anyway).

`src/build.sh` builds the legacy no-voice (chime-only) variant if ever needed;
`src/voice_hook.mp3` (the old 3.5s hook line) is kept but no longer used.
