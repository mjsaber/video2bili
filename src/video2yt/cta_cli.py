"""CLI for a brief contextual CTA over an existing gameplay segment."""
import argparse
from pathlib import Path
import subprocess
import sys

from video2yt import cta


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="video2yt-cta",
        description="Overlay a short CTA on 1080p/30fps H.264 gameplay; keep the timeline and copy audio.",
    )
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--text", required=True, help="One line, 1–40 characters")
    parser.add_argument("--at", type=float, required=True, help="Start time in seconds")
    parser.add_argument("--duration", type=float, default=4.0, help="Display duration in seconds (default 4)")
    parser.add_argument("--position", choices=("top", "bottom"), default="top")
    parser.add_argument("--font", type=Path, help="Font file; default uses the intro's CJK font resolver")
    parser.add_argument("-o", "--output", type=Path, required=True)
    parser.add_argument("--overwrite", action="store_true", help="Replace an existing output after successful validation")
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> Path:
    return cta.render(args.video, args.text, args.at, args.output, duration=args.duration,
                      position=args.position, font=args.font, overwrite=args.overwrite)


def main(argv: list[str] | None = None) -> int:
    try:
        output = run(parse_args(argv))
        print(f"[video2yt-cta] wrote {output}", file=sys.stderr)
        return 0
    except (ValueError, OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"[video2yt-cta] error: {exc}", file=sys.stderr)
        if isinstance(exc, subprocess.CalledProcessError) and exc.stderr:
            print(exc.stderr, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
