# Phase 2：bg_glossary.yaml 扩充 + schema 升级

**Worktree**: `thirsty-rubin-d7e5bd`（继续）
**Started**: 2026-05-16
**Scope**: 把 `bg_glossary.yaml` 从 v0（0 corrections + 12 canonical）扩到 v1（~50 corrections + ~430 canonical），同时把 YAML schema 升级到 category-grouped。**只动字幕侧；不动发布层。**

## Decisions locked (from Phase 2 brainstorm)

- Q1=hybrid（HearthstoneJSON 爆发 canonical；corrections 增量增加）
- Q2=HearthstoneJSON 为主，battle.net zhCN 备用
- Q3=C（英文专名双向收，canonical 列英文表明合法）
- Q4=不预收 identity entry
- Q5=不做 OpenCC（Phase 1 实测稳定）
- Q6=收俚语（F-3 先给候选清单等用户过）
- Q7=做 schema 升级（category-grouped YAML，扁平注入 Codex）
- Q8=先静态全量（Codex prompt 容量监控；超阈值时再切按需检索）
- Q9=不做 `video2yt-glossary-suggest` 工具
- Q10=加 schema + 关键词条存在性单测
- Q11=v1 完成标准：≥4 类 canonical 齐全（hero/race/mechanic/meta）≥50 条总量

---

## Schema 设计

### 新 YAML 结构

```yaml
# 字段一：corrections（错→对，扁平字典；与 v0 相同）
corrections:
  寒热骤变: 寒热剧变      # 可选行内注释；推荐写 source + date
  铁路宝钻针: 铁炉堡锻砧   # observed BV1Z..., 2026-05-16

# 字段二：canonical（升级！）—— 从扁平 list 改为 category-grouped dict
canonical:
  hero: [拉法姆, 加拉克隆, ...]
  minion: [雪人军士, ...]
  spell: [寒热剧变, ...]
  trinket: [铁炉堡锻砧, ...]
  race: [海盗, 野兽, 恶魔, 机械, 元素, 亡灵, 龙, 娜迦, 类人, 法力虚灵]
  mechanic: [刷新, 冻结, 三连, 发现, 战吼, 亡语, ...]
  meta: [炉石传说, 战棋, 酒馆战棋, 英雄战场]
  english: [Brann, Bob, Patches, Triple, Discover, buff, refresh, ...]
  slang: [白板, 鬼装, 金身, ...]   # F-3 用户审过的子集
```

### Reader 实现细节

`subtitle.load_glossary` 要双格式兼容（不破坏 Phase 1 v0 测试）：

```
if canonical_field is a list of strings:           → v0 扁平格式
    flat_canonical = list  (照搬)
elif canonical_field is a dict of {str: list[str]}: → v1 grouped 格式
    flat_canonical = sum(group_lists, [])
                      按 category 顺序 hero → minion → spell → trinket →
                      race → mechanic → meta → english → slang
                      （每组内保留 YAML insertion order）
else:
    ValueError
```

返回的 `Glossary` dataclass **不变** —— 仍然是 `corrections: dict, canonical: list[str]`。category 信息只存在于 YAML 文件和 reader 局部变量；Codex prompt 见到的依旧是扁平 list。这样不动 `_build_cleanup_prompt`，零回归风险。

向后兼容测试：Phase 1 v0 的旧 `bg_glossary.yaml`（扁平 canonical list）能被新 reader 解析为相同的 `Glossary` 实例。

### Codex prompt 注入逻辑

**不变**。`_build_cleanup_prompt` 继续把 `glossary.canonical` 这个 flat list 按 `  - {term}` 格式拼进 prompt。category 顺序由 reader 决定，对 Codex 透明。

按 category 顺序排意味着 Codex 看到的 canonical block 形如：

```
首选用词（若有歧义请偏向以下形式）：
  - 拉法姆
  - 加拉克隆
  ... (heroes first)
  - 雪人军士
  ... (then minions)
  - 海盗
  ... (then races)
  - 刷新
  ... (then mechanics)
  - 炉石传说
  ...
```

按相关概念聚集对 Codex 的注意力分配更友好（同类词聚类）。

---

## 数量级预算与 prompt 容量

| Category | 上限 | 备注 |
|---|---|---|
| hero | 80 | 完整 BG 轮换池；名字短易混淆 |
| minion | **150**（仅当前轮换） | **不收历史池子**（避免 Codex 把退役随从套回来） |
| spell | 40 | BG-only 法术池较小 |
| trinket | 80 | 大小饰品全收 |
| race | 10 | 完整列出 |
| mechanic | 40 | BG 动词 + 通用 HS 关键字 |
| meta | 10 | 产品名 + 频道 vocabulary |
| english | 40 | Q3=C 的混用词 |
| slang | 30 | F-3 用户审过的子集 |
| **canonical 总量** | **~480 条上限** | v1 不必达上限，~250 起步即可 |
| corrections | ~50（v1 起步） | 仅从实测 raw.srt 收集 |

### Prompt 容量估算

参考 Phase 1 Stage E（0 corrections + 12 canonical, 2 ASR segments, 47s clip）：
- 总 prompt ≈ 500 chars input → Codex wall-clock 169s

Phase 2 v1 满载预估（50 corrections + 250 canonical + 200 ASR segments 来自 20 分钟视频）：
- header ~150 chars
- 50 corrections × ~25 chars/行 = ~1250 chars
- 250 canonical × ~12 chars/行 = ~3000 chars
- 200 ASR 输入 × ~60 chars = ~12000 chars
- footer ~80 chars
- **合计 ~16500 chars input**

按 Stage E 单位时间外推（500 chars → 169s ≈ 0.34s/char），16500 chars → **~5600s** ≈ **93 min**。这**严重超过 1200s timeout**。

**结论与对策**：

| 触发条件 | 行动 |
|---|---|
| 单次 cleanup 输入 < 5000 chars（如 1-2 分钟短片段，glossary 满载） | 现状 1200s 够用 |
| 5000 ≤ 输入 < 12000 chars | **F-5 实测后**：若不超时则维持；超时则把 `CLEANUP_TIMEOUT_SECONDS` 调到 1800-2400s |
| ≥ 12000 chars（典型 20+ 分钟视频满载 glossary） | **必须做 Q8=B 按需检索** —— Phase 2.5 议题；本 Phase 不实现 |

**Phase 2 v1 范围内**：用 clip60.mp4（60s, ~150 ASR segments 中只 2 段实质内容）做 F-5 端到端验证。完整 20 分钟视频的 cleanup 走通是 Phase 2.5 的事。

---

## Stage F-0：Schema 升级

**Goal**: YAML 结构改 category-grouped；reader 双格式兼容；新增 schema 单测。**不加任何新词**（保持 Phase 1 v0 的 0 corrections + 12 canonical）。

**Files**:
- `src/video2yt/data/bg_glossary.yaml`（结构改：canonical 从 list 变 dict，内容仍是当前 12 词，分到 race/meta 两类）
- `src/video2yt/subtitle.py::load_glossary`（双格式兼容 reader）
- `tests/test_subtitle.py`（新增几条 schema 单测）

**Success Criteria**:
- 旧测试 460 个全绿
- 新增测试：v1 grouped YAML → 扁平 Glossary（顺序确定）
- 新增测试：v0 flat YAML → 同样的扁平 Glossary（向后兼容）
- 新增测试：bg_glossary.yaml 现在的 corrections + canonical 总条目 > 0

**Commit**: `refactor(subtitle): glossary schema → category-grouped; reader backward-compatible`

**Status**: Complete

---

## Stage F-1：HearthstoneJSON 数据采集

**Goal**: 写一次性 harvester 脚本，从 HearthstoneJSON 拉 BG-tagged 卡的 zhCN 卡名，填入 `bg_glossary.yaml` 的 `hero/minion/spell/trinket` 类。

**Files**:
- `scripts/harvest_hearthstone_json.py`（新建；一次性脚本，不在 distribution 中）
- `src/video2yt/data/bg_glossary.yaml`（追加 hero/minion/spell/trinket）

**Steps**:
1. 验证 HearthstoneJSON 是否仍提供 BG-tagged 数据（URL 形如 `https://api.hearthstonejson.com/v1/latest/zhCN/cards.json`）。如失效，回退到爬战网 zh-cn 卡牌库。如两者都不行，**停下来汇报**。
2. 脚本读取 JSON，筛选 `set` 包含 `BATTLEGROUNDS` 或 `mechanics` 含 `BG_*` 的条目。
3. 按 type 分类（HERO / MINION / SPELL / BATTLEGROUND_TRINKET）。
4. 输出去重 + 排序后的列表到 stdout（人工 inspect）；脚本不直接写 YAML 文件（防误写）。
5. 我手工把脚本输出贴进 `bg_glossary.yaml`。
6. 砍掉明显冗余项（如卡背、皮肤）。

**Success Criteria**:
- hero 类 60-80 条
- minion 类 100-150 条（当前轮换；如果 HearthstoneJSON 区分历史/当前，优先当前）
- spell 类 20-40 条
- trinket 类 50-80 条
- YAML 合法、reader 正确加载
- 现有 460 测试 + Stage F-0 新测试全绿

**Commit**:
- `feat(scripts): add HearthstoneJSON harvester for BG cards`（脚本本身）
- `data(glossary): populate hero/minion/spell/trinket from HearthstoneJSON`（YAML 数据）

**Status**: Complete

**风险**: HearthstoneJSON 可能不区分 BG 轮换池；可能需要二次筛选。如果输出量过大（minion > 300），先报你看是要砍还是接受。

---

## Stage F-2：race / mechanic / meta 手工补齐

**Goal**: 我列候选清单 → 你过 → 写入 YAML 的 race/mechanic/meta 三类。

**候选清单**（这一步会在 chat 里给你过，类似 F-3 的流程）：

**race**（基本没歧义，直接给）：
```
海盗、野兽、恶魔、机械、元素、亡灵、龙、娜迦、类人、法力虚灵
```

**mechanic**（待你确认词条）：
```
刷新、冻结、三连、发现、战吼、亡语、圣盾、嘲讽、剧毒、嗜血、连击、超杀、
酒馆升级、酒馆 N 等、升等、卖、买、招募、过秤、压等、跳费、上等
```

**meta**：
```
炉石传说、战棋、酒馆战棋、英雄战场
```

**Success Criteria**:
- 3 类总计 50-80 条
- YAML 合法
- 测试全绿

**Commit**: `data(glossary): add race/mechanic/meta categories`

**Status**: Complete

---

## Stage F-3：俚语候选清单（先停一下等用户）

**Goal**: 我**先给你一份 30-50 个候选俚语清单**，你 trim 后我才动 YAML。

**清单结构**（在 chat 里出，不写文件）：
- 流派名：背靠背、九鸡野兽、戒指龙流、二鸟、三鸟、刷子流、雪球流……
- 装备/属性俚语：白板、鬼装、金身、爆装……
- 操作俚语：刷酒馆、洗酒馆、卡 5、卡 6、压等、上等、跳费、6 费、7 费、刚开、暴毙、爆牌、嗨过头……
- 状态描述：稳定吃鸡、双倍、buff、debuff、嗜血、连锁、滚雪球……
- 角色俚语：（你解说里有没有特定昵称？）

**Stage F-3a**：贴清单。**这一步停下来等用户答复**。

**Stage F-3b**：你 trim → 我写进 YAML 的 slang 类。

**Success Criteria**:
- slang 类 20-40 条（你审过的最终子集）
- 测试全绿

**Commit (F-3b only)**: `data(glossary): add curated slang vocabulary`

**Status**: Complete

---

## Stage F-4：英文专名 canonical（Q3=C）

**Goal**: 列高频中英混用的英文词进 `canonical.english`，告诉 Codex "这些英文词是合法的，不要尝试翻译/纠正"。

**候选清单**（在 chat 里出，你 trim）：
- 解说角色：Brann、Bob、Patches、Yogg、Reno、Greybough、Y'Shaarj
- 操作动词：Triple、Discover、buff、debuff、freeze、refresh、shop、tavern、cleave
- 数字/属性：HP、ATK、DPS（少用，可能不收）
- 流派俚语：DR（deathrattle）、BG（battlegrounds 自指）
- 卡名英文留存：（如果你有特别习惯说英文卡名的）

**Stage F-4a**：贴清单，等用户 trim。

**Stage F-4b**：写进 YAML。

**Success Criteria**:
- english 类 20-40 条
- 测试全绿

**Commit (F-4b only)**: `data(glossary): add mixed-language English terms`

**Status**: Complete

---

## Stage F-5：端到端冒烟

**Goal**: 用 clip60.mp4（Phase 1 Stage E 用过的 60s 片段，已缓存）跑一次满载 glossary 的完整 pipeline，验证：

1. Codex 不超时（实测 wall-clock 与 Phase 1 的 169s 对比）
2. cleaned.srt 输出仍是简体
3. ±20% 校验不触发 fallback
4. 与 Phase 1 cleaned.srt 比较：Codex 的"瞎猜"是否减少？例如 `古本那加冥想者 → 库本那加冥想者` 还是仍是错猜？

**关键验证 KPI**：
- wall-clock < 600s（如超过 600s 但 < 1200s，**警告但不阻塞**，记录数据点）
- 若超过 1200s timeout → 立即停止，回头切按需检索（Q8=B）

**Success Criteria**:
- Codex 不超时
- Output 100% 简体
- raw.srt 中 ≥1 个 Phase 1 误识别词在 cleaned.srt 中被改对（比如 `古本那加` 如果你已加进 corrections 的话）

**Commit**: 通常不修代码；如果需要调 timeout 或微调 prompt，单独 commit

**Status**: Complete

---

## Stage F-6：收尾

**Goal**: 更新 plan 的 verification log；汇报 Phase 2 v1 完成。

**Files**:
- `IMPLEMENTATION_PLAN_PHASE2.md`（status + verification log）

**Success Criteria**:
- 所有 Stage 状态 Complete
- F-5 实测指标写进 log
- canonical 总条目 ≥ 250、corrections ≥ 0 起步（Phase 1 v0 留下空表，Phase 2 不刻意填，等真实素材进来）

**Commit**: `docs(plan): Phase 2 v1 closeout — glossary expanded to N entries across 9 categories`

**Status**: Complete

---

## Out-of-scope（Phase 2.5+ 议题）

- **Q8=B 按需检索**：从 raw.srt 抽 token → 在 glossary 模糊匹配 → 只塞命中条目。仅当 F-5 实测超时才做。
- **Q9=glossary-suggest CLI**：自动从 raw.srt 提候选词 + 模糊匹配现有 canonical。Phase 2 不做。
- **Codex 调用分批**：长视频 cleanup_with_codex 拆 chunk。已在 memory 中 deferred，本 Phase 不动。
- **`video2yt-glossary-suggest` 全产品化**：Q9 已 deferred。
- **constructed-mode glossary 拆**：未来如果你做构筑视频再拆 `constructed_glossary.yaml`。本 Phase 不拆。
- **glossary 自动更新机制**：HearthstoneJSON 每个 BG patch 都会有新卡。Phase 2 v1 拉一次手动同步；自动化以后再说。

---

## Phase 2 verification log

**Verified**: 2026-05-16

**Commits** (oldest → newest):
- `985ae68` — Phase 2 plan
- `deb7de5` — F-0 schema upgrade + dual-format reader + 7 schema tests
- `2ea5237` — F-1a HearthstoneJSON harvester script
- `e685b36` — F-1b populate hero/minion/spell/trinket
- `c009bdc` — F-2 race/mechanic + drop single-char hero `古`
- `5fa1018` — F-3 45 slang entries
- `d5f4d03` — F-4 33 english entries
- `<this commit>` — F-6 closeout

**Final glossary state**:
| category | count | source |
|---|---|---|
| hero | 118 | HearthstoneJSON minus `古` |
| minion | 270 | HearthstoneJSON |
| spell | 71 | HearthstoneJSON |
| trinket | 217 | HearthstoneJSON minus 肖像 portraits |
| race | 10 | F-2 manual |
| mechanic | 35 | F-2 manual (8 existing + 27 added) |
| meta | 2 | unchanged from Phase 1 |
| english | 33 | F-4 manual |
| slang | 47 | F-3 manual (45 added + 2 from Phase 1) |
| **canonical total** | **803** | |
| corrections | 0 | empty; populate from real .raw.srt observations in Phase 2.5+ |

**Tests**: 467/467 passing (subtitle suite grew 70 → 77 with F-0 schema tests).

**Stage F-5 end-to-end smoke** on `/tmp/v2y_stageA/clip60.mp4` (60s clip, 2 ASR segments):

| metric | value | vs Phase 1 |
|---|---|---|
| total wall-clock | 60s | (Phase 1 was 4m05s but included whisperx ~47s; F-5 hit ASR cache) |
| Codex cleanup wall-clock | **35.4s** | **169s** (4.8× faster despite 803 vs 12 canonical) |
| segment count preservation | 2 → 2 | identical |
| ±20% fallback triggered | no | identical |
| Traditional chars in output | 0 | identical |
| prompt size (input) | 8202 chars / 16KB | ~500 chars |

**Glossary effect (observed in diff)**: with `护戒纳迦` in canonical.minion, Codex chose it for the `古本那加` mishearing instead of Phase 1's pure-knowledge guess `四本娜迦`. This is exactly the intended mechanism: populated canonical shifts Codex from guessing to selecting from a known-good list.

**Plan calibration**:
- §"Prompt 容量估算" predicted 5600s linear extrapolation at full v1 size → actual 35.4s. Codex wall-clock is **NOT linear in prompt length** at this magnitude. The yellow/red zone thresholds in the plan can be relaxed substantially. Q8=B (按需检索) likely doesn't need to be built until very large videos (>30 min) actually surface a problem.
- F-1 actual minion count was 270, not the plan's 150 estimate. Total 803 canonical exceeded the 480-cap estimate; no adverse effect observed.

**One environmental hiccup**: between Phase 1 and Phase 2 the Codex OAuth refresh-token rotated and broke (`Your access token could not be refreshed because your refresh token was already used`). User ran `codex logout && codex login` to recover. The subtitle pipeline's fallback to raw ASR was the correct safety net during the broken interval — no data loss, exit 0 with WARNING — but a fresh re-run with valid auth was necessary for actual cleanup. Document this as a known operational dependency.

---

## Decision points（Phase 2 还需要你拍板的）

| # | 问题 | 备选 | 我的建议 |
|---|---|---|---|
| **P1** | HearthstoneJSON 拉到 minion > 200 时怎么办（含历史 / BG 退役） | (a) 全收 (b) 仅当前 patch 轮换 (c) 你过一遍砍 | **(b)** —— 不污染 Codex 知识。需要看 HearthstoneJSON 是否有 patch tag 字段；如果没有，回退 (c) |
| **P2** | mechanic 类 `酒馆 N 等` 这种带数字的要不要收？ | (a) 收 `酒馆 5 等` `酒馆 6 等` 等具体 (b) 只收抽象 `酒馆升级` `升等` | **(b)** —— 抽象词覆盖性更好；具体数字 Codex 会照常识处理 |
| **P3** | slang 类我列出来的 30-50 条，你过的目标比例 | (a) 留 ≥ 20 条 (b) 留 ≥ 30 条 (c) 全收 | **(a)** —— 俚语过度收会让 Codex 把官方词改成俚语；少而精 |
| **P4** | F-1 脚本是否要保留在 repo（scripts/） | (a) 保留供下次 BG patch 更新用 (b) 一次性，用完删 | **(a)** —— 后面新 patch 重跑成本接近零 |
| **P5** | Stage F-5 实测如果 wall-clock 在 600s-1200s 之间（黄区） | (a) 接受，标记 KPI (b) 立即触发 Q8=B 按需检索 | **(a)** —— 1200s 内都算 pass；超过才动结构 |
| **P6** | corrections 起步内容 | (a) Phase 2 不动 corrections（仍保留空字典） (b) 把 Stage E 看到的 7 个误识别先填进去 | **(b)** —— Stage E 实测素材现成，不用就浪费；条目附 source = `BV1Z..., 2026-05-16` 注释 |
| **P7** | F-2 mechanic 候选里 `招募` / `跳费` / `压等` 这种你确定是 BG 词吗 | （我列出来你过即可） | 等你审 |

---

## Working notes

- 所有 Stage 都在 `claude/thirsty-rubin-d7e5bd` 分支上，紧接 Phase 1 之后 commit。
- 每个 Stage 通过后才进下一个；F-3a / F-4a 是 blocking 用户审。
- 不动 Phase 1 commit；不删 Phase 1 的 `IMPLEMENTATION_PLAN.md`。
- 不动发布层（topic.py / upload.py / thumbnail.py / docs/spec workflow）。
