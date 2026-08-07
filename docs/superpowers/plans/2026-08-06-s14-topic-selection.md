# S14 新版本选题筛选 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 生成一份带完整 Bilibili 来源链接的 S14 新版本候选报告，并选出下一期最适合制作的双主播题材。

**Architecture:** 先使用现有 `video2yt-topic` 管线扫描最近 7 天白名单主播视频并生成标准报告，再读取报告、弹幕摘要和已完成题材清单验证 S14 归属与去重。只有合格候选不足 3 个时才做定向补搜，最终保持 CLI 的 CHAT-READY REPORT 原文并叠加推荐说明。

**Tech Stack:** `video2yt-topic`, yt-dlp, Bilibili browser cookies, Codex batch summarization, Markdown

---

### Task 1: 运行标准 7 天选题扫描

**Files:**
- Create: `output/topics/2026-08-06.md`
- Reference: `assets/topic/streamers.txt`
- Reference: `assets/topic/done_topics.txt`

- [ ] **Step 1: 确认浏览器登录状态与输出目标**

Run:

```bash
test -f assets/topic/streamers.txt
test -f assets/topic/done_topics.txt
test ! -e output/topics/2026-08-06.md
```

Expected: 前两个命令成功；当日报告尚不存在。若报告已存在，先读取其时间与内容，禁止静默覆盖一次已完成的不同扫描。

- [ ] **Step 2: 扫描最近 7 天素材**

Run:

```bash
uv run video2yt-topic \
  --days 7 \
  --cookies-from-browser chrome \
  -o output/topics/2026-08-06.md
```

Expected: 命令退出码为 0，stdout 出现 `===== CHAT-READY REPORT` 起止标记，报告文件非空。

- [ ] **Step 3: 验证报告结构和来源链接**

Run:

```bash
test -s output/topics/2026-08-06.md
rg -n 'CHAT-READY REPORT|https://www\.bilibili\.com/video/BV' output/topics/2026-08-06.md
```

Expected: 报告包含标记与 Bilibili BV 链接；每个候选段落列出的主播都带可见链接。

### Task 2: 验证 S14 归属、双素材和去重

**Files:**
- Read: `output/topics/2026-08-06.md`
- Read: `assets/topic/done_topics.txt`
- Read: `output/topics/2026-08-04.md`

- [ ] **Step 1: 提取完整 CHAT-READY REPORT**

Run:

```bash
sed -n '/===== CHAT-READY REPORT/,/===== END CHAT-READY REPORT/p' \
  output/topics/2026-08-06.md
```

Expected: 输出完整候选正文，不遗漏任何候选或来源链接。

- [ ] **Step 2: 交叉核对已完成题材**

Run:

```bash
rg -n -F -f assets/topic/done_topics.txt \
  output/topics/2026-08-06.md output/topics/2026-08-04.md
```

Expected: 输出报告中命中的已完成题材词；再逐项检查候选别称，已做过或同义重复的候选明确标注，不进入首选。

- [ ] **Step 3: 核对 S14 机制证据**

逐个读取候选的机制概要、核心卡和两位主播实战亮点。只有明确使用 S14 新卡、黑暗赠礼或 S14 刷新随从池形成的新体系时才保留；仅标题写“新赛季”但内容属于 S13 的候选剔除。

- [ ] **Step 4: 决定是否需要补搜**

Expected: 若保留候选达到 3 个，直接进入 Task 3；不足 3 个时，使用候选中出现的实际 S14 核心卡名和流派别称在 Bilibili 定向搜索，并将找到的双主播链接追加到分析说明中，不改写标准报告原文。

### Task 3: 输出完整报告与首选建议

**Files:**
- Read: `output/topics/2026-08-06.md`

- [ ] **Step 1: 原样转发标准报告**

从 `===== CHAT-READY REPORT` 标记之间复制完整 stdout 内容。不得删除未推荐候选，不得省略任何主播的 Bilibili 链接。

- [ ] **Step 2: 叠加 S14 审核标注**

在原文之后列出：S14 归属、done-topics 同义词检查、素材互补性、冷开场/缩略图卖点。标注不得替换原报告。

- [ ] **Step 3: 给出一个首选题材**

首选必须同时满足：至少两位主播来源、S14 新版本关联明确、未做过、机制适合教学、存在可视化战力兑现。若没有候选满足全部条件，明确说明缺口并保留实际报告，不以 S13 视频凑数。

- [ ] **Step 4: 最终核验**

Run:

```bash
test -s output/topics/2026-08-06.md
git status --short output/topics/2026-08-06.md
```

Expected: 当日报告存在且未误改代码或其他历史报告。
