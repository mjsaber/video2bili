# Subscribe CTA clip

`subscribe_cta.mp4` — a ~6.3s faceless subscribe call-to-action: the channel
mascot (二次元 tavern-keeper girl) bounces/sways while the project's Volcengine
BigTTS voice says the hook + "訂閱馬哥！", a red 訂閱 button fades in, and an
animated arrow points at it. Output spec matches burn (1920x1080 30fps h264
yuv420p + AAC 48k) so it concats losslessly onto a battle segment.

## How it's used (per video)

Append it to the **first battle segment** (the first gameplay segment, NOT the
intro) so the CTA plays mid-roll between battle 1 and battle 2, then feed the
combined clip to `video2yt-merge`. See Step 6.5 of
`docs/superpowers/specs/2026-04-18-video-production-workflow.md`.

```bash
scripts/append_cta.sh output/<project>/<battle1>_final.mp4   # -> <battle1>_final_cta.mp4
# then use <battle1>_final_cta.mp4 as that --segment in video2yt-merge
```

The CTA rides *inside* battle 1's chapter, so each chapter still satisfies
YouTube's ≥10s rule and no stray chapter is created.

## Regenerating / editing (`src/`)

1. `src/make_assets.sh` — background, red button, arrow (ImageMagick).
2. `src/gen_char.py` — mascot via codex `image_gen` (transparent PNG). Edit the
   prompt to restyle the character.
3. Voices (project TTS voice `zh_female_vv_uranus_bigtts`):
   ```bash
   cd src
   uv run video2yt-tts --text "想了解最新最熱流派，猛猛上分嗎？" -o voice_hook.mp3
   uv run video2yt-tts --text "訂閱馬哥！" -o voice_cta.mp3
   # --speech-rate 15~30 for more energy; --speaker <id> for a different voice
   ```
4. `src/build_tts.sh` — measures the voices, auto-fits the timeline, writes
   `slogan_tts.ass`, composites, and copies the result to
   `../subscribe_cta.mp4` (the canonical file).

`src/build.sh` builds a no-voice (chime-only) variant if ever needed.
