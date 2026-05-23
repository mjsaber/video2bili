# Music Swap Vocal Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce residual copyrighted BGM after Demucs by applying a voice-activity-style gate to the isolated vocals stem before mixing replacement music.

**Architecture:** Keep the existing Demucs-first pipeline. Add one focused post-processing stage between `separate_vocals()` and `mix()`: `gate_vocals()` uses ffmpeg `agate` to preserve speech-level vocals while muting low-level non-speech residual bleed. Expose conservative CLI controls and default the gate on, with `--no-vocal-gate` for comparison/debugging.

**Tech Stack:** Python 3.10, ffmpeg audio filters (`agate`, optional `highpass`), pytest with subprocess mocked at module boundary.

---

## Root-cause summary

The existing pipeline is behaving as designed: it extracts audio, runs Demucs `--two-stems vocals`, discards `no_vocals`, then mixes replacement music. The problem is that in real Hearthstone livestream audio, Demucs leaves audible BGM inside `vocals.wav`. A 60-second probe showed the vocals stem energy almost matching original audio (`original mean_volume ~= -27.2 dB`, `vocals ~= -27.8 dB`), while `no_vocals` was much quieter. That means the bad BGM is already inside the stem we keep.

This plan does not try to preserve game SFX. It implements option 2 from the discussion: keep speech moments, aggressively suppress non-speech moments.

## File Structure

| File | Responsibility |
|---|---|
| `src/video2yt/music_swap.py` | Add `vocal_gate`, `vocal_gate_threshold`, `vocal_gate_release_ms` fields; add `gate_vocals()`; call it between Demucs and mix. |
| `src/video2yt/music_swap_cli.py` | Add CLI flags `--no-vocal-gate`, `--vocal-gate-threshold`, `--vocal-gate-release-ms`; pass them into `MusicSwapInputs`. |
| `tests/test_smoke.py` | Add unit tests for ffmpeg gate command, render pipeline ordering, and CLI parsing defaults/flags. |
| `README.md` | Document the music-swap vocal gate behavior and comparison flags. |

## Task 1: Add `gate_vocals()` ffmpeg stage

**Files:**
- Modify: `src/video2yt/music_swap.py`
- Test: `tests/test_smoke.py`

- [ ] **Step 1: Write the failing test**

Append near the existing `test_mix_with_ducking` tests in `tests/test_smoke.py`:

```python
def test_gate_vocals_builds_agate_command(tmp_path, monkeypatch):
    vocals = tmp_path / "vocals.wav"
    vocals.write_bytes(b"x")
    out = tmp_path / "vocals_gated.wav"
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return MagicMock(returncode=0)

    monkeypatch.setattr("video2yt.music_swap.subprocess.run", fake_run)
    music_swap.gate_vocals(
        vocals,
        out,
        threshold=0.015,
        release_ms=250,
    )

    cmd = captured["cmd"]
    joined = " ".join(cmd)
    assert cmd[0] == "ffmpeg"
    assert str(vocals) in cmd
    assert str(out) in cmd
    assert "agate=" in joined
    assert "threshold=0.015" in joined
    assert "release=250" in joined
    assert "highpass=f=80" in joined
    assert "pcm_s16le" in cmd
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run pytest tests/test_smoke.py::test_gate_vocals_builds_agate_command -v
```

Expected: FAIL with `AttributeError: module 'video2yt.music_swap' has no attribute 'gate_vocals'`.

- [ ] **Step 3: Implement minimal gate function**

In `src/video2yt/music_swap.py`, add after `separate_vocals()`:

```python
def gate_vocals(
    vocals_path: Path,
    gated_path: Path,
    threshold: float = 0.015,
    release_ms: int = 250,
) -> None:
    """Mute low-level residual music bleed in the isolated vocals stem.

    This is a voice-activity-style energy gate, not a semantic speech model.
    Demucs often leaves quiet BGM in ``vocals.wav`` during non-speech regions;
    ``agate`` pushes those regions to silence while keeping louder streamer
    speech. ``highpass`` removes low-end rumble before the gate/mix.

    ``threshold`` is a linear ffmpeg amplitude value. 0.015 is about -36.5 dBFS,
    chosen from the redchroma probe where non-speech residual vocals clustered
    below roughly -45 dBFS and speech peaks clustered around -20 dBFS.
    """
    if threshold <= 0 or threshold >= 1:
        raise ValueError("vocal gate threshold must be between 0 and 1")
    if release_ms <= 0:
        raise ValueError("vocal gate release must be positive milliseconds")
    filtergraph = (
        "highpass=f=80,"
        f"agate=threshold={threshold}:ratio=20:range=0:"
        f"attack=10:release={release_ms}:detection=rms"
    )
    cmd = [
        "ffmpeg", "-y",
        "-i", str(vocals_path),
        "-af", filtergraph,
        "-c:a", "pcm_s16le",
        str(gated_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
uv run pytest tests/test_smoke.py::test_gate_vocals_builds_agate_command -v
```

Expected: PASS.

## Task 2: Wire gate into render pipeline, default enabled

**Files:**
- Modify: `src/video2yt/music_swap.py`
- Test: `tests/test_smoke.py`

- [ ] **Step 1: Write failing render tests**

Modify `test_render_orchestrates_pipeline_in_order` in `tests/test_smoke.py` to mock and expect `gate` between `separate` and `mix`:

```python
monkeypatch.setattr(
    "video2yt.music_swap.gate_vocals",
    lambda v, gp, threshold=0.015, release_ms=250:
    calls.append("gate") or gp.write_bytes(b"g"),
)
```

Then add these assertions:

```python
assert calls.index("separate") < calls.index("gate")
assert calls.index("gate") < calls.index("mix")
```

Add a second test after it:

```python
def test_render_can_disable_vocal_gate(tmp_path, monkeypatch):
    src = tmp_path / "seg.mp4"
    src.write_bytes(b"x" * 100)
    out = tmp_path / "seg_clean.mp4"
    calls = []

    monkeypatch.setattr("video2yt.music_swap.validate.probe",
                        lambda p: _mk_info(duration=300.0, width=1920,
                                           height=1080, has_video=True,
                                           has_audio=True, vcodec="h264"))
    monkeypatch.setattr("video2yt.music_swap.extract_audio",
                        lambda i, o: o.write_bytes(b"a"))
    monkeypatch.setattr("video2yt.music_swap.separate_vocals",
                        lambda w, m, d: _touch(d / "v.wav"))
    monkeypatch.setattr("video2yt.music_swap.gate_vocals",
                        lambda *a, **k: calls.append("gate"))
    monkeypatch.setattr("video2yt.music_swap.music_library.ensure_manifest_cached",
                        lambda manifest, cache: None)
    monkeypatch.setattr("video2yt.music_swap.music_library.load_manifest",
                        lambda: [])
    monkeypatch.setattr("video2yt.music_swap.music_library.scan_cache",
                        lambda cache: [_track("a.mp3", 400.0)])
    monkeypatch.setattr("video2yt.music_swap.music_library.select_sequence",
                        lambda pool, dur, crossfade, seed: pool)
    monkeypatch.setattr("video2yt.music_swap.build_music_bed",
                        lambda seq, dur, bed, crossfade=2.0: bed.write_bytes(b"b"))
    monkeypatch.setattr("video2yt.music_swap.mix",
                        lambda v, b, mv, dk, mp: mp.write_bytes(b"m"))
    monkeypatch.setattr("video2yt.music_swap.remux",
                        lambda i, m, o: o.write_bytes(b"o"))

    music_swap.render(music_swap.MusicSwapInputs(
        input_path=src,
        output_path=out,
        vocal_gate=False,
    ))

    assert calls == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/test_smoke.py::test_render_orchestrates_pipeline_in_order tests/test_smoke.py::test_render_can_disable_vocal_gate -v
```

Expected: FAIL because `MusicSwapInputs` has no `vocal_gate` field and render does not call `gate_vocals()`.

- [ ] **Step 3: Add dataclass fields and render wiring**

In `src/video2yt/music_swap.py`, update `MusicSwapInputs`:

```python
@dataclass
class MusicSwapInputs:
    input_path: Path
    output_path: Path
    music_volume: float = 0.25
    duck: bool = True
    model: str = "htdemucs"
    seed: int | None = None
    keep_temp: bool = False
    vocal_gate: bool = True
    vocal_gate_threshold: float = 0.015
    vocal_gate_release_ms: int = 250
```

In `render()`, replace:

```python
vocals = separate_vocals(wav, inputs.model, demucs_out)
```

with:

```python
vocals = separate_vocals(wav, inputs.model, demucs_out)
voice_for_mix = vocals
if inputs.vocal_gate:
    _log(
        "gating isolated vocals "
        f"(threshold={inputs.vocal_gate_threshold}, "
        f"release_ms={inputs.vocal_gate_release_ms})"
    )
    gated = work / "vocals_gated.wav"
    gate_vocals(
        vocals,
        gated,
        threshold=inputs.vocal_gate_threshold,
        release_ms=inputs.vocal_gate_release_ms,
    )
    voice_for_mix = gated
```

Then replace:

```python
mix(vocals, bed, inputs.music_volume, inputs.duck, mixed)
```

with:

```python
mix(voice_for_mix, bed, inputs.music_volume, inputs.duck, mixed)
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
uv run pytest tests/test_smoke.py::test_render_orchestrates_pipeline_in_order tests/test_smoke.py::test_render_can_disable_vocal_gate -v
```

Expected: PASS.

## Task 3: Add CLI controls

**Files:**
- Modify: `src/video2yt/music_swap_cli.py`
- Test: `tests/test_smoke.py`

- [ ] **Step 1: Write failing CLI tests**

Update `test_cli_parse_args_defaults`:

```python
assert args.no_vocal_gate is False
assert args.vocal_gate_threshold == 0.015
assert args.vocal_gate_release_ms == 250
```

Update `test_cli_parse_args_all_flags` argument list to include:

```python
"--no-vocal-gate", "--vocal-gate-threshold", "0.02", "--vocal-gate-release-ms", "400"
```

Add assertions:

```python
assert args.no_vocal_gate is True
assert args.vocal_gate_threshold == 0.02
assert args.vocal_gate_release_ms == 400
```

Update `test_cli_run_derives_default_output` to assert fields passed into render:

```python
assert captured["inputs"].vocal_gate is True
assert captured["inputs"].vocal_gate_threshold == 0.015
assert captured["inputs"].vocal_gate_release_ms == 250
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/test_smoke.py::test_cli_parse_args_defaults tests/test_smoke.py::test_cli_parse_args_all_flags tests/test_smoke.py::test_cli_run_derives_default_output -v
```

Expected: FAIL because parser lacks the new args.

- [ ] **Step 3: Add parser flags**

In `src/video2yt/music_swap_cli.py`, add after `--no-duck`:

```python
parser.add_argument(
    "--no-vocal-gate", action="store_true",
    help=(
        "Disable post-Demucs vocal gating. Useful for A/B comparison; "
        "default is to gate low-level non-speech bleed."
    ),
)
parser.add_argument(
    "--vocal-gate-threshold", type=float, default=0.015,
    help=(
        "ffmpeg agate threshold as linear amplitude (default: 0.015, "
        "about -36.5 dBFS). Lower keeps more voice but more BGM bleed; "
        "higher suppresses more bleed but may clip quiet speech."
    ),
)
parser.add_argument(
    "--vocal-gate-release-ms", type=int, default=250,
    help="Vocal gate release time in milliseconds (default: 250).",
)
```

In `run()`, add to `MusicSwapInputs(...)`:

```python
vocal_gate=not args.no_vocal_gate,
vocal_gate_threshold=args.vocal_gate_threshold,
vocal_gate_release_ms=args.vocal_gate_release_ms,
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
uv run pytest tests/test_smoke.py::test_cli_parse_args_defaults tests/test_smoke.py::test_cli_parse_args_all_flags tests/test_smoke.py::test_cli_run_derives_default_output -v
```

Expected: PASS.

## Task 4: Document behavior and comparison workflow

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add README section**

Add a `video2yt-music-swap` section after the merge section or near workflow docs:

```markdown
## Replace background music / reduce Content ID risk

`video2yt-music-swap` isolates streamer commentary with Demucs, discards the non-vocal mix, gates low-level non-speech residual bleed from the vocals stem, then mixes in royalty-free music.

```bash
uv run video2yt-music-swap path/to/BVxxx_with_danmaku.mp4 --seed 1
```

Useful A/B options:

```bash
# Disable the post-Demucs vocal gate for comparison
uv run video2yt-music-swap path/to/input.mp4 --no-vocal-gate -o no_gate.mp4

# More aggressive bleed suppression; may cut quiet speech
uv run video2yt-music-swap path/to/input.mp4 --vocal-gate-threshold 0.025 -o stronger_gate.mp4

# Softer release, less choppy but leaves more tails
uv run video2yt-music-swap path/to/input.mp4 --vocal-gate-release-ms 400 -o softer_gate.mp4
```

Trade-off: the gate mostly helps when the streamer is not speaking. If copyrighted music leaks under active speech, no energy gate can remove it perfectly without damaging the voice. For high-risk clips, compare a 60-second sample before processing the full video.
```

- [ ] **Step 2: No test required**

Docs-only change. Verify visually with:

```bash
grep -n "Replace background music" -A25 README.md
```

Expected: section appears and code fences render correctly.

## Task 5: Run full tests and smoke a real 60-second sample

**Files:**
- No source changes expected.

**Testing strategy:** This feature must pass both code-level tests and media-level A/B checks. Unit tests prove the pipeline calls the new gate correctly; they do not prove the audio sounds better. The real sample tests are therefore required before calling the feature done.

**Acceptance criteria:**
- Unit tests pass.
- With `--music-volume 0.0`, the gated output has much lower per-second median / low-percentile RMS than the no-gate output on the 60-second probe, showing non-speech residual was suppressed. Whole-file `volumedetect mean_volume` is not sufficient because loud speech peaks dominate it.
- Speech peaks remain similar enough that the streamer is not globally muted; per-second p90 RMS and `max_volume` should not collapse by many dB.
- A short listening sample confirms non-speech BGM bleed is reduced and speech is still intelligible. If speech sounds choppy, lower `--vocal-gate-threshold` or increase `--vocal-gate-release-ms` and rerun the A/B.

- [ ] **Step 1: Run focused tests**

Run:

```bash
uv run pytest tests/test_smoke.py::test_gate_vocals_builds_agate_command \
  tests/test_smoke.py::test_render_orchestrates_pipeline_in_order \
  tests/test_smoke.py::test_render_can_disable_vocal_gate \
  tests/test_smoke.py::test_cli_parse_args_defaults \
  tests/test_smoke.py::test_cli_parse_args_all_flags \
  tests/test_smoke.py::test_cli_run_derives_default_output -v
```

Expected: all PASS.

- [ ] **Step 2: Run broader smoke tests**

Run:

```bash
uv run pytest tests/test_smoke.py -q
```

Expected: all PASS.

- [ ] **Step 3: Generate a 60-second comparison sample**

Run from repo root:

```bash
SRC='output/redchroma/炉石郭枫：8回合谁碰谁15！这就是目前龙的强度！/BV1JvLr6sEwi_with_danmaku.mp4'
SAMPLE='/tmp/video2yt_gate_probe_60s.mp4'
BASE='/tmp/video2yt_gate_probe_no_gate.mp4'
GATED='/tmp/video2yt_gate_probe_gated.mp4'
ffmpeg -hide_banner -y -ss 00:05:00 -t 60 -i "$SRC" -map 0:v:0 -map 0:a:0 -c copy "$SAMPLE"
uv run video2yt-music-swap "$SAMPLE" -o "$BASE" --no-vocal-gate --music-volume 0.0 --seed 1
uv run video2yt-music-swap "$SAMPLE" -o "$GATED" --music-volume 0.0 --seed 1
```

Expected: both outputs are created. `BASE` is old behavior; `GATED` should suppress quiet BGM bleed in non-speech gaps.

- [ ] **Step 4: Measure rough loudness difference**

Run:

```bash
for f in "$SAMPLE" "$BASE" "$GATED"; do
  echo "--- $f"
  ffmpeg -hide_banner -nostats -i "$f" -af volumedetect -vn -f null - 2>&1 | grep -E 'mean_volume|max_volume'
done
```

Expected: `volumedetect` is only a coarse sanity check. `GATED` may have a similar whole-file mean if the sample has frequent loud speech. Max volume should remain in the same rough range because speech peaks are preserved.

- [ ] **Step 5: Measure per-second RMS distribution**

Run:

```bash
python3 - <<'PY'
import subprocess, wave, numpy as np
files = {'no_gate': '/tmp/video2yt_gate_probe_no_gate.mp4',
         'gated': '/tmp/video2yt_gate_probe_gated.mp4'}
for name, path in files.items():
    wav = f'/tmp/{name}_audio.wav'
    subprocess.run(['ffmpeg', '-hide_banner', '-y', '-i', path, '-vn', '-ac', '1',
                    '-ar', '44100', '-c:a', 'pcm_s16le', wav],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    with wave.open(wav, 'rb') as w:
        sr = w.getframerate()
        data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
    rms = []
    for i in range(len(data) // sr):
        x = data[i * sr:(i + 1) * sr]
        rms.append(20 * np.log10(np.sqrt(np.mean(x * x) + 1e-12) + 1e-12))
    print(name,
          'median', round(float(np.median(rms)), 1),
          'p10', round(float(np.percentile(rms, 10)), 1),
          'p90', round(float(np.percentile(rms, 90)), 1))
    print('first20', ' '.join(f'{v:.1f}' for v in rms[:20]))
PY
```

Expected: `gated` median and p10 are far lower than `no_gate` (often near digital silence in non-speech seconds), while p90 stays close.

- [ ] **Step 6: Export listenable A/B clips**

Run:

```bash
ffmpeg -hide_banner -y -i "$SAMPLE" -vn -t 30 -c:a libmp3lame -b:a 128k /tmp/video2yt_gate_probe_original_30s.mp3
ffmpeg -hide_banner -y -i "$BASE" -vn -t 30 -c:a libmp3lame -b:a 128k /tmp/video2yt_gate_probe_no_gate_30s.mp3
ffmpeg -hide_banner -y -i "$GATED" -vn -t 30 -c:a libmp3lame -b:a 128k /tmp/video2yt_gate_probe_gated_30s.mp3
```

Expected: three MP3 files exist. Listen to `no_gate_30s` vs `gated_30s`. The gated version should have less music in pauses/non-speech regions. If speech is clipped/choppy, rerun Step 3 with one of:

```bash
uv run video2yt-music-swap "$SAMPLE" -o "$GATED" --music-volume 0.0 --seed 1 --vocal-gate-threshold 0.010
uv run video2yt-music-swap "$SAMPLE" -o "$GATED" --music-volume 0.0 --seed 1 --vocal-gate-release-ms 400
```

- [ ] **Step 7: Clean temp files**

Run:

```bash
rm -f /tmp/video2yt_gate_probe_60s.mp4 \
      /tmp/video2yt_gate_probe_no_gate.mp4 \
      /tmp/video2yt_gate_probe_gated.mp4 \
      /tmp/video2yt_gate_probe_no_gate_music_credits.txt \
      /tmp/video2yt_gate_probe_gated_music_credits.txt \
      /tmp/video2yt_gate_probe_original_30s.mp3 \
      /tmp/video2yt_gate_probe_no_gate_30s.mp3 \
      /tmp/video2yt_gate_probe_gated_30s.mp3 \
      /tmp/no_gate_audio.wav \
      /tmp/gated_audio.wav
```

Expected: no project output files are touched.

## Self-review

- Spec coverage: implements option 2 by muting non-speech residual after Demucs; keeps old behavior available through `--no-vocal-gate`; adds CLI tuning for threshold/release; documents trade-offs.
- Placeholder scan: no TBD/TODO/implement-later steps.
- Type consistency: `MusicSwapInputs.vocal_gate`, `vocal_gate_threshold`, `vocal_gate_release_ms` are consistently used by CLI and render.
