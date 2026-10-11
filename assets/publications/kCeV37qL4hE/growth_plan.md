# murloc_poison · growth_plan（2026-09-20）

1. **受眾與承諾**：想玩魚人、不知道該養大哥還是下毒的玩家。承諾：毒魚板凳怎麼打身材哥、未來鰭＋合唱團怎麼把體質兌現；決策 = 有沒有七本。標題數字「四萬七」= 郭楓荷 A 23:14 自述（畫面最左那隻被裁掉，未能讀到數字）；「上萬海盜」= B 20:15 對面 13K/16K/17K（frames/b_end.jpg）。
2. **證據**：content_understanding.md。兩局最後 0.4 秒都有「第一名！！」結算（B 14584、A 14306），文案可寫兩局第一。
3. **開場**：intro 30.0s 三段式（結果→三張卡→決策）→ CTA 4.9s → 正片。
4. **正文**：先 B（毒死海盜，結果先行）再 A（未來鰭養大）。兩段 --cut 0~18 去純臉冷開場；源自帶字幕 → --no-subtitle。
5. **教學承諾**：封面「完整教學」。正文有啟動條件（毒魚 + 板凳 / 七本未來鰭）、關鍵決策（B 4:14 純電表、A 19:08 決賽打誰手裡放毒）、限制（B 15:23 法術沒拿失誤、A 0:53 這版本元素比魚人大）。
6. **CTA**：intro 後獨立 4.9s 段。
7. **下一條影片**：上一期 c19m0rmgk80（屠殺亡靈），片尾元素指向它；描述互鏈。
8. **實驗**：本期只換一個變數 = 兩局同一主播（郭 solo 雙視角）對照上期雙主播。
9. **Shorts**：A 22:30~23:39（最後一回合招募→四萬七戰鬥）；B 19:30~20:42（19:34「不是我要吃雞嗎」→ 毒魚清場）。均 no_music.wav + 音樂床。

## 製作狀態（2026-09-20）
- intro.mp4 30.0s 立體聲，三張卡（膽汁噴吐者 / 未來鰭 / 魚人合唱團）。
- 封面 thumbnail.jpg = thumbnail_polish_v1（雙卡 未來鰭後 / 膽汁噴吐者前；毒魚板凳 / 四萬七大哥 / 完整教學）。
- Shorts：a 73s、b 76s，均帶 thumb.jpg。

## 發布記錄（2026-09-20）
- 長片 kCeV37qL4hE https://www.youtube.com/watch?v=kCeV37qL4hE ；44:22，訂閱留言 UgwqI_jUVjUbFOwxdCl4AaABAg（已置頂）；列表「英雄戰場 S14 流派教學」；片尾元素：訂閱 + 指定影片 c19m0rmgk80（44:02–44:22，Studio 模板，Save 後顯示 Edit）。
- Short B 隕燼毒魚 4xeznqmjRIg（19:30~20:43）留言 Ugw6c6tUbkcFU45iePN4AaABAg（已置頂）；Short A 未來鰭 j62ourmjMMQ（22:30~23:39）留言 Ugy9wBzkcRjgEOShvNV4AaABAg（已置頂）；均在「英雄戰場 S14 Shorts」；Studio「相關影片」→ kCeV37qL4hE（Save 變灰確認）。
- 成片音量：intro P85 −13.0 / B −13.7 / A −14.0（10 分鐘取樣）；true peak −0.2 dBFS；立體聲 48 kHz。
- regionRestriction 首查（上傳後約 20 分鐘）：三條皆 None、processed、public。1 小時後複查：見 region_recheck.log。
- 教訓：兩源「無結算畫面」是抽幀取樣沒抽到最後 0.4 秒；結算畫面只在片尾最後半秒（用 -sseof -0.4 抽）。
