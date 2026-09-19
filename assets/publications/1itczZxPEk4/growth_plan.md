# balinda_mech · growth_plan（2026-09-17）

1. **受眾與承諾**：想玩機械巴琳達、不知道該掛機還是手動的玩家。承諾：看懂一張法術四次效果的鏈條（巴琳達→墜盒→華麗機器人合體→通用無人機回合結束），以及自動擋 vs 手動擋的取捨。標題/封面數字「一萬攻」= 郭楓荷 18:17 自己場上 6900→17000（抽幀 bm_key_sheet.jpg 下排己方）。
2. **證據**：content_understanding.md（ASR 時間 + 抽幀 + 卡面文本）。郭楓荷 18:41 第一名 15774；瓦莉拉影片停在第 14 回合招募，無名次，任何文案不寫瓦莉拉名次。
3. **開場**：不用冷開場（使用者決定）。intro 31.5s 三段式（結果→機制→決策）→ CTA 4.9s → 正片。
4. **正文**：郭楓荷 BV1bBeA6CEP7（--cut 0~12 去掉主播自帶冷開場；源自帶字幕 → --no-subtitle）→ 瓦莉拉 BV1N9eE6UEvM（無內嵌字幕，清洗 49 塊、DROP 10，review READY）。順序：先手動擋成功局，再自動擋的教訓。
5. **教學承諾**：封面「完整教學」。正文有啟動條件（巴琳達＋墜盒＋華麗機器人＋通用無人機）、關鍵決策（自動 vs 手動、沒錢時餵誰）、限制（郭 12:24 沒錢卡住；瓦莉拉自認選錯）。
6. **CTA**：intro 後獨立 4.9s 段（沿用 escapist_core/cta.mp4）。
7. **下一條影片**：上一期 A1Zc2GGfDLY（逃脫者），片尾元素指向它；描述互鏈。
8. **實驗**：本期只換一個變數 = 標題用「決策對比」（自動擋不如手動擋）對照上期的「數字 payoff」。
9. **Shorts**（每素材一條，同日上傳）：郭楓荷 16:33~18:41.8（最後一回合招募→回合結束 6900→17000→第一名；彈幕密度峰值其實在 12:25~13:55 貸款段子 48 條，但無數值畫面，改用 payoff 回合）；瓦莉拉 4:50~6:58（彈幕密度峰值 5:10~6:40 共 33 條：融合巴琳達 / 自動機械遊戲結束 / 手動＞自動）。均用 no_music.wav + 音樂床。

## 製作狀態（2026-09-17）
- 成片 balinda_mech_final.mp4：33:33，1920×1080 30fps h264 + AAC 48k，章節 13 條（editorial_chapters.txt，抽幀核對 18:22 = 6900→17000、26:54 低語決策）。音量 mean −14～−25 dB，peak ≤ −0.4 dB。
- 段落：intro 31.5s（三段式，5 張卡）→ CTA 4.9s → 郭楓荷（--cut 0~12 去主播冷開場，源自帶字幕不疊）→ 瓦莉拉（清洗字幕 39 塊燒錄，review READY）。
- 封面 thumbnail.jpg = thumbnail_polish_v2（v1 人物過高蓋到「完整教學」，縮到 68% 後重排）。
- Shorts：guo（16:33~18:41.8，132.8s）、val（4:50~6:58，132s），均 no_music.wav + 音樂床、彈幕重排。修了 short.py：兩行斷言時語境/預期行下移 96px（v1 兩行斷言被語境框蓋住）。
- 待「發」：上傳長片 → 兩條 Short → 留言/置頂/相關影片/片尾元素 → 1 小時後 regionRestriction。

## 發布記錄（2026-09-17）
- 長片 1itczZxPEk4 https://www.youtube.com/watch?v=1itczZxPEk4 ；訂閱留言 UgwfD5cinirrVlkVi2p4AaABAg（已置頂）；列表「英雄戰場 S14 流派教學」；片尾元素：訂閱 + 指定影片 A1Zc2GGfDLY（33:13–33:33，Studio 模板，Save 後顯示 Edit）。
- Short 郭楓荷 da0akvJh6lI（16:33~18:41.8）留言 UgzBoL97XSjf9X9SMPB4AaABAg（已置頂）；Short 瓦莉拉 1aHF3PyvYX4（4:50~6:58）留言 UgwvFJFArtAich9EyPZ4AaABAg（已置頂）；均在「英雄戰場 S14 Shorts」；Studio「相關影片」→ 1itczZxPEk4（Save 變灰確認）。
- Short 上傳教訓：metadata `thumbnail_path` 為 null 會在上傳前 TypeError，Short 也要給一張 thumb.jpg（取 2.2s 幀）。
- regionRestriction 首查（上傳後 15 分鐘）：三條皆 None、processed、public。1 小時後複查：待執行。
