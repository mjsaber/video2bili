"""Measure the two voice clips, compute the compact 2-beat CTA timeline, write
the ASS slogan + a `timeline.env` the build script sources. Kept as a real file
(not a heredoc) so it is debuggable on its own.

Beat A (subscribe, visual-secondary): voice 訂閱馬哥！ while the arrow clicks
the red 訂閱 button -> grey 已訂閱 -> bell pops/shakes with the single ding.
Beat B (comment, spoken-primary): voice 想看什麼陣容？留言告訴我！ with the
blue speech bubble. Total lands ~5s (research: commercial subscribe stings
cluster at 4-6s; one primary ask + one visual secondary max).
"""
import subprocess


def dur(p: str) -> float:
    out = subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", p]).strip()
    return float(out)


def ass_t(s: float) -> str:
    cs = int(round(s * 100))
    h, rem = divmod(cs, 360000)
    m, rem = divmod(rem, 6000)
    sec, cc = divmod(rem, 100)
    return f"{h}:{m:02d}:{sec:02d}.{cc:02d}"


c = dur("voice_cta.mp3")
m = dur("voice_comment.mp3")

CTA_START = 0.35
CLICK_T = round(CTA_START + 0.25, 3)      # arrow "click": red -> grey swap
BELL_T = round(CLICK_T + 0.18, 3)         # bell pops + the ONE ding (synced)
CTA_END = CTA_START + c
COMMENT_START = round(CTA_END + 0.35, 3)
TOTAL = round(COMMENT_START + m + 0.85, 3)

header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
ScaledBorderAndShadow: yes
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Hook,Hiragino Sans GB,88,&H00FFFFFF,&H000000FF,&H00301808,&H64000000,1,0,0,0,100,100,1,0,1,6,3,8,80,80,70,1
Style: CTA,Hiragino Sans GB,128,&H0000D7FF,&H000000FF,&H00201004,&H64000000,1,0,0,0,100,100,1,0,1,7,3,8,80,80,80,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
cta = ("Dialogue: 0," + ass_t(CTA_START) + "," + ass_t(COMMENT_START - 0.10)
       + r",CTA,,0,0,0,,{\fad(120,0)\fscx70\fscy70\t(0,260,\fscx116\fscy116)}訂閱馬哥！")
ask = ("Dialogue: 0," + ass_t(COMMENT_START) + "," + ass_t(TOTAL)
       + r",Hook,,0,0,0,,{\fad(150,120)}想看什麼陣容？留言告訴我！")
with open("slogan_tts.ass", "w", encoding="utf-8") as f:
    f.write(header + cta + "\n" + ask + "\n")

with open("timeline.env", "w", encoding="utf-8") as f:
    f.write(f"CTA_MS={int(CTA_START*1000)}\n")
    f.write(f"COMMENT_MS={int(COMMENT_START*1000)}\n")
    f.write(f"BELL_MS={int(BELL_T*1000)}\n")
    f.write(f"CLICK_T={CLICK_T}\n")
    f.write(f"BELL_T={BELL_T}\n")
    f.write(f"COMMENT_START={COMMENT_START}\n")
    f.write(f"TOTAL={TOTAL}\n")
    f.write(f"PAD_OUT={round(TOTAL-0.7,3)}\n")

print(f"[timeline] cta={c:.3f}s comment={m:.3f}s click={CLICK_T}s "
      f"bell={BELL_T}s COMMENT_START={COMMENT_START}s TOTAL={TOTAL}s")
