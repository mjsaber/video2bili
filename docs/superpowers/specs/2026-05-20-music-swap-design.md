# video2yt-music-swap — Design

**Date**: 2026-05-20
**Status**: Design approved, pending implementation plan
**Author**: Brainstormed with the user (jun)

## 1. Problem

Bilibili Hearthstone-stream source clips carry a single mixed audio track:
streamer commentary (Chinese voice) + Hearthstone game sound effects + the
streamer's own background music (a Spotify / playlist running the whole
stream). When these clips are republished to YouTube, the streamer's
background music repeatedly triggers YouTube Content ID claims.

The goal: suppress the streamer's background music and replace it with
royalty-free music, so the published video is very unlikely to draw a YouTube
Content ID claim on that music.

This is a risk-reduction goal, not a guarantee — see the honest limits in
section 2.

## 2. Constraints and the core trade-off

The background music runs **the entire stream** — there is no music-free
segment to preserve untouched. The audio is one mixed track, so removing the
music requires source separation.

AI source separation (Demucs) splits audio into *voice* vs
*drums / bass / other*. The commentary comes out clean in the voice stem. But
**game sound effects and the streamer's music both fall into the same
non-voice bucket** — no separator distinguishes "video game SFX" from "pop
music". With music playing continuously, keeping the SFX means keeping the
music.

**Decision (Approach A):** isolate the commentary voice, discard the entire
non-voice mix (music *and* game SFX), and lay a royalty-free music bed
underneath. This sacrifices the original game sound effects to drive the
copyrighted music down to a level very unlikely to be matched. This trade-off
was explicitly chosen by the user over the alternatives (keep a quiet
residual — still clearly risks a claim; or no audio surgery — handle claims in
YouTube Studio).

**Honest limits — this reduces claim risk, it does not eliminate it:**

- Demucs separation is imperfect. Faint music can bleed into the vocals stem.
  Content ID is robust to attenuation, so heavy bleed could in principle still
  match — vocal isolation makes a match *unlikely*, not impossible.
- The replacement royalty-free track carries its own claim risk (see the
  vetting caveat in section 6).
- Therefore the spec deliberately avoids any "100% safe" / "guaranteed"
  language. The deliverable is a file with the original music strongly
  suppressed, not a file with a mathematical safety guarantee. The user should
  still expect to occasionally check claims in YouTube Studio.

## 3. Scope

A new CLI, `video2yt-music-swap`, that takes one burnt segment MP4 and
produces an MP4 with the original background music suppressed and replaced.

Out of scope: detecting *which* song is playing; preserving game SFX;
processing the intro (Step 5 compose output, which has its own TTS narration
and no copyright issue); final loudness normalization (already handled by
`video2yt-merge`).

## 4. Workflow placement

```
burn (Step 6) → music-swap (new Step 6.5) → subtitle (Step 6.6) → merge (Step 7)
```

music-swap runs **before** the subtitle step on purpose: the subtitle step's
speech recognition then operates on clean isolated vocals instead of a
music-cluttered mix, producing better transcripts at no extra cost. The
existing Step 6.5 (subtitle) becomes Step 6.6.

music-swap operates on the **burnt segment MP4** (the Step 6 output), not the
raw download — it needs the final burnt-in frames and only swaps the audio
track (`-c:v copy`, no video re-encode).

## 5. Internal pipeline

Input: one segment MP4 (1920x1080, 30fps, h264 + AAC — the Step 6 output).

1. **Preflight**
   - `ffmpeg` and `ffprobe` in PATH (`shutil.which`).
   - `demucs` Python package importable (added via `uv add demucs`).
   - Input file exists and ffprobe shows both an audio and a video stream.
   - Fail fast with install instructions on any miss.

2. **Extract audio** — ffmpeg extracts the input audio to a temp WAV
   (44.1 kHz stereo) under a temp dir.

3. **Vocal isolation** — run Demucs with the `htdemucs` model in two-stem mode
   (`--two-stems=vocals`), which yields `vocals.wav` + `no_vocals.wav`. Keep
   `vocals.wav`; discard `no_vocals.wav`. Two-stem mode is faster than the full
   4-stem split. Demucs is invoked as a subprocess (consistent with the
   project's "mock at the `subprocess.run` boundary" test pattern).

4. **Build the music bed**
   - Target duration = input video duration (from ffprobe).
   - The track pool is **every audio file present in the cache dir** — both
     manifest-downloaded tracks and any tracks the user dropped in manually
     (per §6, the cache dir is the source of truth). The pool is not
     manifest-only and not restricted to CC0; the CC0 / redistributable
     constraint governs only what the *manifest* may list, not what the user
     places by hand.
   - Each pooled track's duration is determined by **probing the file with
     ffprobe**, not by reading the manifest. User-supplied tracks have no
     manifest entry, so the manifest `duration` field is at most a selection
     hint — ffprobe is the authoritative source for stitch math.
   - Selection order is shuffled; `--seed` makes it deterministic.
   - Stitch consecutive tracks with ffmpeg `acrossfade` (a short crossfade,
     e.g. 2 s) until the stitched bed is ≥ target duration. If the pool is
     shorter than the target, tracks are reused (the shuffled sequence
     repeats).
   - Trim the bed to the exact target duration and apply a fade-out at the
     very end (`afade`).

5. **Mix** — combine `vocals.wav` (commentary) with the music bed:
   - Music bed scaled to `--music-volume` (default 0.25) relative to voice.
   - `sidechaincompress` keyed off the voice so the music ducks while the
     streamer talks; `--no-duck` disables this and uses a flat mix.
   - Output a single mixed stereo audio stream.

6. **Remux** — ffmpeg combines the input MP4 video stream (`-c:v copy`) with
   the new mixed audio (`-c:a aac`) into the output MP4.

7. **Validate** — ffprobe the output: video stream still 1920x1080 / 30fps /
   h264, an audio stream is present, and the output duration is within a small
   tolerance of the input duration. Fail on any violation.

8. **Write music credits** — for the tracks actually used, collect the
   `attribution` lines of any that came from the manifest and write them to a
   `<output>_music_credits.txt` sidecar (skipped when no manifest-attributed
   track was used). The user pastes this into the YouTube description. See §6.

9. **Cleanup** — remove the temp WAVs and Demucs scratch files by default;
   `--keep-temp` retains them.

## 6. Music library

The track **cache directory** `~/.cache/video2yt/music/` is the source of
truth — the tool builds the music bed from whatever audio files are present
there. The manifest is just an auto-fill convenience on top of it.

- A manifest committed at `src/video2yt/data/music_library.json`. Each entry:
  `{ name, url, sha256, duration, license, attribution }`.
- On first use, missing manifest tracks are downloaded to the cache dir and
  verified against `sha256`. This mirrors `video2yt-research-card`'s card-art
  caching (download once, cache with verification).
- The user may also drop their own tracks straight into the cache dir; the
  tool picks them up alongside the manifest tracks.

### Shipped library — Kevin MacLeod via the Internet Archive (CC BY 3.0)

The original plan assumed an attribution-free CC0 library. That assumption did
not survive contact with reality: **FreePD.com — the obvious CC0 source —
shut down in 2025**, and no remaining source is simultaneously
bulk-downloadable, attribution-free, *and* guaranteed claim-free.

The shipped manifest is therefore seeded with calm/instrumental tracks by
**Kevin MacLeod**, mirrored on the **Internet Archive**
(`archive.org/details/Incompetech`). This was chosen because:

- archive.org provides **stable, redistributable, hotlinkable direct-download
  URLs** — exactly what the manifest auto-download design needs.
- Kevin MacLeod is the most YouTube-proven royalty-free composer and does not
  Content-ID-claim his own music, so claim risk is genuinely low.
- The collection has plenty of calm tracks that suit game background music.

The price: the tracks are **CC BY 3.0**, so **attribution is required**. Each
manifest entry carries an `attribution` line, and `render` writes the credit
lines for the tracks actually used to `<output>_music_credits.txt` (see §5
step 8) — the user pastes that into the YouTube description.

**Manifest tracks must be redistributable.** The tool downloads manifest
tracks programmatically, so every manifest URL must point at a host that
permits direct download / redistribution (CC0 *or* CC BY on a permissive host
such as the Internet Archive), and must be a canonical host, not a re-hosted
copy.

**Do NOT put YouTube Audio Library tracks in the manifest.** The YouTube Audio
Library license permits *using* its tracks in your own videos but does **not**
permit redistributing the audio files. A user who wants YouTube Audio Library
music — the zero-attribution, strongest-guarantee option — downloads those
tracks themselves (permitted, personal use) and drops them into the cache dir
manually; that path stays outside the manifest. The tool surfaces no
attribution for cache files with no manifest entry, which is correct for
YouTube Audio Library tracks.

**Honest limit:** even CC0/CC BY music can occasionally be Content-ID-claimed
by bad actors, and a CC BY claim is disputable with the license. This library
reduces risk; it is not a guarantee (consistent with §2).

### Expanding the library

Two supported ways, both documented for the user:

1. Add more entries to `music_library.json` — any archive.org direct-MP3 URL
   (or other redistributable host) with a real `sha256`, `duration`, and
   `attribution`. Compute `sha256` with `shasum -a 256` and `duration` with
   `validate.probe`.
2. Drop audio files straight into `~/.cache/video2yt/music/` — the cache dir
   is the source of truth. This is the path for YouTube Audio Library tracks.

## 7. CLI

```
video2yt-music-swap <input.mp4> [-o OUTPUT] [options]

  -o, --output PATH      output MP4 (default: <input stem>_clean.mp4,
                         written alongside the input)
  --music-volume FLOAT   music bed level relative to voice (default 0.25)
  --no-duck              disable sidechain ducking; use a flat mix
  --model NAME           Demucs model (default: htdemucs)
  --seed INT             reproducible track selection
  --keep-temp            keep temp WAVs / Demucs scratch files
```

The output feeds into `video2yt-merge` as a `--segment`. Final loudness
normalization is left to merge's existing per-segment loudnorm (-14 LUFS), so
music-swap only needs a sane internal mix balance, not a final loudness target.

Entry point `video2yt-music-swap` registered in `pyproject.toml` (via
`uv add` / editing handled by the standard project tooling, never by hand).

## 8. Performance

Demucs is slow on CPU — a 17-minute segment can take roughly 10–30 minutes.
On Apple Silicon, Demucs can use the MPS GPU backend, which is substantially
faster; the tool enables MPS automatically when available. This is a heavy
step on the order of the existing subtitle step; the workflow spec gets a
performance note like the one already on Step 6.5 (subtitle).

## 9. Error handling

- Missing `ffmpeg` / `ffprobe` / `demucs` → fail fast with the install command.
- Input missing, or ffprobe shows no audio stream or no video stream → fail
  with a clear message.
- Demucs produces an empty or silent `vocals.wav` → warn (the source may have
  had no isolable voice).
- An individual manifest track fails to download or fails its sha256 check →
  **warn and skip that track**, then continue with the rest. One bad URL must
  not abort the whole run.
- After manifest auto-fill, the cache dir contains **no usable audio track at
  all** → fail with a clear message telling the user to fix the manifest /
  network or drop tracks into the cache dir manually. (An empty *manifest* is
  not itself an error — the cache dir is the source of truth per §6, so
  user-supplied tracks alone are sufficient.)
- Output duration drifts beyond tolerance from the input → fail validation.

## 10. Module layout

```
src/video2yt/
├── music_swap.py        # pipeline: extract → demucs → bed → mix → remux → validate
├── music_swap_cli.py    # video2yt-music-swap entry point (parse_args / run / main)
├── music_library.py     # manifest load + download/cache + sha256 verify + track selection
└── data/music_library.json   # committed CC0 track manifest
```

`music_library.py` is split out from `music_swap.py` so the library logic
(manifest parsing, caching, selection) is independently testable and the
pipeline file stays focused.

## 11. Testing

Follows `tests/test_smoke.py`: everything mocked at the `subprocess.run`
boundary — no network, no ffmpeg, no ffprobe, no Demucs actually invoked.

Test cases:
- Argument parsing: defaults, each flag, output-filename derivation.
- Manifest parsing: well-formed manifest, malformed / empty manifest.
- Track caching: cache hit (skip download), cache miss (download + verify),
  sha256 mismatch / download failure (warn + skip that track, run continues),
  user-supplied track in the cache dir picked up alongside manifest tracks.
- Empty-library failure: no manifest tracks and no cache-dir tracks → fail;
  empty manifest but user-supplied tracks present → succeeds.
- Bed-stitch duration math: tracks stitched to ≥ target, trimmed to exact
  length; deterministic with `--seed`.
- Preflight failures: missing ffmpeg / ffprobe / demucs, missing input,
  no audio stream, no video stream.
- Validation: output duration within / outside tolerance; resolution / codec
  preserved.

## 12. Documentation updates

- `docs/superpowers/specs/2026-04-18-video-production-workflow.md`: add
  Step 6.5 (music-swap), renumber the existing subtitle step to 6.6, add the
  performance note, update the per-project workflow checklist.
- `CLAUDE.md`: add the command to the Commands block, the module to the
  Architecture map, the flags to the Feature flags reference, and a gotcha for
  the Demucs performance cost and the CC0-vetting caveat.
