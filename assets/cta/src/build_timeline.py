"""Measure the two voice clips, compute the interstitial timeline, write the
ASS slogan + a `timeline.env` the build script sources. Kept as a real file
(not a heredoc) so it is debuggable on its own."""
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


h = dur("voice_hook.mp3")
c = dur("voice_cta.mp3")
HOOK_START = 0.40
HOOK_END = HOOK_START + h + 0.30
CTA_START = round(HOOK_END + 0.35, 3)
TOTAL = round(CTA_START + c + 0.95, 3)

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
hook = ("Dialogue: 0," + ass_t(HOOK_START) + "," + ass_t(HOOK_END)
        + r",Hook,,0,0,0,,{\fad(180,150)}想了解最新最熱流派、猛猛上分嗎？")
cta = ("Dialogue: 0," + ass_t(CTA_START) + "," + ass_t(TOTAL)
       + r",CTA,,0,0,0,,{\fad(150,0)\fscx70\fscy70\t(0,260,\fscx116\fscy116)}訂閱馬哥！")
with open("slogan_tts.ass", "w", encoding="utf-8") as f:
    f.write(header + hook + "\n" + cta + "\n")

with open("timeline.env", "w", encoding="utf-8") as f:
    f.write(f"HOOK_MS={int(HOOK_START*1000)}\n")
    f.write(f"CTA_MS={int(CTA_START*1000)}\n")
    f.write(f"CTA_MS2={int(CTA_START*1000)+150}\n")
    f.write(f"CTA_START={CTA_START}\n")
    f.write(f"TOTAL={TOTAL}\n")
    f.write(f"PAD_OUT={round(TOTAL-0.7,3)}\n")

print(f"[timeline] hook={h:.3f}s cta={c:.3f}s CTA_START={CTA_START}s TOTAL={TOTAL}s")
