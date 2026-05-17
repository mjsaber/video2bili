# video2yt Backlog

Items deferred from production runs. Use when project pressure subsides.

---

## Subtitle punctuation gap (Phase 3 candidate)

**Recorded**: 2026-05-17 (during `kalecgos-dual-build` first end-to-end run)

**Problem**: Subtitles burnt by `video2yt-subtitle` arrive **without punctuation or natural sentence breaks**. The on-screen reading experience is poor — long unbroken runs of characters that don't track the speaker's pauses. The audience sees a wall of text drifting across the bottom band.

**Reproduction**: any `cleaned.srt` produced under Phase 2 satload glossary. Example from `kalecgos-dual-build` segment A:

> `你先记一些优质法术备用比如寒热骤变有成长也能有经济虽然阵容大部分都是中立随从每局都有但邪火咒龙只会在有龙和恶魔的对局出现...`

No `，`, `。`, `？` anywhere in the cleaned form despite the speaker clearly using sentence-level pauses on the audio.

**Possible root causes** (not yet verified):

1. **whisperx VAD segmentation** chops by silence gaps, not grammatical boundaries. The 44 raw segments in A are timestamps-of-speech-runs, not phrases.
2. **`subtitle.py::split_subtitle_lines`** (the 44 → 62 entries step) splits by character count (MAX_LINE_CHARS=33), not by syntactic structure. Lines break mid-clause whenever the char counter trips.
3. **Codex cleanup prompt** explicitly says "只修正错字、术语、人名；不改写语意、不增删句子" — it forbids adding punctuation. The prompt would need to be relaxed/expanded.

**Candidate fixes (brainstorm, not committed)**:

- **(a)** Loosen the Codex prompt: add "在自然語法停頓處補上適當的逗號和句號；保持簡體，不改字數超過 ±20%" to `_build_cleanup_prompt`. Lowest impl cost. Risk: Codex might add punctuation that confuses the SRT split step, increasing line count beyond what timing supports.
- **(b)** Add a deterministic post-cleanup step: use `jieba` POS tagging + punctuation rules to insert `，` at phrase boundaries before the split step. More predictable than (a) but adds a dependency and a tunable.
- **(c)** Re-run whisperx with `word_timestamps=True` and replace the current paragraph-level split with word-aligned syntactic re-segmentation. Highest quality output, but ASR re-run is 8 min/episode and breaks the cleaned.srt cache contract.

**Priority**: **Phase 3** — wait until the current `kalecgos-dual-build` project ships and a few more episodes accumulate, so we have a stable corpus to measure fix candidates against. Do NOT touch in mid-production.

---

(Add new backlog items below as separate `## ...` sections with `**Recorded**: <date>`.)
