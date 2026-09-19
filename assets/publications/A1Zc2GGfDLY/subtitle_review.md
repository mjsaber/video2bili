# escapist_core subtitle review (raw ASR vs subagent-cleaned SRT)

Reviewed 2026-09-16. Read-only review; no SRT was modified.

- guo: raw `temp/炉石郭枫：逃脱大师配置要正确，不然酒馆小钱不够！/BV1Wsew6eEfW/speech.wav.speech2srt.srt` → `output/escapist_core/guo.cleaned.srt` (audit `guo_subtitle_audit.md`)
- night: raw `temp/高冷难神：【夜吹的战棋日记2336】自残恶魔，逃脱大师才是恶魔的核心！/BV1GMew6LEWj/speech.wav.speech2srt.srt` → `output/escapist_core/night.cleaned.srt` (audit `night_subtitle_audit.md`)
- Glossary: `output/escapist_core/subtitle_context.txt`

Checks a–d were run by script (scratchpad `check.py` / `check3.py`); the full raw-vs-cleaned side-by-side of every block was also read end to end for the meaning review.

## (a) Structure — PASS (both)

| file | raw blocks | cleaned blocks | index+timestamp lines identical | numbering 1..N in order |
|---|---|---|---|---|
| guo | 138 | 138 | yes (0 mismatches) | yes |
| night | 171 | 171 | yes (0 mismatches) | yes |

`[DROP]` blocks: guo 16 (#47 65 83 84 85 91 92 93 95 98 104 121 124 129 133 134), night 35 (#9 10 11 12 19 20 22 23 29 40 50 61 63 78 81 83 93 97 99 100 101 113 115 116 119 127 129 130 131 132 137 152 153 154 164). Every `[DROP]` is exactly one line `[DROP]`, matching the audits' counts.

## (b) No Simplified-only characters — PASS (both)

Scanned every non-`[DROP]` line against the mandated list (这 个 说 对 时 会 没 后 还 为 么 发 过 让 样 应 该 现 实 强 帮 买 卖 谁 边 张 转 几 关 头 见 战 术 圣 阵 与 击 满 达) plus ~90 additional Simplified-only characters (们 来 种 东 问 题 开 点 场 里 输 赢 变 换 动 进 给 两 条 钱 择 类 马 鸡 飞 龙 师 纸 铁 药 蛋 胜 负 钟 结 组 织 务 讲 阶 级 尽 驱 轮 随 财 风 异 办 认 识 经 验 规 则 处 长 门 间 闪 电 绝 确 证 据 话 语 记 录 乐 观 众 听 闻 声 响 连 续 继 断 减 简 单 复 杂 难 …). Hits: **none** in either file. (A first pass with an over-broad table flagged 它/西/盾/回/呀/吧/哪/少 — those are all valid Traditional characters, i.e. false positives, not findings.)

## (c) Line length ≤ 22 and ≤ 2 lines per block — PASS (both)

| file | max line length | lines > 22 | blocks > 2 lines | empty blocks |
|---|---|---|---|---|
| guo | 22 | 0 | 0 | 0 |
| night | 19 | 0 | 0 | 0 |

## (d) Term compliance — PASS (both)

No remaining occurrences of 逃脫大師 / 逃脱大师 / 淘淘大师 / 陀螺大师 / 淘特大师 / 淘汰大师 / bare 逃脱 / 塞拉斯 / 唐三 / 萨格拉斯 / 巴林达 / 巴林達 / 酒馆 / 酒館 in either cleaned file. No 薩格拉斯 without 之眼.

| term | guo blocks | night blocks |
|---|---|---|
| 逃脫者 | 3, 23, 74, 80, 88, 89, 138 | 86, 87, 95, 96, 105, 158, 159 |
| 希拉斯 | 9, 110 | — (not in source) |
| 薩格拉斯之眼 | 117 | — (not in source) |
| 巴琳達 | — (not in source) | 122 |
| 銅鬚 | — (not in source) | 44, 46, 49 |

Also confirmed: 旅店 in guo #136 (酒馆→旅店), 爆手牌 in night #82/126/138/139/163, 觸發戰吼 in night #118.

## Spot-check (15 random non-[DROP] blocks per file, seed 20260916)

Verdict key: OK = script conversion / punctuation / obvious ASR fix only, meaning preserved.

### guo

| # | raw | cleaned | verdict |
|---|---|---|---|
| 6 | 这英雄这把门任务太容易完成了，超级容易完成。 | 這英雄這把任務太容易完成了，／超級容易完成。 | OK (dropped stray 门) |
| 14 | 偷了比较好，感觉。 | 偷了比較好，感覺。 | OK |
| 21 | 左右西西猪。 | 左右吸吸豬。 | OK (matches #20 左吸一下右吸一下) |
| 31 | 我的亲哥！ | 我的親哥！ | OK |
| 49 | 滂臭啊，简直。 | 滂臭啊，簡直。 | OK |
| 50 | 真是势不可挡别呀，兄弟，你踢啥呢？ | 別呀，兄弟，你踢啥呢？ | OK (game voice line 真是勢不可擋 stripped) |
| 67 | 唯一一个有盾的是他，这你敢信？ | 唯一一個有盾的是他，這你敢信？ | OK |
| 78 | 因为一号位要卖掉了，所以说不要了，我要玩手动留车吧。 | 因為一號位要賣掉了，所以說不要了。 | OK (unintelligible tail dropped; #79/#80 carry the point) |
| 88 | 淘汰大师和猪头是冲突的，没有配合。 | 逃脫者和豬頭是衝突的，沒有配合。 | OK (glossary) |
| 90 | 其实是有点冲突的。 | 其實是有點衝突的。 | OK |
| 97 | 好吧，这个我还真不知道。 | 好吧，這個我還真不知道。 | OK |
| 109 | 他把我的毒破了，让我输了。 | 他把我的毒破了，讓我輸了。 | OK |
| 123 | 因为确实我不会买恶魔现在，小粉确实可以走。 | 因為現在我確實不會買惡魔，小粉確實可以走。 | OK (word-order tidy, same meaning) |
| 125 | 还是没金王子，有金王子应该会舒服很多。 | 還是沒金王子，有金王子應該會舒服很多。 | OK |
| 137 | 卡成这样怎么用一个随从加入我们的队哎呀，快点呀！ | 卡成這樣怎麼用？哎呀，快點呀！ | OK (voice line 隨從加入我們的隊 stripped) |

### night

| # | raw | cleaned | verdict |
|---|---|---|---|
| 15 | 哦，这里不就偷了两木棍。 | 哦，這裡不就偷了兩木棍。 | OK |
| 37 | 四五九万，你主要也没身材呀。 | 你主要也沒身材呀。 | OK (garbled 四五九万 dropped) |
| 52 | 这真是好东西。 | 這真是好東西。 | OK |
| 56 | 恶魔是什么？ | 惡魔是什麼？ | OK |
| 75 | 要不要换呀？ | 要不要換呀？ | OK |
| 76 | 好想升本啊。 | 好想升本啊。 | OK |
| 77 | 真是个设计小天才。 | 真是個設計小天才。 | OK |
| 85 | 但有个问题啊。 | 但有個問題啊。 | OK |
| 120 | 啊滚吧，别触发了啊，他肯定不存在好吧。 | 啊滾吧，別觸發了啊，／他肯定不存在好吧。 | OK |
| 123 | 然后我再看这里面有没有那谁，有没有金色的那谁，没有。 | 然後我再看這裡面有沒有那誰，／有沒有金色的那誰，沒有。 | OK |
| 143 | 妈，就一个盾吗？ | 就一個盾嗎？ | OK (swear removed per glossary) |
| 144 | 你不会吃不到吧？ | 你不會吃不到吧？ | OK |
| 148 | 能不能换一个这个呢？ | 能不能換一個這個呢？ | OK |
| 163 | 这里应该先清清手牌的，妈的爆牌了回头。 | 這裡應該先清清手牌的，靠，爆手牌了。 | OK (妈的→靠, 爆牌→爆手牌 per glossary) |
| 165 | 不知道该不该上，我是不知道该上食尸鬼，该上火车王啊。 | 不知道該不該上，／不知道該上食屍鬼，還是該上火車王啊。 | OK (added 還是 for readability; same meaning) |

No invented content or meaning changes found in the samples.

### Additional findings from the full side-by-side read (all 309 blocks)

None of these block burn; listed for transparency.

- guo #8 买它个鸡 → 買它個技能: inferred from #7 (兩塊錢能買他一個技能). Plausible; keep.
- guo #55 我有5杀，我怎么死 → 我有5刷，我怎麼死: 殺→刷 is an ASR-fix inference supported by #53 (我這裡有5刷，我怎麼鎖) two blocks earlier; keep, low risk.
- guo #2 机器 → 機械 (tribe name), #87 个人 → 個頭 (size), #116 没错不胡闹吗 → 這不胡鬧嗎 (matches #68): reasonable ASR fixes; keep.
- guo #52 圣盾登录这么多锁啥呀 → 這麼多，鎖啥呀: 圣盾登录 treated as a voice-line fragment; it is unintelligible either way, keep.
- night #38 22 23个 → 22、23號: inferred from #39 (22號); keep.
- night #170 dropped 小粉的 from 觸發小粉的特效 → 觸發特效 to fit the line cap; #170's first half still says 小粉帶毒, so the referent is clear. Acceptable.
- Whole-block drops were checked one by one: every `[DROP]` in both files is a game voice line, song lyric, garbled text, chat noise, or bare filler/swear. No gameplay commentary was dropped.

## Verdicts on the audits' judgment calls

### guo

| # | raw → cleaned | verdict | reason |
|---|---|---|---|
| 43 | 读的读的他那个28的 → 毒掉他那個28的 | **keep** | 毒 is the segment's established plan (#15 偷了兒子可以下毒, #17/#18 退路就是下毒, #109 他把我的毒破了); "poison his 28" is the only reading that fits. |
| 58 | 这个未读，那个59的未读 → 這個沒毒，那個59的沒毒 | **keep** | Same poison context; 未读 is a homophone of 没毒 and "that 59 has no poison, I have a chance" is coherent combat talk. |
| 66 | 没动了 → 沒盾了 | **keep** | Immediately followed by #67 唯一一個有盾的是他，這你敢信 — 盾 is the topic; 動 makes no sense there. |
| 110 | 没钱买罐 → 沒錢買怪 | **keep** | 沒錢買怪，沒錢刷 is the standard BG phrase; 罐 has no referent in this game. |

### night

| # | raw → cleaned | verdict | reason |
|---|---|---|---|
| 49 | 哪来的金童啊 → 哪來的金銅鬚啊 | **keep** | #44/#46 establish 銅鬚 appearing repeatedly and #47 says 想複製這個…搞成金的; "where did the golden Brann come from" is the natural reading, and 金童 alone would be meaningless on screen. |
| 84 | 把镜花教一教 → 把鏡花交一交 | **keep (low confidence)** | 鏡花 is an unverified nickname and neither 教/交 is verifiable from context; the change is a one-character homophone swap with no term or meaning risk, and there is no evidence to prefer the raw form — not worth a revert, but if the listener hears something else at 09:30 this is the block to fix. |
| 147 | 什么都没用先把西用完 → 什麼都沒用，先用完 | **keep** | 西 is a garbled fragment (same pattern as guo #21 西西→吸吸, but here no referent); trimming it preserves the speaker's point (use everything up first) without inventing a word. |

## Final

- guo.cleaned.srt — checks a–d all PASS, spot-check clean, 4 judgment calls keep.
- night.cleaned.srt — checks a–d all PASS, spot-check clean, 3 judgment calls keep (#84 low confidence, non-blocking).

READY FOR BURN: yes (guo)
READY FOR BURN: yes (night)
