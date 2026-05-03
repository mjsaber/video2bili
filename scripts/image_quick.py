"""Quick image generation: Codex `image_gen` (default) or Gemini 2.5 Flash Image.

Generates an image from a prompt and crops/pads it to a target aspect ratio.

Usage:
    # Default: Codex `image_gen` (no API key, requires `codex` CLI logged in).
    uv run python scripts/image_quick.py \\
        --prompt-file output/<project>/intro_image_prompt.txt \\
        --output      output/<project>/intro_bg.png \\
        --save-raw    output/<project>/intro_bg_raw.png \\
        --target-size 1920x1080 --fit cover

    # Fallback: Gemini (requires GEMINI_API_KEY with billing enabled).
    uv run python scripts/image_quick.py --backend gemini ...
"""
from __future__ import annotations

import argparse
import io
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from dotenv import load_dotenv
from PIL import Image


def generate_gemini(
    prompt: str,
    api_key: str,
    *,
    model: str = "gemini-2.5-flash-image",
) -> Image.Image:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    try:
        response = client.models.generate_content(
            model=model,
            contents=[prompt],
            config=types.GenerateContentConfig(response_modalities=["IMAGE"]),
        )
    except Exception as exc:
        msg = str(exc)
        if "RESOURCE_EXHAUSTED" in msg or "free_tier" in msg or "429" in msg:
            print(
                "[img:gemini] quota exhausted (free-tier limit is 0 for image-gen). "
                "Either enable billing on the GEMINI_API_KEY's project, or rerun "
                "with --backend codex (no setup required if `codex` CLI is logged in).",
                file=sys.stderr,
            )
        raise

    for cand in response.candidates or []:
        for part in cand.content.parts or []:
            if part.inline_data and part.inline_data.data:
                return Image.open(io.BytesIO(part.inline_data.data))
    raise RuntimeError(
        "no image returned. response text: "
        + str(getattr(response, "text", "")[:500])
    )


def generate_codex(
    prompt: str,
    *,
    codex_size: str = "1536x1024",
    timeout: int = 600,
) -> Image.Image:
    """Generate an image via Codex CLI's `image_gen` tool.

    Codex's `image_gen` writes to ~/.codex/generated_images/<session>/. We instruct
    the agent to copy the result to a tempfile inside cwd so we can pick it up
    without scanning the global directory.

    Gotchas (from output/ringnaga/WORKFLOW_NOTES.md):
      - Default sandbox `workspace-write` already allows writing inside cwd; do NOT
        add `writable_roots`. Doing so caused an 11+ minute hang once.
      - Keep the instruction concise. Multi-step checklists trigger an approval loop.
      - `image_gen` defaults to 1536x1024 (3:2). Caller must fit to final aspect ratio.
    """
    # Use a tempdir as cwd so codex (workspace-write sandbox) can write the result
    # there without needing --add-dir. We then read the file back into PIL.
    with tempfile.TemporaryDirectory(prefix="codex_img_") as tmpdir:
        tmpdir_path = Path(tmpdir)
        out_path = tmpdir_path / "image.png"

        instruction = (
            f"Use the image_gen tool to generate one image at size {codex_size}, "
            f"then save the resulting PNG to {out_path}. "
            f"Do not ask any clarifying questions. "
            f"Image prompt:\n\n{prompt}"
        )

        cmd = [
            "codex", "exec",
            "--sandbox", "workspace-write",
            "--cd", str(tmpdir_path),
            "--skip-git-repo-check",
            instruction,
        ]

        print(f"[img:codex] codex exec (size={codex_size}, timeout={timeout}s)", file=sys.stderr)
        try:
            subprocess.run(cmd, check=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            raise RuntimeError(
                f"codex exec timed out after {timeout}s. Common cause: passing "
                "`writable_roots` or a multi-step checklist instruction. See "
                "output/ringnaga/WORKFLOW_NOTES.md for known gotchas."
            )

        if not out_path.exists():
            raise RuntimeError(
                f"codex finished but {out_path} does not exist. The agent may have "
                "saved elsewhere; try running `codex exec` interactively with the "
                "same instruction to debug."
            )

        img = Image.open(out_path)
        img.load()  # force-read pixel data before tmpdir is removed
        return img


def fit_to_size(img: Image.Image, target_w: int, target_h: int, mode: str) -> Image.Image:
    """Resize and crop/pad to target. mode: cover | contain."""
    sw, sh = img.size
    src_ratio = sw / sh
    dst_ratio = target_w / target_h

    if mode == "cover":
        if src_ratio > dst_ratio:
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
    parser.add_argument(
        "--backend", choices=["codex", "gemini"], default="codex",
        help="codex (default; uses `codex exec` + image_gen tool) or gemini (needs GEMINI_API_KEY).",
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
    prompt = args.prompt if args.prompt else args.prompt_file.read_text(encoding="utf-8").strip()
    print(f"[img] backend={args.backend} prompt_chars={len(prompt)}", file=sys.stderr)

    if args.backend == "gemini":
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            print("GEMINI_API_KEY not set in env or .env", file=sys.stderr)
            return 2
        img = generate_gemini(prompt, api_key=api_key, model=args.gemini_model)
    else:
        img = generate_codex(prompt, codex_size=args.codex_size, timeout=args.codex_timeout)

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
