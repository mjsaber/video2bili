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
