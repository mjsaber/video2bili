"""Cut range parsing, normalization, and ASS rewriting for the --cut feature.

See docs/2026-04-12-cut-ranges-design.md for the full specification.
"""
from __future__ import annotations

import re

CutRange = tuple[float, float]


# ---------------------------------------------------------------------------
# Time parsing
# ---------------------------------------------------------------------------

_FRACTIONAL_RE = re.compile(r"^\d+(\.\d+)?$")


def parse_time(text: str) -> float:
    """Parse a time expression into seconds.

    Accepts three formats, disambiguated by the number of ``:`` delimiters:

    - ``SS``          e.g. ``"30"``, ``"30.5"``
    - ``MM:SS``       e.g. ``"1:30"``, ``"2:15.5"``
    - ``HH:MM:SS``    e.g. ``"0:00:30"``, ``"1:05:30.75"``

    Fractional seconds are allowed in all three forms. Negative values are
    rejected. Raises ``ValueError`` on malformed input.
    """
    if not isinstance(text, str) or not text:
        raise ValueError(f"invalid time: {text!r}")
    if text.startswith("-"):
        raise ValueError(f"invalid time (negative): {text!r}")

    parts = text.split(":")
    if len(parts) > 3:
        raise ValueError(
            f"invalid time: {text!r} (too many ':' separators; "
            "expected SS, MM:SS, or HH:MM:SS)"
        )

    for p in parts:
        if not _FRACTIONAL_RE.match(p):
            raise ValueError(f"invalid time component {p!r} in {text!r}")

    try:
        if len(parts) == 1:
            return float(parts[0])
        if len(parts) == 2:
            minutes = int(parts[0])
            seconds = float(parts[1])
            return minutes * 60 + seconds
        # len == 3
        hours = int(parts[0])
        minutes = int(parts[1])
        seconds = float(parts[2])
        return hours * 3600 + minutes * 60 + seconds
    except ValueError as e:
        raise ValueError(f"invalid time: {text!r} ({e})") from e


def parse_cut_range(text: str) -> CutRange:
    """Parse a ``START~END`` cut range string.

    - ``"30~60"`` -> ``(30.0, 60.0)``
    - ``"0:30~1:00"`` -> ``(30.0, 60.0)``
    - ``"00:01:30~00:02:00"`` -> ``(90.0, 120.0)``

    Raises ``ValueError`` if ``~`` is missing or either side is invalid.
    Auto-swap of ``start > end`` is handled later in ``normalize_cuts``.
    """
    if "~" not in text:
        raise ValueError(
            f"cut range must contain '~' separator, got {text!r} "
            "(example: '30~60', '0:30~1:00')"
        )
    left, _, right = text.partition("~")
    start = parse_time(left)
    end = parse_time(right)
    return (start, end)


# ---------------------------------------------------------------------------
# Normalization and keep ranges
# ---------------------------------------------------------------------------

def normalize_cuts(
    ranges: list[CutRange], total_duration: float
) -> list[CutRange]:
    """Normalize a list of cut ranges.

    Steps (in order):
      1. Swap any ``(a, b)`` where ``a > b`` into ``(b, a)``.
      2. Drop zero-width ranges where ``a == b``.
      3. Clip each range to ``[0, total_duration]``; drop any that fall
         entirely outside.
      4. Sort by start time ascending.
      5. Merge overlapping or touching ranges.
      6. Raise ``ValueError`` if the result covers the entire
         ``[0, total_duration]``.
    """
    # 1. Swap
    swapped: list[CutRange] = []
    for a, b in ranges:
        if a > b:
            swapped.append((b, a))
        else:
            swapped.append((a, b))

    # 2. Drop zero-width
    nonzero = [(a, b) for a, b in swapped if a != b]

    # 3. Clip to [0, total_duration]; drop entirely-outside
    clipped: list[CutRange] = []
    for a, b in nonzero:
        if b <= 0 or a >= total_duration:
            continue
        ca = max(0.0, a)
        cb = min(total_duration, b)
        if ca < cb:
            clipped.append((ca, cb))

    # 4. Sort
    clipped.sort(key=lambda r: r[0])

    # 5. Merge overlapping/touching
    merged: list[CutRange] = []
    for a, b in clipped:
        if merged and a <= merged[-1][1]:
            prev_a, prev_b = merged[-1]
            merged[-1] = (prev_a, max(prev_b, b))
        else:
            merged.append((a, b))

    # 6. Validate: not the entire duration
    if (
        len(merged) == 1
        and merged[0][0] <= 0.0
        and merged[0][1] >= total_duration
    ):
        raise ValueError(
            "cut ranges cover the entire video duration "
            f"({total_duration}s); nothing would be kept"
        )

    return merged


def keep_ranges_from_cuts(
    cuts: list[CutRange], total_duration: float
) -> list[CutRange]:
    """Return the complement of ``cuts`` within ``[0, total_duration]``.

    Assumes ``cuts`` is already normalized (sorted, non-overlapping, and
    strictly inside the duration — i.e. the output of ``normalize_cuts``).
    """
    keep: list[CutRange] = []
    cursor = 0.0
    for cs, ce in cuts:
        if cs > cursor:
            keep.append((cursor, cs))
        cursor = max(cursor, ce)
    if cursor < total_duration:
        keep.append((cursor, total_duration))
    return keep


# ---------------------------------------------------------------------------
# ASS rewriting
# ---------------------------------------------------------------------------

_ASS_TIME_RE = re.compile(r"^(\d+):(\d{1,2}):(\d{1,2})(?:\.(\d{1,3}))?$")


def _parse_ass_time(text: str) -> float:
    """Parse an ASS time string (``H:MM:SS.cc``) into seconds."""
    m = _ASS_TIME_RE.match(text.strip())
    if not m:
        raise ValueError(f"invalid ASS time: {text!r}")
    hours = int(m.group(1))
    minutes = int(m.group(2))
    seconds = int(m.group(3))
    frac_str = m.group(4) or "0"
    # ASS centiseconds are two digits, but be lenient with 1-3.
    frac = int(frac_str) / (10 ** len(frac_str))
    return hours * 3600 + minutes * 60 + seconds + frac


def _format_ass_time(seconds: float) -> str:
    """Format a seconds float as an ASS ``H:MM:SS.cc`` string."""
    if seconds < 0:
        seconds = 0.0
    total_cs = round(seconds * 100)
    cs = total_cs % 100
    total_s = total_cs // 100
    s = total_s % 60
    total_m = total_s // 60
    m = total_m % 60
    h = total_m // 60
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _intersects_any_cut(
    d_start: float, d_end: float, cuts: list[CutRange]
) -> bool:
    """Return True iff ``[d_start, d_end)`` touches any cut range at all."""
    for cs, ce in cuts:
        # Half-open interval intersection: [d_start, d_end) ∩ [cs, ce) != ∅
        if d_start < ce and cs < d_end:
            return True
    return False


def _compute_shift(d_start: float, cuts: list[CutRange]) -> float:
    """Total duration of cuts strictly ending at or before ``d_start``."""
    return sum(ce - cs for cs, ce in cuts if ce <= d_start)


def rewrite_ass_for_cuts(ass_text: str, cut_ranges: list[CutRange]) -> str:
    """Drop or shift Dialogue lines based on ``cut_ranges``.

    Rule (α — drop): if a Dialogue's ``[start, end)`` intersects any cut
    range (even by a single frame), drop the line entirely. Otherwise,
    shift both timestamps onto the post-cut timeline by the total duration
    of cuts strictly before ``d_start``.

    All non-Dialogue lines (headers, styles, comments, format lines) are
    passed through unchanged.
    """
    if not cut_ranges:
        return ass_text

    # Preserve original line endings by splitting on \n and rejoining.
    # Bracket the last-line newline if any.
    lines = ass_text.split("\n")
    out: list[str] = []
    for line in lines:
        stripped = line.lstrip()
        if not stripped.startswith("Dialogue:"):
            out.append(line)
            continue

        # Dialogue: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
        # Only the first nine commas are field separators; the Text field
        # itself may contain commas, so we use split with maxsplit.
        prefix, _, rest = line.partition(":")
        # rest starts with " Layer,Start,End,..." — split into 10 fields.
        fields = rest.split(",", 9)
        if len(fields) < 10:
            # Malformed, leave as-is.
            out.append(line)
            continue

        layer = fields[0]
        start_text = fields[1].strip()
        end_text = fields[2].strip()
        try:
            d_start = _parse_ass_time(start_text)
            d_end = _parse_ass_time(end_text)
        except ValueError:
            out.append(line)
            continue

        if _intersects_any_cut(d_start, d_end, cut_ranges):
            # Drop this dialogue entirely.
            continue

        shift = _compute_shift(d_start, cut_ranges)
        new_start = d_start - shift
        new_end = d_end - shift
        new_fields = [
            layer,
            _format_ass_time(new_start),
            _format_ass_time(new_end),
            *fields[3:],
        ]
        out.append(f"{prefix}:" + ",".join(new_fields))

    return "\n".join(out)
