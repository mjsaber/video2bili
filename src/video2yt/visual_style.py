"""Shared art direction for generated backgrounds, covers and intros."""
from pathlib import Path

from PIL import Image, UnidentifiedImageError

DEFAULT_STYLE = "anime-sketch"
STYLES = (DEFAULT_STYLE, "warm-tavern")
SKETCH_MASCOT = Path("assets/branding/anime_sketch/mascot.png")
LEGACY_MASCOT = Path("assets/cta/src/mascot_raw.png")


def default_mascot(style: str) -> Path:
    if style not in STYLES:
        raise ValueError(f"unknown visual style: {style}")
    # Generated sprites can contain a painted checkerboard instead of alpha.
    # Never select such a candidate as the default overlay.
    if style == DEFAULT_STYLE:
        try:
            with Image.open(SKETCH_MASCOT) as image:
                alpha = image.convert("RGBA").getchannel("A")
                if alpha.getextrema() == (0, 255):
                    return SKETCH_MASCOT
        except (OSError, UnidentifiedImageError):
            pass
    return LEGACY_MASCOT


def style_prompt(scene: str, style: str = DEFAULT_STYLE) -> str:
    """Keep scene content; the selected preset takes precedence for rendering."""
    if style == "none":
        return scene
    if style not in STYLES:
        raise ValueError(f"unknown visual style: {style}")
    direction = (
        "Japanese anime pencil-sketch illustration with fresh Japanese pastel colors: "
        "expressive graphite linework, "
        "fine hand-drawn cross-hatching and restrained screentone on natural ivory "
        "sketchbook paper. Use cream ivory, mint green, powder blue, peach pink and "
        "apricot yellow in clearly visible colored-pencil areas and gentle washes "
        "across the scene. A harmonious airy slice-of-life palette with soft spring "
        "daylight; keep pencil strokes visible through the color. Color must remain "
        "recognizable at mobile-thumbnail size, never monochrome, sepia-dominated "
        "or barely tinted grayscale. Airy negative space and clear silhouettes; "
        "no neon saturation, glossy metallic glow, heavy vignette, photorealism, "
        "oil painting or 3D rendering. Draw all scene details in this style, not a "
        "photo with a sketch filter."
        if style == DEFAULT_STYLE else
        "Warm fantasy tavern illustration, amber and honey-gold palette, soft "
        "candlelight, warm mid-tones, restrained edge vignette."
    )
    return (f"Scene and composition:\n{scene}\n\n"
            f"Required art direction (takes precedence over conflicting style or "
            f"lighting wording above):\n{direction}")
