# 日式动漫素描画风

自 2026-09-05 起，新封面与片头背景默认采用 `anime-sketch`。

- **画法**：日式动漫线稿、可见铅笔笔触、细排线、轻网点；纸张纹理自然。
- **配色**：米白纸底、石墨深灰，少量低饱和赭黄与灰蓝铅笔淡彩。
- **构图**：左侧标题区与左下字幕区留白；本期主题道具集中在中右部，避免抢字。
- **合成**：深墨标题、浅纸细描边；去掉金色光晕和厚重暗角。背景及角色要使用真实生成的素描素材，合成参数不会把旧油画变成素描。
- **辨识**：官方卡面与游戏标识保持原样；头像和已经制作的 CTA 视频继续使用各自原素材。

## 新背景

项目提示词描述场景和道具；默认风格会作为最终画法要求附加到提示词，并同时用于 Codex / Gemini 后端。

```bash
uv run video2yt-image \
  --prompt 'Subjectless fantasy tavern, a pirate treasure chest and scattered coins at lower center-right; quiet pale left half for titles; no people, text or logos.' \
  --style anime-sketch --target-size 1920x1080 \
  -o output/demo/intro_bg_sketch.png
```

图像生成具有随机性，生成后检查线稿、留白和纹理；不要直接复用与新风格矛盾的旧背景。通用参考图：`assets/branding/anime_sketch/tavern_bg.png`。其他流派应替换道具，不必每期都画宝箱。

## 封面

```bash
uv run python scripts/thumbnail_polish.py \
  --bg assets/branding/anime_sketch/tavern_bg.png \
  --card assets/cards/hooktusk_master_marauder_zhTW_bgs_512.png \
  --primary '鉤牙海盜' --secondary '全隊破萬' \
  --style anime-sketch --layout payoff \
  --output output/demo/thumbnail_sketch.png
```

透明素描角色已完成，路径为 `assets/branding/anime_sketch/mascot.png`。在用户授权后，从原参考稿本地提取真实 alpha，清除外部棋盘格及发卷空隙，保留皮肤、浅色头发和围裙。封面与片头默认自动选用该角色；素材缺失或不透明时才回退原角色。原稿和可复用遮罩分别保存在 `mascot_reference.png`、`mascot_alpha.png`；复现方法见 [素材记录](../assets/branding/anime_sketch/README.md)。可用 `--mascot` 指定其他透明 PNG。`--no-mascot`、`--no-logo` 和双卡/第三行选项仍可用。`brand/payoff` 仅控制文案层级，与画风独立。

实验仍使用 `--variant-id`、`--video-title`、`--hypothesis` 三个参数，manifest 记录 `style`、布局与素材哈希，并生成 320×180 缩图。新画风的点击效果需要后续真实实验验证。

## 动态片头

```bash
uv run video2yt-intro --audio output/demo/intro.mp3 \
  --bg output/demo/intro_bg_sketch.png --srt output/demo/intro.srt \
  --cards output/demo/intro_cards.txt --style anime-sketch \
  -o output/demo/intro_sketch.mp4
```

素描主题保留原背景亮度，跳过旧暗角遮罩，使用深墨字幕与浅纸描边。卡牌时间、角色摆动和字幕位置保持现有行为。

## 旧画风

显式 `--style warm-tavern` 可选择旧配色与旧角色（图像生成、封面、片头三处均支持）。重新制作旧项目时应同时选择旧背景和旧主题；图像生成的 `--style none` 表示完整使用自定义提示词。已有项目产物不会自动被覆盖。

## 本次预览

背景由内置 ImageGen 根据原鉤牙项目背景重新绘制，最终提示词存于 `assets/branding/anime_sketch/tavern_bg.prompt.txt`。
封面预览：`output/style_preview/thumbnail_sketch_clean.png`，缩图：`output/style_preview/thumbnail_sketch_clean_mobile.png`。预览使用既有鉤牙卡面及项目文案，仅展示画风，不代表新视频已发布或完成效果实验。

2026-09-05 收尾验收：`output/repository_closeout_20260905/` 保存最终单卡、双卡封面、320×180 移动端预览、三色底角色检查图及 3 秒片头。均使用默认透明素描角色，未改动历史成片。
