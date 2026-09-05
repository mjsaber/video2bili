# Anime Sketch Visual Style Implementation Plan

**Goal:** 将用户指定的日式动漫素描作为新封面和片头背景的默认画风。

**Architecture:** 图像生成负责真实铅笔线稿、排线和淡彩纸纹；合成器负责深墨标题、浅色描边与克制阴影。官方卡面保持原图，角色使用新生成的透明素描素材。`anime-sketch` 与 `warm-tavern` 独立于封面 `brand/payoff` 布局，旧素材保留。

**Tech Stack:** Python、Pillow、FFmpeg/libass、ImageGen、pytest。

- [x] 在 `tests/test_visual_style.py`、`tests/test_thumbnail_variants.py` 增加默认风格、生成后端、浅底对比、旧风格兼容测试，执行 `uv run pytest tests/test_visual_style.py tests/test_thumbnail_variants.py -q` 确认新行为尚未实现。
- [x] 新增 `src/video2yt/visual_style.py` 定义风格、角色路径和提示词；`image_gen_cli.py` 默认 `--style anime-sketch`，`--style none` 保留原始提示词。
- [x] `scripts/thumbnail_polish.py` 增加默认浅纸底、石墨标题、无金色光晕的素描主题，并在 variant manifest 中记录 style。
- [x] `intro_cli.py` / `intro_compose.py` 默认选择素描角色，去掉全图压暗，字幕采用深墨色与浅纸描边；显式 `warm-tavern` 保留旧渲染。
- [x] 将生成的背景和透明角色放入 `assets/branding/anime_sketch/`；更新 README、CLAUDE 和制作 SOP。
- [x] 执行 `uv run pytest -q`、`git diff --check`；渲染 1280×720 封面、320×180 缩图和短片头，肉眼检查文字与角色。

不覆盖历史项目产物，不修改已有视频或上传。预览用现有鉤牙海盜素材与文案，以便直接比较画风。

执行结果：背景、主题、文档、实际封面与 3 秒片头验证已完成。独立代码审阅无问题。生成服务未提供真实 alpha；本次用户明确允许本地 Python 抠图，已从原参考稿制作 RGBA `mascot.png` 并保留 `mascot_alpha.png`，封面和片头默认自动选用。三色底检查、单卡/双卡封面、移动端缩图和 3 秒 1080p/30fps 片头已验收。另修复双卡扇形的底部和宽后卡裁切，回归测试先复现失败再通过。
