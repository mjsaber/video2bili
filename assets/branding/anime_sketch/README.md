# Anime sketch assets

- `tavern_bg.png`: generated ivory-paper tavern background; scene and art
  direction are recorded in `tavern_bg.prompt.txt`.
- `mascot_reference.png`: original generated sketch reference, RGB with a baked
  checkerboard. Do not use this file as an overlay.
- `mascot_alpha.png`: reviewed grayscale alpha mask at 1024×1536.
- `mascot.png`: final RGBA sprite, retaining the original reference RGB pixels.

## Extraction record — 2026-09-05

Built-in ImageGen was asked to remove only the baked checkerboard, including
enclosed gaps between hair curls, and preserve the whole character, pose,
graphite details, pale-gold costume and opaque skin/apron on actual alpha.
It returned another RGB image, so that attempt was not used as the final asset.
The user then explicitly authorized local Python background extraction.

The mask was derived from the original reference using neutral bright pixels
(RGB spread ≤10, minimum channel ≥200). Connected background regions seeded at
`(0,0)`, `(224,609)`, `(116,541)`, `(816,651)`, `(949,596)` were removed. The largest
remaining connected component retains the complete mascot, including opaque
eye highlights and light clothing. A 0.45px Gaussian blur antialiases the mask.
The mask is saved so reconstruction requires only Pillow, not segmentation
libraries or another generation call.

Recreate a separate copy from the repository root:

```bash
uv run python - <<'PY'
from pathlib import Path
from PIL import Image
assets = Path('assets/branding/anime_sketch')
sprite = Image.open(assets / 'mascot_reference.png').convert('RGBA')
sprite.putalpha(Image.open(assets / 'mascot_alpha.png').convert('L'))
output = Path('output/mascot_recreated.png')
output.parent.mkdir(parents=True, exist_ok=True)
sprite.save(output)
PY
```

Alpha extrema are `(0,255)`; about 58.6% of pixels are fully transparent.
Dark, paper-white and green composites were inspected, as were the final cover,
320×180 mobile preview, and a 3-second 1920×1080/30fps intro. Preview artifacts
are under `output/repository_closeout_20260905/`; they are not new publications.
