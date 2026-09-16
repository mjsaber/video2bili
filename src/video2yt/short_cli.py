"""CLI: cut a vertical Short (1080x1920) from a 16:9 gameplay video."""
import argparse
from pathlib import Path
import subprocess
import sys

from video2yt import short
from video2yt.cuts import parse_time


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="video2yt-short",
        description=(
            "Cut [start, end) of a 1920x1080 gameplay video into a 1080x1920 Short: "
            "zoomed board on top, streamer face (or 女老板 mascot) below, claim + comp/rank "
            "labels, optional subtitles, and a subscribe/link outro."
        ),
    )
    parser.add_argument("--video", type=Path, required=True, help="1920x1080 source (raw <bv>.mp4 preferred)")
    parser.add_argument("--start", help="SS / MM:SS / HH:MM:SS in the source timeline (single range)")
    parser.add_argument("--end", help="SS / MM:SS / HH:MM:SS in the source timeline (single range)")
    parser.add_argument("--range", action="append", default=[], metavar="START~END",
                        help="Source range to keep, repeatable and concatenated in order "
                             "(e.g. --range 19:48~21:57 --range 22:02~22:04.3); replaces --start/--end")
    parser.add_argument("--claim", required=True, help="Assertion shown at t=0, 1-2 lines ≤12 chars each; use \\n for a line break")
    parser.add_argument("--comp", required=True, help="流派 label, e.g. 海盜倒轉")
    parser.add_argument("--rank", required=True, help="Result label, e.g. 這局第1名")
    parser.add_argument("--context", help="語境行 shown with the claim (≤20 chars), e.g. 第14回合・剩2血・場上300攻")
    parser.add_argument("--promise", help="預期行 shown with the claim (≤20 chars), e.g. 90秒後全場破萬 最後第1名")
    parser.add_argument("--stage", action="append", default=[], metavar="LABEL@TIME",
                        help="Top-left stage label from a SOURCE time until the next stage (≤6 chars), repeatable, "
                             "e.g. --stage 招募中@19:48 --stage 開戰@21:22 --stage 結算@22:02")
    parser.add_argument("--audio", type=Path, help="Source-timeline audio track to use instead of the source mix "
                        "(default: <video stem>/no_music.wav, else speech.wav, from video2yt-stems — no BGM, no Content ID block)")
    parser.add_argument("--original-audio", action="store_true", help="Keep the source mix even if stems exist (BGM may get the Short blocked)")
    parser.add_argument("--bed", type=Path, help="Music bed wav in the source timeline (default: <video stem>.music_bed.wav "
                        "from video2yt-music-mix when present); mixed like the long-form: volume 0.12, sidechain-ducked under the voice")
    parser.add_argument("--no-bed", action="store_true", help="Do not mix a music bed even if the sibling wav exists")
    parser.add_argument("--caption-band", type=int, default=0, metavar="PX",
                        help="Solid black strip of this height at the top of the face panel; captions go inside it. "
                             "Use it to hide a streamer's own banner (e.g. 瓦莉拉「小助理」: face 1470:790:450:290 + band 150)")
    parser.add_argument("--danmaku", type=Path, help="Danmaku to burn on the board: Bilibili .xml (re-laid out for the board panel, preferred) or source-timeline .ass; default: <video stem>.danmaku.xml, else .danmaku.ass, next to the video")
    parser.add_argument("--no-danmaku", action="store_true", help="Do not burn danmaku even if the sibling ASS exists")
    parser.add_argument("--srt", type=Path, help="Subtitles in the SOURCE timeline (e.g. <name>.cleaned.srt); shifted to the clip")
    parser.add_argument("--face", help="Face-cam crop X:Y:W:H in the source; omit to show the mascot instead")
    parser.add_argument("--board", default=":".join(str(v) for v in short.DEFAULT_BOARD),
                        help=f"Board crop X:Y:W:H in the source (default {':'.join(str(v) for v in short.DEFAULT_BOARD)})")
    parser.add_argument("--hook-seconds", type=float, default=3.0, help="How long the claim stays (0 = whole clip)")
    parser.add_argument("--outro-seconds", type=float, default=4.0, help="Outro length (0 = no outro)")
    parser.add_argument("--cta-text", default=short.DEFAULT_CTA_TEXT, help="Outro CTA, 1-2 lines ≤12 chars; \\n for a line break")
    parser.add_argument("--link-text", default=short.DEFAULT_LINK_TEXT)
    parser.add_argument("--bg", type=Path, default=short.DEFAULT_BG, help="Outro / mascot-panel background")
    parser.add_argument("--mascot", type=Path, help="RGBA mascot; default = anime-sketch 女老板")
    parser.add_argument("--font", type=Path, help="Font file; default uses the intro's CJK font resolver")
    parser.add_argument("-o", "--output", type=Path, required=True)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args(argv)


def _ranges(args: argparse.Namespace) -> list[tuple[float, float]]:
    if args.range:
        if args.start or args.end:
            raise ValueError("use either --range or --start/--end, not both")
        out = []
        for text in args.range:
            if "~" not in text:
                raise ValueError(f"range must be START~END, got {text!r}")
            a, b = text.split("~", 1)
            out.append((parse_time(a), parse_time(b)))
        return out
    if not (args.start and args.end):
        raise ValueError("pass --start and --end, or one or more --range START~END")
    return [(parse_time(args.start), parse_time(args.end))]


def _stages(args: argparse.Namespace) -> list[tuple[str, float]]:
    out = []
    for text in args.stage:
        if "@" not in text:
            raise ValueError(f"stage must be LABEL@TIME, got {text!r}")
        label, t = text.rsplit("@", 1)
        out.append((label, parse_time(t)))
    return out


def run(args: argparse.Namespace) -> Path:
    return short.render(
        args.video, _ranges(args), args.output,
        claim=args.claim.replace("\\n", "\n"), comp=args.comp, rank=args.rank,
        context=args.context, promise=args.promise, stages=_stages(args),
        danmaku=args.danmaku, auto_danmaku=not args.no_danmaku, caption_band=args.caption_band,
        audio=args.audio, auto_audio=not args.original_audio, bed=args.bed, auto_bed=not args.no_bed,
        srt=args.srt, face=short.Rect.parse(args.face) if args.face else None,
        board=short.Rect.parse(args.board), hook_seconds=args.hook_seconds,
        outro_seconds=args.outro_seconds, cta_text=args.cta_text.replace("\\n", "\n"), link_text=args.link_text,
        bg=args.bg, mascot=args.mascot, font=args.font, overwrite=args.overwrite,
    )


def main(argv: list[str] | None = None) -> int:
    try:
        output = run(parse_args(argv))
        print(f"[video2yt-short] wrote {output}", file=sys.stderr)
        return 0
    except (ValueError, OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"[video2yt-short] error: {exc}", file=sys.stderr)
        if isinstance(exc, subprocess.CalledProcessError) and exc.stderr:
            print(exc.stderr, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
