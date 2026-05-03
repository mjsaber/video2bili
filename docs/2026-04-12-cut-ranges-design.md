# Cut Ranges Design (`--cut`)

**Date**: 2026-04-12
**Status**: Approved, ready for implementation

## 1. Goal

Allow users to specify one or more `START~END` time ranges to be **removed** from the final video. Both video/audio **and** danmaku in those ranges are removed; the remaining segments are concatenated into a single seamless output with danmaku timestamps re-mapped to the new (shorter) timeline.

## 2. CLI

### 2.1 `--cut` flag

```
--cut START~END
```

- Repeatable: `--cut 30~60 --cut 2:15~2:45 --cut 5:00~6:30`
- Separator is `~` (tilde, U+007E)
- Each `START` and `END` is a time expression in one of three formats:
  - `SS` (seconds): `30`, `90.5`, `1815.3`
  - `MM:SS`: `0:30`, `5:12.5`
  - `HH:MM:SS`: `0:00:30`, `1:10:05.25`

The format is chosen by the number of `:` delimiters (0 / 1 / 2). Fractional seconds are allowed in all three forms.

### 2.2 Examples

```bash
uv run video2yt <url> --cut 37~59
uv run video2yt <url> --cut 0:30~1:00 --cut 5:00~6:30
uv run video2yt <url> --cut 00:00:30~00:00:45 --cut 00:02:10~00:02:30
```

### 2.3 Interaction with `--preview-seconds`

- **Cut is applied first, in the original source timeline**. The source is cut, then the remaining segments are concatenated, producing a new timeline.
- **Preview is applied second, on the new timeline**. `--preview-seconds 60` with `--cut 30~60` on a 300-second source means: remove 30-60 from the source (yielding a 270-second clip), then keep only the first 60 seconds of that → output is 60 seconds, containing the original 0-30 plus the original 60-90.

## 3. Time parsing

Function: `cuts.parse_time(text: str) -> float`

- `"30"` → `30.0`
- `"30.5"` → `30.5`
- `"1:30"` → `90.0`
- `"1:30.25"` → `90.25`
- `"1:05:30"` → `3930.0`
- `"1:05:30.75"` → `3930.75`
- `"0:00:30"` → `30.0`

Error on malformed input: `ValueError` with clear message.

## 4. Cut range parsing

Function: `cuts.parse_cut_range(text: str) -> tuple[float, float]`

- `"30~60"` → `(30.0, 60.0)`
- `"0:30~1:00"` → `(30.0, 60.0)`
- `"00:01:30~00:02:00"` → `(90.0, 120.0)`

Error cases:
- Missing `~`: `ValueError("cut range must contain '~' separator, got ...")`
- Invalid time on either side: propagate the `parse_time` error
- `start > end` is **auto-swapped** (not an error)
- `start == end`: silently dropped during normalization (zero-width cut)
- `start < 0`: `ValueError`

## 5. Normalization

Function: `cuts.normalize_cuts(ranges: list[tuple[float, float]], total_duration: float) -> list[tuple[float, float]]`

Transformation steps (in order):
1. **Swap** any `(a, b)` where `a > b` into `(b, a)`
2. **Drop zero-width** ranges where `a == b`
3. **Clip** each range to `[0, total_duration]`; drop ranges that fall entirely outside
4. **Sort** by start time ascending
5. **Merge** overlapping or touching ranges
6. **Validate**: raise `ValueError` if the result covers the entire `[0, total_duration]` (nothing would be kept)

Output: a sorted, non-overlapping list of ranges within `[0, total_duration]`.

## 6. Keep ranges

Function: `cuts.keep_ranges_from_cuts(cuts: list[tuple[float, float]], total_duration: float) -> list[tuple[float, float]]`

Given the normalized cut list, returns the **complement** within `[0, total_duration]`.

Example:
- `cuts = [(30, 60), (135, 165)]`, `total_duration = 1260`
- → `[(0, 30), (60, 135), (165, 1260)]`

Edge cases:
- `cuts = []` → `[(0, total_duration)]` (no cut)
- `cuts = [(0, 30)]` → `[(30, total_duration)]` (cut at the start)
- `cuts = [(1230, 1260)]` → `[(0, 1230)]` (cut at the end)
- `cuts = [(0, 1260)]` → already caught by `normalize_cuts` as invalid

## 7. ASS rewriting (boundary handling: α — drop)

Function: `cuts.rewrite_ass_for_cuts(ass_text: str, cut_ranges: list[tuple[float, float]]) -> str`

**Rule**: for each `Dialogue:` line with times `(d_start, d_end)`:

- If `[d_start, d_end)` **intersects** any cut range in `cut_ranges` (even by a single frame) → **drop** the line entirely.
- Otherwise → **shift** the timestamps to the post-cut timeline. The shift amount is `sum of cut durations that are entirely before d_start`.

### 7.1 Why "α drop" instead of clipping or shifting kept-fragments

- **Simple to reason about**: every kept dialogue is fully within a single keep range; no partial displays, no cross-range weirdness.
- **Avoids "dialogue that spans a cut" displaying for a strange fraction of time**.
- **Minimal information loss in practice**: dialogues typically last 5-15 seconds; the fraction that happen to straddle a cut boundary is small.

### 7.2 Shift computation

For a dialogue starting at `d_start` (which is known to be in a keep range, i.e., not inside any cut):

```python
shift = sum(cut_end - cut_start for cut_start, cut_end in cut_ranges if cut_end <= d_start)
new_start = d_start - shift
new_end = d_end - shift
```

(We use `cut_end <= d_start` because the dialogue is outside this cut, so the cut must be strictly earlier.)

### 7.3 ASS time format

ASS uses `H:MM:SS.cc` (hours, minutes, seconds, centiseconds). The rewriter must:
- Parse the `Dialogue:` line's `Start` and `End` fields using this format
- Compute new times in seconds
- Format the result back to `H:MM:SS.cc`

Helpers:
- `_parse_ass_time("0:01:30.25") -> 90.25`
- `_format_ass_time(90.25) -> "0:01:30.25"`

### 7.4 Non-Dialogue lines

All lines that are not `Dialogue:` (including `[Script Info]`, `[V4+ Styles]`, `Format:`, `Comment:`, etc.) are passed through unchanged.

## 8. ffmpeg filter_complex for burn

Function: `burn._build_filter_complex(keep_ranges: list[tuple[float, float]], ass_filename: str) -> str`

For `keep_ranges = [(s0,e0), (s1,e1), ..., (sN-1, eN-1)]`:

```
[0:v]trim=s0:e0,setpts=PTS-STARTPTS[v0];
[0:v]trim=s1:e1,setpts=PTS-STARTPTS[v1];
...
[0:a]atrim=s0:e0,asetpts=PTS-STARTPTS[a0];
[0:a]atrim=s1:e1,asetpts=PTS-STARTPTS[a1];
...
[v0][a0][v1][a1]...concat=n=N:v=1:a=1[cv][ca];
[cv]subtitles=f='<ass_filename>'[outv]
```

When there are no cuts (`keep_ranges = [(0, duration)]`), this degenerates to the equivalent of the current `-vf "subtitles=f='...'"` flow; in that case we keep the current simple path (`_build_filter_complex` is NOT called) to avoid unnecessary filter_complex overhead.

### 8.1 Full ffmpeg invocation (with cuts)

```
ffmpeg -y -i <video> \
  -filter_complex "<filter_complex>" \
  -map "[outv]" -map "[ca]" \
  -c:a aac -b:a 160k \
  -c:v libx264 -preset medium -crf 20 \
  [-t <preview_seconds>] \
  <output>
```

Notes:
- `-c:a aac` (not `copy`): audio must be re-encoded because `atrim` produces a new stream; `copy` would fail.
- `-t` (preview seconds) is applied as an **output** option after the filter_complex, so it clamps the concatenated result.
- `cwd=temp_dir` is still used because `subtitles=f='<filename>'` still lives inside the filter_complex and still has the same path escaping concerns.

### 8.2 When there are NO cuts

The existing simple command is used:

```
ffmpeg -y -i <video> -vf "subtitles=f='<ass>'" \
  -c:a copy -c:v libx264 -preset medium -crf 20 \
  [-t <preview_seconds>] \
  <output>
```

The `-c:a copy` branch is faster (no audio re-encode). We use it whenever `cut_ranges` is empty (i.e., `keep_ranges == [(0, source.duration)]`).

## 9. `check_output` duration

Update the expected duration computation in `cli.run()`:

```python
kept_duration = sum(end - start for start, end in keep_ranges)
expected_duration = (
    min(float(args.preview_seconds), kept_duration)
    if args.preview_seconds is not None
    else kept_duration
)
validate.check_output(source_info, output_info, expected_duration=expected_duration)
```

No change to `validate.check_output` itself.

## 10. CLI surface

Add to `parse_args`:

```python
parser.add_argument(
    "--cut", action="append", default=[], metavar="START~END",
    help=(
        "Time range to REMOVE from the output. Repeatable. "
        "START/END accept SS, MM:SS, or HH:MM:SS with optional "
        "fractional seconds. Examples: "
        "--cut 30~60, --cut 0:30~1:00, --cut 00:01:30~00:02:00."
    ),
)
```

`run()` processes the list:

```python
raw_cuts = [cuts.parse_cut_range(s) for s in args.cut]
cut_ranges = cuts.normalize_cuts(raw_cuts, total_duration=source_info.duration)
keep_ranges = cuts.keep_ranges_from_cuts(cut_ranges, total_duration=source_info.duration)
```

If the user passed any `--cut`, log the original list, the normalized list, and the total removed duration for debugging.

## 11. Error handling

- Malformed cut expression → `ValueError` from `parse_cut_range`, caught by `cli.main()`, printed clearly, exit 1
- Cut ranges cover the full video → `ValueError` from `normalize_cuts`, same handling
- ffmpeg filter_complex failure (malformed, e.g., impossible trim) → `subprocess.CalledProcessError`, stderr printed

## 12. Files touched

### New
- `src/video2yt/cuts.py` — parsing, normalization, keep_ranges, ASS rewriting
- `tests/test_cuts.py` OR extend `tests/test_smoke.py` (stick with one file per project convention)

### Modified
- `src/video2yt/burn.py` — new `render(cut_ranges=None, ...)` path with filter_complex
- `src/video2yt/cli.py` — new `--cut` arg, integration in `run()`, new logging
- `tests/test_smoke.py` — many new tests

### Unchanged
- `src/video2yt/validate.py` — already supports `expected_duration`
- `src/video2yt/download.py` — no change
- ffprobe probes — no change

## 13. Tests (TDD)

### 13.1 Parsing (`parse_time`, `parse_cut_range`)
- Valid SS, MM:SS, HH:MM:SS, fractional
- Invalid: non-numeric, negative, missing separator
- Cut range: valid, missing `~`, start > end (auto-swap)

### 13.2 Normalization (`normalize_cuts`)
- Swap
- Drop zero-width
- Clip to duration
- Sort
- Merge overlapping (abutting: `(10,20) + (20,30)` → `(10,30)`; overlapping: `(10,30) + (20,40)` → `(10,40)`)
- Error on full coverage

### 13.3 Keep ranges (`keep_ranges_from_cuts`)
- Empty cuts → `[(0, D)]`
- Cut in middle → two keep ranges
- Cut at start → one keep starting after
- Cut at end → one keep ending before
- Multiple non-overlapping cuts → N+1 keep ranges

### 13.4 ASS rewriting (`rewrite_ass_for_cuts`)
- No-op when no cuts
- Dialogue inside a cut → dropped
- Dialogue inside a keep range after one cut → shifted by cut duration
- Dialogue straddling a cut boundary (partially in a cut) → dropped
- Multiple cuts → correct cumulative shift
- Non-Dialogue lines preserved

### 13.5 burn filter_complex
- `_build_filter_complex(keep_ranges, ass_filename)` returns the expected string
- `burn.render` with `cut_ranges=None` uses the simple path (no filter_complex)
- `burn.render` with `cut_ranges=[(30,60)]` builds filter_complex and uses `-c:a aac`

### 13.6 CLI integration
- `parse_args` accepts `--cut` repeatable, stores in `args.cut` as list[str]
- `run()` parses, normalizes, computes keep_ranges, passes to `burn.render` and ass rewriter
- `check_output` called with `expected_duration = sum(keep_ranges)` (or min with preview_seconds)

## 14. Docs

After code is done:

- `README.md`: add `--cut` usage section with examples; document interaction with `--preview-seconds`
- `CLAUDE.md`: add a brief reference to the cut feature under "Commands" or a new "Feature overview" section; also backfill `--codec`, `--preview-seconds`, `--font-face`, `--font-size` which aren't yet documented there

## 15. Acceptance test

Run against `https://www.bilibili.com/video/BV1vTQMB3ET9/` with:

```bash
uv run video2yt \
  "https://www.bilibili.com/video/BV1vTQMB3ET9/" \
  --preview-seconds 60 \
  --cut 37~59 \
  --keep-temp
```

Expected behavior:
- Preview captures the first 60 seconds of the **cut** timeline
- `--cut 37~59` removes 22 seconds in the source
- Output duration: min(60, source_duration - 22). If source is much longer than 60s, output is 60s.
- Timeline mapping for the output:
  - Output [0s, 37s] = source [0s, 37s]
  - Output [37s, 60s] = source [59s, 82s]
- No danmaku from source [37, 59] appears in the output
- Danmaku from source [59, 82] appears at output [37, 60]
