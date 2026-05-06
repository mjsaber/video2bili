"""Volcengine BigTTS HTTP Chunked client.

Synthesizes speech from text via the `seed-tts-2.0` resource and writes the
result to disk as MP3 (default) or other audio format. Authentication is
`X-Api-Key`, fetched from the env var `VOLCENGINE_API_KEY` by the CLI layer.
"""
from __future__ import annotations

import base64
import json
import sys
import uuid
from pathlib import Path

import requests

ENDPOINT = "https://openspeech.bytedance.com/api/v3/tts/unidirectional"
DEFAULT_SPEAKER = "zh_female_vv_uranus_bigtts"
DEFAULT_RESOURCE_ID = "seed-tts-2.0"
DEFAULT_SAMPLE_RATE = 24000
DEFAULT_AUDIO_FORMAT = "mp3"


def synthesize(
    text: str,
    api_key: str,
    speaker: str,
    output_path: Path,
    *,
    resource_id: str = DEFAULT_RESOURCE_ID,
    speech_rate: int = 0,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    audio_format: str = DEFAULT_AUDIO_FORMAT,
) -> dict:
    """Stream-synthesize `text` via Volcengine and write audio to `output_path`.

    Returns a dict with `bytes`, `chunks`, `sentences`, `logid`, `usage`. Raises
    `RuntimeError` on non-200 HTTP, non-zero TTS error code, or empty audio.
    """
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
    sentences: list = []
    logid = "(none)"

    with requests.post(ENDPOINT, headers=headers, json=body, stream=True, timeout=120) as resp:
        if resp.status_code != 200:
            raise RuntimeError(
                f"HTTP {resp.status_code}: {resp.text}\n"
                f"X-Tt-Logid: {resp.headers.get('X-Tt-Logid')}"
            )
        logid = resp.headers.get("X-Tt-Logid", "(none)")
        print(f"[tts] connected, logid={logid}", file=sys.stderr)

        for raw_line in resp.iter_lines(decode_unicode=False):
            if not raw_line:
                continue
            try:
                msg = json.loads(raw_line)
            except json.JSONDecodeError:
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
    if not audio_bytes:
        raise RuntimeError("TTS returned no audio chunks")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(audio_bytes)

    return {
        "bytes": len(audio_bytes),
        "chunks": len(audio_chunks),
        "sentences": len(sentences),
        "logid": logid,
        "usage": (final_status or {}).get("usage"),
    }
