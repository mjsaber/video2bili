"""Quick validation script for Gemini 2.5 Flash Image (nanobanana).

Generates an image from a prompt and crops/pads it to a target aspect ratio.

Usage:
    uv run python scripts/image_quick.py \\
        --prompt "..." --output bg.png \\
        --target-size 1920x1080 \\
        --fit cover
"""
from __future__ import annotations

import argparse
import io
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types
from PIL import Image


def generate(
    prompt: str,
    api_key: str,
    *,
    model: str = "gemini-2.5-flash-image",
) -> Image.Image:
    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=model,
        contents=[prompt],
        config=types.GenerateContentConfig(
            response_modalities=["IMAGE"],
        ),
    )
    for cand in response.candidates or []:
        for part in cand.content.parts or []:
            if part.inline_data and part.inline_data.data:
                return Image.open(io.BytesIO(part.inline_data.data))
    raise RuntimeError(
        "no image returned. response text: "
        + str(getattr(response, "text", "")[:500])
    )


def fit_to_size(img: Image.Image, target_w: int, target_h: int, mode: str) -> Image.Image:
    """Resize and crop/pad to target. mode: cover | contain."""
    sw, sh = img.size
    src_ratio = sw / sh
    dst_ratio = target_w / target_h

    if mode == "cover":
        # Scale so the image fully covers, then center-crop.
        if src_ratio > dst_ratio:
            # Source wider — scale to height, crop width.
            new_h = target_h
            new_w = round(sw * new_h / sh)
        else:
            new_w = target_w
            new_h = round(sh * new_w / sw)
        img = img.resize((new_w, new_h), Image.LANCZOS)
        left = (new_w - target_w) // 2
        top = (new_h - target_h) // 2
        return img.crop((left, top, left + target_w, top + target_h))

    if mode == "contain":
        # Letterbox/pillarbox.
        if src_ratio > dst_ratio:
            new_w = target_w
            new_h = round(sh * new_w / sw)
        else:
            new_h = target_h
            new_w = round(sw * new_h / sh)
        img = img.resize((new_w, new_h), Image.LANCZOS)
        canvas = Image.new("RGB", (target_w, target_h), (0, 0, 0))
        canvas.paste(img, ((target_w - new_w) // 2, (target_h - new_h) // 2))
        return canvas

    raise ValueError(f"unknown fit mode: {mode}")


def parse_size(spec: str) -> tuple[int, int]:
    w_str, h_str = spec.lower().split("x")
    return int(w_str), int(h_str)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    prompt_grp = parser.add_mutually_exclusive_group(required=True)
    prompt_grp.add_argument("--prompt", help="Text prompt")
    prompt_grp.add_argument("--prompt-file", type=Path)
    parser.add_argument("--output", "-o", type=Path, required=True)
    parser.add_argument("--model", default="gemini-2.5-flash-image")
    parser.add_argument(
        "--target-size", default="1920x1080",
        help="Target WIDTHxHEIGHT, e.g. 1920x1080. Empty to skip fit.",
    )
    parser.add_argument(
        "--fit", choices=["cover", "contain", "none"], default="cover",
        help="cover = scale + center-crop; contain = letterbox; none = save as-is",
    )
    parser.add_argument(
        "--save-raw", type=Path, default=None,
        help="Optional path to also save the raw model output before fit.",
    )
    args = parser.parse_args()

    load_dotenv()
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("GEMINI_API_KEY not set in env or .env", file=sys.stderr)
        return 2

    prompt = args.prompt if args.prompt else args.prompt_file.read_text(encoding="utf-8").strip()
    print(f"[img] model={args.model} prompt_chars={len(prompt)}", file=sys.stderr)

    img = generate(prompt, api_key=api_key, model=args.model)
    print(f"[img] generated {img.size[0]}x{img.size[1]} mode={img.mode}", file=sys.stderr)

    if img.mode != "RGB":
        img = img.convert("RGB")

    if args.save_raw:
        args.save_raw.parent.mkdir(parents=True, exist_ok=True)
        img.save(args.save_raw)
        print(f"[img] raw saved to {args.save_raw}", file=sys.stderr)

    if args.fit != "none" and args.target_size:
        tw, th = parse_size(args.target_size)
        img = fit_to_size(img, tw, th, args.fit)
        print(f"[img] fitted to {tw}x{th} via {args.fit}", file=sys.stderr)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    img.save(args.output)
    print(f"[img] saved to {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
