# night (夜吹 BV1GMew6LEWj) subtitle cleanup audit

- Source: `temp/.../BV1GMew6LEWj/speech.wav.speech2srt.srt` (raw speech2srt, 171 blocks, ends 00:21:10)
- Output: `output/escapist_core/night.cleaned.srt`
- Blocks: **171** (all block numbers + timestamps preserved verbatim, verified by diff)
- `[DROP]`: **35**
  - game voice lines: 9, 10, 11, 12, 19, 40, 63, 78, 83, 99, 101, 116, 127, 129, 130, 131, 132, 137
  - chat-noise / no game content: 20, 22, 23, 119
  - pure filler: 81, 97, 115
  - unintelligible / garbled: 29, 50, 61, 93, 100, 113, 152, 153, 154, 164

## Card / hero / term normalizations (before → after, block numbers)

| before | after | blocks | note |
|---|---|---|---|
| 淘淘大师 | 逃脫者 | 86, 87 | glossary |
| 逃脱大师 | 逃脫者 | 95, 105, 159 | glossary |
| 陀螺大师 | 逃脫者 | 96 | glossary |
| 逃脱 (bare) | 逃脫者 | 158 | "第一次玩逃脱" = the card |
| 巴林达 | 巴琳達 | 122 | glossary |
| 同需 / 同学 | 銅鬚 | 44, 46 | tóng xū mis-hearing of 銅鬚 (Brann); ASR context "我選戰吼" confirms |
| 金童 | 金銅鬚 | 49 | inferred from 46–47 (拿銅鬚 → 搞成金的); flag if listener disagrees |
| 爆牌 | 爆手牌 | 82, 126, 138, 139, 163 | glossary |
| 出发战吼 | 觸發戰吼 | 118 | homophone |
| 夏伦 | 下輪 | 105 | homophone |
| 没读 | 沒毒 | 126 | poison context (157/168) |
| 食尸鬼 / 火车王 | 食屍鬼 / 火車王 | 165 | script conversion only |
| 圣盾 / 战吼 / 三连 / 升本 / 挖矿 / 猪 | 聖盾 / 戰吼 / 三連 / 升本 / 挖礦 / 豬 | 161; 44,118,170; 45; 18,76; 42,47,48,53,54; 107,108 | script conversion, nicknames kept |

Kept unchanged (streamer nicknames): 小粉, 二王, 挖礦, 大學生, 熊貓, 15, 曲奇, 奇魂打擊樂手, 黑暗之刺, 麵包, 耳環, 鏡花 (unverified nickname, literal).
薩格拉斯之眼 / 惡魔野豬 / 希拉斯 do not occur in this segment's ASR.

## Profanity
- 他妈 (23) → block dropped (chat noise); 我操 (95, 163 妈的) → 「靠」; 我操他的 (119), 我操 (162), 妈的 (161), 妈 (143) → swear word removed, sentence kept.
