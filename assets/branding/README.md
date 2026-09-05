# Channel branding

`channel_avatar.png` (1024×1024) — the YouTube channel avatar: a head-and-shoulders
bust of the **女老板** (boss-lady) mascot, kept visually consistent with the
subscribe-CTA mascot (`../cta/subscribe_cta.mp4`). YouTube applies its own circular
crop; the face/hat are centred to survive it. `channel_avatar_800.png` is YouTube's
recommended 800×800 size (use either; both are < 4 MB).

## Regenerate

```bash
uv run python assets/cta/src/gen_avatar.py output/avatar/cand.png \
  "Playful cheerful wink with one eye, head tilted slightly, holding one glowing gold coin up near her cheek."
```

That clause is the chosen "金币版" variant (wink + gold coin + witch hat). Drop the
clause for a plain straight-on smile. Base character design lives in
`assets/cta/src/gen_avatar.py`.

## Set it live

The YouTube **avatar** can't be changed via the Data API (that only covers banners) —
it's a brand-account setting. Upload `channel_avatar.png` in YouTube Studio →
Customization → Branding → Picture, or in Google Account → brand-account photo.

## Cover and intro style (2026-09-05)

`anime_sketch/tavern_bg_pastel.png` is the current colored-pencil background reference: mint, powder blue, peach and apricot on cream paper. The earlier mostly graphite `tavern_bg.png` is preserved for history.
`anime_sketch/mascot.png` is the completed RGBA overlay, selected automatically for sketch covers/intros. User-authorized local extraction removed the baked checkerboard from `mascot_reference.png`; the original reference and reusable `mascot_alpha.png` are preserved. See [asset provenance and reproduction](anime_sketch/README.md). The original transparent mascot remains the fallback for missing or opaque sketch assets.
The new art direction is Japanese anime pencil sketch; official card images stay original.
These files do not replace the avatar or previously rendered CTA clips.
See [visual style guide](../../docs/visual-style.md) for generation and composition.
