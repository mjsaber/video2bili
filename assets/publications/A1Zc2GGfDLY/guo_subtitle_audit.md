# guo.cleaned.srt audit (郭楓荷 BV1Wsew6eEfW)

- Source: `temp/…/BV1Wsew6eEfW/speech.wav.speech2srt.srt` (raw speech2srt, no codex cleanup)
- Blocks: 138 (all block numbers + timestamps preserved verbatim, verified by diff)
- `[DROP]` blocks: 16 — #47 #65 #83 #84 #85 #91 #92 #93 #95 #98 #104 #121 #124 #129 #133 #134
  - English lyrics / garbled letters: #47 (also stripped lyric fragments from #35, #48, #75)
  - In-game voice lines: #83 你選中了一個高貴的隨從, #84 我會盡力的, #85 是該找個更好的, #124 找個更好的來, #133 什麼能比這個隨從的組成更美麗, #134 這裡有些不錯的新人 (voice-line fragments also stripped from #50 真是勢不可擋, #112/#137 隨後加入我們的隊, #52 聖盾登錄)
  - Chinese song lyrics: #91 #92
  - Pure filler / swear only: #93 啊？, #95 我操！, #104 我操。
  - Unintelligible: #65, #98 云呢, #121 奧克蘭特三, #129 個117K的好男寵女
- Profanity: 我操 → 靠 in #26, #75; dropped in #95, #104

## Card / hero term normalizations (before → after, block numbers)

| Before (ASR) | After | Blocks |
|---|---|---|
| 逃脱大师 | 逃脫者 | 3, 23, 80, 138 |
| 淘特大师 | 逃脫者 | 74 |
| 淘汰大师 | 逃脫者 | 88, 89 |
| 唐三 | 希拉斯 | 9 |
| 塞拉斯 | 希拉斯 | 110 |
| 萨格拉斯 | 薩格拉斯之眼 | 117 |
| 酒馆 | 旅店 | 136 |
| 猪头 | 豬頭 (nickname kept) | 88, 89 |
| 猪 | 豬 (kept; not clearly the card) | 20, 21, 86, 87 |
| 儿子 / 宝宝 / 学徒 / 小粉 / 二王 / 挖矿 | 兒子 / 寶寶 / 學徒 / 小粉 / 二王 / 挖礦 (nicknames kept, Traditional form) | 7, 12–20, 22–25, 29, 81, 122, 123 |

## Non-term ASR fixes worth a glance

- #43 读的读的 → 毒掉 (poison context, #15/#109)
- #58 未读 → 沒毒
- #66 没动了 → 沒盾了 (next line #67 唯一一個有盾的是他)
- #110 买罐 → 買怪
- #2 tail 还不如普通枪玩, #78 tail 我要玩手动留车吧, #122 留王水 — unintelligible fragments omitted, rest of block kept
- 巴林达 did not occur in this transcript.
