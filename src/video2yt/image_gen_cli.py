"""CLI for video2yt-image: generate an image from a text prompt and fit it."""

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from video2yt import image_gen


def _log(msg: str) -> None:
    print(f"[video2yt-image] {msg}", file=sys.stderr)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="video2yt-image",
        description=(
            "Generate an image from a prompt (Codex `image_gen` by default; "
            "Gemini 2.5 Flash Image with --backend gemini) and crop/pad it to "
            "a target aspect ratio."
        ),
    )
    prompt_grp = parser.add_mutually_exclusive_group(required=True)
    prompt_grp.add_argument("--prompt", help="Inline text prompt.")
    prompt_grp.add_argument("--prompt-file", type=Path, help="UTF-8 file with the prompt.")
    parser.add_argument("-o", "--output", type=Path, required=True)
    parser.add_argument(
        "--backend", choices=["codex", "gemini"], default="codex",
        help="codex (default; uses `codex exec` + image_gen tool) or gemini "
             "(needs GEMINI_API_KEY with billing enabled).",
    )
    parser.add_argument(
        "--gemini-model", default="gemini-2.5-flash-image",
        help="Gemini model id (only used when --backend gemini).",
    )
    parser.add_argument(
        "--codex-size", default="1536x1024",
        help="Size hint passed to Codex's image_gen tool (only used when --backend codex).",
    )
    parser.add_argument(
        "--codex-timeout", type=int, default=600,
        help="Timeout (seconds) for the codex exec subprocess.",
    )
    parser.add_argument(
        "--target-size", default="1920x1080",
        help="Target WIDTHxHEIGHT, e.g. 1920x1080. Used with --fit.",
    )
    parser.add_argument(
        "--fit", choices=["cover", "contain", "none"], default="cover",
        help="cover = scale + center-crop; contain = letterbox; none = save as-is.",
    )
    parser.add_argument(
        "--save-raw", type=Path, default=None,
        help="Optional path to also save the raw model output before fit.",
    )
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> Path:
    load_dotenv()

    if args.prompt:
        prompt = args.prompt
    else:
        if not args.prompt_file.exists():
            raise FileNotFoundError(f"prompt file not found: {args.prompt_file}")
        prompt = args.prompt_file.read_text(encoding="utf-8").strip()
    if not prompt:
        raise ValueError("prompt is empty")

    _log(f"backend={args.backend} prompt_chars={len(prompt)}")

    if args.backend == "gemini":
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY not set in env or .env")
        img = image_gen.generate_gemini(prompt, api_key=api_key, model=args.gemini_model)
    else:
        img = image_gen.generate_codex(
            prompt, codex_size=args.codex_size, timeout=args.codex_timeout
        )

    _log(f"generated {img.size[0]}x{img.size[1]} mode={img.mode}")
    if img.mode != "RGB":
        img = img.convert("RGB")

    if args.save_raw:
        args.save_raw.parent.mkdir(parents=True, exist_ok=True)
        img.save(args.save_raw)
        _log(f"raw saved to {args.save_raw}")

    if args.fit != "none" and args.target_size:
        tw, th = image_gen.parse_size(args.target_size)
        img = image_gen.fit_to_size(img, tw, th, args.fit)
        _log(f"fitted to {tw}x{th} via {args.fit}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    img.save(args.output)
    _log(f"saved to {args.output}")
    return args.output


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        run(args)
        return 0
    except (ValueError, FileNotFoundError, RuntimeError) as e:
        _log(f"error: {e}")
        return 1
