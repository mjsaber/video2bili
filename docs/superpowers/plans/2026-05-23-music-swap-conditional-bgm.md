# Plan: Music-Swap — Debug Metadata + Conditional Sparse BGM

Date: 2026-05-23
Driver: Bleed observed in the 夜吹 segment around 7:00-8:30 (original BGM
leaked through Demucs into the final mix). Two requirements:

1. **Permanent debug metadata** — every music-swap run writes a sidecar
   recording enough info to retroactively diagnose bleed without re-running.
2. **Conditional sparse BGM** — current pipeline lays the CC-BY bed across
   the entire video. New behavior: detect which ranges of the original
   carried copyrighted music ("needs-replacement" regions). Lay BGM only over
   those ranges, AND only if a needs-replacement region is ≥5s continuous.
   Non-music regions keep the original game SFX so the viewing experience is
   richer.

This is a meaningful shift away from "Approach A (sacrifice SFX everywhere)"
toward something closer to "Approach C (surgical replacement, preserve SFX
elsewhere)". The 2026-05-20 design spec should be updated when this lands.

## Decisions locked 2026-05-23

- **Music region <5s: strip only, don't replace.** Demucs no_vocals for that
  short range is zeroed out (so the copyrighted music IS removed), but the
  new sparse bed does NOT cover that range either. The result is just gated
  vocals (voice only) for those brief stretches — no original music, no new
  BGM. Trades a momentary audio "hole" for full claim protection without
  jarring 5s bed-stubs.
- **Three regime types for each second of the timeline**:
  | Type | Original music | <5s | Output |
  |---|---|---|---|
  | Music ≥5s | YES | — | gated vocals + new sparse bed (no_vocals zeroed) |
  | Music <5s | YES | YES | gated vocals only (no_vocals zeroed, no bed) |
  | No music | NO | — | gated vocals + original no_vocals (SFX preserved) |
- **Boundary fades** — 0.5s linear fades on both edges of each bed segment.
- **Music detection metric** — Stage 2 starts with sustained RMS + spectral
  flatness on no_vocals. Upgrade only if it misclassifies on the 夜吹 segment.

## Stage 1: Debug metadata sidecar
**Goal**: Every `video2yt-music-swap` run writes
`<output>_music_swap_debug.json` next to the output MP4, capturing enough
information to diagnose bleed and gating issues offline.

**Success criteria**:
- File exists at the expected path after every successful run.
- Contains: run config (model, device, seed, music_volume, duck, gate
  threshold/release), input/output paths, total duration, music-bed timeline
  (per-track start/end seconds in the bed), and per-30s chunk loudness for
  `vocals.wav` and `no_vocals.wav` (integrated LUFS via ffmpeg `astats`/
  `ebur128`).
- Schema documented inline in `music_swap.py` so future agents can extend it.

**Tests**:
- `test_swap_debug_sidecar_written` — render() writes the JSON to the
  expected sidecar path with all required keys.
- `test_swap_debug_sidecar_contains_track_timeline` — bed timeline matches
  `select_sequence` output and is monotonically ascending.
- `test_swap_debug_sidecar_contains_chunk_loudness` — loudness arrays have
  the expected length (ceil(duration/30)) for both stems.

**Status**: Not Started

## Stage 2: Music-presence detection on the no_vocals stem
**Goal**: Given Demucs's `no_vocals.wav` (= original music + SFX), classify
each 1s window as "has music" / "no music". Output: a list of music-active
intervals.

**Method (starting point — refine if it misclassifies on real data)**:
1. RMS in dB over a 1s sliding window, hop 0.25s.
2. Spectral flatness over the same window (music ≈ low flatness, SFX/silence
  ≈ high flatness or low energy).
3. A window is "music" if `rms > -45 dBFS AND spectral_flatness < 0.3`.
4. Merge consecutive "music" windows; require ≥5s continuous to keep.
5. Apply a 1s tolerance gap-fill so a single SFX hit doesn't split a music
  region.

**Success criteria**:
- On the 夜吹 segment, the detected music intervals **include** the bleed
  region around 7:00-8:30.
- On the same segment, intervals **exclude** at least one verified SFX-only
  stretch (need user to identify one for ground truth).
- The function returns `list[tuple[float, float]]` (start, end) in seconds.

**Tests**:
- `test_detect_music_intervals_finds_continuous_music` — synthetic input:
  10s of sine wave, returns one interval covering it.
- `test_detect_music_intervals_skips_short_bursts` — synthetic: 3s sine +
  10s silence + 3s sine → empty list (no interval ≥5s).
- `test_detect_music_intervals_merges_via_gap_fill` — 4s sine + 0.5s gap +
  3s sine → one 7.5s interval.
- `test_detect_music_intervals_ignores_silence` — pure silence → empty list.

**Status**: Not Started

## Stage 3: Sparse music bed (only over detected music intervals)
**Goal**: Replace `build_music_bed` with a variant that produces a music bed
where audio is non-silent ONLY during the detected music intervals; the rest
is digital silence. Crossfades at each edge.

**Method**:
1. `build_sparse_music_bed(tracks, intervals, total_duration, bed_path)`:
   - For each interval `(start, end)`, take a slice from the CC-BY track
     sequence to fill `(end - start)` seconds.
   - Apply 0.5s `afade` in/out at the interval edges.
   - Concatenate intervals with silence padding via `aevalsrc=0` filler.
2. Track sequencing should still draw from the manifest seed-deterministic
   order, but only consume the portion needed for the active intervals
   (not the full video duration).

**Success criteria**:
- Output WAV has loud content only inside the detected intervals (silencedetect
  confirms silence regions match the gap between intervals).
- Total duration = `total_duration` (full video length, padded with silence).
- Edges have 0.5s fades (no pops).

**Tests**:
- `test_build_sparse_music_bed_silence_outside_intervals` — bed is silent
  outside intervals (silencedetect output matches expected gaps).
- `test_build_sparse_music_bed_full_length` — output duration = total_duration.
- `test_build_sparse_music_bed_empty_intervals` — no music intervals → bed
  is pure silence (full duration).
- `test_build_sparse_music_bed_single_interval` — one 10s interval at 30-40s
  in a 60s video → silent 0-29.5s, music 29.5-40.5s (with fades), silent
  40.5-60s.

**Status**: Not Started

## Stage 4: Preserve no_vocals (SFX) outside music intervals
**Goal**: In the final mix, the parts of the video where there was NO music
should retain the original `no_vocals` stem (game SFX, ambience) at the
original level. The parts WITH music ≥5s get the new sparse bed; the parts
with music <5s get nothing (just voice).

**Method**:
1. Run detection twice: get all music intervals (any duration), then split
   into `long_intervals` (≥5s, will be covered by bed) and `short_intervals`
   (<5s, no bed but still strip from no_vocals).
2. Generate `no_vocals_masked.wav`: `no_vocals.wav` with **all** music
   intervals (long AND short) zeroed out — protects against claim from any
   detected music regardless of duration.
3. Generate `sparse_bed.wav`: only covers `long_intervals` (Stage 3).
4. Three-way mix in `mix()`:
   - vocals_gated (full duration) — voice
   - sparse_bed (full duration, silent outside long_intervals) — new BGM
   - no_vocals_masked (full duration, silent inside ALL music intervals) — SFX
5. amix=inputs=3:duration=first. Voice still ducks the new bed via
   sidechain; no_vocals is left alone (no ducking — SFX is meant to punctuate).

**Success criteria**:
- Spot-check at a known SFX-only timestamp (e.g., combat sound): the SFX is
  audible in the final mix.
- Spot-check at a music-bleed timestamp (7:00-8:30 on 夜吹): the original
  music is gone, replaced by new bed.
- Voice is still ducked under the new bed where new bed is active.

**Tests**:
- `test_three_way_mix_includes_all_stems` — amix command has 3 inputs.
- `test_no_vocals_masked_zeroes_music_intervals` — given intervals
  `[(10, 20)]`, the no_vocals_masked stem is silent 10-20s, audible elsewhere.

**Status**: Not Started

## Stage 5: End-to-end re-run on 夜吹 + validate
**Goal**: Re-run music-swap on `BV1UodgBJEXj_with_danmaku.mp4` with the new
pipeline. Verify: (a) bleed at 7:00-8:30 is fixed, (b) SFX is audible in
non-music regions, (c) debug sidecar is present and accurate.

**Success criteria**:
- User listens to the new clean.mp4 and confirms bleed is gone and SFX is
  preserved in at least one SFX-only segment.
- Debug sidecar lists the music intervals and matches user's auditory
  observation.
- Existing pipeline (burn → music-swap → subtitle → merge) still works
  end-to-end on the new clean.mp4.

**Tests**:
- Manual verification by user.
- `test_smoke.py` for all stages 1-4 still pass.
- Existing `tests/test_smoke.py` music-swap tests pass with the new
  pipeline (some assertions may need updating for the 3-way mix).

**Status**: Not Started

---

## Scope and non-goals

- This plan ONLY changes `music_swap.py` and tests. Does not touch
  download, burn, subtitle, merge, compose, or upload.
- We do NOT swap the Demucs model or upgrade separation quality. Bleed
  reduction comes from sparse-bed placement, not better separation.
- We do NOT add a manual-override flag to force music intervals (user can
  edit the sidecar JSON manually if needed — out of scope for this plan).
- Existing `--no-duck`, `--music-volume`, `--seed`, `--model`, `--keep-temp`
  flags stay unchanged.

## Risks

- **Music detection misclassifies** — if the heuristic flags music when
  there is none (or misses real music), the result is either over-replacement
  (Approach A back) or under-protection (bleed remains). Stage 2 success
  criteria require validation on real data before moving on.
- **Boundary artifacts** — 0.5s fades may not be enough; if the new bed
  "fades in" sounds jarring next to game SFX, may need longer fades or a
  short ducking ramp on the SFX side too.
- **Test stability** — chunk loudness measurements depend on ffmpeg version;
  may need looser tolerances in assertions or mock the measurement at the
  subprocess boundary (consistent with existing test patterns).
