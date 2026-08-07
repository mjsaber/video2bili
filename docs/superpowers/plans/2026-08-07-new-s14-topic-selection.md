# S14 下一期选题筛选 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 生成一份带完整 Bilibili 来源链接的 S14 新候选报告，并选出下一期最适合制作的双主播题材。

**Architecture:** 先用现有 `video2yt-topic` 管线扫描最近 7 天白名单主播视频，再结合当日报告、已完成题材清单和已发布 S14 项目做归属与同义去重。正式候选不足 3 个时才围绕扫描中出现的 S14 新卡和流派别称定向补搜，最终保留标准报告并给出唯一首选。

**Tech Stack:** `video2yt-topic`, yt-dlp, Bilibili Chrome cookies, Markdown, `rg`, `jq`

---

## File map

- Create: `output/topics/2026-08-07.md` — 当日标准选题扫描报告与聊天可转发候选。
- Read: `assets/topic/streamers.txt` — 白名单主播范围。
- Read: `assets/topic/done_topics.txt` — 已完成题材与同义词去重基准。
- Read: `output/topics/2026-08-06.md` — 上一次 S14 扫描结果，用于识别旧候选与新增素材。
- Read: `output/choice_quilboar_s14/youtube_metadata.json` — 已完成的 S14 抉擇野豬题材证据。
- Read: `output/fishbait_beast_s14/youtube_metadata.json` — 已完成的 S14 魚餌野獸题材证据。
- Do not modify: 现有扫描报告、已发布项目输出和用户工作区中的其他未提交文件。

### Task 1: 预检扫描输入与输出路径

- [ ] **Step 1: 验证工具、白名单和去重文件**

Run:

```bash
command -v yt-dlp
command -v codex
test -s assets/topic/streamers.txt
test -s assets/topic/done_topics.txt
uv run video2yt-topic --help >/dev/null
```

Expected: 两个命令返回可执行文件路径，两个输入文件非空，CLI 帮助命令退出码为 0。

- [ ] **Step 2: 检查当日报告是否已经存在**

Run:

```bash
if test -e output/topics/2026-08-07.md; then
  stat -f '%Sm %N' output/topics/2026-08-07.md
  sed -n '1,40p' output/topics/2026-08-07.md
else
  echo 'report_absent'
fi
```

Expected: 新任务输出 `report_absent`；若已有报告，先读取并判断它是否为同一轮完整扫描，禁止静默覆盖不同结果。

### Task 2: 运行最近 7 天标准扫描

- [ ] **Step 1: 使用 Chrome 登录 Cookie 扫描白名单主播**

Run:

```bash
uv run video2yt-topic \
  --days 7 \
  --cookies-from-browser chrome \
  -o output/topics/2026-08-07.md
```

Expected: 命令退出码为 0；stdout 包含 `===== CHAT-READY REPORT =====` 与 `===== END CHAT-READY REPORT =====`；报告文件非空。

- [ ] **Step 2: 验证报告结构与来源链接**

Run:

```bash
test -s output/topics/2026-08-07.md
rg -n '===== CHAT-READY REPORT|===== END CHAT-READY REPORT' output/topics/2026-08-07.md
rg -n 'https://www\.bilibili\.com/video/BV' output/topics/2026-08-07.md
```

Expected: 起止标记各出现一次，并至少存在一条完整 Bilibili 视频链接。

### Task 3: 提取候选并执行 S14 归属检查

- [ ] **Step 1: 提取完整聊天候选区块**

Run:

```bash
sed -n '/===== CHAT-READY REPORT =====/,/===== END CHAT-READY REPORT =====/p' \
  output/topics/2026-08-07.md
```

Expected: 输出所有候选标题、主播、核心机制和完整来源链接，不遗漏不推荐候选。

- [ ] **Step 2: 对照上一轮报告识别新增素材**

Run:

```bash
if test -s output/topics/2026-08-06.md; then
  rg -o 'https://www\.bilibili\.com/video/BV[[:alnum:]]+' \
    output/topics/2026-08-06.md output/topics/2026-08-07.md | sort
else
  echo 'previous_report_absent'
fi
```

Expected: 能区分 8 月 6 日已出现来源与 8 月 7 日新增来源；上一轮报告不存在时明确输出缺失状态。

- [ ] **Step 3: 核对正式候选的 S14 证据**

对每个候选读取报告中的机制摘要和弹幕证据，记录：S14 新卡、黑暗贈禮、新随从池变化或其他明确版本依据。仅标题写“新版本”而机制证据不足的候选降为储备，不进入前三。

Expected: 每个进入前三的候选都有一条可说明 S14 归属的实际内容证据。

### Task 4: 去除已完成题材与同义重复

- [ ] **Step 1: 交叉检查 done topics**

Run:

```bash
rg -n -F -f assets/topic/done_topics.txt output/topics/2026-08-07.md || true
```

Expected: 输出报告中命中的已完成词；逐项判断候选是否为历史题材同义改名。

- [ ] **Step 2: 强制排除本周已经发布的两期 S14**

Run:

```bash
jq -r '.title' output/choice_quilboar_s14/youtube_metadata.json
jq -r '.title' output/fishbait_beast_s14/youtube_metadata.json
rg -n '抉擇野豬|抉择野猪|魚餌野獸|鱼饵野兽' output/topics/2026-08-07.md || true
```

Expected: 抉擇野豬和魚餌野獸及其同义题材明确标为已完成，不进入正式候选。

- [ ] **Step 3: 验证双主播准入条件**

逐个统计候选中的不同主播与链接。正式候选必须至少有两位不同白名单主播，且每位都对应一条完整 Bilibili URL；只有一位主播的题材仅保留为储备。

Expected: 前三候选均满足双主播条件。

### Task 5: 合格候选不足时定向补搜

- [ ] **Step 1: 判断是否需要补搜**

统计完成 S14 归属、去重和双主播检查后的正式候选数量。

Expected: 数量达到 3 个时跳过本任务剩余步骤；少于 3 个时继续 Step 2。

- [ ] **Step 2: 从实际报告提取补搜关键词**

从报告中选择未完成题材的正式卡名、流派名和常见别称，每个方向使用一个明确关键词组合，例如 `S14 + 卡名 + 酒馆战棋`。不得使用未在报告或视频内容中出现的猜测词。

- [ ] **Step 3: 验证补充来源**

对定向搜索得到的视频记录标题、主播、BVID、完整 URL、时长和 S14 机制证据。只有形成第二位不同主播的完整实战时，才把该题材升级为正式候选。

Expected: 补充候选仍满足双主播、S14 归属和去重规则；无法补足时保留实际候选数量。

### Task 6: 输出候选与唯一首选

- [ ] **Step 1: 按统一标准排序**

按以下顺序比较正式候选：S14 新鲜度、双素材互补性、机制教学价值、战力视觉兑现、素材完整度。

Expected: 每个候选都有明确的优点、风险和排序理由。

- [ ] **Step 2: 输出聊天报告**

从标准报告保留全部正式候选内容，并为每个候选补充：

```text
S14 依据：
双素材差异：
核心机制：
成片卖点：
风险：
来源 1：https://www.bilibili.com/video/<BVID>
来源 2：https://www.bilibili.com/video/<BVID>
```

Expected: 所有候选都带可点击的完整来源链接；明确标出唯一首选。

- [ ] **Step 3: 最终验证**

Run:

```bash
test -s output/topics/2026-08-07.md
rg -n 'https://www\.bilibili\.com/video/BV' output/topics/2026-08-07.md
git status --short output/topics/2026-08-07.md
```

Expected: 当日报告存在、链接可见，且没有误改历史报告或其他项目文件。
