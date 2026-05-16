# Phase 1：字幕链路全简体迁移

**Worktree**: `thirsty-rubin-d7e5bd`
**Started**: 2026-05-16
**Scope**: whisperx ASR → Codex 术语清理 → 字幕 burn 这一条链路统一为简体中文。**不动** YouTube 标题/描述/章节/缩略图发布层（仍繁体）。

## Decisions locked

- Q1=A：信任 whisperx 默认输出，不传 `initial_prompt`，不加 OpenCC（Stage A 实测验证）
- Q3.1=B：清空 `bg_glossary.yaml` 的 corrections，canonical 全部翻译成简体
- Q3.2：产品名走"两边各自的官方译名" —— 字幕用国服 `炉石传说` / `战棋`；发布元信息（标题/描述）保留繁体台服 `爐石戰記：英雄戰場` 不动
- Q3.3：canonical 其他词条按字面繁→简映射
- Q3.4：identity entry 保留在 corrections 区（加注释解释 intent）
- Q4.1：不新增"繁体兜底"测试（YAGNI；如果 Stage A 实测有问题再加）
- Q5.1：本文档即 plan；不走完整 spec 流程
- Q5.2：继续用 `thirsty-rubin-d7e5bd`

## Boundary scan (DO NOT TOUCH list)

确认以下文件**不在 Phase 1 改动范围内**：

| 文件 | 含繁体的原因 | 处置 |
|---|---|---|
| `docs/superpowers/specs/2026-04-18-video-production-workflow.md` | 描述 YouTube 标题/描述模板（繁体） | 保留 |
| `docs/superpowers/specs/2026-05-14-video2yt-subtitle-design.md` | 历史 design doc，记录原 prompt 繁体 | 保留（历史快照） |
| `docs/superpowers/plans/2026-05-14-video2yt-subtitle.md` | 历史 plan doc | 保留 |
| `CLAUDE.md` "Battlegrounds workflow rule" 段 | `戒指龍 / 護戒` 历史叙述 | 保留 |
| `src/video2yt/topic.py` | 已经全简体；regex `战棋\|战旗`、`戒指龙流` 示例 | 保留 |
| `src/video2yt/upload.py` / `upload_cli.py` | 无 CJK 硬编码 | 保留 |
| `src/video2yt/thumbnail.py` / `thumbnail_cli.py` | 仅简体占位字 `"国"` | 保留 |
| `tests/test_smoke.py` (line 5391 等) | topic / 缩略图 / 上传相关测试夹具 | 保留 |

**未发现 subtitle ↔ 发布层共享常量**。两条路径完全独立，可以安全只改字幕侧。

---

## Stage A：whisperx 实测默认输出

**Goal**: 用一段真实音频跑 `_run_asr`，确认 whisperx large-v3 默认输出是否为简体。

**Steps**:
1. 在 worktree 或主仓 `temp/` 下找一段已下载的 `.mp4`（或 `.wav`）。若无，停下来问用户提供。
2. 写一个 throwaway 脚本（不 commit），调用 `subtitle._run_asr(wav_path)` 输出前 5 段。
3. 人工目检：是否含繁体专属字符（`戰/實/這/個/長/讀/還/們/應/聲/邊/見/讓` 等）。

**Success Criteria**:
- 输出 5 段样本，绝大多数（≥4/5）为纯简体 → 走原计划，不改 ASR 调用
- 若发现繁简混杂或繁体为主 → **停下来汇报**，决定是否启用 `initial_prompt` 或 OpenCC `t2s`

**Tests**: 无（实测脚本不进 git）

**Commit**: 无独立 commit（实测结果以聊天确认 + 本文件 Status 字段记录）

**Status**: Not Started

---

## Stage B：Codex prompt 改简体

**Goal**: 把 `subtitle.py::_build_cleanup_prompt` 的整段 prompt 改为简体，并显式要求 Codex 输出简体。

**Files**:
- `src/video2yt/subtitle.py:437-457` `_build_cleanup_prompt`

**改动要点**:
- 第一行 "繁體中文爐石戰記戰棋實況解說" → "简体中文炉石传说战棋实况解说"
- 中间所有指令字符串（"術語對應表" / "首選用詞" / "輸入" / "輸出" / "請只輸出"）→ 简体
- 新增一条显式约束："输出必须为简体中文；若输入夹杂繁体字，请一并转为简体"

**Success Criteria**:
- `grep -nE "繁體|繁体" src/video2yt/subtitle.py` 返回 0 行
- 单测 `pytest tests/test_subtitle.py -k cleanup` 通过（与 Stage D 协同；这一 stage 单测可能临时挂红，等 Stage D 修复）

**Tests**: 现有 cleanup-相关测试在 Stage D 一起更新

**Commit**: `refactor(subtitle): codex prompt → simplified Chinese`

**Status**: Not Started

---

## Stage C：bg_glossary.yaml 改简体

**Goal**: 按 Q3.1=B 方案：清空 `corrections`，`canonical` 翻译成简体。

**Files**:
- `src/video2yt/data/bg_glossary.yaml`

**改动要点**:
- `corrections` 区：清空 5 条繁体条目，保留空字典 `{}` 加注释说明"Phase 2 用实测 .raw.srt 重新填充"
- `canonical` 区按字面 t2s：
  - 爐石戰記 → 炉石传说（**注意**：与发布层标题前缀 `爐石戰記：英雄戰場` 不同步是有意为之，见 Decisions Q3.2）
  - 戰棋 → 战棋
  - 酒館 → 酒馆
  - 隨從 → 随从
  - 餵牌 → 喂牌
  - 三星（不变）
  - 吃雞 → 吃鸡
  - 加血（不变）
  - 上分（不变）
  - 開酒館 → 开酒馆
  - 護甲 → 护甲
  - 法力水晶（不变）
- 文件头注释更新："Simplified Chinese terminology corrections (Phase 1)"

**Success Criteria**:
- `grep -nE "[一-鿿]" src/video2yt/data/bg_glossary.yaml` 输出全部为简体（人工目检）
- `pytest tests/test_subtitle.py::test_glossary_load_default` 失败（预期 —— 等 Stage D 同步）

**Tests**: 在 Stage D 修复

**Commit**: `refactor(subtitle): glossary → simplified; clear stale corrections`

**Status**: Not Started

---

## Stage D：test_subtitle.py 字符串改简

**Goal**: 把 `tests/test_subtitle.py` 中所有繁体测试夹具/断言翻译成简体。

**Files**:
- `tests/test_subtitle.py`（**仅此文件**；`test_smoke.py` 内的繁体属于 topic 模块测试，不动）

**改动要点**（按目前 grep 结果）：
- L38：`assert g.corrections.get("戰旗") == "戰棋"` → 改为新 glossary 的实际内容（清空后 corrections 应为空，这条断言需重写为 "load_default 返回的 corrections 字典为空")
- L266：`"字幕"`（OCR 测试，已经简体，不动）
- L286：`"弹幕"`（已简体，不动）
- L314-340：`"你好" / "世界" / "世界，再見。"` → `"再見" → "再见"`
- L366-376（cleanup_with_codex 测试）：
  - `"戰旗很有趣" / "拉法母真的強" / "戰棋很有趣\n拉法姆真的強\n"` 全套改简体
  - corrections 字典 `{"戰旗": "戰棋", "拉法母": "拉法姆"}` → 新简体测试夹具（注意不依赖打包 glossary，是测试内部构造的）
- L413：`"短\n這是個被改寫太多的句子\n"` → `"短\n这是个被改写太多的句子\n"`
- L445：`"短短的一句話只有幾個字"` → `"短短的一句话只有几个字"`
- L454：`"二十五個字大概就是這樣長的一句話可以讀完"` → `"二十五个字大概就是这样长的一句话可以读完"`
- L462,472：split 测试中的"前半段...後半段..." → 简体
- L499 注释 `"。"` 测试（无繁体）
- L548-555：`"下一段的字幕內容"` → `"下一段的字幕内容"`

**Success Criteria**:
- `grep -nE "[繁體戰實這個還們應聲讀見讓內] " tests/test_subtitle.py` 返回 0 行（粗略扫描）
- `uv run pytest tests/test_subtitle.py` 全绿
- `uv run pytest tests/test_smoke.py tests/test_compose_outline_shadow.py` 全绿（确保没误伤其他模块）

**Tests**: 现有测试集本身

**Commit**: `test(subtitle): translate fixtures and assertions to simplified Chinese`

**Status**: Not Started

---

## Stage E：端到端冒烟

**Goal**: 用一段真实 BV 视频跑完整 subtitle pipeline，确认全简体可用、Codex 不返工。

**Steps**:
1. 选一段已缓存 BV 视频（temp/ 内）
2. `uv run video2yt-subtitle <seg.mp4> --force-add`（强制 ADD 路径，绕过 detection）
3. 检查产物：
   - `<stem>.raw.srt` 内容是否为简体
   - `<stem>.cleaned.srt` 是否未触发 ±20% 长度 fallback（看 WARNING 日志）
   - 烧录后的 mp4 字幕目检
4. 若 cleaned.srt 出现繁体或 fallback 频繁 → 停下来汇报

**Success Criteria**:
- 三个产物都是简体
- 无 ±20% fallback WARNING
- 烧录视频字幕肉眼正常

**Tests**: 无自动化测试（端到端冒烟靠目检）

**Commit**: 不修代码则无 commit；若发现需要微调（如 prompt 措辞），单独 commit

**Status**: Not Started

---

## Out-of-scope (Phase 2 will handle)

- 战棋 glossary 实测扩充（英雄名 / 随从名 / 种族 / 关键动词）
- whisperx GPU 加速 + 跨段模型缓存
- wav2vec2 强制对齐以获得真实词级时间戳
