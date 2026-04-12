# video2yt 设计文档

**日期**: 2026-04-11
**状态**: Draft → 待用户确认
**基于**: `docs/plan.md`（原始方案书）

---

## 1. 目标与范围

### 1.1 目标

构建一个本地 CLI 工具，输入一个 B 站视频链接，输出一个**带弹幕烧录效果**的本地 MP4 文件。

### 1.2 本期范围（MVP）

对应 `plan.md §5.1` 的本期交付，**加上** Chrome cookie 登录支持（为了保证能拉到 1080p 清晰度）：

- ✅ 单链接输入 → 单 MP4 输出
- ✅ 可配置输出目录
- ✅ 可配置清晰度上限（默认 1080p）
- ✅ 可配置是否保留中间文件
- ✅ 从本地 Chrome 读 cookie 登录
- ✅ 下载、转 ASS、烧录全流程自动化
- ✅ 输入/输出基本验证（时长、分辨率、流完整性等）

### 1.3 明确不在范围内

对应 `plan.md §5.2`，以下特性留给后续版本：

- ❌ 批量处理多个链接
- ❌ 多 P 视频的分 P 选择
- ❌ 失败重试
- ❌ 弹幕样式定制（字体、字号、屏蔽）
- ❌ 非烧录的双版本输出
- ❌ 详细日志框架（只用 stderr `print`）

---

## 2. 技术栈

| 层 | 工具 | 版本要求 |
|---|---|---|
| Python 运行时 | Python | `>=3.10` |
| 包管理 | `uv` | 最新 |
| 下载 | `yt-dlp` | `>=2025.1.1`（宽松下限，靠 `uv.lock` 精确锁） |
| 弹幕转 ASS | `yt-dlp-danmaku` | `>=0.2.0`（yt-dlp 的 postprocessor 插件，底层基于 `biliass`） |
| 视频烧录 | `ffmpeg` | 系统级安装（`brew install ffmpeg`） |
| 探测视频 metadata | `ffprobe` | 随 ffmpeg 附带 |
| 测试 | `pytest` | `>=8.0`（dev 依赖） |

### 2.1 弹幕工具选型说明

`plan.md` 原文写的是"yt-dlp-danmaku"。查证后确认：

- **仓库**: https://github.com/UlyssesZh/yt-dlp-danmaku
- **形态**: yt-dlp 的 postprocessor plugin，用法是 `--use-postprocessor danmaku`
- **底层**: 基于 `biliass`（yutto-dev 维护的 B 站弹幕转 ASS 库）
- **优势（vs 传统 `danmaku2ass`）**：
  1. 和 yt-dlp 的下载管线无缝集成，不需要自己管中间 XML 文件
  2. biliass 质量优于老牌 `danmaku2ass`，社区活跃
  3. README 给出的工作流正好是本项目需要的

### 2.2 依赖获取方式

`yt-dlp` 获取弹幕的机制：B 站弹幕在 yt-dlp 里作为一条字幕轨（`danmaku` 语言）暴露。

- 不加插件：`--write-subs --sub-langs danmaku` 可直接拿原始 XML
- 加插件：`--use-postprocessor danmaku` 会在后处理阶段调 biliass 把 XML 转成 `.danmaku.ass`

本项目只使用后者。

---

## 3. 项目结构

```
video2yt/
├── CLAUDE.md                      # Agent 项目上下文（命令、陷阱、约定）
├── README.md                      # 人类用户文档
├── pyproject.toml                 # uv 项目配置
├── uv.lock                        # 精确锁定的依赖版本（提交到仓库）
├── .python-version                # Python 版本 pin
├── .gitignore                     # 忽略 temp/、output/、__pycache__ 等
├── src/
│   └── video2yt/                  # Python 包名
│       ├── __init__.py
│       ├── __main__.py            # 支持 `python -m video2yt`
│       ├── cli.py                 # 参数解析 + main() 串流程
│       ├── download.py            # yt-dlp 封装
│       ├── burn.py                # ffmpeg 封装
│       └── validate.py            # ffprobe + ASS 校验
├── tests/
│   └── test_smoke.py              # mock subprocess 的 smoke test
├── docs/
│   ├── plan.md                    # 原始方案书（从根目录迁入）
│   ├── 2026-04-11-video2yt-design.md  # 本文档
│   ├── architecture.md            # 组件边界、数据流（实现时补）
│   └── usage.md                   # 详细用法、排错（实现时补）
├── temp/                          # 中间文件（gitignored，运行时创建）
└── output/                        # 最终视频（gitignored，运行时创建）
```

### 3.1 `src/` layout 的理由

- `src/video2yt/` 双层结构是 Python 包语义要求：`video2yt/` 是包名，`src/` 只是一个不可导入的容器目录。
- 相比扁平布局（`video2yt/` 直接在根），`src/` layout 强制先安装包才能导入，防止 cwd 污染，利于将来发布到 PyPI。

### 3.2 `CLAUDE.md` 内容要点

项目级 `CLAUDE.md` 不重复全局规则，只放：

- 项目一句话目标
- 常用命令（`uv run video2yt <url>`、`uv run pytest`）
- 外部依赖的特殊注意（ffmpeg 必须系统安装、yt-dlp 对 B 站解析规则易变需关注升级）
- 已知陷阱（ffmpeg `subtitles=` filter 路径转义敏感 → 代码里用 `cwd=` 切目录绕开）

---

## 4. 模块设计

### 4.1 `cli.py`

**职责**：参数解析、流程串联、错误输出。

**对外入口**：`main()`（由 `pyproject.toml` 的 `[project.scripts]` 注册为 `video2yt` 命令）。

**CLI 参数**：

| 参数 | 默认 | 说明 |
|---|---|---|
| `url`（位置参数） | — | B 站视频链接 |
| `-o, --output-dir` | `./output` | 最终视频输出目录 |
| `-t, --temp-dir` | `./temp` | 中间文件目录 |
| `-q, --quality` | `1080` | 清晰度上限（1080 / 720 / 480） |
| `-b, --browser` | `chrome` | cookie 来源浏览器 |
| `--keep-temp` | `False` | 保留中间文件 |

**调用示例**：

```bash
uv run video2yt "https://www.bilibili.com/video/BV191DpBmE2t/" --quality 1080
```

### 4.2 `download.py`

**职责**：调用 `yt-dlp` 下载视频并生成 `.danmaku.ass`。

**对外接口**：

```python
def fetch(
    url: str,
    temp_dir: Path,
    quality: int,
    browser: str,
    bv_id: str,
) -> tuple[Path, Path]:
    """返回 (video_path, ass_path)"""
```

**构造的命令**：

```bash
yt-dlp \
  --cookies-from-browser chrome \
  -f "bv*[height<=1080]+ba/b[height<=1080]/b" \
  --write-subs \
  --use-postprocessor danmaku \
  --output "<temp_dir>/<BV>.%(ext)s" \
  <url>
```

**设计说明**：

- 格式字符串的末尾 `/b` 是兜底——视频没有 1080p 变体时自动降级
- 用户传 `--quality 720` 时替换为 `[height<=720]`
- 文件命名用从 URL 正则提取的 BV 号做前缀（不用 yt-dlp 默认的视频标题），避免中文/特殊字符导致后续 ffmpeg 路径问题
- `--output` 模板在 Python 里预格式化为 `f"{temp_dir}/{bv_id}.%(ext)s"`（BV 号是普通字符串,`%(ext)s` 是 yt-dlp 模板变量）
- yt-dlp-danmaku 插件输出的 ASS 文件名由插件决定（通常为 `<base>.danmaku.ass`）。`fetch()` 返回前用 `sorted(temp_dir.glob(f"{bv_id}*.ass"))` 找到实际文件,避免硬编码后缀

### 4.3 `validate.py`

**职责**：用 `ffprobe` 探测视频 metadata，对输入/输出做完整性校验。

**对外接口**：

```python
@dataclass
class MediaInfo:
    duration: float
    width: int
    height: int
    has_video: bool
    has_audio: bool
    vcodec: str
    acodec: str | None
    size_bytes: int

def probe(path: Path) -> MediaInfo:
    """调 ffprobe -v error -print_format json -show_format -show_streams"""

def check_source(info: MediaInfo, requested_quality: int) -> list[str]:
    """返回 warnings；硬错误直接 raise"""

def check_ass(path: Path) -> int:
    """校验 ASS 结构，返回 Dialogue 行数（即弹幕条数）"""

def check_output(source: MediaInfo, output: MediaInfo) -> None:
    """失败 raise ValueError"""
```

**校验规则详表**：

**源视频校验 (`check_source`)**:

| 校验项 | 严重度 | 处理 |
|---|---|---|
| 无 video stream | 致命 | raise |
| duration == 0 或 None | 致命 | raise |
| 无 audio stream | 警告 | 打印但继续（无声视频合法） |
| 分辨率 < 要求清晰度 | 警告 | 打印（提示可能 cookie 未生效） |

**ASS 校验 (`check_ass`)**:

| 校验项 | 处理 |
|---|---|
| 能以 UTF-8 读取 | 否则 raise |
| 包含 `[Events]` 段 | 否则 raise |
| `Dialogue:` 行数 ≥ 1 | 否则 raise（"该视频无可用弹幕"） |

返回 Dialogue 行数用于打印"检测到 X 条弹幕"的日志。

**输出视频校验 (`check_output`)**:

| 校验项 | 处理 |
|---|---|
| 文件存在且 size > 0 | raise |
| ffprobe 能解析（exit 0） | raise |
| 有 video stream + audio stream（若源有 audio） | raise |
| 视频编码 == `h264` | raise（确认 libx264 参数生效） |
| `abs(output.duration - source.duration) < 1.0` 秒 | raise（catches 截断） |
| `output.width == source.width && output.height == source.height` | raise |
| output size 在 `[source.size × 0.3, source.size × 5]` 之间 | 仅警告 |

### 4.4 `burn.py`

**职责**：调用 `ffmpeg` 把 ASS 烧录进视频。

**对外接口**：

```python
def render(video_path: Path, ass_path: Path, output_path: Path) -> Path:
    """返回 output_path"""
```

**构造的命令**：

```bash
ffmpeg -y \
  -i <video_filename> \
  -vf "subtitles=<ass_filename>" \
  -c:a copy \
  -c:v libx264 -preset medium -crf 20 \
  <output_filename>
```

**关键细节**：

- **subprocess 的 `cwd=temp_dir`**：ffmpeg 的 `subtitles=` filter 对绝对路径的转义极其敏感（空格、冒号、括号都会炸），这是业界公认的坑。解决办法：
  - `subprocess.run(..., cwd=temp_dir)` 切到 temp 目录
  - `-vf "subtitles=<ass_filename>"` 里传 **相对文件名**（因为 ASS 就在 cwd）
  - `-i` 也传相对文件名（视频同在 temp 目录）
  - **输出路径传绝对路径**（`output_path` 在 `output/` 目录，不在 cwd），ffmpeg 的输出参数不经过 `-vf` filter，对绝对路径无转义问题
- **编码参数**：`-c:v libx264 -preset medium -crf 20` 是视觉无损与速度的甜蜜点；`-c:a copy` 直接拷贝音频流，不重编码。

### 4.5 `__main__.py`

```python
from video2yt.cli import main
if __name__ == "__main__":
    main()
```

---

## 5. 执行流程

```
cli.main()
  ├─ 1. 解析参数
  ├─ 2. 预检依赖（fail-fast）
  │     - shutil.which('ffmpeg') → 否则报错
  │     - shutil.which('ffprobe') → 否则报错
  │     - import biliass → 否则报错（提示 uv add yt-dlp-danmaku）
  ├─ 3. 正则提取 BV 号（URL 校验一体化）
  ├─ 4. 创建 temp_dir 和 output_dir
  ├─ 5. download.fetch() → (video_path, ass_path)
  ├─ 6. source_info = validate.probe(video_path)
  ├─ 7. validate.check_source(source_info, quality)
  ├─ 8. n_danmaku = validate.check_ass(ass_path)
  │     打印 "检测到 {n_danmaku} 条弹幕"
  ├─ 9. output_path = <output_dir>/<BV>_with_danmaku.mp4
  ├─ 10. burn.render(video_path, ass_path, output_path)
  ├─ 11. output_info = validate.probe(output_path)
  ├─ 12. validate.check_output(source_info, output_info)
  ├─ 13. 清理 temp（除非 --keep-temp）
  └─ 14. 打印成功 + 输出路径
```

---

## 6. 错误处理策略

**总原则**：fail-fast，透传底层工具 stderr，不包装不美化。

| 场景 | 行为 |
|---|---|
| URL 格式不合法 | 立即报错，打印期望格式示例 |
| 缺 `ffmpeg` / `ffprobe` | 立即报错，提示 `brew install ffmpeg` |
| 缺 `yt-dlp-danmaku` | 立即报错，提示 `uv add yt-dlp-danmaku` |
| `yt-dlp` 非零退出 | 捕获 stderr 原样打印 |
| Chrome cookie 读取失败 | yt-dlp 会给出明确原因（Chrome 未装 / 正运行 / DB 锁），透传 |
| ASS 校验失败 | 报 "该视频无可用弹幕"，不产出视频 |
| `ffmpeg` 非零退出 | 捕获 stderr 原样打印 |
| 输出视频校验失败 | raise，打印具体不一致项，保留 output 文件供检查 |
| Ctrl-C | 保留 temp/（方便调试），stderr 打印 "已取消，中间文件保留在 temp/" |
| 正常完成 | 删除 temp/（除非 `--keep-temp`），打印输出路径 |

**实现约定**：所有 `subprocess.run(..., check=True, capture_output=True, text=True)`，失败时拿 `e.stderr` 展示；不用 logging 框架，直接 `print(..., file=sys.stderr)`。

---

## 7. 测试策略

### 7.1 自动化测试

单个文件 `tests/test_smoke.py`，用 `monkeypatch` mock 掉 `subprocess.run` 和 `ffprobe` 输出：

1. **URL 解析**：
   - 合法 `https://www.bilibili.com/video/BV191DpBmE2t/?spm_id_from=...` 能提取 `BV191DpBmE2t`
   - 非法 URL（比如 YouTube 链接）报错

2. **命令构造正确**：
   - `download.fetch()` 构造的 yt-dlp 命令包含 `--cookies-from-browser chrome`、`-f "bv*[height<=1080]+..."`、`--use-postprocessor danmaku`、正确的 `--output`
   - `burn.render()` 构造的 ffmpeg 命令 `-i` 和 `subtitles=` 都用相对文件名,输出用绝对路径,`subprocess.run` 的 `cwd` 参数为 `temp_dir`

3. **validate 逻辑**：
   - `check_source`: 无 video stream → raise；duration == 0 → raise；分辨率不足 → 只警告不 raise
   - `check_ass`: 文件不存在 → raise；无 `[Events]` → raise；0 条 Dialogue → raise；正常文件 → 返回正确行数
   - `check_output`: duration 偏差 > 1s → raise；分辨率不一致 → raise

4. **依赖预检**：
   - `shutil.which('ffmpeg')` 返回 `None` → main() 报错退出

**跑法**：`uv run pytest`。全部 mock，毫秒级完成。

### 7.2 手动验收

实现完成后，用测试 URL `https://www.bilibili.com/video/BV191DpBmE2t/` 跑一次完整流程：

1. `uv run video2yt "<url>"` 执行成功
2. `output/BV191DpBmE2t_with_danmaku.mp4` 存在且可在 QuickTime/VLC 中播放
3. 肉眼确认视频中有弹幕滚动
4. `ffprobe` 查看输出视频分辨率 ≥ 1080p
5. 测一次 `--keep-temp`，确认中间文件保留
6. 测一次无效 URL，确认错误信息清晰

手动步骤写进 `docs/usage.md` 作为验收 checklist。

---

## 8. 依赖版本锁定

`pyproject.toml`:

```toml
[project]
name = "video2yt"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = [
    "yt-dlp>=2025.1.1",
    "yt-dlp-danmaku>=0.2.0",
]

[project.optional-dependencies]
dev = ["pytest>=8.0"]

[project.scripts]
video2yt = "video2yt.cli:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/video2yt"]
```

**策略**：依赖用宽松 `>=` 下限，精确锁定交给 `uv.lock`（提交到仓库）。`yt-dlp` 更新频繁（B 站反爬规则常变），锁死具体版本会影响升级；让 `uv.lock` 承担可复现性是 uv 工作流的标准做法。

---

## 9. 里程碑

对应 `plan.md §13`，本设计文档覆盖里程碑 1-2 的实现。里程碑 3-4 属于后续增强。

1. **M1 - 环境搭建**：`uv init` + 装依赖 + 系统装 ffmpeg
2. **M2 - 单链接打通**：实现 4 个模块 + smoke test + 手动验收通过
3. **M3 - 异常处理**（后续）：失败重试、多 P 支持、无弹幕兜底
4. **M4 - 工程化完善**（后续）：日志框架、批量处理、UI 工具

---

## 10. 已知限制

继承自 `plan.md §11`：

- B 站平台规则变动可能导致 `yt-dlp` 解析失效
- 极高密度弹幕的视觉效果与 B 站原生引擎有差异
- `ffmpeg` ASS 渲染依赖系统字体（macOS 默认有中文字体，通常无需额外配置）
- Chrome cookie 读取要求 Chrome 完全退出或至少不持有 cookie DB 锁

## 11. 验收标准

对应 `plan.md §12`：

1. ✅ 输入 `BV191DpBmE2t` 后产出一个 MP4 文件
2. ✅ 输出视频可见弹幕
3. ✅ 弹幕时间轴与原视频一致
4. ✅ 输出可在 QuickTime / VLC 直接播放
5. ✅ 失败时错误信息清晰（URL 不合法 / 依赖缺失 / 无弹幕 / 下载失败各给明确提示）
6. ✅ 输出视频通过 `validate.check_output()` 全部校验
