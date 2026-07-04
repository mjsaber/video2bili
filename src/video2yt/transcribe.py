"""Align a written script to an audio file via ffmpeg-derived speech span.

The user has the authoritative script text. ffmpeg silencedetect + ffprobe
give us the speech span [speech_start, speech_end]; the script is sliced
proportionally by char weight into that span.

This assumes constant-pace narration (our input is single-speaker Volcengine
BigTTS with no music bed). For audio with long dramatic pauses the
proportional model drifts — see
docs/superpowers/specs/2026-07-04-transcribe-ffmpeg-span.md (which also
records why the previous whisperx-based span source was replaced: it
deterministically dropped the audio tail on two consecutive productions).
"""

import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

# silencedetect tuning (internal constants — logged on every run so the
# values are observable; see spec "Resolved questions" #3).
_SPAN_NOISE_DB = -35.0
_SPAN_MIN_SILENCE = 0.35
# A trailing silence run counts as "reaches EOF" if its end lands within this
# many seconds of the ffprobe container duration. Wide on purpose: VBR MP3
# header duration and encoder/decoder padding can disagree with the decoded
# stream by well over 50ms.
_EOF_TOLERANCE = 0.25
# A leading silence run counts as "starts at 0" within this tolerance.
_LEAD_TOLERANCE = 0.1


@dataclass
class AlignedSegment:
    """One aligned piece of text with timestamps."""

    text: str
    start: float  # seconds
    end: float  # seconds


def strip_markdown(md: str) -> str:
    """Remove markdown structural characters, keeping prose.

    - Drop fenced code blocks and inline code
    - Drop heading markers, list markers, blockquote markers
    - Drop bold/italic emphasis markers
    - Collapse blank lines
    """
    # Drop fenced code blocks entirely
    md = re.sub(r"```.*?```", " ", md, flags=re.DOTALL)
    # Drop inline code
    md = re.sub(r"`[^`]*`", " ", md)
    # Drop markdown heading markers at line start
    md = re.sub(r"^\s*#{1,6}\s*", "", md, flags=re.MULTILINE)
    # Drop list markers
    md = re.sub(r"^\s*[-*+]\s+", "", md, flags=re.MULTILINE)
    md = re.sub(r"^\s*\d+\.\s+", "", md, flags=re.MULTILINE)
    # Drop blockquote markers
    md = re.sub(r"^\s*>\s*", "", md, flags=re.MULTILINE)
    # Drop bold/italic markers (simple cases)
    md = re.sub(r"(\*\*|__)(.*?)\1", r"\2", md)
    md = re.sub(r"(\*|_)(.*?)\1", r"\2", md)
    # Collapse whitespace
    md = re.sub(r"\n{2,}", "\n", md)
    return md.strip()


# Sentence-ending punctuation — CJK + Latin. Latin "." only counts when
# followed by whitespace or end-of-string (avoids splitting on decimals).
_SENTENCE_END = re.compile(r"([。！？!?]+|\.(?=\s|$))")

# Secondary punctuation, used by `split_long_sentences` to break up sentences
# that exceed `max_block_chars` (semicolons, ideographic comma, full-width comma,
# Latin semicolon, Latin comma).
_SECONDARY_PUNCT = re.compile(r"([；，、;,]+)")


def split_into_sentences(text: str) -> list[str]:
    """Split prose into sentences by punctuation (CJK + Latin).

    The trailing punctuation stays attached to the sentence. Empty pieces are
    dropped. If the input has no terminal punctuation the whole thing is
    returned as a single sentence.
    """
    text = re.sub(r"[ \t]+", " ", text)
    parts = _SENTENCE_END.split(text)
    sentences: list[str] = []
    buf = ""
    for p in parts:
        if _SENTENCE_END.fullmatch(p):
            buf += p
            if buf.strip():
                sentences.append(buf.strip())
            buf = ""
        else:
            buf += p
    if buf.strip():
        sentences.append(buf.strip())
    return sentences


def split_long_sentences(sentences: list[str], max_chars: int) -> list[str]:
    """Split any sentence longer than `max_chars` at secondary punctuation.

    Sentence-end punctuation (。！？) is the primary splitter (`split_into_sentences`).
    For long-form scripts where the writer used semicolons/commas instead of periods,
    the resulting SRT block can be too long for one screen. This pass cuts those
    sentences at `；，、;,` while leaving short sentences untouched.

    `max_chars <= 0` disables the pass (preserves legacy behaviour). If a sentence
    exceeds the limit but contains no secondary punctuation, it is returned intact —
    we don't break mid-word.
    """
    if max_chars <= 0:
        return sentences

    out: list[str] = []
    for s in sentences:
        if len(s) <= max_chars:
            out.append(s)
            continue
        chunks: list[str] = []
        buf = ""
        for part in _SECONDARY_PUNCT.split(s):
            buf += part
            if _SECONDARY_PUNCT.fullmatch(part):
                if buf.strip():
                    chunks.append(buf.strip())
                buf = ""
        if buf.strip():
            chunks.append(buf.strip())
        out.extend(chunks if chunks else [s])
    return out


def _count_effective_chars(text: str) -> int:
    """Count characters relevant for speech-pacing.

    CJK characters count as 1 unit each; Latin words count as ~2 units each
    (rough heuristic for how long a typical English word takes to say relative
    to a single Chinese syllable).
    """
    cjk = len(re.findall(r"[\u4e00-\u9fff]", text))
    latin_words = len(re.findall(r"\b[A-Za-z]+\b", text))
    return cjk + latin_words * 2


def align_script_to_span(
    script_sentences: list[str],
    speech_start: float,
    speech_end: float,
) -> list[AlignedSegment]:
    """Assign (start, end) times to each script sentence.

    Strategy: proportional allocation. Compute the total char-weight of all
    sentences, then map each sentence to a proportional slice of
    [speech_start, speech_end].

    Assumes the reader followed the script from start to end at constant pace
    without large skips or insertions (true for TTS narration). Interior
    pauses are absorbed by the proportional model.
    """
    if not script_sentences:
        raise ValueError("no script sentences to align")

    total_duration = speech_end - speech_start
    if total_duration <= 0:
        raise ValueError(
            f"word timestamps span zero duration: {speech_start} to {speech_end}"
        )

    weights = [_count_effective_chars(s) for s in script_sentences]
    total_weight = sum(weights)
    if total_weight == 0:
        raise ValueError("script sentences contain no alignable characters")

    segments: list[AlignedSegment] = []
    cursor = speech_start
    for sentence, weight in zip(script_sentences, weights):
        duration = total_duration * (weight / total_weight)
        segments.append(
            AlignedSegment(text=sentence, start=cursor, end=cursor + duration)
        )
        cursor += duration
    return segments


def align_script_to_words(
    script_sentences: list[str],
    word_timestamps: list[tuple[str, float, float]],
) -> list[AlignedSegment]:
    """DEPRECATED shim over :func:`align_script_to_span`.

    Kept for one release for API compatibility with the old whisperx-based
    interface: consumes a word-timestamp list but only ever used
    ``word_timestamps[0].start`` and ``word_timestamps[-1].end``.
    """
    if not word_timestamps:
        raise ValueError("no word timestamps provided (whisperx returned no words)")
    return align_script_to_span(
        script_sentences,
        speech_start=word_timestamps[0][1],
        speech_end=word_timestamps[-1][2],
    )


def _format_srt_time(seconds: float) -> str:
    """Format seconds as SRT timestamp: HH:MM:SS,mmm"""
    if seconds < 0:
        seconds = 0
    total_ms = round(seconds * 1000)
    hours = total_ms // 3_600_000
    minutes = (total_ms % 3_600_000) // 60_000
    secs = (total_ms % 60_000) // 1000
    ms = total_ms % 1000
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def segments_to_srt(segments: list[AlignedSegment]) -> str:
    """Render aligned segments as an SRT file."""
    lines: list[str] = []
    for i, seg in enumerate(segments, start=1):
        lines.append(str(i))
        lines.append(
            f"{_format_srt_time(seg.start)} --> {_format_srt_time(seg.end)}"
        )
        lines.append(seg.text)
        lines.append("")
    return "\n".join(lines)


_SILENCE_START = re.compile(r"silence_start:\s*(-?[0-9.]+(?:[eE][+-]?\d+)?)")
_SILENCE_END = re.compile(r"silence_end:\s*(-?[0-9.]+(?:[eE][+-]?\d+)?)")


def _run_silencedetect(
    audio_path: Path, noise_db: float, min_silence: float
) -> str:
    """One ffmpeg decode pass; returns stderr (where silencedetect logs).

    Explicit mono downmix so stereo channel imbalance cannot skew detection.
    Isolated so tests can monkeypatch this subprocess boundary.
    """
    result = subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-nostats",
            "-i", str(audio_path),
            "-af",
            (
                "aformat=channel_layouts=mono,"
                f"silencedetect=n={noise_db}dB:d={min_silence}"
            ),
            "-f", "null", "-",
        ],
        check=True, capture_output=True, text=True,
    )
    return result.stderr


def detect_speech_span(
    audio_path: Path,
    noise_db: float = _SPAN_NOISE_DB,
    min_silence: float = _SPAN_MIN_SILENCE,
) -> tuple[float, float]:
    """Return (speech_start, speech_end) via ffmpeg silencedetect + ffprobe.

    - speech_start: end of a leading silence run (one starting within
      ``_LEAD_TOLERANCE`` of 0), else 0.0.
    - speech_end: start of a trailing silence run (one whose end is missing —
      file ends silent — or lands within ``_EOF_TOLERANCE`` of the container
      duration), else the container duration. Never truncated below a
      parsed value by a shorter metadata duration.
    - raises ValueError if the detected span is degenerate (< 0.5s), e.g. the
      whole file is silence.
    """
    from video2yt import validate

    info = validate.probe(audio_path)
    if not info.has_audio:
        raise ValueError(f"audio file has no audio stream: {audio_path}")
    duration = info.duration

    stderr = _run_silencedetect(audio_path, noise_db, min_silence)

    # Pair silence_start/silence_end lines in order; a final start without a
    # matching end means the file ends inside a silence run.
    events: list[tuple[float, float | None]] = []
    pending_start: float | None = None
    for line in stderr.splitlines():
        m = _SILENCE_START.search(line)
        if m:
            pending_start = float(m.group(1))
            continue
        m = _SILENCE_END.search(line)
        if m and pending_start is not None:
            events.append((pending_start, float(m.group(1))))
            pending_start = None
    if pending_start is not None:
        events.append((pending_start, None))

    speech_start = 0.0
    speech_end = duration

    if events:
        first_start, first_end = events[0]
        if first_start <= _LEAD_TOLERANCE and first_end is not None:
            speech_start = first_end

        last_start, last_end = events[-1]
        reaches_eof = last_end is None or last_end >= duration - _EOF_TOLERANCE
        if reaches_eof:
            # For an all-silence file this drives the span degenerate
            # (speech_end <= speech_start) and the guard below raises.
            speech_end = last_start

    if speech_end - speech_start < 0.5:
        raise ValueError(
            f"audio appears to be silent (detected speech span "
            f"{speech_start:.2f}-{speech_end:.2f}s in {audio_path})"
        )

    print(
        f"[transcribe] speech span {speech_start:.2f}-{speech_end:.2f}s "
        f"of {duration:.2f}s (silencedetect n={noise_db}dB d={min_silence}s)",
        file=sys.stderr,
    )
    return speech_start, speech_end


def transcribe_script(
    audio_path: Path,
    script_text: str,
    language: str = "zh",
    model_name: str = "small",
    device: str = "cpu",
    max_block_chars: int = 0,
) -> str:
    """End-to-end: align audio + script -> SRT string.

    `max_block_chars > 0` enables a secondary split: any sentence longer than
    that many characters is cut at semicolons/commas (`；，、;,`). 0 = legacy
    behavior (split on `。！？` only).

    `language` / `model_name` / `device` are DEPRECATED and ignored (whisperx
    leftovers, kept one release for API compatibility — the span now comes
    from ffmpeg silencedetect).
    """
    del language, model_name, device  # deprecated, ignored

    prose = strip_markdown(script_text)
    sentences = split_into_sentences(prose)
    sentences = split_long_sentences(sentences, max_block_chars)
    if not sentences:
        raise ValueError("script has no sentences after markdown stripping")

    speech_start, speech_end = detect_speech_span(audio_path)
    segments = align_script_to_span(sentences, speech_start, speech_end)
    return segments_to_srt(segments)
