"""Quick validation script for Volcengine BigTTS HTTP Chunked endpoint.

Usage:
    uv run python scripts/tts_quick.py --text "..." --output out.mp3
    uv run python scripts/tts_quick.py --text-file script.txt --output out.mp3 --speech-rate 70
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import uuid
from pathlib import Path

import requests
from dotenv import load_dotenv

ENDPOINT = "https://openspeech.bytedance.com/api/v3/tts/unidirectional"


def synthesize(
    text: str,
    api_key: str,
    speaker: str,
    output_path: Path,
    *,
    resource_id: str = "seed-tts-2.0",
    speech_rate: int = 0,
    sample_rate: int = 24000,
    audio_format: str = "mp3",
) -> dict:
    headers = {
        "X-Api-Key": api_key,
        "X-Api-Resource-Id": resource_id,
        "X-Api-Request-Id": str(uuid.uuid4()),
        "Content-Type": "application/json",
    }
    body = {
        "user": {"uid": "video2yt"},
        "req_params": {
            "text": text,
            "speaker": speaker,
            "audio_params": {
                "format": audio_format,
                "sample_rate": sample_rate,
                "speech_rate": speech_rate,
            },
        },
    }

    audio_chunks: list[bytes] = []
    final_status = None
    sentences = []

    with requests.post(ENDPOINT, headers=headers, json=body, stream=True, timeout=120) as resp:
        if resp.status_code != 200:
            raise RuntimeError(
                f"HTTP {resp.status_code}: {resp.text}\n"
                f"X-Tt-Logid: {resp.headers.get('X-Tt-Logid')}"
            )
        logid = resp.headers.get("X-Tt-Logid", "(none)")
        print(f"[tts] connected, logid={logid}", file=sys.stderr)

        # Chunked response: each chunk is a JSON object on its own line (or framed).
        # Per docs, server returns multiple JSON objects separated by newlines/chunks.
        for raw_line in resp.iter_lines(decode_unicode=False):
            if not raw_line:
                continue
            try:
                msg = json.loads(raw_line)
            except json.JSONDecodeError as e:
                print(f"[tts] non-json line ({len(raw_line)}b): {raw_line[:200]!r}", file=sys.stderr)
                continue
            code = msg.get("code", -1)
            if code not in (0, 20000000):
                raise RuntimeError(f"TTS error code={code}: {msg.get('message')}")
            data = msg.get("data")
            if data:
                audio_chunks.append(base64.b64decode(data))
            if msg.get("sentence"):
                sentences.append(msg["sentence"])
            if code == 20000000:
                final_status = msg

    audio_bytes = b"".join(audio_chunks)
    output_path.write_bytes(audio_bytes)

    return {
        "bytes": len(audio_bytes),
        "chunks": len(audio_chunks),
        "sentences": len(sentences),
        "logid": logid,
        "usage": (final_status or {}).get("usage"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    text_grp = parser.add_mutually_exclusive_group(required=True)
    text_grp.add_argument("--text", help="Text to synthesize")
    text_grp.add_argument("--text-file", type=Path, help="Path to UTF-8 text file")
    parser.add_argument("--output", "-o", type=Path, required=True)
    parser.add_argument("--speaker", default="zh_female_vv_uranus_bigtts")
    parser.add_argument(
        "--speech-rate", type=int, default=0,
        help="[-50, 100], 0=1x, 100=2x, -50=0.5x. Default 0.",
    )
    parser.add_argument("--resource-id", default="seed-tts-2.0")
    parser.add_argument("--sample-rate", type=int, default=24000)
    args = parser.parse_args()

    load_dotenv()
    api_key = os.environ.get("VOLCENGINE_API_KEY")
    if not api_key:
        print("VOLCENGINE_API_KEY not set in env or .env", file=sys.stderr)
        return 2

    text = args.text if args.text else args.text_file.read_text(encoding="utf-8").strip()
    if not text:
        print("text is empty", file=sys.stderr)
        return 2

    args.output.parent.mkdir(parents=True, exist_ok=True)

    print(f"[tts] speaker={args.speaker} rate={args.speech_rate} chars={len(text)}", file=sys.stderr)
    info = synthesize(
        text=text,
        api_key=api_key,
        speaker=args.speaker,
        output_path=args.output,
        resource_id=args.resource_id,
        speech_rate=args.speech_rate,
        sample_rate=args.sample_rate,
    )
    print(
        f"[tts] saved {info['bytes']/1024:.1f} KB to {args.output} "
        f"(chunks={info['chunks']}, usage={info['usage']})",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
