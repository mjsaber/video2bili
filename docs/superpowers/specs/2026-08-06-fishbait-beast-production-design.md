# S14 鱼饵野兽双视角视频制作设计

**日期：** 2026-08-06  
**状态：** 待用户书面确认  
**项目目录：** `output/fishbait_beast_s14/`

## 1. 目标

制作一期强调《炉石战记：英雄战场》第 14 赛季更新的鱼饵野兽教学视频。正片采用郭枫荷与瓦莉拉两条完整实战，Intro 必须从下载后的 speech 与弹幕中提炼，只介绍两场对局实际出现的新版本卡牌、黑暗之赐与成长链，不根据标题猜测机制。

## 2. 源视频

1. 郭枫荷：[版本答案，鱼饵流野兽玩法——酒馆战棋新版本](https://www.bilibili.com/video/BV1wdGA61EhL)
2. 瓦莉拉：[【炉石瓦莉拉】酒馆战棋新版本不败吃鸡 看看野兽也多强！](https://www.bilibili.com/video/BV1ADMk6mEDv)

两条源先通过 `video2yt-prefetch` 串行下载到共用 `temp/` 缓存，并验证分辨率、音视频完整性和弹幕文件。随后分别运行 stems 与一次 `--skip-cleanup` ASR，用 raw speech 和弹幕完成内容理解。

## 3. 叙事设计

Intro 固定以「你敢相信？」开头，使用繁体中文和英雄战场词汇，时长约 30 秒。叙事顺序为：

1. 点出 S14 新增的鱼饵机制，让野兽在招募阶段主动攻击并获得成长。
2. 展示两场实战共同出现的核心新卡、黑暗之赐或关键组件。
3. 对比郭枫荷的提速／成型思路与瓦莉拉的不败运营路线。
4. 用一句话说明观众能从两场对局学到的升本、组件与终局选择。

任何具体卡名、英雄名、饰品或黑暗之赐名称都必须先从视频内容中确认，再通过官方 zhTW 卡面核对；未在两场实战中出现的更新卡不进入 Intro。

## 4. 背景图视觉升级

采用“深海荧光鱼饵”方向，替换目前偏平、吸睛度不足的暖色旅店背景：

- 场景仍是无人物的英雄战场旅店环境，但受到深海魔法侵染。
- 画面低处中央设置单一、明确的金橙色发光鱼饵作为第一视觉焦点。
- 周围使用深蓝、青绿水流、珊瑚剪影、潮湿木材和少量漂浮粒子制造层次。
- 通过青蓝环境与金橙焦点形成高饱和冷暖对比，提高首屏冲击力。
- 右侧女老板覆盖区域、左下字幕区域和顶部标题安全区保持局部偏暗、低细节。
- 不生成角色、动物主体、卡牌、文字、数字、Logo 或 UI。
- 缩略图沿用频道标准双层标题、核心卡牌与女老板构图，并复用这套高反差色彩语言。

建议的基础 Prompt 结构：

> A cinematic high-impact Hearthstone-inspired battlegrounds tavern transformed by bioluminescent deep-sea magic, a single molten-gold enchanted fishbait glowing intensely at the lower center as the clear focal point, saturated teal and cyan currents, coral silhouettes, wet polished wood, suspended bubbles and magical particles, dramatic volumetric lighting, strong cool-versus-warm contrast, rich depth, premium fantasy game key art, locally darker and less detailed across the entire right side, lower-left subtitle area, and top title strip, no characters, no creatures, no cards, no text, no numbers, no logos, no interface, 16:9 composition.

生成后必须以缩略图尺寸检查焦点是否仍然清楚；若金色鱼饵不够醒目，只调整亮度、尺寸、轮廓与周边对比，不增加第二个视觉主体。

## 5. 制作流程与检查点

1. 下载两条源并检查 1920×1080、时长、音轨与弹幕。
2. 提取 speech，运行一次 raw ASR，结合弹幕写 `content_understanding.md` 与 `intro_script.txt`。
3. 向用户提交内容理解与 Intro 文案，完成审核检查点 1。
4. 核对官方 zhTW 卡面并修正术语。
5. 生成新版高反差背景、TTS、对齐字幕与动态 Intro。
6. 向用户提交 `intro.mp4`，完成审核检查点 2。
7. 清洗两条正片字幕、替换音乐、烧录、追加 CTA、合并并验证。
8. 生成缩略图和 YouTube 元数据，上传前提交最终审核。
9. 经明确授权后上传，自动加入 S14 独立播放列表并发布订阅评论。

## 6. 错误处理与验收

- 任一源低于 1080p、下载截断、无有效音轨或缺少弹幕时，先修复或替换源，不带病进入烧录。
- ASR 只调用一次；后续繁体清洗保持原块号与时间戳完全不变。
- Intro 中每个展示卡名都必须能在 SRT 中顺序匹配，并与官方 zhTW 卡面一致。
- 背景图在 640px 宽预览下仍需看见单一金橙焦点，字幕和女老板区域不得被高亮细节干扰。
- 最终视频需通过分辨率、帧率、编码、音频采样率、时长与章节检查。
- 上传后的播放列表必须是 S14 专属列表，不得加入 S13 列表。

