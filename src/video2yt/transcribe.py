"""Align a written script to an audio file using whisperx forced alignment.

The user has the authoritative script text. whisperx gives us audio-derived
word-level timestamps. We use the timestamps to slice the script proportionally.
"""

import re
from dataclasses import dataclass
from pathlib import Path


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


def align_script_to_words(
    script_sentences: list[str],
    word_timestamps: list[tuple[str, float, float]],
) -> list[AlignedSegment]:
    """Assign (start, end) times to each script sentence.

    Strategy: proportional allocation. Compute the total char-weight of all
    sentences, then map each sentence to a proportional slice of
    [first_word.start, last_word.end].

    Assumes the reader followed the script from start to end without large
    skips or insertions. If they did improvise, results will drift — a future
    upgrade could use difflib anchors between whisperx's ASR text and the
    script to recalibrate between anchors.
    """
    if not word_timestamps:
        raise ValueError("no word timestamps provided (whisperx returned no words)")
    if not script_sentences:
        raise ValueError("no script sentences to align")

    total_start = word_timestamps[0][1]
    total_end = word_timestamps[-1][2]
    total_duration = total_end - total_start
    if total_duration <= 0:
        raise ValueError(
            f"word timestamps span zero duration: {total_start} to {total_end}"
        )

    weights = [_count_effective_chars(s) for s in script_sentences]
    total_weight = sum(weights)
    if total_weight == 0:
        raise ValueError("script sentences contain no alignable characters")

    segments: list[AlignedSegment] = []
    cursor = total_start
    for sentence, weight in zip(script_sentences, weights):
        duration = total_duration * (weight / total_weight)
        segments.append(
            AlignedSegment(text=sentence, start=cursor, end=cursor + duration)
        )
        cursor += duration
    return segments


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


def run_whisperx_alignment(
    audio_path: Path,
    language: str = "zh",
    model_name: str = "small",
    device: str = "cpu",
) -> list[tuple[str, float, float]]:
    """Run whisperx ASR + phoneme-level forced alignment.

    Returns a list of (word, start, end) tuples covering the audio.

    Isolated in its own function so tests can monkeypatch this boundary; real
    calls hit whisperx and are slow on first run (model download).
    """
    import whisperx

    audio = whisperx.load_audio(str(audio_path))

    model = whisperx.load_model(
        model_name, device, compute_type="int8", language=language
    )
    result = model.transcribe(audio, language=language)
    segments = result.get("segments", [])
    if not segments:
        raise RuntimeError(
            f"whisperx ASR returned no segments for {audio_path}; audio may be silent"
        )

    align_model, metadata = whisperx.load_align_model(
        language_code=language, device=device
    )
    aligned = whisperx.align(
        segments,
        align_model,
        metadata,
        audio,
        device,
        return_char_alignments=False,
    )

    word_tuples: list[tuple[str, float, float]] = []
    for seg in aligned.get("segments", []):
        for w in seg.get("words", []):
            word = w.get("word") or w.get("text") or ""
            start = w.get("start")
            end = w.get("end")
            if word and start is not None and end is not None:
                word_tuples.append((str(word).strip(), float(start), float(end)))

    if not word_tuples:
        raise RuntimeError(
            f"whisperx alignment produced no word-level timestamps for {audio_path}"
        )
    return word_tuples


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
    """
    prose = strip_markdown(script_text)
    sentences = split_into_sentences(prose)
    sentences = split_long_sentences(sentences, max_block_chars)
    if not sentences:
        raise ValueError("script has no sentences after markdown stripping")

    word_timestamps = run_whisperx_alignment(
        audio_path=audio_path,
        language=language,
        model_name=model_name,
        device=device,
    )
    segments = align_script_to_words(sentences, word_timestamps)
    return segments_to_srt(segments)
