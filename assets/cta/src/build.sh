#!/usr/bin/env bash
# Build the 6s "subscribe" interstitial from the mascot + assets.
# Output args mirror burn.py (yuv420p, r30, h264, aac 48k) so the clip can be
# appended to a 1920x1080/30 battle segment without re-encode surprises.
set -euo pipefail
cd "$(dirname "$0")"

FONT="/System/Library/Fonts/Hiragino Sans GB.ttc"
[ -f "$FONT" ] || FONT="/System/Library/Fonts/STHeiti Medium.ttc"

# ---- 1) synth a royalty-free sting (entrance twinkle + button arpeggio + soft pad)
ffmpeg -y -v error \
 -f lavfi -t 0.20 -i sine=frequency=784 \
 -f lavfi -t 0.30 -i sine=frequency=1047 \
 -f lavfi -t 0.18 -i sine=frequency=523 \
 -f lavfi -t 0.18 -i sine=frequency=659 \
 -f lavfi -t 0.18 -i sine=frequency=784 \
 -f lavfi -t 0.34 -i sine=frequency=1047 \
 -f lavfi -t 6   -i sine=frequency=261.63 \
 -f lavfi -t 6   -i sine=frequency=329.63 \
 -f lavfi -t 6   -i sine=frequency=392.00 \
 -filter_complex "
  [0]afade=t=out:st=0.08:d=0.12,adelay=300,volume=0.34[t0];
  [1]afade=t=out:st=0.14:d=0.16,adelay=470,volume=0.30[t1];
  [2]afade=t=out:st=0.09:d=0.09,adelay=2550,volume=0.52[a2];
  [3]afade=t=out:st=0.09:d=0.09,adelay=2720,volume=0.52[a3];
  [4]afade=t=out:st=0.09:d=0.09,adelay=2890,volume=0.52[a4];
  [5]afade=t=out:st=0.16:d=0.18,adelay=3060,volume=0.64[a5];
  [6]volume=0.035[p0];[7]volume=0.030[p1];[8]volume=0.030[p2];
  [p0][p1][p2]amix=inputs=3:normalize=0,afade=t=in:d=0.6,afade=t=out:st=5.3:d=0.7[pad];
  [t0][t1][a2][a3][a4][a5][pad]amix=inputs=7:normalize=0,alimiter=limit=0.95,apad,atrim=0:6,asetpts=N/SR/TB[aout]
 " -map "[aout]" -ar 48000 -ac 2 sting.wav

# ---- 2) composite the interstitial
ffmpeg -y -v error \
 -loop 1 -t 6 -i bg.png \
 -i mascot_raw.png \
 -loop 1 -t 6 -i arrow.png \
 -loop 1 -t 6 -i button.png \
 -i sting.wav \
 -filter_complex "
  [1:v]scale=-2:780,format=rgba,rotate=a='0.05*sin(2*PI*t*1.8)':ow=rotw(0):oh=roth(0):c=black@0[masc];
  [3:v]drawtext=fontfile='${FONT}':text='訂閱':fontcolor=white:fontsize=60:x=(w-text_w)/2:y=(h-text_h)/2-4,format=rgba,fade=t=in:st=2.5:d=0.2:alpha=1[btn];
  [0:v]scale=1920:1080,setsar=1[bg0];
  [bg0][masc]overlay=x='(W-w)/2-260+50*sin(2*PI*t*0.9)':y='H-h-50-55*abs(sin(2*PI*t*1.8))'[v1];
  [v1][btn]overlay=x=1250:y=540:enable='gte(t,2.5)'[v2];
  [v2][2:v]overlay=x='1000+26*sin(2*PI*(t-2.5)*3)':y=540:enable='gte(t,2.5)'[v3];
  [v3]subtitles=f='slogan.ass'[outv]
 " \
 -map "[outv]" -map 4:a \
 -t 6 -r 30 -pix_fmt yuv420p -c:v libx264 -preset medium -crf 18 \
 -c:a aac -ar 48000 -b:a 192k \
 subscribe_v1.mp4

echo "=== done ==="
ffprobe -v error -select_streams v:0 -show_entries stream=width,height,r_frame_rate,pix_fmt,duration -of default=nw=1 subscribe_v1.mp4
ffprobe -v error -select_streams a:0 -show_entries stream=codec_name,sample_rate,channels -of default=nw=1 subscribe_v1.mp4
