# 视频拉新：制作与复盘

本规则自 2026-09-05 起取代旧的固定长片头、固定 4+4 字封面、固定完整教学标题和第一场结束后 CTA 规则。品牌声音、繁体术语核验、原片来源和音乐署名继续保留。

## 每期内容计划

在项目根目录写 `growth_plan.md`，记录以下决策及证据。它会随发布记录归档。

1. **受众与承诺**：本期帮助哪类玩家做什么决定；标题和封面的数字要对应实际画面。
2. **证据**：来源 URL、准确时间点、画面/台词内容、补丁/赛季和核验人。模型输出一律待核验；无法确定版本则标未知，不能强行宣传“新版本”。
3. **开场时间线**：先试验 0–5 秒展示结果、5–15 秒解释本期问题、15–20 秒进入关键操作。机制介绍按需分散到正文；`你敢相信？` 可保留，但不为口号延后证据。不把该时长当作平台标准。
4. **正文剪辑表**：来源起止时间、保留理由、该段解释的买牌/升本/转型/站位决策。删除重复等待时保留经济、血量和阵容上下文，不把所有准备阶段一律删掉。
5. **教学承诺核验**：使用“完整教学”必须包含启动条件、关键决策、缺组件时的替代方案及限制；两场高上限对局不足以证明“最稳”“T0”。
6. **CTA**：选在第一次兑现有用信息之后，用一句话说明订阅的持续价值。记录精确时间点，检查附近是否出现留存下降；不要硬性等第一场打完。
7. **下一条视频**：写出具体相关视频 ID 与衔接理由，片尾保留适合显示推荐的画面；Studio 添加片尾元素后记录验收结果。
8. **实验**：本期改变的变量、对照、预期指标、停止条件、结果与结论。不要每期同时换片头长度、文案、封面和剪辑节奏然后归因给其中一个。

## 合并与章节

输入段仍须 1920×1080、30fps、h264、有音频和正时长。可只有一个或两个片段，短 hook 与 CTA 均可成为剪辑片段。默认仅在片段自然满足章节规则时生成章节；否则省略。

```bash
uv run video2yt-merge \
  --segment output/demo/hook.mp4 --label '結果預覽' \
  --segment output/demo/battle.mp4 --label '關鍵決策' \
  --chapters-file output/demo/editorial_chapters.txt \
  --title '海盜倒轉' -o output/demo/final.mp4
```

`editorial_chapters.txt` 使用最终视频时间线，不是源视频时间。例如下列示例需最终视频至少 5:10：

```text
00:00 這局能做成什麼
00:30 何時開始轉型
05:00 缺少核心卡怎麼辦
```

显式章节必须至少三个、首个 00:00、递增，每段含最后一段至少十秒。`--no-chapters` 可明确关闭。只将成功生成的 `_chapters.txt` 放入描述，省略时不要复用旧章节。

## 实战内 CTA

```bash
uv run video2yt-cta --video output/demo/battle.mp4 \
  --text '訂閱馬哥，每期拆解一個轉型決策' --at 90 --duration 4 \
  -o output/demo/battle_cta.mp4
```

90 秒仅是命令示例，选择本期首次提供价值的位置。文字覆盖不延长片长或改变音频；预览其位置，避开手牌、阵容和字幕。旧 `append_cta.sh` 保留为显式选择的整屏 CTA，不再是强制默认。片尾推荐需在 Studio 设置，CLI 不假装完成线上配置。

## 标题、封面实验

默认采用**日式动漫素描**：奶油白底、铅笔线稿与轻排线，搭配清晰可见的薄荷绿、雾蓝、蜜桃粉和浅杏黄彩铅色块。`video2yt-image`、`thumbnail_polish.py`、`video2yt-intro` 统一默认 `--style anime-sketch`。风格与 `brand/payoff` 布局独立；真实卡面保留，素描角色已通过真实透明通道和合成预览检查，默认启用；原透明角色保留为回退。生成步骤、参考图和旧风格选项见 [画风规范](visual-style.md)。

标题将具体结果或决策放前面，游戏、流派、主播信息按需要后置；不要求固定全称前缀或“完整教学”。标题/封面只承诺实际兑现的内容。

```bash
uv run python scripts/thumbnail_polish.py \
  --bg output/demo/intro_bg.png --card assets/cards/hooktusk_master_marauder_zhTW_bgs_512.png \
  --primary '鉤牙海盜' --secondary '全隊破萬' --layout payoff \
  --variant-id payoff --video-title '13回合全隊破萬，鉤牙海盜怎麼轉型？｜英雄戰場' \
  --hypothesis '結果優先的封面能吸引第一次看到本頻道的玩家' \
  --output output/demo/thumbnail_payoff.png
```

同一项目保存不同文件名，避免覆盖变体；脚本输出 `.variant.json` 和 `_mobile.png`，用于移动端可读性检查与归档。生成图片只代表准备完成，不代表实验已在 YouTube 运行。

在符合资格的 Studio 中测试最多三组不同标题/封面。先只改标题或只改封面，若测试整套包装则仅对整套归因。在项目根目录保存 `experiment_results.json`，记录 video_id、变体 ID、起止时间、平台结果、实际观看时长占比及结论；样本不足就写未确定。实验运行中手改标题/封面会终止平台实验。

官方说明：https://support.google.com/youtube/answer/16391400?hl=en

## 发布、恢复、归档

```bash
uv run video2yt-upload --metadata output/demo/youtube_metadata.json --dry-run
uv run video2yt-upload --metadata output/demo/youtube_metadata.json
```

上传元数据必须包含正整数 `season`。`publication.json` 的 `complete` 才代表上传和所选后续步骤完成；退出码 1 表示仍需处理。重复命令会复用视频 ID，继续失败的封面/播放列表步骤。只有封面变化时可在同一视频重试；已上传的视频文件或上传元数据变化会拒绝，以免悄悄重复发布。

上传中断且没有 ID 时，先检查 Studio。如果视频已存在，以准确的同频道同标题视频恢复；该命令会继续本地封面与播放列表设置：

```bash
uv run video2yt-upload --metadata output/demo/youtube_metadata.json --adopt-video-id VIDEO_ID
```

只有确认 Studio 没有创建视频后才用 `--retry-uncertain`。旧项目只有 `youtube_metadata.json` 时不会自动获得清理资格，须先核验已有视频。归档在 `assets/publications/<video_id>/`：文稿、证据、制作封面、实验记录、回执永久保留；`uploaded_thumbnail.*` 是与成功上传哈希相符的封面，与尚未上传的本地候选区分。

```bash
uv run video2yt-cleanup --project demo
uv run video2yt-cleanup --project demo --yes
```

先查看 dry-run。工具先归档当前和待清理项目，再回收媒体；归档出错则停止删除。`output/` 和 `temp/` 是大文件工作区，`assets/publications/` 与 `assets/analytics/` 不属于清理范围。

## 24 小时、7 天、28 天复盘

```bash
uv run video2yt-analytics report --receipt assets/publications/VIDEO_ID/publication.json
uv run video2yt-analytics collect --receipt assets/publications/VIDEO_ID/publication.json --window 7d
```

`collect` 需首次授权 Analytics 只读访问，使用独立的 `youtube_analytics_token.json`。不会使用或升级上传令牌。结果存 `assets/analytics/`。它采集 API 支持的播放、观看时长、观看页订阅和来源；曝光、CTR、新观众、精确 30 秒留存不能从这些指标推断，保留空值并支持 Studio 导入。

Studio 导入用规范 JSON 或 CSV，需要手动把本地化导出的列映射到以下字段。这里的数字仅为格式示例：

```json
{
  "metrics": {
    "views": 1000,
    "watch_minutes": 5000,
    "average_view_duration_seconds": 300,
    "retention_30s_pct": 62.5,
    "subscribers_gained": 3,
    "impressions": 8000,
    "impressions_ctr_pct": 5.2,
    "new_viewers": 700
  },
  "traffic_sources": {"BROWSE": {"views": 600, "watch_minutes": 3000}}
}
```

```bash
uv run video2yt-analytics import \
  --receipt assets/publications/VIDEO_ID/publication.json --input studio.json \
  --window 24h --start 2026-09-05 --end 2026-09-06
```

日期是太平洋时区、包含起止日；API 按日桶不能冒充发布后精确 24 小时。`--window-kind exact` 使用带时区的 ISO 起止时间，且回执必须有核实后的 `published_at`。实际区间、采集时间、来源和完成度会一起保存。缺数据不记作零；没有真实发布时间时明确使用上传时间参考。

复盘按相近发布时间、视频形态及流量来源比较，观察新观众、前 30 秒留存、观看时长、每千次观看订阅及下一条观看。浏览、推荐、搜索分开看；曝光扩大同时 CTR 下降不自动判失败。不要用一次小样本前后变化宣布因果。
