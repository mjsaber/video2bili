"""CLI for video2yt-tts: synthesize speech via Volcengine BigTTS."""

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from requests.exceptions import RequestException

from video2yt import tts


def _log(msg: str) -> None:
    print(f"[video2yt-tts] {msg}", file=sys.stderr)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="video2yt-tts",
        description=(
            "Synthesize speech with Volcengine BigTTS. Reads VOLCENGINE_API_KEY from the "
            "environment (or .env). Default voice is the female `vv_uranus` BigTTS speaker."
        ),
    )
    text_grp = parser.add_mutually_exclusive_group(required=True)
    text_grp.add_argument("--text", help="Inline text to synthesize.")
    text_grp.add_argument("--text-file", type=Path, help="Path to a UTF-8 text file.")
    parser.add_argument("-o", "--output", type=Path, required=True)
    parser.add_argument("--speaker", default=tts.DEFAULT_SPEAKER)
    parser.add_argument(
        "--speech-rate", type=int, default=0,
        help="[-50, 100], 0=1x, 100=2x, -50=0.5x. Default 0.",
    )
    parser.add_argument("--resource-id", default=tts.DEFAULT_RESOURCE_ID)
    parser.add_argument("--sample-rate", type=int, default=tts.DEFAULT_SAMPLE_RATE)
    parser.add_argument("--audio-format", default=tts.DEFAULT_AUDIO_FORMAT)
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> Path:
    load_dotenv()
    api_key = os.environ.get("VOLCENGINE_API_KEY")
    if not api_key:
        raise ValueError("VOLCENGINE_API_KEY not set in env or .env")

    if args.text:
        text = args.text
    else:
        if not args.text_file.exists():
            raise FileNotFoundError(f"text file not found: {args.text_file}")
        text = args.text_file.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError("text is empty")

    _log(f"speaker={args.speaker} rate={args.speech_rate} chars={len(text)}")
    info = tts.synthesize(
        text=text,
        api_key=api_key,
        speaker=args.speaker,
        output_path=args.output,
        resource_id=args.resource_id,
        speech_rate=args.speech_rate,
        sample_rate=args.sample_rate,
        audio_format=args.audio_format,
    )
    _log(
        f"saved {info['bytes']/1024:.1f} KB to {args.output} "
        f"(chunks={info['chunks']}, usage={info['usage']})"
    )
    return args.output


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        run(args)
        return 0
    except (ValueError, FileNotFoundError, RuntimeError) as e:
        _log(f"error: {e}")
        return 1
    except RequestException as e:
        _log(f"network error: {e}")
        return 1
