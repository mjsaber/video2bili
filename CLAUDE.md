# CLAUDE.md

Project context for Claude agents working in this repo.

## Purpose

A local CLI that takes a Bilibili video URL and produces an MP4 with burned-in danmaku, optional STT subtitles, and an optional replacement background music swap. The per-segment pipeline is five stages orchestrated by `video2yt`:

```
yt-dlp+biliass → song-remover stems → speech2srt (火山 Seed-ASR + codex) subtitle → replacement music bed → ONE ffmpeg pass that
burns danmaku ASS + subtitle ASS + sidechain-ducked speech+bed amix all together
```

Each stage has its own cache layer, its own CLI, and its own meta-sidecar so a rerun only redoes the slowest changed step. Supports `--cut START~END` to remove time ranges, `--speed FLOAT` for playback-multiplier output, `--preview-seconds` for fast iteration, `--no-subtitle` / `--no-music-swap` skip flags, and `--device {cpu,mps,auto,remote}` (default `remote` — Modal cloud GPU ~7.2× faster than local CPU).

## Commands

```bash
uv run video2yt "<url>" -o output/<project>/                           # full pipeline (5 stages)
uv run video2yt "<url>" --no-subtitle -o output/<project>/             # skip Stage 3 STT subtitle
uv run video2yt "<url>" --no-music-swap -o output/<project>/           # skip Stage 4; use source audio
uv run video2yt "<url>" --no-subtitle --no-music-swap -o ...           # legacy danmaku-only path
uv run video2yt "<url>" --device cpu -o ...                            # offline source separation
uv run video2yt "<url>" --cut 30~60 --speed 1.5 -o ...                 # cuts + speed multiplier
uv run video2yt-fetch "<url>" -o temp/                                 # only Stage 1 (download + biliass)
uv run video2yt-prefetch "<url1>" "<url2>" -o temp/ &                  # background serial pre-download of Step 6 sources (truncation retry + low-res quarantine + fail-fast)
uv run video2yt-stems temp/<dir>/<bv>.mp4                              # only Stage 2 (song-remover)
uv run video2yt-subtitle temp/<dir>/<bv>.mp4 --context-file output/<project>/subtitle_context.txt   # only Stage 3 (speech2srt)
uv run video2yt-music-mix temp/<dir>/<bv>.mp4                          # only Stage 4 (replacement bed)
uv run video2yt-burn temp/<dir>/ --bv <bv> -o output/<bv>_final.mp4    # only Stage 5 (single ffmpeg)
uv run video2yt-compose --audio a.mp3 --image bg.jpg --srt subs.srt --title "T"   # legacy static intro composer (still image)
uv run video2yt-intro --audio intro.mp3 --bg intro_bg.png --srt intro.srt --cards intro_cards.txt -o output/<project>/intro.mp4   # dynamic intro: 女老板 narrator + per-card spotlight + scrim
uv run video2yt-cta --video battle.mp4 --text "訂閱馬哥，每期拆解轉型決策" --at 90 -o battle_cta.mp4  # choose a value-delivered moment
uv run video2yt-merge --segment a.mp4 --label "A" --segment b.mp4 --label "B" --segment c.mp4 --label "C" --title "T"   # concat + loudnorm + chapters
uv run video2yt-cleanup --project <project>                            # LAST step after upload: DRY-RUN plan — purge current project's temp/ + delete previous shipped project's whole output/ folder
uv run video2yt-cleanup --project <project> --yes                      # actually delete (reclaim disk; current output/<project>/ kept as a one-period buffer)
uv run python scripts/backfill_playlists.py [--yes]                    # one-time playlist backfill (dry-run default); NEW uploads are auto-added by video2yt-upload via playlists.add_video (keyword rules on the title)
uv run --extra dev pytest                                              # run tests with the dev extra (bare `uv run pytest` may pick an unrelated pytest)
uv add <pkg>                                                           # add a dep (NEVER edit pyproject.toml deps by hand)
```

## External dependencies

- `ffmpeg` and `ffprobe` must be in PATH (system install, not Python package). Check with `shutil.which('ffmpeg')`. **Must include libass** — see "Known gotchas".
- video2yt downloads the raw danmaku XML via `yt-dlp --write-subs --sub-langs danmaku` and converts to ASS in-process using `biliass.convert_to_ass`, so the height and font_size are known before conversion. The `yt-dlp-danmaku` plugin is no longer used as a postprocessor (refactored away in `aa1d91c`); we still depend on the `biliass` Python package that ships with it.
- `song-remover` (out-of-tree subprocess at `~/code/song-remover`) must be on `$PATH` for `video2yt-stems` (Stage 2). One-time install: `cd ~/code/song-remover && uv tool install '.[remote]'` (the `[remote]` extra bakes the `modal` SDK into the tool's venv — without it, `--device remote` will fail with `ModuleNotFoundError: modal`). Verify with `song-remover --version`. For the default Modal cloud-GPU path (`--device remote`, 7.2× faster than local CPU, ~$0.10/segment within Modal's $30/mo free tier), the one-time Modal setup additionally requires: `uv run modal token new && uv run modal deploy -m modal_app.prep && uv run modal run -m modal_app.prep && uv run modal deploy -m modal_app.separator` (all from the song-remover repo).
- `speech2srt` (out-of-tree subprocess at `~/code/speech2srt`) must be on `$PATH` for `video2yt-subtitle` (Stage 3). One-time install: `cd ~/code/speech2srt && uv tool install . --force`. Verify with `speech2srt --version`. Backend is Volcengine 豆包录音文件识别模型2.0 (Seed-ASR); needs `VOLCENGINE_API_KEY` either exported or in `.env` at the cwd where you run `video2yt`/`video2yt-subtitle`. Per-call cost is roughly ¥0.0003/char (~¥0.1 per 4-min segment). Cleanup goes through `codex exec` — same key as Step 4 intro alignment.
- `codex` CLI (used by Stage 3 subtitle cleanup, image gen, and ad-hoc Codex tasks) — `brew install codex && codex login`. NOT used by `transcribe.py`'s intro alignment (that path is pure ffmpeg).
- Step 4 intro alignment (`video2yt-transcribe`) is **pure ffmpeg/ffprobe** since 2026-07-04: speech span via `silencedetect` + proportional script slicing. whisperx was removed from `pyproject.toml` — it deterministically dropped the audio tail twice (tiger −10s, leapfrog −3.4s) while its word timestamps were otherwise unused. See `docs/superpowers/specs/2026-07-04-transcribe-ffmpeg-span.md`. `--language/--model/--device` remain as ignored deprecated flags for one release.

## Project folder convention

When working on a multi-step video project (intro + multiple burnt segments + final merge), use `-o output/<project>/` for `video2yt` / `video2yt-compose`, and full MP4 output paths for `video2yt-intro` / `video2yt-merge` so all artifacts land under one folder. Example: `output/back2back/` contains `intro.mp4`, segment subfolders, the final merged MP4, the YouTube thumbnail, and any scratch files. This keeps unrelated projects isolated and makes cleanup easy.

## Topic selection rule (video2yt-topic output)

`video2yt-topic` prints the **full link-bearing report to stdout** between
`===== CHAT-READY REPORT … =====` markers (logs go to stderr; the same markdown
is also written to `output/topics/<date>.md`). When presenting candidates:

1. **Relay that stdout block verbatim** + `SendUserFile output/topics/<date>.md`. Do NOT hand-author a condensed candidate table — that is how source URLs get dropped.
2. **EVERY candidate carries both streamers' `https://www.bilibili.com/video/<BVID>` URLs in the visible chat text** — including ones you are NOT recommending. Never name-drop a candidate without its links.
3. Layer your `done_topics` / 补丁 annotations ON TOP of the verbatim block; don't replace it. (The report already flags `[已做过 → …]`, but cross-check label mismatches, e.g. 飞纳流 = 飞龙娜迦.)

## Battlegrounds workflow rule (intro from content, then term-check)

Before starting or resuming a video project, read the Claude project-memory index at
`~/.claude/projects/-Users-jun-code-video2yt/memory/MEMORY.md` and the linked entries
relevant to the current workflow/topic. The repository `.claude/` directory contains
settings/worktrees, not this project memory.

The intro is built from the **actual content** of the two source videos, not guessed from the topic. All-source fetch failure must fail without overwriting reports; topic JSON evidence/confidence/version stays pending human verification. Relative views/hour ranking is a candidate heuristic, not predicted YouTube growth. Order (full SOP in `docs/superpowers/specs/2026-04-18-video-production-workflow.md`, Steps 1–4):

1. **Download both sources** (`video2yt-prefetch`), then **understand the content**: `video2yt-stems` + `video2yt-subtitle --skip-cleanup` (speech2srt runs ONCE, raw) → read the raw ASR + the danmaku text → write each video's 思路 → combine into one intro angle → draft `intro_script.txt`. Show the user the understanding + script together (review #1).
2. **Term-check (HARD RULE) before TTS.** Verify every card/hero/異變/流派 against the in-game **zhTW card art** (download via `art.hearthstonejson.com/.../zhTW/...`), not fan sites. After `ringnaga` (護戒 = the card 戒指龍 / Ring Bearer, not a Spellcraft buff) and `midas_arrow` (简中「点金箭」= 台服「黃金箭」, an 異變 not a 饰品). Danmaku+topic often name the cards already — use them to term-check early. Correct `intro_script.txt`, THEN TTS (so you don't voice a wrong term and redo it).
3. Use BG vocabulary (阵容/隨從/旅店/跳本/餵/疊屬性/吃雞 · 異變 not 畸變), NOT constructed-mode vocabulary (牌組/起手/過渡). Full glossary in the spec, Step 2. **Tavern = 旅店 in zhTW** (`旅店法術` on every Tavern-spell card face); 简中「酒馆」is not the 台服 term — user decision 2026-07-24 on the `bkb_t0` project.
4. **Evidence-first intro (2026-09-05, user-approved growth review):** keep the channel voice and verified Traditional Chinese terminology. Start by showing the actual promised result, then explain the viewer's decision/problem. Trial baseline: 0–5s result, 5–15s promise, 15–20s key gameplay; durations are hypotheses for retention review, not hard platform rules. `你敢相信？` is optional if it does not delay proof. Explain mechanisms at their relevant gameplay moments. Avoid “最穩”, “T0”, or guaranteed ranking gains unless supported beyond selected high-roll games. Use “完整教學” only if the body explains setup conditions, key decisions, fallback options, and limitations.
5. **Packaging and review:** use `docs/growth-workflow.md` as the current growth SOP. Put concrete payoff/decision before boilerplate in titles. The old fixed full-game-name prefix, 4+4-char formula and mandatory mascot are retired as requirements; brand remains a configurable default. Save local thumbnail variants, mobile previews and experimental hypotheses. Studio A/B tests remain a separate manual step. Record real metrics at 24h/7d/28d; missing values stay unknown.


**Subtitle cleanup is done by Claude subagents, NOT a second speech2srt call** (Step 5): speech2srt runs once at understanding-time (`--skip-cleanup`); the burnt 繁體 subtitle is cleaned by splitting the raw SRT → parallel cleanup subagents (preserve block#+timestamps) → review subagent → `compose.srt_to_ass`. This avoids re-running the flaky Volcengine upload and the codex length-drift guard that silently falls back to raw 简体 subs.

## Known gotchas

### ffmpeg / burn pipeline

- **ffmpeg `subtitles=` filter path escaping**: chokes on absolute paths containing spaces, colons, or parentheses. Workaround in `burn.py`: run subprocess with `cwd=temp_dir` and pass the ASS filename as a basename; the `-i` input also uses the basename. ffmpeg 8+ is stricter and requires the explicit `subtitles=f='<name>'` quoted form.
- **Chaining two `subtitles=` filters in one filter_complex**: T6 verified on ffmpeg 8.1 + libass that `[cv]subtitles=f='d.ass'[sv1]; [sv1]subtitles=f='c.ass'[sv]` renders both layers correctly. Cleaned-subtitle ASS lives under `<bv>/speech.cleaned.ass`; burn pre-flight symlinks it to a flat sibling `<bv>.cleaned.ass` so the cwd-with-basename trick works for both files.
- **Cleaned ASS symlink target is absolute**: `sym_path.symlink_to(cleaned_target.resolve())`. Relative targets resolve against the symlink's parent (not cwd) and would produce a broken link when `temp_dir` itself is relative.
- **Multi-range cuts + music-swap require asplit**: ffmpeg filter labels are single-consumer. With N>1 cuts AND `apply_music_swap=True`, the normalized `[1:a]`/`[2:a]` outputs must be asplit before the per-range atrim loop, or libavfilter rejects the graph.
- **ffmpeg must be built with libass**: the default `brew install ffmpeg` bottle does NOT always include libass, so the `subtitles` filter we rely on is missing. Symptom: ffmpeg emits `No option name near '<filename.ass>'` or `No such filter: 'subtitles'`. Fix: `brew tap homebrew-ffmpeg/ffmpeg && brew install homebrew-ffmpeg/ffmpeg/ffmpeg`. Pre-flight check: `ffmpeg -filters | grep subtitles` must list the filter.
- **Speed is applied last in the filter chain**: subtitles burn BEFORE `setpts` so the ASS timeline matches the original video; `setpts`/`atempo` then scale the already-burned pixels and the mixed audio. Same logic for both the danmaku layer and the cleaned-subtitle layer.
- **Cut boundary dialogues are dropped, not clipped**: when a danmaku/cleaned dialogue intersects a `--cut` range (even by a single frame), the whole dialogue is dropped. Rationale: simpler semantics, avoids partial-display weirdness. See `cuts.rewrite_ass_for_cuts`. The rewrite is ephemeral inside `burn.render` — the on-disk `<bv>.danmaku.ass` and `<bv>/speech.cleaned.ass` always stay un-cut for cache stability.
- **Burn output args satisfy merge strict mode**: every burn re-encode uses `-pix_fmt yuv420p -r 30 -ar 48000 -c:v libx264 -c:a aac` so `video2yt-merge`'s strict 1920x1080 30fps h264 yuv420p + AAC 48kHz check passes.

### Cache invalidation chain (spec §11 Q9)

- **`<bv>/.stems_source_meta.json`**: stems cache key. Records `{sha256: first-1MB-of-<bv>.mp4, duration, width, height, quality_label}`. Mismatch → song-remover re-runs.
- **Stage 3 cache** (post-speech2srt-integration 2026-05-27): video2yt no longer owns a subtitle cache. speech2srt writes its own sidecar pair at `<bv>/speech.wav.speech2srt.json` (cache key) + `<bv>/speech.wav.speech2srt.srt` (canonical SRT). Cache key includes wav sha256(first 1MB) + size + max_line_chars + cleanup-on + context sha256. Force-regen via `video2yt-subtitle --force-asr` (deletes the speech2srt sidecar pair before invoking). The legacy `<bv>/.speech_source_meta.json` + `speech.raw.srt` + threshold-keyed `speech.cleaned.*.srt` were all removed in T4/T5 of the speech2srt-integration plan.
- **`<bv>.music_bed_meta.json`**: music-mix cache key. Records `{duration, width, height}` with a 0.5s duration tolerance for ffprobe jitter. Mismatch → bed + credits regenerate atomically.
- **Atomic writes**: all meta sidecars + the music_credits.txt write to a `.tmp` and then `os.replace`. A mid-run crash never leaves a half-written sidecar that the next run would accept as cache-valid.

### yt-dlp / Bilibili

- **yt-dlp release cadence**: yt-dlp updates frequently because Bilibili's extractor rules shift. If downloads suddenly break, first try `uv lock --upgrade-package yt-dlp`.
- **aria2c auto-used (VIDEO call only) when on PATH**: `download.fetch` makes TWO yt-dlp calls — (1) danmaku XML via the **native** downloader, (2) video+audio via `--downloader aria2c --downloader-args "aria2c:-x16 -s16 -k1M --max-tries=10 …"` when `aria2c` is installed (16-connection, **bounded** retries) — survives Bilibili's flaky CDN mirrors (`upos-*-mirror*` read-timeouts) that make yt-dlp's single-stream downloader give up. aria2c must NEVER touch the danmaku XML: it chokes on the deflate-encoded subs with `libz::inflate() failed` and aborts Stage 1 (see `project_bilibili_download_robustness`), which is why the subs ride a separate native-downloader call. No-op if aria2c isn't installed (`brew install aria2`). Separate from the merger-hiccup guard (`TruncatedDownloadError` quarantines a video whose muxed audio got truncated and re-downloads).
- **Chrome cookie DB lock**: `--cookies-from-browser chrome` requires Chrome to not be holding the cookie database lock. If it fails, close Chrome first.
- **Bilibili VIP-locked 1080p**: some BV sources only expose 480p/360p without a premium account (yt-dlp `-F` confirms with `1080P ... you have to become a premium member`). `video2yt-merge` enforces strict 1920x1080 30fps h264, so a 480p burnt segment will fail merge late. **Pre-flight**: after `video2yt-fetch`, eyeball the "probing source video" log — if it warns about lower-than-requested resolution, either upscale via `ffmpeg -i in.mp4 -vf "scale=1920:1080:flags=lanczos" -c:v libx264 -preset medium -crf 20 -pix_fmt yuv420p -r 30 -c:a copy out.mp4` or swap source.

### Stems / song-remover

- **`--device remote` requires one-time Modal setup**: cli.run does an early Modal-token preflight (checks `~/.modal.toml` exists) so a misconfigured remote run fails BEFORE the 30s yt-dlp fetch, not after. Use `--device cpu` for offline runs (slower).
- **All 4 stems kept on disk**: `<bv>/{speech,music,sfx,no_music}.wav` are all preserved after Stage 2 finishes. Downstream stages only consume `speech.wav`; the other three are for manual inspection. User decision 2026-05-24: "先都留我自己删".
- **If you manually edit speech.wav, the cache regenerates**: the sidecar's sha256 won't match. To force regen WITHOUT changing speech.wav, delete `<bv>/.stems_source_meta.json` and re-run.

### Subtitle / speech2srt

- **Per-project context file is mandatory for quality**: speech2srt's `--cleanup` uses codex with a free-form `--context` string describing the streamer, 流派, key cards, 口頭禪, and known ASR error patterns. Authored per project at `output/<project>/subtitle_context.txt` (≤ 2 KB UTF-8). Pass via `video2yt --subtitle-context-file <path>` (full pipeline) or `video2yt-subtitle --context-file <path>` (standalone). NO sibling fallback (codex review caught that `<segment>.parent` lands in `temp/<dir>/`, not the project folder). When omitted, a stderr WARNING fires and speech2srt runs without context — quality drops.
- **Wall-clock**: cold ~3-6 min per 4-min segment (Volcengine ASR upload + 8 query polls + codex cleanup ~30s-13min depending on prompt length). Warm speech2srt cache hits return in <5s. T1 smoke on a real 4-min dragon_snip clip: 4:43 cold, ¥0.0981, 25 utterances.
- **Privacy**: audio bytes go to Volcengine (火山引擎) for ASR; cleanup text goes to OpenAI via codex. Sensitive recordings should pass `--skip-cleanup` (keeps audio local-only-to-Volcengine, no codex round-trip) OR `--no-subtitle` (no Stage 3 at all).
- **Force regen**: `--force-asr` deletes speech2srt's `<wav>.speech2srt.{json,srt}` sidecars BEFORE invocation. This forces a fresh ASR + cleanup AND repopulates the cache. (We deliberately avoid speech2srt's own `--no-cache` flag because it also skips the cache STORE.)
- **Subtitle CLI input is `<bv>.mp4`, NOT speech.wav**: the subtitle CLI needs ffprobe-derived dimensions for ASS PlayResX/Y. It looks up `<bv>/speech.wav` as a sibling internally; errors with "Run video2yt-stems first" if missing.
- **Exit codes propagated from speech2srt**: 1 (preflight / missing VOLCENGINE_API_KEY), 2 (input file problem incl. missing context-file), 3 (auth), 4 (quota), 5 (timeout/network), 6 (API business error), 7 (response parse). subtitle_cli preserves the speech2srt exit code unchanged.

### Music-mix (replacement bed build)

- **replacement risk reduction, not a guarantee**: song-remover's `speech.wav` is used as the dry voice in the final amix; the original music+SFX mix is discarded. Game sound effects are lost by design — Approach A trade-off, see the spec. The replacement replacement track also carries its own (very low) claim risk. Strong suppression, not mathematical guarantee.
- **Music library + attribution**: `~/.cache/video2yt/music/` is the source of truth. On first run music_mix auto-downloads a shipped manifest (`src/video2yt/data/music_library.json`) of calm Kevin MacLeod tracks from the Internet Archive — these are **CC BY 3.0, attribution required**. `music_mix.render` writes `<bv>.music_credits.txt`; the orchestrator copies it to `<bv>_final_music_credits.txt`; those lines MUST go in the YouTube description. To avoid attribution, drop YouTube Audio Library tracks into the cache dir by hand (cache files with no manifest entry need no credit). NEVER put YouTube Audio Library tracks in the manifest — its license forbids redistribution.

### Workflow / cleanup

- **`--keep-temp` is a no-op**: T7 of step6-restructure made the orchestrator preserve all per-stage caches by default (raw mp4 + xml + danmaku.ass + 4 stems + speech2srt sidecars + speech.cleaned.{srt,ass} + music_bed.wav). Flag kept for backwards CLI compat. To force a fresh run of a single stage, delete its meta sidecar (Stage 2 = `.stems_source_meta.json`; Stage 3 = both speech2srt sidecars OR use `video2yt-subtitle --force-asr`; Stage 4 = `<bv>.music_bed_meta.json`); to nuke a whole segment, delete the `temp/<dir>/` subfolder.
- **Output filename**: `<bv>_final[_cut][_<speed>x][_preview].mp4`. The legacy `_with_danmaku` / `_clean` / `_subbed` pipeline-stage suffixes are gone (T7 of step6-restructure) since one ffmpeg pass does all three.
- **Agent E2E test rule**: DO NOT run `rm -rf output/` or `rm -rf temp/` during E2E tests — that wipes every cached raw download and the outputs of unrelated videos. Clean only the specific `temp/<subfolder>/` under test, or just let the cache hit on the next run. This is a workflow rule, not a code invariant.
- **`video2yt-cleanup` is the ONLY blessed way to reclaim disk after shipping — never hand-roll an `rm -rf temp/*<glob>*`** (a past glob once wiped 5 unrelated caches). Policy (user has limited storage): after a video is uploaded, the CURRENT project's `temp/<source>/` caches are deleted (regenerable) while `output/<project>/` is KEPT as a one-period buffer; the PREVIOUS shipped project's whole `output/<project>/` is deleted. A "shipped project" requires `publication.json` with `status=complete`, a video ID, channel ID and valid upload timestamp. Metadata alone never qualifies. Upload and cleanup share process locks; cleanup archives lightweight artifacts to `assets/publications/<video_id>/` before deleting any media, and orders projects by receipt timestamps. Failed/incomplete uploads and legacy metadata-only projects are protected. Use verified `--adopt-video-id` recovery for old uploads, never fabricate receipts. The `--project` you name (or the inferred newest) MUST itself be a shipped project living inside `output/`; a non-shipped/infra folder or a path outside `output/` is refused (otherwise the real latest video would be mis-classified as "previous" and deleted). Current project's temp dirs are linked by two signals (matching `output/<project>/<segment>/` subfolder name **or** a `temp/<dir>/<bv>.mp4` for a BV referenced in the project). Every delete passes `cleanup.assert_within`, which refuses anything not strictly inside `./temp` or `./output` (and refuses the roots themselves + the current project). DRY-RUN is the default; `--yes` deletes; `--all-previous` sweeps every older project (default deletes only the single latest previous); `--no-prev` purges temp only. Run it as the final workflow step (after the subscribe comment).

### Dynamic intro (video2yt-intro)

The `video2yt-intro` composer (`intro_compose.py`) builds the intro in ONE ffmpeg pass: pale anime-sketch bg → SRT-timed card spotlights → animated sketch 女老板 mascot → dark ink subtitle. These were all caught by codex review of the design (do not regress them):

- **drawtext fontfile must be an ABSOLUTE `.ttc` path**: `fontfile='Hiragino Sans GB.ttc'` (basename) silently falls back to Verdana → CJK tofu. `resolve_font()` returns the first existing of `/System/Library/Fonts/Hiragino Sans GB.ttc` / `STHeiti Medium.ttc`.
- **Dynamic text via `textfile=` + `expansion=none`**: never interpolate user/card text into the filtergraph (`: ' % \ ,` newline break it). The optional title is written to `_title.txt` and referenced by basename (cwd trick).
- **`-framerate 30` before EVERY `-loop 1` image input**: looped stills default to 25 fps, so animation/gates would run at 25 and `-r 30` would duplicate frames.
- **Half-open card gates** `enable='gte(t,Sk)*lt(t,Ek)'` (plain commas inside the `'…'` quotes), Sk/Ek quantized to 1/30 s, so adjacent cards never double-show a seam frame. The last card runs to the exact audio duration (unquantized, else it overshoots).
- **First card has NO fade** (visible from t=0 lead-in); cards 2..N fade in. **Mascot rotate is bounded** `ow=rotw(0.045):oh=roth(0.045)` so the sway never clips.
- **Card timing** is resolved from the SRT with a forward cursor (a card's 中文卡名 is matched only in blocks at/after the previous card's match); no match → fail fast (or use an explicit `| start end` override). Display starts must be strictly increasing.
- **Visual style defaults to `anime-sketch`** for generated backgrounds, thumbnail polish and dynamic intro. Use real Japanese anime pencil-sketch art (graphite linework, light hatching, cream ivory paper and clearly visible Japanese pastel colored-pencil areas: mint green, powder blue, peach pink and apricot yellow; never near-grayscale or sepia-dominated), a matching `assets/branding/anime_sketch/mascot.png` with verified actual alpha (completed by user-authorized local extraction; original mascot is the fallback for a missing/opaque sketch asset), dark ink text with pale outlines, no gold glow or full-frame dimming. Official card art stays unchanged. See `docs/visual-style.md`. An old painted background must be regenerated; compositing does not redraw it.
- **Subtitle legibility**: sketch theme uses dark graphite with a 3px paper outline and no shadow; `--style warm-tavern` retains white subtitles and the reusable dark scrim (`assets/intro/intro_scrim.png`). Both use bold W6 at 54px, MarginL 80 / MarginR 680 / MarginV 120, capped to 2 lines.
- **Card-name captions were removed** (the card art already shows the name); the top title defaults OFF (`--title` optional).

### Compose / merge

- **compose SRT path escaping**: `compose.render` uses `cwd=<srt.parent>` and references the SRT by basename in the `subtitles` filter (same trick as `burn.py`). Absolute paths for `-i` inputs are fine because `-i` doesn't go through filter_complex.
- **merge media validation**: one or more 1920x1080 30fps h264 segments with audio and positive duration; short hooks and single-source videos are valid. Chapters are independent: use `--chapters-file` with final-video timestamps or `--no-chapters`. Automatic segment chapters are emitted only when valid (3+, 00:00 first, each ≥10s), otherwise omitted. Dimensions/codec still fail fast.
- **merge CFR-normalizes each video input before concat**: `_build_filter_complex` runs `[i:v]fps=30,setpts=PTS-STARTPTS` on every segment before the concat filter. Without it, a segment with internal PTS discontinuities — notably a `scripts/append_cta.sh` stream-copy `_cta.mp4` whose internal CTA join leaves a timestamp gap — makes the concat **filter** silently drop frames (cost ~23s on needle_duel; merge's own output-duration check catches it as a >1s mismatch). `fps=30` is a no-op on already-clean CFR segments, so this is safe + general.
- **Contextual CTA:** default to `video2yt-cta` text overlay after the first useful decision; retain gameplay/audio and record the exact time in `growth_plan.md`. Preview for collisions with cards/subtitles. `append_cta.sh` remains an optional full-screen variant, no longer mandatory between battles. A short CTA can also be an independent merge segment; use explicit editorial chapters to avoid making it a short chapter. Verify a concrete related video in Studio end screens after publishing.
- **merge chapters**: there is no burned-in progress bar — segmentation is delivered as chapter markers. The **only officially-supported** YouTube chapter source is timestamps in the video description (≥3 ascending, first at 00:00, each ≥10s, exactly one block). When chapters are enabled and valid, merge produces two outputs: `<title>_chapters.txt` is the description paste (this is the supported path); `<title>_ffmeta.txt` is embedded into the MP4 via `-map_metadata`/`-map_chapters` as a best-effort extra — YouTube does NOT officially document reading embedded chapter atoms, so do NOT treat the embed as a safety net. Common breakage: a description with two timestamp blocks (繁體 + 简体) is not strictly ascending and YouTube discards the whole list — keep the block to exactly one occurrence.

## Architecture

```
src/video2yt/
├── cli.py            # video2yt — orchestrator: chains the 5 stages, skip flags, per-stage timing
├── fetch.py          # Stage 1: yt-dlp + biliass; returns FetchResult dataclass
├── fetch_cli.py      # video2yt-fetch entry point
├── prefetch_cli.py   # video2yt-prefetch: serial pre-download of N sources into the
│                     #   Stage 1 cache (truncation retry + low-res quarantine + fail-fast)
├── download.py       # thin yt-dlp subprocess wrapper (cache check + format spec)
├── stems.py          # Stage 2: song-remover subprocess wrapper + .stems_source_meta.json
├── stems_cli.py      # video2yt-stems entry point
├── subtitle_cli.py   # video2yt-subtitle entry point; Stage 3 — shells out to
│                     #   the external speech2srt CLI (火山 Seed-ASR + codex cleanup),
│                     #   converts the SRT to <bv>/speech.cleaned.ass for Stage 5
├── music_mix.py      # Stage 4: replacement bed build + .music_bed_meta.json
├── music_mix_cli.py  # video2yt-music-mix entry point
├── music_library.py  # replacement manifest + download cache + track selection
├── burn.py           # Stage 5: single ffmpeg pass — chained subtitles + sidechain-ducked amix
│                     #   + ephemeral cut-rewrite + pre-flight cleaned-ASS symlink
├── burn_cli.py       # video2yt-burn entry point
├── meta.py           # shared sidecar helpers: atomic JSON, first-1MB sha256, meta_matches
├── compose.py        # ffmpeg wrapper for audio+image+SRT -> 1080p MP4 (legacy static intro); srt_to_ass shared by intro_compose
├── compose_cli.py    # video2yt-compose entry point
├── intro_compose.py  # dynamic intro: 女老板 narrator + SRT-timed card spotlight + scrim, single ffmpeg pass
├── intro_cli.py      # video2yt-intro entry point
├── merge.py          # strict segment validation, concat + per-seg loudnorm, chapters embed
├── merge_cli.py      # video2yt-merge entry point
├── playlists.py      # channel playlists: keyword classify (全集/異變/剋制轉型/郭楓荷) +
│                     #   idempotent add; video2yt-upload auto-adds every new upload
├── upload.py         # OAuth creds (7-day Testing-app token), videos.insert + thumbnail
├── upload_cli.py     # video2yt-upload entry point; channel guard + playlist auto-add
├── cleanup.py        # post-ship disk reclaim: find current project's temp/ caches +
│                     #   previous shipped project's output/ folder; assert_within path guard
├── cleanup_cli.py    # video2yt-cleanup entry point (dry-run by default, --yes to delete)
├── validate.py       # ffprobe + source/ASS/output validators
└── cuts.py           # cut range parsing, normalization, keep_ranges, ASS rewriter
```

Tests live in `tests/`, covering the individual stages, orchestrator, publication
recovery, cleanup, analytics, topic evidence, chapters, CTA and thumbnail styles.
Run `uv run --extra dev pytest -q`. External services are mocked; real FFmpeg
checks use local synthetic media and skip if their required tools are absent.
No production upload, OAuth grant or user-media deletion belongs in the suite.

`cli.run()` flow (the orchestrator, T7 of step6-restructure):

```
preflight → early Modal-token check (only when needs_stems and --device remote) →
Stage 1 fetch.fetch_and_build → Stage 2 stems.separate (gated on needs_stems) →
Stage 3 subtitle_cli.run (gated on --no-subtitle) → Stage 4 music_mix.render
(gated on --no-music-swap) → Stage 5 burn.render (single ffmpeg pass) →
copy music_credits.txt next to <bv>_final.mp4 → validate output
```

Each stage logs its wall-clock to the per-run timings summary.

## Feature flags quick reference

```
--quality {480,720,1080}: yt-dlp format height cap (Stage 1)
--codec {h264,h265,auto}: format codec preference (default h264 for YouTube) (Stage 1)
--font-face NAME:        ASS font family (default "Hiragino Sans GB", macOS-accessible CJK)
--font-size N:           Danmaku font size (default auto: video_height * 25/540 per Bilibili native)
--preview-seconds N:     ffmpeg -t clamp on output
--cut START~END:         remove time ranges, repeatable, ~ separator, SS/MM:SS/HH:MM:SS
--speed {0.5..2.0}:      playback multiplier via setpts+atempo (pitch preserved)
--no-subtitle:           skip Stage 3 (STT subtitle)
--subtitle-context-file: per-project free-form cleanup context for speech2srt (Stage 3)
--no-music-swap:         skip Stage 4 (replacement bed); Stage 5 maps source audio
--no-danmaku:            tolerate a source with no danmaku (低播放搬运/切片) instead of failing Stage 1's empty-ASS guard; danmaku layer is just empty. WITHOUT it, zero danmaku stays a hard error (catches a failed danmaku download)
--device {cpu,mps,auto,remote}: Stage 2 song-remover device (default remote = Modal GPU)
--chunk-min N:           Stage 2 chunk length for --device remote (default 5)
--keep-temp:             no-op (everything kept by default since T7)
```

## Publication receipts and analytics

`video2yt-upload` writes an atomic `publication.json` before and after upload, resumes thumbnail/playlist work using the existing ID, and refuses automatic repeat inserts after an uncertain interruption. Same project with a different video or upload metadata is rejected; edit remote metadata in Studio deliberately. An intentionally changed thumbnail can be retried against the same video. Archive verified uploaded artwork separately from local variants.

`video2yt-analytics import|collect|report` saves measurements in `assets/analytics/`, outside disposable outputs. Analytics uses separate read-only OAuth and `youtube_analytics_token.json`. API daily buckets are not exact 24-hour windows; public `publishedAt` is used when verified, otherwise upload time is labeled as a proxy. CTR, impressions, new viewers and exact 30-second retention are Studio imports. Full commands and evidence/experiment checklist: `docs/growth-workflow.md`.
