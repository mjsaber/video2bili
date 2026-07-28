# New Topic Selection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Select one strong, not-yet-covered Hearthstone Battlegrounds topic from the last seven days of whitelisted Bilibili uploads.

**Architecture:** Run the repository's existing topic-discovery CLI with its seven-day defaults, preserve its complete link-bearing report, then manually cross-check every new candidate against the shipped-topic corpus. Rank viable pairs by recency, complementary gameplay, mechanism clarity, and packaging potential.

**Tech Stack:** `video2yt-topic`, Bilibili API, Codex summarization, Markdown report, repository topic history.

---

### Task 1: Generate the candidate report

**Files:**
- Create: `output/topics/2026-07-27.md`

- [ ] **Step 1: Run discovery**

```bash
uv run video2yt-topic --days 7
```

Expected: the command prints a `CHAT-READY REPORT` block and writes `output/topics/2026-07-27.md`.

- [ ] **Step 2: Verify report integrity**

```bash
test -s output/topics/2026-07-27.md
rg -n 'https://www.bilibili.com/video/' output/topics/2026-07-27.md
```

Expected: the report is non-empty and every listed pair contains two Bilibili video URLs.

### Task 2: Cross-check and rank candidates

**Files:**
- Read: `output/topics/2026-07-27.md`
- Read: `assets/topic/done_topics.txt`
- Read: `output/*/intro_script.txt`

- [ ] **Step 1: Check every candidate marked new**

Compare its strategy, core card, hero, and alternate Simplified/Traditional names with the completed-topic corpus. Treat automatic annotations as hints only.

- [ ] **Step 2: Rank viable candidates**

Use this order:

1. Not previously shipped.
2. Two usable battle videos with complementary ideas.
3. A mechanism explainable in one sentence.
4. Strong cold-open and thumbnail moments.
5. Prefer different streamers; accept one streamer with two clearly complementary games.

- [ ] **Step 3: Present the result**

Relay the CLI's complete report without removing or rewriting links. Add a recommendation only if both source URLs are repeated beside every candidate named in the recommendation or skip notes.

### Task 3: Handle an empty seven-day window

- [ ] **Step 1: Confirm the absence of viable new pairs**

Expected: all generated pairs are either previously shipped, factually suspect, or lack two suitable sources.

- [ ] **Step 2: Expand only if needed**

```bash
uv run video2yt-topic --days 14 -o output/topics/2026-07-27-14d.md
```

Expected: produce a second complete link-bearing report and apply the same cross-check and ranking rules.
