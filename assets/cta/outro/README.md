# 片尾小鈴鐺 CTA (subscribe outro)

`assets/branding/outro_subscribe.mp4` — 7.5 s, appended as the LAST merge segment of LONG videos only (never on Shorts)
(`intro → cta → 郭 → 瓦 → outro`). Spoken line (BigTTS 女老板):
「如果都看到這裡了，就按個小鈴鐺再走吧～求求啦！」— no on-screen location is named.

Visual: 女老板 bottom-centre-left, a RED bell icon (bell_red.png, recolored from src/bell.png) right-centre; a cursor flies in,
clicks the bell at 4.0 s, the bell shakes and a ding plays (Mixkit, no attribution).
Subtitle top-centre. Rebuild with `assets/cta/outro/build.sh`; change the line by
editing `outro_script.txt` → `video2yt-tts` → hand-time `outro.srt` (click at 4.0 s
assumes the line ends ≈4.3 s; shift the `4.0`/`2.4` constants in build.sh if it moves).

Studio end screen: after `Apply template`, set the elements to the last ≈7.5 s
(start = total − 7.5 s) so they sit on the outro, not on the last game.
