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
  mascot. Research: a specific bounded question is the highest-converting
  mid-roll ask; share asks convert worst and were dropped.

Output spec matches burn (1920x1080 30fps h264 yuv420p + AAC 48k) so it
satisfies merge strict mode after the append.

## How it's used (per video)

Append it to the **first battle segment** (the first gameplay segment, NOT the
intro) so the CTA plays mid-roll between battle 1 and battle 2, then feed the
combined clip to `video2yt-merge`. See Step 6.5 of
`docs/superpowers/specs/2026-04-18-video-production-workflow.md`.

```bash
scripts/append_cta.sh output/<project>/<battle1>_final.mp4   # -> <battle1>_final_cta.mp4
# then use <battle1>_final_cta.mp4 as that --segment in video2yt-merge
```

`append_cta.sh` re-encodes (filter-level concat, ~5 min for a 24-min segment).
Stream copy was abandoned 2026-06-11: it once emitted a backward-pts join that
made merge's concat silently drop the segment tail + the CTA.

The CTA rides *inside* battle 1's chapter, so each chapter still satisfies
YouTube's ≥10s rule and no stray chapter is created.

**Step 10 tie-in**: open the post-upload pinned comment with the same question
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
