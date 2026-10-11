# val.cleaned.srt review (瓦莉拉 BV1AAey6UEVb) — 2026-09-19

Raw: `temp/炉石传说：【炉石瓦莉拉】兄弟你好猛啊/BV1AAey6UEVb/speech.wav.speech2srt.srt` (82 blocks)
Cleaned: `output/slaughter_undead/val.cleaned.srt` (82 blocks)

## Verdict: READY (after 2 fixes applied below)

## Checks
1. Structure: 82/82 blocks; every block number and timestamp identical to raw (script-verified).
2. Traditional Chinese: full-character scan with opencc `s2t` — no simplified characters remain
   (only diffs were 吃→喫, an opencc variant artifact; 吃 is standard zhTW). 亡靈 correct in block 18.
3. Term map: 宰割/仔哥/仔大哥→屠殺 (17, 23, 45, 46); 萨拉刘斯→塞納留斯 (11);
   施法者肖像/示法者肖像/西巴倒肖像→淵喉施法者頭像 (31, 63, 65); 法强→法強 (61, kept as 口語 per context);
   吃鸡→雞 (64, 65 「雞給我了」). No 复生/时尚魅影 occurrences in this source. No leftover simplified terms.
4. Profanity: 他妈/我操/傻逼 all removed or replaced with 靠 (12, 40, 44, 71, 72, 73, 80, 82). None remain.
5. Line length: max 21 chars/line (block 81); no block exceeds 2 lines.
6. No invented content: every kept line traces to the raw. Paraphrases are minimal and faithful
   (17 「你昨天是正道的光」, 40 「牌好爛」 replacing profanity, 61 「不宜特」completed to 「不宜特別多」 in parallel with the next clause).
7. [DROP] decisions: Bob voice lines (14, 21, 27, 28, 29, 34, 35, 47, 48, 57, 67, 68), pure fillers/garble (10, 26, 36, 41, 43, 69, 79) — all reasonable; streamer speech kept.

## Fixes applied (to val.cleaned.srt; numbers/timestamps untouched)
Rationale: `compose.srt_to_ass` has no display-duration clamp, so text stays on screen for the block's
whole span. The ASR merged these two trivial streamer phrases with Bob lines / lyrics much later, so the
timestamp span is far longer than the speech; the 4-char text would hang across an entire battle.

- block 19: "這個我買了。" -> "[DROP]"   (span 00:04:12–00:04:31 = 19 s, raw was lyrics + 「这个我买了」)
- block 62: "是手爛了。" -> "[DROP]"     (span 00:17:03–00:18:22 = 80 s, raw was 「是手烂了」+ Bob 「你是对的，我收下了」)

## Notes (no change made — timestamps are out of scope for this review)
- Blocks 30 (21 s), 61 (22 s) and 82 (41 s, to 25:22) also have long spans, but the text is decision-relevant
  (61 法強配置, 82 「1% 失敗率」 is a key beat), so they are kept. If the hang looks bad in the burn preview,
  the only clean fix is trimming the end timestamp by hand (e.g. 82 → 00:24:44).
- Block 20 「你真是個設計小天才，對吧？」: raw merged the streamer's remark with Bob's 「你该雇几个新人」;
  the cleaner kept the streamer part and attached the trailing 「對吧」. Acceptable.
