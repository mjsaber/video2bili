"""Cut a vertical 1080x1920 Short from a 16:9 gameplay video in one ffmpeg pass.

Layout (evidence: assets/analytics/2026-09-13_bg_shorts_research.md — the
top English BG Shorts all use it): top panel = zoomed board crop so minions are
readable on a phone; bottom panel = the streamer's face cam crop, or the
女老板 mascot on the pastel tavern background when no face region is given.

Overlays:
  - label  (top-right, whole clip): "<comp>｜<rank>", e.g. 海盜倒轉｜這局第1名
  - claim  (below the board, first ``hook_seconds``): the one-line assertion
    the viewer sees at t=0, e.g. 第9回合 全隊破萬
  - subtitles (optional, from an SRT in the SOURCE timeline; shifted here)
  - outro (``outro_seconds``): pastel background + mascot + CTA line + link line

Text goes through ``drawtext textfile= ... expansion=none`` written into the
ffmpeg cwd (never interpolated into the filtergraph), same as cta.py.
"""
from __future__ import annotations

import math
import os
import re
import shutil
import subprocess
import tempfile
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from video2yt import validate
from video2yt.burn import _MUSIC_BED_VOLUME, _SIDECHAIN_PARAMS
from video2yt.compose import srt_to_ass
from video2yt.cuts import _format_ass_time, _parse_ass_time
from video2yt.fetch import compute_font_size
from video2yt.intro_compose import SrtBlock, parse_srt_blocks, resolve_font
from video2yt.visual_style import default_mascot

CANVAS_W, CANVAS_H = 1080, 1920
TOP_H = 896                 # board panel height
BOT_H = CANVAS_H - TOP_H    # 1024: face / mascot panel
SOURCE_W, SOURCE_H = 1920, 1080
DEFAULT_BOARD = (600, 120, 1060, 880)   # x, y, w, h of the board in a 1080p source
MAX_CLIP_SECONDS = 178.0                # YouTube Shorts cap is 3:00 incl. outro
DEFAULT_BG = Path("assets/branding/anime_sketch/tavern_bg_pastel.png")
SUB_FONT_FACE = "Hiragino Sans GB"
SUB_FONT_SIZE = 54
SUB_TOP_Y = TOP_H + 24       # subtitles sit at the top of the face/mascot panel (clear of the face);
                             # blocks are pushed past the hook window so they never overlap the claim
CLAIM_Y = TOP_H + 32
CONTEXT_Y = TOP_H + 250      # 語境行 (turn / HP / board state), hook window only
PROMISE_Y = TOP_H + 316      # 預期行 (what the viewer will see), hook window only
MAX_BIG_CHARS = 12           # 84px glyphs: 12 × 84 = 1008 < 1080
MAX_SMALL_CHARS = 20         # 46px glyphs: 20 × 46 = 920 < 1080
MAX_STAGE_CHARS = 6
DANMAKU_TOP_MARGIN = 110     # board-panel danmaku rows start below the corner labels (y 32..~108)
SLIDE_SECONDS = 0.3          # hook texts slide up into place over this long

DEFAULT_CTA_TEXT = "點左下角「訂閱」\n每期拆解一個轉型決策"
OUTRO_BOTTOM_CLEAR = 400     # Shorts player covers the bottom ~20% (title/handle/subscribe) — keep art above it
ARROW_GLYPH = "↙"            # points at the player's native subscribe button (bottom-left)
DEFAULT_LINK_TEXT = "完整影片：看簡介置頂連結"


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    w: int
    h: int

    @classmethod
    def parse(cls, text: str) -> "Rect":
        parts = text.split(":")
        if len(parts) != 4:
            raise ValueError(f"rect must be X:Y:W:H, got {text!r}")
        try:
            x, y, w, h = (int(p) for p in parts)
        except ValueError as exc:
            raise ValueError(f"rect must be four integers X:Y:W:H, got {text!r}") from exc
        if w <= 0 or h <= 0 or x < 0 or y < 0:
            raise ValueError(f"rect must have positive size and non-negative origin, got {text!r}")
        return cls(x, y, w, h)

    def check_within(self, width: int, height: int, name: str) -> None:
        if self.x + self.w > width or self.y + self.h > height:
            raise ValueError(f"{name} rect {self} exceeds the {width}x{height} source frame")


def _check_text(value: str, name: str, max_chars: int, *, max_lines: int = 1) -> None:
    lines = value.split("\n")
    if not value.strip() or len(lines) > max_lines or any(not ln.strip() for ln in lines):
        raise ValueError(f"{name} must be {max_lines} non-empty line(s)")
    if any(len(ln) > max_chars for ln in lines):
        raise ValueError(f"{name} lines must be at most {max_chars} characters")
    if any(unicodedata.category(ch).startswith("C") and ch != "\n" for ch in value) or any(
        ch in value for ch in "\r\t\u2028\u2029"
    ):
        raise ValueError(f"{name} must not contain control characters")


def shift_srt(srt_text: str, start: float, end: float) -> list[SrtBlock]:
    """Keep blocks overlapping [start, end); re-base them to the clip and clamp."""
    kept: list[SrtBlock] = []
    for b in parse_srt_blocks(srt_text):
        if b.end <= start or b.start >= end:
            continue
        s = max(b.start, start) - start
        e = min(b.end, end) - start
        if e - s >= 0.2:
            kept.append(SrtBlock(start=round(s, 3), end=round(e, 3), text=b.text))
    return kept


def shift_ass(ass_text: str, start: float) -> str:
    """Re-base an ASS file (e.g. the fetch-stage danmaku) so source time ``start`` becomes 0.

    Dialogue lines that end before ``start`` are dropped; ones straddling it are clamped.
    Styles, resolution and everything else are kept verbatim."""
    out: list[str] = []
    for line in ass_text.splitlines():
        if not line.startswith("Dialogue:"):
            out.append(line)
            continue
        fields = line.split(",", 9)
        if len(fields) < 10:
            continue
        s0 = _parse_ass_time(fields[1]) - start
        e0 = _parse_ass_time(fields[2]) - start
        if e0 <= 0:
            continue
        fields[1] = _format_ass_time(max(s0, 0.0))
        fields[2] = _format_ass_time(e0)
        out.append(",".join(fields))
    return "\n".join(out) + "\n"


_ASS_XY = re.compile(r"\\(move|pos)\(\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*(?:,\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*)?\)")


def offset_ass_y(ass_text: str, dy: int) -> str:
    """Push every ``\\move``/``\\pos`` y coordinate down by ``dy`` px (used when a full-frame
    danmaku ASS is burned before the board crop, so rows at y<board.y are not cut off)."""
    def sub(m: re.Match) -> str:
        tag, x1, y1, x2, y2 = m.groups()
        if x2 is None:
            return f"\\{tag}({x1},{float(y1) + dy:g})"
        return f"\\{tag}({x1},{float(y1) + dy:g},{x2},{float(y2) + dy:g})"
    return _ASS_XY.sub(sub, ass_text)


def danmaku_ass_for_board(xml_bytes: bytes) -> str:
    """Convert Bilibili danmaku XML for the 1080x896 board panel (biliass, Bilibili-native size)."""
    import biliass
    return biliass.convert_to_ass(
        xml_bytes, stage_width=CANVAS_W, stage_height=TOP_H,
        font_face=SUB_FONT_FACE, font_size=compute_font_size(TOP_H),
    )


def _fmt_srt_time(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def blocks_to_srt(blocks: list[SrtBlock]) -> str:
    return "\n\n".join(
        f"{i}\n{_fmt_srt_time(b.start)} --> {_fmt_srt_time(b.end)}\n{b.text}"
        for i, b in enumerate(blocks, 1)
    ) + "\n"


_STYLES = {
    # white on a dark box: legible over any gameplay / webcam pixels
    "box": "fontcolor=white:box=1:boxcolor=black@0.72:boxborderw=16",
    # dark graphite with a paper outline: the anime-sketch text treatment
    "ink": "fontcolor=0x2B2B2B:borderw=5:bordercolor=0xFCFAF5",
}


def _drawtext(textfile: str, *, size: int, x: str, y: str, style: str, enable: str | None = None) -> str:
    gate = f":enable='{enable}'" if enable else ""
    return (f"drawtext=fontfile=font.ttf:textfile={textfile}:expansion=none:"
            f"fontsize={size}:{_STYLES[style]}:x={x}:y={y}:line_spacing=14{gate}")


def _slide_y(base: int, delay: float, travel: int = 60) -> str:
    """y expression: start ``travel`` px lower and slide up over SLIDE_SECONDS after ``delay``."""
    return f"{base}+{travel}*max(0\\,1-max(0\\,t-{delay:.2f})/{SLIDE_SECONDS})"


def source_to_clip_time(ranges: list[tuple[float, float]], t: float) -> float:
    """Map a SOURCE time to the concatenated clip timeline (gaps snap to the next range start)."""
    offset = 0.0
    for rs, re_ in ranges:
        if t < rs:
            return offset
        if t < re_:
            return offset + (t - rs)
        offset += re_ - rs
    return offset


def build_filter_complex(
    *,
    board: Rect,
    face: Rect | None,
    ranges: list[tuple[float, float]],
    hook_seconds: float,
    with_subs: bool,
    outro_inputs: tuple[int, int, int] | None,
    bottom_inputs: tuple[int, int] | None,
    with_context: bool = False,
    with_promise: bool = False,
    stages: list[tuple[float, float]] | None = None,
    danmaku_on: str | None = None,
    caption_band: int = 0,
    audio_input: int = 0,
    bed_input: int | None = None,
) -> str:
    """Filter graph. Input [0] is the source seeked to the first range start; ``ranges``
    are (start, end) RELATIVE to it and are trimmed + concatenated in order (recruit
    phase + combat + result, for example). ``outro_inputs`` = (bg, mascot, silence)
    input indices or None for no outro; ``bottom_inputs`` = (bg, mascot) indices for
    the mascot panel, or None when ``face`` is given."""
    clip = sum(e - s for s, e in ranges)
    parts: list[str] = []
    n = len(ranges)
    # danmaku is burned BEFORE the trims (only the global -ss shift matters for its
    # timeline): on the full 16:9 frame ("frame", y-offset ASS) or on the cropped
    # 1080x896 board panel ("board", ASS converted for that stage size)
    if danmaku_on not in (None, "frame", "board"):
        raise ValueError(f"danmaku_on must be None, 'frame' or 'board', got {danmaku_on!r}")
    dm = ",subtitles=f='danmaku.ass'" if danmaku_on == "frame" else ""
    parts.append(f"[0:v]fps=30{dm},split={n}" + "".join(f"[r{i}v]" for i in range(n)))
    parts.append(f"[{audio_input}:a]asplit={n}" + "".join(f"[r{i}a]" for i in range(n)))
    for i, (rs, re_) in enumerate(ranges):
        parts.append(f"[r{i}v]trim=start={rs:.3f}:end={re_:.3f},setpts=PTS-STARTPTS[t{i}v]")
        parts.append(f"[r{i}a]atrim=start={rs:.3f}:end={re_:.3f},asetpts=PTS-STARTPTS[t{i}a]")
    parts.append("".join(f"[t{i}v][t{i}a]" for i in range(n)) + f"concat=n={n}:v=1:a=1[clipv][clipa0]")
    if bed_input is not None:
        # same trims on the music bed, then the long-form recipe (burn.py A2):
        # bed at _MUSIC_BED_VOLUME, sidechain-ducked by the voice, amix
        parts.append(f"[{bed_input}:a]aresample=48000,aformat=channel_layouts=stereo,asplit={n}"
                     + "".join(f"[b{i}]" for i in range(n)))
        for i, (rs, re_) in enumerate(ranges):
            parts.append(f"[b{i}]atrim=start={rs:.3f}:end={re_:.3f},asetpts=PTS-STARTPTS[tb{i}]")
        parts.append("".join(f"[tb{i}]" for i in range(n)) + f"concat=n={n}:v=0:a=1,afade=t=in:d=1.0[clipbed]")
        parts.append("[clipa0]aresample=48000,aformat=channel_layouts=stereo,asplit=2[sp_a][sp_b]")
        parts.append(f"[clipbed]volume={_MUSIC_BED_VOLUME}[bed_scaled]")
        parts.append(f"[bed_scaled][sp_a]sidechaincompress={_SIDECHAIN_PARAMS}[bed_ducked]")
        parts.append("[sp_b][bed_ducked]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[clipa]")
    else:
        parts.append("[clipa0]anull[clipa]")
    if face is not None:
        parts.append("[clipv]split=2[src0][src1]")
        parts.append(
            f"[src1]crop={face.w}:{face.h}:{face.x}:{face.y},"
            f"scale={CANVAS_W}:{BOT_H}:force_original_aspect_ratio=increase,"
            f"crop={CANVAS_W}:{BOT_H},setsar=1[bottom]"
        )
    else:
        assert bottom_inputs is not None
        bbg, bmas = bottom_inputs
        parts.append("[clipv]null[src0]")
        parts.append(
            f"[{bbg}:v]scale={CANVAS_W}:{BOT_H}:force_original_aspect_ratio=increase,"
            f"crop={CANVAS_W}:{BOT_H},setsar=1,fps=30[bb]"
        )
        parts.append(f"[{bmas}:v]scale=-2:{BOT_H - 80},format=rgba,fps=30[bm]")
        parts.append("[bb][bm]overlay=x=(W-w)/2:y=H-h[bottom]")
    dmb = ",subtitles=f='danmaku.ass'" if danmaku_on == "board" else ""
    parts.append(f"[src0]crop={board.w}:{board.h}:{board.x}:{board.y},scale={CANVAS_W}:{TOP_H},setsar=1{dmb}[board]")
    parts.append("[board][bottom]vstack=inputs=2[stack]")

    chain = []
    if caption_band > 0:
        # solid strip at the top of the face panel: hides a streamer's own banner and
        # gives the captions a clean home (see --caption-band)
        chain.append(f"drawbox=x=0:y={TOP_H}:w={CANVAS_W}:h={caption_band}:color=black:t=fill")
    chain.append(_drawtext("label.txt", size=44, x="w-text_w-32", y="32", style="box"))
    for i, (ss, se) in enumerate(stages or []):
        chain.append(_drawtext(f"stage{i}.txt", size=44, x="32", y="32", style="box",
                               enable=f"gte(t,{ss:.3f})*lt(t,{se:.3f})"))
    gate = f"lt(t,{hook_seconds:.3f})" if hook_seconds > 0 else None
    chain.append(_drawtext("claim.txt", size=84, x="(w-text_w)/2", y=_slide_y(CLAIM_Y, 0.0), style="box", enable=gate))
    if with_context:
        chain.append(_drawtext("context.txt", size=46, x="(w-text_w)/2", y=_slide_y(CONTEXT_Y, 0.15), style="box", enable=gate))
    if with_promise:
        chain.append(_drawtext("promise.txt", size=46, x="(w-text_w)/2", y=_slide_y(PROMISE_Y, 0.30), style="box", enable=gate))
    if with_subs:
        chain.append("subtitles=f='subs.ass'")
    chain.append("format=yuv420p")
    parts.append("[stack]" + ",".join(chain) + "[main]")
    fade_start = max(clip - 0.5, 0.0)
    afmt = "aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo"
    parts.append(f"[clipa]afade=t=out:st={fade_start:.3f}:d=0.5,{afmt}[a0]")
    if outro_inputs is None:
        parts.append("[main]null[v];[a0]anull[a]")
        return ";".join(parts)

    obg, omas, osil = outro_inputs
    parts.append(
        f"[{obg}:v]scale={CANVAS_W}:{CANVAS_H}:force_original_aspect_ratio=increase,"
        f"crop={CANVAS_W}:{CANVAS_H},setsar=1,fps=30[obg]"
    )
    parts.append(f"[{omas}:v]scale=-2:900,format=rgba,fps=30[om]")
    parts.append(f"[obg][om]overlay=x=(W-w)/2+60:y=H-h-{OUTRO_BOTTOM_CLEAR}[o1]")
    bob = f"{CANVAS_H - OUTRO_BOTTOM_CLEAR - 260}+18*sin(2*PI*t*2)"
    parts.append(
        "[o1]" + _drawtext("cta.txt", size=84, x="(w-text_w)/2", y="150", style="ink")
        + "," + _drawtext("link.txt", size=50, x="(w-text_w)/2", y="430", style="box")
        + "," + _drawtext("arrow.txt", size=240, x="60", y=bob, style="ink")
        + ",format=yuv420p[outro]"
    )
    parts.append(f"[{osil}:a]{afmt}[a1]")
    parts.append("[main][a0][outro][a1]concat=n=2:v=1:a=1[v][a]")
    return ";".join(parts)


def render(
    video: Path,
    ranges: list[tuple[float, float]],
    output: Path,
    *,
    claim: str,
    comp: str,
    rank: str,
    srt: Path | None = None,
    face: Rect | None = None,
    board: Rect = Rect(*DEFAULT_BOARD),
    hook_seconds: float = 3.0,
    outro_seconds: float = 4.0,
    context: str | None = None,
    promise: str | None = None,
    caption_band: int = 0,
    danmaku: Path | None = None,
    auto_danmaku: bool = True,
    audio: Path | None = None,
    auto_audio: bool = True,
    bed: Path | None = None,
    auto_bed: bool = True,
    stages: list[tuple[str, float]] | None = None,
    cta_text: str = DEFAULT_CTA_TEXT,
    link_text: str = DEFAULT_LINK_TEXT,
    bg: Path = DEFAULT_BG,
    mascot: Path | None = None,
    font: Path | None = None,
    overwrite: bool = False,
) -> Path:
    """Render the concatenated ``ranges`` (source seconds, in order) of ``video`` as a
    1080x1920 Short with an outro."""
    _check_text(claim, "claim", MAX_BIG_CHARS, max_lines=2)
    if context is not None:
        _check_text(context, "context", MAX_SMALL_CHARS)
    if promise is not None:
        _check_text(promise, "promise", MAX_SMALL_CHARS)
    for label, _ in stages or []:
        _check_text(label, "stage label", MAX_STAGE_CHARS)
    _check_text(comp, "comp", 12)
    _check_text(rank, "rank", 12)
    _check_text(cta_text, "cta text", MAX_BIG_CHARS, max_lines=2)
    _check_text(link_text, "link text", 20)
    if not ranges:
        raise ValueError("at least one range is required")
    flat = [v for r in ranges for v in r] + [hook_seconds, outro_seconds]
    if not all(math.isfinite(v) for v in flat):
        raise ValueError("times must be finite")
    for i, (rs, re_) in enumerate(ranges):
        if rs < 0 or re_ <= rs:
            raise ValueError(f"range {i + 1}: end must be greater than start, both >= 0")
        if i and rs < ranges[i - 1][1]:
            raise ValueError(f"range {i + 1} must start at or after the previous range ends")
    start, end = ranges[0][0], ranges[-1][1]
    clip = sum(re_ - rs for rs, re_ in ranges)
    if clip + outro_seconds > MAX_CLIP_SECONDS:
        raise ValueError(f"clip + outro must be <= {MAX_CLIP_SECONDS:.0f}s for a Short, got {clip + outro_seconds:.1f}s")
    if outro_seconds < 0 or hook_seconds < 0:
        raise ValueError("outro and hook seconds must be >= 0")
    if outro_seconds > 0 and outro_seconds < 1.0:
        raise ValueError("outro must be 0 or at least 1 second")
    if caption_band < 0 or caption_band > BOT_H // 2:
        raise ValueError(f"caption band must be 0..{BOT_H // 2} px")
    if output.suffix.lower() != ".mp4":
        raise ValueError("output must be an .mp4 file")
    source_path = video.resolve()
    output_path = output.absolute()
    if source_path == output_path.resolve():
        raise ValueError("output must differ from the input video")
    if output_path.exists() and not overwrite:
        raise FileExistsError(f"output exists; pass --overwrite to replace: {output}")
    for tool in ("ffmpeg", "ffprobe"):
        if shutil.which(tool) is None:
            raise RuntimeError(f"{tool} not found in PATH")

    info = validate.probe(source_path)
    if (info.width, info.height) != (SOURCE_W, SOURCE_H):
        raise ValueError(f"source must be {SOURCE_W}x{SOURCE_H}, got {info.width}x{info.height}")
    if not info.has_audio and audio is None and not auto_audio:
        raise ValueError("source has no audio stream")
    if end > info.duration + 0.05:
        raise ValueError(f"end {end:.3f}s exceeds source duration {info.duration:.3f}s")
    board.check_within(SOURCE_W, SOURCE_H, "board")
    if face is not None:
        face.check_within(SOURCE_W, SOURCE_H, "face")

    mascot_path = Path(mascot or default_mascot("anime-sketch")).resolve()
    bg_path = bg.resolve()
    font_path = Path(font or resolve_font()).resolve()
    for p, name in ((mascot_path, "mascot"), (bg_path, "background"), (font_path, "font")):
        if not p.is_file():
            raise FileNotFoundError(f"{name} not found: {p}")

    blocks: list[SrtBlock] = []
    if srt is not None:
        text = srt.read_text(encoding="utf-8")
        offset = 0.0
        for rs, re_ in ranges:
            for b in shift_srt(text, rs, re_):
                bs, be = b.start + offset, b.end + offset
                if hook_seconds > 0 and bs < hook_seconds:
                    bs = hook_seconds          # the hook block owns the panel top until then
                if be - bs >= 0.2:
                    blocks.append(SrtBlock(start=round(bs, 3), end=round(be, 3), text=b.text))
            offset += re_ - rs
    # Audio: the source mix carries the streamer's BGM, which Content ID blocks on Shorts
    # (dZFbEQ0k-zk, 2026-09-15: "Selfish" by Anth → blocked globally). Prefer the
    # song-remover `<stem>/no_music.wav` (voice + game SFX, music removed; same timeline),
    # or `speech.wav` (dry voice) when only that exists.
    if audio is None and auto_audio:
        for name in ("no_music.wav", "speech.wav"):   # voice + game SFX first; dry voice as fallback
            candidate = source_path.with_suffix("") / name
            if candidate.is_file():
                audio = candidate
                break
    if audio is not None and not audio.is_file():
        raise FileNotFoundError(f"audio track not found: {audio}")
    # Music bed: `<stem>.music_bed.wav` from video2yt-music-mix (CC BY library; its
    # `<stem>.music_credits.txt` must go into the description — copied next to the output).
    credits_src: Path | None = None
    if bed is None and auto_bed:
        candidate = source_path.with_name(source_path.stem + ".music_bed.wav")
        if candidate.is_file():
            bed = candidate
    if bed is not None:
        if not bed.is_file():
            raise FileNotFoundError(f"music bed not found: {bed}")
        cand = bed.with_name(bed.name.replace(".music_bed.wav", ".music_credits.txt"))
        credits_src = cand if cand.is_file() else None
    if danmaku is None and auto_danmaku:
        for suffix in (".danmaku.xml", ".danmaku.ass"):
            candidate = source_path.with_name(source_path.stem + suffix)
            if candidate.is_file():
                danmaku = candidate
                break
    if danmaku is not None and not danmaku.is_file():
        raise FileNotFoundError(f"danmaku file not found: {danmaku}")
    if danmaku is not None and danmaku.suffix.lower() not in (".xml", ".ass"):
        raise ValueError("danmaku must be a Bilibili .xml or a source-timeline .ass")
    danmaku_on = None
    if danmaku is not None:
        if danmaku.suffix.lower() == ".xml":
            danmaku_text = offset_ass_y(shift_ass(danmaku_ass_for_board(danmaku.read_bytes()), start),
                                        DANMAKU_TOP_MARGIN)
            danmaku_on = "board"
        else:
            danmaku_text = offset_ass_y(shift_ass(danmaku.read_text(encoding="utf-8"), start), board.y)
            danmaku_on = "frame"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".short-", dir=output_path.parent) as work_dir:
        work = Path(work_dir)
        shutil.copyfile(font_path, work / "font.ttf")
        (work / "label.txt").write_text(f"{comp}｜{rank}", encoding="utf-8")
        (work / "claim.txt").write_text(claim, encoding="utf-8")
        if danmaku_on is not None:
            (work / "danmaku.ass").write_text(danmaku_text, encoding="utf-8")
        if context is not None:
            (work / "context.txt").write_text(context, encoding="utf-8")
        if promise is not None:
            (work / "promise.txt").write_text(promise, encoding="utf-8")
        stage_windows: list[tuple[float, float]] = []
        if stages:
            times = [source_to_clip_time(ranges, t) for _, t in stages]
            if any(b <= a for a, b in zip(times, times[1:])):
                raise ValueError("stage times must be strictly increasing in the clip timeline")
            for i, ((label, _), st) in enumerate(zip(stages, times)):
                (work / f"stage{i}.txt").write_text(label, encoding="utf-8")
                en = times[i + 1] if i + 1 < len(times) else clip
                stage_windows.append((st, en))
        (work / "cta.txt").write_text(cta_text, encoding="utf-8")
        (work / "link.txt").write_text(link_text, encoding="utf-8")
        (work / "arrow.txt").write_text(ARROW_GLYPH, encoding="utf-8")
        if blocks:
            ass = srt_to_ass(
                blocks_to_srt(blocks), CANVAS_W, CANVAS_H, SUB_FONT_FACE, SUB_FONT_SIZE,
                position="top", outline_px=3,
                margin_v=(TOP_H + max(8, (caption_band - 2 * SUB_FONT_SIZE - 8) // 2)) if caption_band else SUB_TOP_Y,
                margin_l=32, margin_r=32,
                max_lines=2, bold=True,
            )
            (work / "subs.ass").write_text(ass, encoding="utf-8")
        outro = max(outro_seconds, 0.0)
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
               "-ss", f"{start:.3f}", "-t", f"{end - start:.3f}", "-i", str(source_path)]
        n_inputs = 1
        audio_input = 0
        if audio is not None:
            cmd += ["-ss", f"{start:.3f}", "-t", f"{end - start:.3f}", "-i", str(audio.resolve())]
            audio_input = n_inputs
            n_inputs += 1
        bed_input = None
        if bed is not None:
            cmd += ["-ss", f"{start:.3f}", "-t", f"{end - start:.3f}", "-i", str(bed.resolve())]
            bed_input = n_inputs
            n_inputs += 1
        outro_inputs = None
        if outro > 0:
            cmd += ["-framerate", "30", "-loop", "1", "-t", f"{outro:.3f}", "-i", str(bg_path),
                    "-framerate", "30", "-loop", "1", "-t", f"{outro:.3f}", "-i", str(mascot_path),
                    "-f", "lavfi", "-t", f"{outro:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
            outro_inputs = (n_inputs, n_inputs + 1, n_inputs + 2)
            n_inputs += 3
        bottom_inputs = None
        if face is None:
            cmd += ["-framerate", "30", "-loop", "1", "-t", f"{clip:.3f}", "-i", str(bg_path),
                    "-framerate", "30", "-loop", "1", "-t", f"{clip:.3f}", "-i", str(mascot_path)]
            bottom_inputs = (n_inputs, n_inputs + 1)
            n_inputs += 2
        rel = [(rs - start, re_ - start) for rs, re_ in ranges]
        graph = build_filter_complex(board=board, face=face, ranges=rel, hook_seconds=hook_seconds,
                                     with_subs=bool(blocks), outro_inputs=outro_inputs,
                                     bottom_inputs=bottom_inputs, with_context=context is not None,
                                     with_promise=promise is not None, stages=stage_windows,
                                     danmaku_on=danmaku_on, caption_band=caption_band,
                                     audio_input=audio_input, bed_input=bed_input)
        staged = work / "rendered.mp4"
        cmd += ["-filter_complex", graph, "-map", "[v]", "-map", "[a]",
                "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
                "-r", "30", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
                "-movflags", "+faststart", str(staged)]
        subprocess.run(cmd, cwd=work, check=True, capture_output=True, text=True)

        result = validate.probe(staged)
        expected = clip + outro
        if (result.width, result.height) != (CANVAS_W, CANVAS_H):
            raise ValueError(f"output is {result.width}x{result.height}, expected {CANVAS_W}x{CANVAS_H}")
        if not result.has_audio or abs(result.duration - expected) > 0.35:
            raise ValueError(f"output duration {result.duration:.3f}s, expected {expected:.3f}s (audio={result.has_audio})")
        os.replace(staged, output_path)
    if credits_src is not None:
        shutil.copyfile(credits_src, output_path.with_name(output_path.stem + "_music_credits.txt"))
    return output
