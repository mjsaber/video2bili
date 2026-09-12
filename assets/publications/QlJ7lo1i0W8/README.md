# 自傷惡魔：发布与改动总结

视频：[2 血養出萬攻惡魔！死亡之聲與自傷，資源怎麼接？｜英雄戰場](https://www.youtube.com/watch?v=QlJ7lo1i0W8)。2026-09-12 已公开，成片 39 分 04 秒，1080p / 30 fps / AAC 48 kHz。

## 本期成片

- 采用用户批准的彩色漫画海报，副标题改为「無限經濟？」；旧变体、提示词及实际上传封面均保留。内置 ImageGen 未提供可核验的模型 ID。
- 17.47 秒开场保留「你敢相信？」：2 血万攻证据、瓦莉拉卡位原声，再交代死亡之声补法术与自伤拿蛋糕。
- 郭枫保留原内嵌字幕；瓦莉拉清理后显示 37 段字幕，原始 73 段和审计记录保留。
- 删除郭枫前 14.6667 秒无关短片与瓦莉拉前 3.5 秒原作者片头；同步更新 10 个章节和 CTA。
- 片尾推荐在 38:58:00–39:03:29 显示，目标为食料恶魔视频 `OWs72CWD_bU`；Studio 保存后重新打开核验。

## 流程修正

本期发现原合并器在 loudnorm 前重采样，最终 AAC 仍变成 96 kHz。成片已重新导出为 48 kHz；本次代码提交将重采样移到 loudnorm 后，并显式指定输出 48 kHz。真实 ffmpeg 回归测试覆盖 48/96 kHz 输入，修复前均输出 96 kHz 并失败，修复后通过。

制作 SOP 增加源片前缀检查、最终接点抽查、采样率与完整解码验收、线上播放及片尾验证，以及带 BV 文件名的来源记录。发布文案只保留音乐署名和许可，去掉内部粘贴说明。原上传元数据和最终线上描述分别保留。

## 验收与清理

- 本地完整解码通过；相关回归测试：`uv run pytest -q tests/test_merge_chapters.py tests/test_publication.py tests/test_cleanup.py`，79 项通过。
- API 确认 `public / processed / succeeded`，Studio 高清处理完成，观看页实际播放已核验。
- 清理工具此前删除本期两条来源缓存和上一期 `golem_transition_s14` 输出，回收 5.7 GB；本次复查无剩余清理目标。本期 `output/self_damage_demons_s14/` 成片按既定规则保留。
- 未运行封面 A/B 实验；订阅评论只有草稿，未发布。全片检查包含解码与抽查，不等同于逐秒实时听审。

最终记录：`publication.json`、`online_verification.json`、`watch_page_verification.json`、`endscreen_verification.json`、`delivery_verification.json`。实际线上文案见 `published_description.txt`；原上传文案见 `uploaded_metadata.json`。
