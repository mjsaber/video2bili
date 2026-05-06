"""Generate an image from a text prompt and optionally fit it to a target aspect ratio.

Two backends:
  - codex: shells out to `codex exec` and uses its `image_gen` tool. No API key
    required (assumes the local Codex CLI is logged in).
  - gemini: calls Gemini 2.5 Flash Image via the google-genai SDK. Requires
    GEMINI_API_KEY with billing enabled (free tier quota is 0).

The pure pixel transforms (`fit_to_size`, `parse_size`) are independent of the
backend so they can be unit-tested without any model call.
"""
from __future__ import annotations

import io
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image


def parse_size(spec: str) -> tuple[int, int]:
    w_str, h_str = spec.lower().split("x")
    return int(w_str), int(h_str)


def fit_to_size(img: Image.Image, target_w: int, target_h: int, mode: str) -> Image.Image:
    """Resize and crop/pad to (target_w, target_h). mode: cover | contain."""
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
            hint = (
                " (free-tier limit is 0 for image-gen; either enable billing "
                "on the GEMINI_API_KEY's project, or rerun with --backend codex)"
            )
        else:
            hint = ""
        raise RuntimeError(f"Gemini SDK error: {exc}{hint}") from exc

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

    Codex's `image_gen` writes to ~/.codex/generated_images/<session>/. We
    instruct the agent to copy the result to a tempfile inside cwd so we can
    pick it up without scanning the global directory.

    Gotchas (from output/ringnaga/WORKFLOW_NOTES.md):
      - Default sandbox `workspace-write` already allows writing inside cwd; do
        NOT add `writable_roots`. Doing so caused an 11+ minute hang once.
      - Keep the instruction concise. Multi-step checklists trigger an approval loop.
      - `image_gen` defaults to 1536x1024 (3:2). Caller must fit to final aspect ratio.
    """
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
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(
                f"codex exec failed with exit code {exc.returncode}. "
                "Re-run interactively to inspect the codex output."
            ) from exc

        if not out_path.exists():
            raise RuntimeError(
                f"codex finished but {out_path} does not exist. The agent may have "
                "saved elsewhere; try running `codex exec` interactively with the "
                "same instruction to debug."
            )

        img = Image.open(out_path)
        img.load()  # force-read pixel data before tmpdir is removed
        return img
