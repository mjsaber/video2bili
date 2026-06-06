#!/usr/bin/env bash
# Voiced version: same interstitial as build.sh but driven by the project's
# Volcengine BigTTS voice (zh_female_vv_uranus_bigtts). Timeline auto-fits the
# two voice clips (hook line + CTA line) so audio and on-screen text stay in sync.
set -euo pipefail
cd "$(dirname "$0")"

FONT="/System/Library/Fonts/Hiragino Sans GB.ttc"
[ -f "$FONT" ] || FONT="/System/Library/Fonts/STHeiti Medium.ttc"

# ---- 0) measure voices, compute timeline, write slogan_tts.ass + timeline.env
python3 build_timeline.py
source ./timeline.env

# ---- 1) audio: two voices (focus) + soft accents + faint pad
ffmpeg -y -v error \
 -i voice_hook.mp3 \
 -i voice_cta.mp3 \
 -f lavfi -t 0.28 -i sine=frequency=988 \
 -f lavfi -t 0.18 -i sine=frequency=784 \
 -f lavfi -t 0.32 -i sine=frequency=1175 \
 -f lavfi -t "${TOTAL}" -i sine=frequency=329.63 \
 -filter_complex "
  [0:a]aformat=channel_layouts=stereo,adelay=${HOOK_MS}|${HOOK_MS},volume=1.0[vh];
  [1:a]aformat=channel_layouts=stereo,adelay=${CTA_MS}|${CTA_MS},volume=1.0[vc];
  [2]afade=t=out:st=0.14:d=0.14,adelay=${HOOK_MS}|${HOOK_MS},volume=0.16[tw];
  [3]afade=t=out:st=0.09:d=0.09,adelay=${CTA_MS}|${CTA_MS},volume=0.20[d1];
  [4]afade=t=out:st=0.16:d=0.16,adelay=${CTA_MS2}|${CTA_MS2},volume=0.24[d2];
  [5]volume=0.022,afade=t=in:d=0.6,afade=t=out:st=${PAD_OUT}:d=0.7[pad];
  [vh][vc][tw][d1][d2][pad]amix=inputs=6:normalize=0,alimiter=limit=0.95,apad,atrim=0:${TOTAL},asetpts=N/SR/TB[aout]
 " -map "[aout]" -ar 48000 -ac 2 sting_tts.wav

# ---- 2) composite (all image inputs looped so rotate-wobble actually animates)
ffmpeg -y -v error \
 -loop 1 -t "${TOTAL}" -i bg.png \
 -loop 1 -t "${TOTAL}" -i mascot_raw.png \
 -loop 1 -t "${TOTAL}" -i arrow.png \
 -loop 1 -t "${TOTAL}" -i button.png \
 -i sting_tts.wav \
 -filter_complex "
  [1:v]scale=-2:780,format=rgba,rotate=a='0.06*sin(2*PI*t*1.9)':ow=rotw(0):oh=roth(0):c=black@0[masc];
  [3:v]drawtext=fontfile='${FONT}':text='訂閱':fontcolor=white:fontsize=60:x=(w-text_w)/2:y=(h-text_h)/2-4,format=rgba,fade=t=in:st=${CTA_START}:d=0.2:alpha=1[btn];
  [0:v]scale=1920:1080,setsar=1[bg0];
  [bg0][masc]overlay=x='(W-w)/2-260+50*sin(2*PI*t*0.9)':y='H-h-50-58*abs(sin(2*PI*t*1.9))'[v1];
  [v1][btn]overlay=x=1250:y=540:enable='gte(t,${CTA_START})'[v2];
  [v2][2:v]overlay=x='1000+26*sin(2*PI*(t-${CTA_START})*3)':y=540:enable='gte(t,${CTA_START})'[v3];
  [v3]subtitles=f='slogan_tts.ass'[outv]
 " \
 -map "[outv]" -map 4:a \
 -t "${TOTAL}" -r 30 -pix_fmt yuv420p -c:v libx264 -preset medium -crf 18 \
 -c:a aac -ar 48000 -b:a 192k \
 subscribe_v2.mp4

echo "=== done ==="
ffprobe -v error -select_streams v:0 -show_entries stream=width,height,r_frame_rate,pix_fmt,duration -of default=nw=1 subscribe_v2.mp4
ffprobe -v error -select_streams a:0 -show_entries stream=codec_name,sample_rate,channels,duration -of default=nw=1 subscribe_v2.mp4

# Publish as the canonical asset that scripts/append_cta.sh consumes.
cp subscribe_v2.mp4 ../subscribe_cta.mp4
echo "[build_tts] updated canonical: assets/cta/subscribe_cta.mp4"
