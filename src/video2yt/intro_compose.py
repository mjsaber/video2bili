"""Dynamic intro composer (Option A: single big card spotlight).

Builds a 1920x1080 intro in ONE ffmpeg pass: a dimmed looped background, the
女老板 mascot animated as the on-screen narrator (overlay + sway/bounce), the
currently-introduced card shown large top-center and swapped in time with the
narration, a bottom-left burned subtitle, and a top title band.

The design + codex review that hardened it live in
``output/intro_redesign/intro_dynamic_design.md``. Key correctness points baked
in here (each maps to a codex finding):

  - absolute .ttc fontfile, never a basename (else CJK silently -> Verdana)
  - dynamic title/card-name text via ``textfile=`` + ``expansion=none`` (no raw
    user text in the filtergraph)
  - ``-framerate 30`` before every ``-loop 1`` image input
  - half-open card gates ``enable='gte(t,Sk)*lt(t,Ek)'`` quantized to 1/30 s
  - first card has NO fade (visible from t=0); cards 2..N fade in
  - mascot ``rotate`` bounded with ``rotw(MAX_ANGLE)/roth(MAX_ANGLE)`` so the
    sway never clips
  - subtitle capped to 2 lines, MarginR raised to clear the mascot
"""
from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from video2yt import compose, validate

# ---- layout constants (1920x1080) -----------------------------------------
CANVAS_W = 1920
CANVAS_H = 1080
FPS = 30

CARD_H = 640                 # spotlight card height
CARD_X = 538                 # spotlight card left edge (center-left bias)
CARD_Y = 150                 # spotlight card top edge
CARD_FADE = 0.25             # alpha fade-in for cards 2..N

MASCOT_H = 820               # mascot scaled height
MASCOT_MAX_ANGLE = 0.045     # rad; rotate sway amplitude (also the rotw/roth bound)

TITLE_FONT_SIZE = 54         # only used when an optional title is supplied

# Subtitle: bold W6 weight + larger size + outline & drop-shadow read far better
# over a busy frame than the thin default. Bottom-left, clears the mascot.
# (font family comes from inputs.font_face; bold selects the W6 cut.)
SUB_FONT_SIZE = 54
SUB_BOLD = True
SUB_OUTLINE = 3
SUB_SHADOW = 2
SUB_MARGIN_L = 80
SUB_MARGIN_R = 680           # clears the mascot's left edge (~1319)
SUB_MARGIN_V = 120           # raised ~one line off the bottom edge
SUB_MAX_LINES = 2

_FONT_CANDIDATES = (
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
)


def resolve_font() -> str:
    """First existing absolute CJK .ttc path (codex BLOCKER #1)."""
    for path in _FONT_CANDIDATES:
        if Path(path).exists():
            return path
    raise RuntimeError(
        "no CJK font found; expected one of: " + ", ".join(_FONT_CANDIDATES)
    )


# ---- SRT parsing -----------------------------------------------------------
_SRT_BLOCK_TIME = re.compile(
    r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)"
)


def _to_seconds(h: str, m: str, s: str, ms: str) -> float:
    ms = ms.ljust(3, "0")[:3]
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0


@dataclass(frozen=True)
class SrtBlock:
    start: float
    end: float
    text: str


def parse_srt_blocks(srt_text: str) -> list[SrtBlock]:
    """Parse SRT into (start, end, text) blocks (text is one joined string)."""
    blocks: list[SrtBlock] = []
    for raw in re.split(r"\n\s*\n", srt_text.strip()):
        lines = raw.strip().splitlines()
        if len(lines) < 2:
            continue
        idx = 1 if lines[0].strip().isdigit() else 0
        if idx >= len(lines):
            continue
        m = _SRT_BLOCK_TIME.search(lines[idx])
        if not m:
            continue
        start = _to_seconds(*m.group(1, 2, 3, 4))
        end = _to_seconds(*m.group(5, 6, 7, 8))
        text = " ".join(lines[idx + 1:]).strip()
        if text:
            blocks.append(SrtBlock(start=start, end=end, text=text))
    return blocks


# Punctuation / framing chars stripped before substring matching so the card
# name matches regardless of quotes, dashes, spaces (codex MAJOR #10).
_NORMALIZE_STRIP = re.compile(r"[\s『』「」“”\"'，。、—…·‧・,.!?！？:：;；()（）\-]+")


def normalize_text(s: str) -> str:
    return _NORMALIZE_STRIP.sub("", s)


# ---- card timeline ---------------------------------------------------------
@dataclass
class CardSpec:
    png: str          # basename or path as written in the cards file
    name: str         # 中文 name to match in the SRT
    start: float | None = None  # explicit display start override
    end: float | None = None    # explicit display end override


@dataclass(frozen=True)
class ResolvedCard:
    png: Path
    name: str
    display_start: float
    display_end: float
    fade: bool


def parse_cards_file(path: Path) -> list[CardSpec]:
    """Parse ``intro_cards.txt``.

    One card per line, in display order::

        <png> | <中文卡名> [| <start> <end>]

    Blank lines and ``#`` comments are skipped. Explicit ``start end`` (seconds)
    override the SRT-derived timing for that card.
    """
    specs: list[CardSpec] = []
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 2 or not parts[0] or not parts[1]:
            raise ValueError(
                f"{path}:{lineno}: expected '<png> | <name> [| <start> <end>]', "
                f"got {raw!r}"
            )
        png, name = parts[0], parts[1]
        start = end = None
        if len(parts) >= 3 and parts[2]:
            nums = parts[2].split()
            if len(nums) != 2:
                raise ValueError(
                    f"{path}:{lineno}: explicit time must be '<start> <end>', "
                    f"got {parts[2]!r}"
                )
            try:
                start, end = float(nums[0]), float(nums[1])
            except ValueError as e:
                raise ValueError(f"{path}:{lineno}: bad time {parts[2]!r}") from e
        specs.append(CardSpec(png=png, name=name, start=start, end=end))
    if not specs:
        raise ValueError(f"{path}: no card entries found")
    return specs


def _quantize(t: float) -> float:
    """Snap to the nearest frame (1/30 s) so gate seams are frame-exact."""
    return round(t * FPS) / FPS


def resolve_cards(
    specs: list[CardSpec],
    blocks: list[SrtBlock],
    duration: float,
    cards_dir: Path,
) -> list[ResolvedCard]:
    """Resolve each card's display window from the SRT + explicit overrides.

    Logic (codex MAJOR #4/#5/#9/#10):
      - forward cursor: each name is searched only in blocks at/after the
        previous card's matched block, so a card mentioned twice (teaser then
        real) does not steal a later card's slot.
      - explicit ``start end`` on a spec overrides the SRT match.
      - first card's display_start is forced to 0.0 (lead-in) so the screen is
        never empty at the open; that card gets NO fade.
      - display_end[i] = display_start[i+1]; the last card ends at ``duration``.
      - validation: 0 <= start < end <= duration, strictly increasing starts.
        Anything else raises ValueError (no silent guesses).
    """
    norm_blocks = [(b, normalize_text(b.text)) for b in blocks]
    match_starts: list[float] = []
    cursor = 0
    for spec in specs:
        if spec.start is not None:
            match_starts.append(spec.start)
            continue
        target = normalize_text(spec.name)
        found = None
        for i in range(cursor, len(norm_blocks)):
            if target in norm_blocks[i][1]:
                found = i
                break
        if found is None:
            raise ValueError(
                f"card {spec.name!r} ({spec.png}) not found in the SRT at or "
                f"after block #{cursor + 1}. Fix the name or add an explicit "
                f"'| <start> <end>' to its line in the cards file."
            )
        match_starts.append(norm_blocks[found][0].start)
        cursor = found + 1

    n = len(specs)
    resolved: list[ResolvedCard] = []
    for i, spec in enumerate(specs):
        start = 0.0 if (i == 0 and spec.start is None) else match_starts[i]
        is_final_fallback = spec.end is None and i + 1 == n
        if spec.end is not None:
            end = spec.end
        elif i + 1 < n:
            end = match_starts[i + 1]
        else:
            end = duration
        # Quantize seams to frame boundaries, but the last card runs to the
        # exact audio duration (quantizing it could overshoot past the end).
        start = _quantize(start)
        if not is_final_fallback:
            end = _quantize(end)

        if not (0.0 <= start < end <= duration + 1e-6):
            raise ValueError(
                f"card {spec.name!r}: window [{start:.3f}, {end:.3f}] invalid "
                f"(need 0 <= start < end <= {duration:.3f})"
            )
        png_path = Path(spec.png)
        if not png_path.is_absolute():
            png_path = cards_dir / spec.png
        if not png_path.exists():
            raise FileNotFoundError(f"card image not found: {png_path}")
        resolved.append(
            ResolvedCard(
                png=png_path,
                name=spec.name,
                display_start=start,
                display_end=end,
                fade=not (i == 0 and start == 0.0),
            )
        )

    for a, b in zip(resolved, resolved[1:]):
        if not b.display_start > a.display_start:
            raise ValueError(
                f"card display starts not strictly increasing: "
                f"{a.name!r}@{a.display_start:.3f} then "
                f"{b.name!r}@{b.display_start:.3f}. Add explicit times."
            )
    return resolved


# ---- ffmpeg graph ----------------------------------------------------------
@dataclass
class IntroInputs:
    audio: Path
    bg: Path
    srt: Path
    cards_file: Path
    mascot: Path
    cards_dir: Path
    title: str = ""              # optional top-band title; "" = no title text
    font_face: str = "Hiragino Sans GB"
    # Soft dark vignette + bottom gradient overlaid on the BACKGROUND so white
    # subtitles stay legible and the warm-gold mascot/cards pop, independent of
    # what image-gen produced. None disables it; a missing file is skipped.
    scrim: Path | None = Path("assets/intro/intro_scrim.png")


def _build_filter(
    cards: list[ResolvedCard],
    n_inputs_before_cards: int,
    font: str,
    scrim_idx: int | None = None,
    show_title: bool = False,
) -> str:
    """Assemble the filter_complex string.

    Input indices: [0]=bg, [1]=mascot, [2..]=cards (in order), then an optional
    scrim at ``scrim_idx``. drawtext uses ``textfile=`` (basenames, resolved
    against ffmpeg cwd) so the actual text files are written by ``render``.
    """
    parts: list[str] = []
    # background: cover-fit + slight dim
    parts.append(
        f"[0:v]scale={CANVAS_W}:{CANVAS_H}:force_original_aspect_ratio=increase,"
        f"crop={CANVAS_W}:{CANVAS_H},setsar=1,eq=brightness=-0.04[bg0]"
    )
    # mascot: sway bounded so rotate never clips
    parts.append(
        f"[1:v]scale=-2:{MASCOT_H},format=rgba,"
        f"rotate=a='{MASCOT_MAX_ANGLE}*sin(2*PI*t*0.7)':"
        f"ow=rotw({MASCOT_MAX_ANGLE}):oh=roth({MASCOT_MAX_ANGLE}):c=black@0[masc]"
    )
    # each card: scale (+ fade-in for cards 2..N)
    for k, card in enumerate(cards):
        idx = n_inputs_before_cards + k
        chain = f"[{idx}:v]scale=-2:{CARD_H},format=rgba"
        if card.fade:
            chain += f",fade=t=in:st={card.display_start:.3f}:d={CARD_FADE}:alpha=1"
        chain += f"[card{k}]"
        parts.append(chain)

    # darken the background with the scrim (vignette + bottom gradient) so the
    # subtitle/mascot/cards pop; foreground is drawn on top, so only the bg dims
    base = "bg0"
    if scrim_idx is not None:
        parts.append(f"[bg0][{scrim_idx}:v]overlay=0:0[bgs]")
        base = "bgs"

    # overlay cards onto bg (half-open gates, one visible at a time)
    cur = base
    for k, card in enumerate(cards):
        out = f"v{k}"
        gate = f"gte(t,{card.display_start:.3f})*lt(t,{card.display_end:.3f})"
        parts.append(
            f"[{cur}][card{k}]overlay=x={CARD_X}:y={CARD_Y}:"
            f"enable='{gate}'[{out}]"
        )
        cur = out

    # mascot on top
    parts.append(
        f"[{cur}][masc]overlay="
        f"x='{CANVAS_W - 20}-w-18+16*sin(2*PI*t*0.5)':"
        f"y='{CANVAS_H}-h-24-26*abs(sin(2*PI*t*0.85))'[vm]"
    )
    cur = "vm"

    # optional title band + text (card names are NOT drawn — the card art
    # already carries the name)
    if show_title:
        parts.append(
            f"[{cur}]drawbox=x=0:y=0:w={CANVAS_W}:h=96:color=black@0.55:t=fill,"
            f"drawtext=fontfile='{font}':textfile='_title.txt':expansion=none:"
            f"fontcolor=white:fontsize={TITLE_FONT_SIZE}:borderw=4:bordercolor=black:"
            f"x=(w-text_w)/2:y=26[vt]"
        )
        cur = "vt"

    # subtitle last
    parts.append(f"[{cur}]subtitles=f='_intro.sub.ass'[outv]")
    return ";".join(parts)


def render(inputs: IntroInputs, output_path: Path) -> Path:
    """Compose the dynamic intro MP4. Returns the output path."""
    for p in (inputs.audio, inputs.bg, inputs.srt, inputs.cards_file, inputs.mascot):
        if not Path(p).exists():
            raise FileNotFoundError(f"input not found: {p}")

    duration = validate.probe(inputs.audio).duration
    blocks = parse_srt_blocks(inputs.srt.read_text(encoding="utf-8"))
    if not blocks:
        raise ValueError(f"no SRT blocks parsed from {inputs.srt}")
    specs = parse_cards_file(inputs.cards_file)
    cards = resolve_cards(specs, blocks, duration, inputs.cards_dir)
    font = resolve_font()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    work_dir = output_path.parent

    # subtitle ASS (bottom-left, bold W6 + outline + shadow, 2-line cap, clears mascot)
    ass_text = compose.srt_to_ass(
        srt_text=inputs.srt.read_text(encoding="utf-8"),
        video_width=CANVAS_W,
        video_height=CANVAS_H,
        font_face=inputs.font_face,
        font_size=SUB_FONT_SIZE,
        position="bottom",
        outline_px=SUB_OUTLINE,
        shadow_px=SUB_SHADOW,
        margin_l=SUB_MARGIN_L,
        margin_r=SUB_MARGIN_R,
        margin_v=SUB_MARGIN_V,
        max_lines=SUB_MAX_LINES,
        bold=SUB_BOLD,
    )
    (work_dir / "_intro.sub.ass").write_text(ass_text, encoding="utf-8")

    # optional title text file (card names are no longer drawn)
    show_title = bool(inputs.title.strip())
    if show_title:
        (work_dir / "_title.txt").write_text(inputs.title, encoding="utf-8")

    use_scrim = inputs.scrim is not None and Path(inputs.scrim).exists()
    scrim_idx = 2 + len(cards) if use_scrim else None
    filter_complex = _build_filter(
        cards, n_inputs_before_cards=2, font=font, scrim_idx=scrim_idx,
        show_title=show_title,
    )

    cmd: list[str] = ["ffmpeg", "-y"]
    # [0] bg, [1] mascot, [2..] cards, [optional] scrim — every still gets
    # -framerate 30 -loop 1 so animation/gates run at 30 fps
    cmd += ["-framerate", str(FPS), "-loop", "1", "-t", f"{duration:.3f}",
            "-i", str(inputs.bg.resolve())]
    cmd += ["-framerate", str(FPS), "-loop", "1", "-t", f"{duration:.3f}",
            "-i", str(inputs.mascot.resolve())]
    for card in cards:
        cmd += ["-framerate", str(FPS), "-loop", "1", "-t", f"{duration:.3f}",
                "-i", str(card.png.resolve())]
    if use_scrim:
        cmd += ["-framerate", str(FPS), "-loop", "1", "-t", f"{duration:.3f}",
                "-i", str(Path(inputs.scrim).resolve())]
    audio_input_idx = 2 + len(cards) + (1 if use_scrim else 0)
    cmd += ["-i", str(inputs.audio.resolve())]

    cmd += [
        "-filter_complex", filter_complex,
        "-map", "[outv]",
        "-map", f"{audio_input_idx}:a",
        "-r", str(FPS),
        "-pix_fmt", "yuv420p",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-c:a", "aac", "-ar", "48000", "-b:a", "192k",
        "-t", f"{duration:.3f}",
        str(output_path.resolve()),
    ]

    print(
        f"[intro] {len(cards)} cards, {duration:.2f}s, "
        f"{audio_input_idx + 1} inputs -> {output_path.name}",
        file=sys.stderr,
    )
    subprocess.run(cmd, check=True, capture_output=True, text=True, cwd=work_dir)
    return output_path
