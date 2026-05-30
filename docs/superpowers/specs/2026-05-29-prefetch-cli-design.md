# Design: `video2yt-prefetch` — 提前串行预取 Step 6 源视频

**状态**: 设计已批准（brainstorming 2026-05-29），待 writing-plans
**分支**: `prefetch-workflow`
**关联**:
- `docs/prefetch-workflow-brief.md`（问题来源 / 今天 feina 实测证据）
- `docs/superpowers/specs/2026-04-18-video-production-workflow.md`（9 步流水线）
- `docs/superpowers/specs/2026-05-24-step6-restructure.md` §7（`video2yt-fetch` 契约）

## 问题

9 步流水线严格串行：Step 1–5（写稿/TTS/配图/字幕对齐/合成，几乎不占带宽）做完后，Step 6 才开始 `video2yt <url>` 烧制每段 B 站源——而 Step 6 第一件事是 yt-dlp 下载 ~20 分钟 1080p 源（几百 MB、B 站限速、单段实测 15+ 分钟）。这段下载本可在不占带宽的 Step 1–5 期间后台跑完。

并行下载会踩坑：feina 项目把两段 `video2yt` 并行起飞，郭枫荷段 yt-dlp 合流产出 5s 截断视频（video 5.0s vs audio 1115.0s），被 `download.fetch` 的 AV 时长校验拦下报错。怀疑两段同时下载抢带宽诱发 merger hiccup。

## 目标 / 成功标准

- Step 6 到达时，源 mp4 + danmaku.xml 已在 `temp/<uploader>：<title>/` 缓存就绪，秒命中缓存进 stems。
- 预取**串行化**多段下载（不并行，避开截断诱因）。
- 截断合流**自动重试**而非直接报错退出。
- 对现有缓存语义**零破坏**：预取就是提前填 Step 1 fetch 的同一份缓存。不修改 `fetch.py`/`cli.py` 现有逻辑。

## 选定方向

brief 方向 2：新增 `video2yt-prefetch <url>...` CLI。串行下载多个 URL 进缓存 + 截断自动重试 + 分辨率预检。复用现有 `fetch.fetch_and_build`，人工在 Step 1 时后台起飞。

（方向 1 纯文档脚手架无法吃掉「截断自动重试 / 分辨率预检」两个坑；方向 3 项目级编排器需引入 manifest 概念，改动过大，YAGNI。）

## 设计决策（brainstorming 确认）

| 决策点 | 选定 | 理由 |
|---|---|---|
| 截断合流处理 | 自动重试 2 次（共 3 次尝试），仍坏则标记失败 | 截断是偏瞬态 hiccup，重试大概率能成 |
| 多 URL 某段彻底失败 | **fail-fast**，第一个失败就停 | 问题立刻暴露，不浪费带宽下后面段 |
| 分辨率低于请求质量 | **当作失败报错** | 早报警；merge 严格要 1920×1080，晚发现成本高 |
| 后台机制 | 交给 shell（`video2yt-prefetch url1 url2 &`） | CLI 保持前台串行，零新依赖、不 daemon 化 |
| 参数面 | 镜像 `video2yt-fetch`：`-o/--temp-dir`、`-q/--quality`、`--codec`、`-b/--browser` | 必须产出和 Step 6 一模一样的缓存；字体参数省略（fetch 每次重建 ASS） |

**已知张力（有意为之）**：fail-fast + 低分辨率当失败 ⇒ 若预取 `[url1, url2]` 而 url1 只有 480p，预取在 url1 处报错停下，url2 不下载。符合「早报警、不浪费带宽」意图。低分辨率失败时坏缓存会被隔离（见架构「分辨率不足必须隔离坏缓存」），不会污染 Step 6。

## 架构

**新增文件**：`src/video2yt/prefetch_cli.py`（`video2yt-prefetch` 入口）。
**`pyproject.toml`**：注册 `video2yt-prefetch = "video2yt.prefetch_cli:main"` script（用 `uv` 不手编辑——实际通过编辑 `[project.scripts]` 表，这是声明不是依赖）。
**对 `download.py` 的唯一改动**：引入向后兼容的截断专用异常类（见下）。
**不碰**：`fetch.py`、`cli.py`、`fetch_cli.py` 的现有逻辑。

### 截断错误分类

当前 `download.fetch` 检测到截断（AV 时长不匹配）时把坏文件改名 `.broken` 并抛 `RuntimeError`（文案含 "truncated audio"）。预取需要区分「截断」（可重试）与「其他错误」（VIP 锁低分辨率 / 网络 / cookie 锁——不重试，fail-fast）。

方案：在 `download.py` 定义

```python
class TruncatedDownloadError(RuntimeError):
    """yt-dlp merger hiccup: video/audio stream durations disagree."""
```

把 `download.fetch` 中现有的那处 `raise RuntimeError(...)`（line 167）改为 `raise TruncatedDownloadError(...)`。因为它是 `RuntimeError` 子类，现有所有把它当 `RuntimeError` 捕获的调用方（`fetch_cli.main` 的 `except (..., RuntimeError)`）行为完全不变。这是对现有代码唯一的、向后兼容的侵入点。

### 核心流程 `run(args)`

```
preflight()                          # 复用 fetch_cli 的检查：ffmpeg/ffprobe/yt-dlp/biliass
results = []
for url in args.urls:                # 串行，按顺序
    for attempt in 1..MAX_ATTEMPTS(=3):
        try:
            result = fetch.fetch_and_build(url, temp_dir, quality, codec, browser)
            if result.info.height < quality:
                _quarantine_lowres(result)               # 隔离坏缓存，见下
                raise PrefetchResolutionError(            # fail-fast，不重试
                    f"{bv}: got {w}x{h}, requested <={quality}p "
                    f"(VIP-locked? merge needs 1920x1080)")
            results.append(success)
            break
        except TruncatedDownloadError:
            if attempt == MAX_ATTEMPTS:
                raise                                     # 3 次都截断 → fail-fast
            _cleanup_partials(temp_subdir, bv)            # 清 .broken / .part 残留
            log(f"truncated, retry {attempt+1}/{MAX_ATTEMPTS}")
            continue
    # PrefetchResolutionError / 其他异常 不被 except 捕获 → 直接冒泡 → fail-fast
print_summary(results)               # 每个 URL: bv / 标题 / 分辨率 / cache命中or新下 / 耗时
```

- **串行**：单层 for，无并发。
- **重试只针对 `TruncatedDownloadError`**；其他异常（含 `PrefetchResolutionError`）直接冒泡，触发 fail-fast。
- **重试前清残留**：`download.fetch` 已把截断坏文件改名 `.broken`，重试时它的 cache probe 看不到完整 mp4 会重新 yt-dlp；但要清掉可能残留的 `.part`/`.broken`，避免堆积。
- **缓存命中**：`fetch.fetch_and_build` → `download.fetch` 内部 cache probe 命中则秒回，预取对已就绪的段是 no-op。

### 分辨率不足必须隔离坏缓存（Codex review 2026-05-29 抓出）

`fetch.fetch_and_build` 是**先把 mp4+xml 写进缓存再 return**，分辨率检查在它 return 之后。若直接 fail-fast 而不处理，那个低分辨率 mp4 就留在 `temp/<uploader>：<title>/<bv>.mp4`——下次 Step 6 跑 `video2yt <url>` 时 `download.fetch` 的 cache probe 看到一个完好、AV 一致的低清文件，**静默命中缓存**一路用到 merge 才炸，「早报警」彻底失效且更隐蔽。

修法 `_quarantine_lowres(result)`：参照 `download.fetch` 的 `.broken` 隔离模式，在抛 `PrefetchResolutionError` 前把缓存的 video + danmaku XML 改名加 `.lowres` 后缀（如 `<bv>.mp4.lowres`、`<bv>.danmaku.xml.lowres`）。`download.fetch` 的 cache probe 用 `glob("{bv}.mp4")` / `glob("{bv}*.xml")`，`.lowres` 结尾的文件都不匹配，所以后续 Step 6 会重新下载（要么用户已换源/升采样，要么再次失败暴露问题）。改名而非删除：保留文件供人工检查，与 `.broken` 约定一致。`<bv>.danmaku.ass` 无需隔离（每次重建）。

隔离逻辑放 `prefetch_cli`（分辨率下限是预取特有策略，`fetch_and_build` 把 quality 当格式上限而非硬要求，不该承担此责任）。`result.raw_video` / `result.danmaku_xml` 提供待隔离路径。

### CLI 形状（沿用项目 `preflight/parse_args/run/main` 约定）

```
video2yt-prefetch <url1> [<url2> ...]
  -o/--temp-dir  ./temp
  -q/--quality   1080  (choices 1080/720/480)
  --codec        h264  (choices h264/h265/auto)
  -b/--browser   chrome
```

`main` 退出码：
- `0` 全部成功
- `1` 任一 URL fail-fast 失败（截断耗尽重试 / 分辨率不足 / 网络 / cookie 锁 / 其他）
- `130` KeyboardInterrupt

失败时 stderr 打印：已成功哪几个 URL、在哪个 URL 失败、失败原因。

## 数据流 / 缓存

预取写入的缓存与 `video2yt-fetch` 完全相同：`temp/<uploader>：<title>/<bv>.mp4` + `<bv>*.xml` + `<bv>.danmaku.ass`。Step 6 (`video2yt <url>`) 到达时 `download.fetch` 的 cache probe 命中，跳过 yt-dlp，直接进 stems。预取不写任何新的 sidecar、不引入新缓存键。

## 测试（`tests/test_prefetch.py`，mock `subprocess.run` 边界，无网络）

跟现有测试风格一致（所有外部工具在 `subprocess.run` 处 mock）：

1. 单 URL 成功 → 缓存文件就绪、退出码 0
2. 截断一次后重试成功 → 第 2 次尝试拿到完好文件
3. 截断 3 次（MAX_ATTEMPTS 都返回截断）→ fail-fast、退出码 1、stderr 含 "truncated"
4. 低分辨率（probe 返回 height < quality）→ fail-fast、退出码 1、stderr 含分辨率提示
5. **低分辨率隔离坏缓存**：失败后 `<bv>.mp4` 被改名为 `<bv>.mp4.lowres`（不再匹配 cache probe 的 glob），XML 同理 → 保证下次 Step 6 不会命中坏缓存
6. 多 URL 串行，第 2 个失败 → 第 3 个 `fetch_and_build` 不被调用（mock 断言调用次数）
7. 缓存命中（`from_cache=True`）→ yt-dlp 不被调用、秒回
8. `TruncatedDownloadError` 是 `RuntimeError` 子类（保证现有 `except RuntimeError` 调用方不破坏）

## 文档

- 更新 `CLAUDE.md` 的 Commands 段加一行 `video2yt-prefetch`，External dependencies 不变。
- 更新 9 步流水线 workflow spec：在 Step 1 处注明「可后台起飞 `video2yt-prefetch <url>... &` 预取 Step 6 源」。
- 完成后删除 `docs/prefetch-workflow-brief.md`（已被本 spec 取代）——或留作历史，由 writing-plans 阶段定。

## 非目标（YAGNI）

- 不做并行下载（正是问题诱因）。
- 不做 daemon / 进度文件 / 通知（shell `&` 足够）。
- 不引入项目 manifest / 自动编排（方向 3，未来再说）。
- 不暴露 `--retries`（固定 3 次；真有调参需求再加）。
- 不暴露字体参数（预取阶段建的 ASS 不影响最终，fetch 每次重建）。
