#!/usr/bin/env bash
# Compact 2-beat voiced CTA (~5s), driven by the project's Volcengine BigTTS
# voice (zh_female_vv_uranus_bigtts). Timeline auto-fits the two voice clips.
#
# Beat A: 「訂閱馬哥！」 — arrow clicks red 訂閱 -> grey 已訂閱 -> bell pops with
#         a decaying shake + the single Mixkit bell ding (the ONLY sfx, mixed
#         under the voice per loudness best practice).
# Beat B: 「想看什麼陣容？留言告訴我！」 — the spoken PRIMARY ask. A dark-mode
#         YouTube-style comment card slides up beside the mascot: gold letter
#         avatar 「你」 + 「@你 · 剛剛」 + body 「想看〇〇流！」 — demonstrates
#         the wanted action without duplicating the subtitle. No extra sfx.
set -euo pipefail
cd "$(dirname "$0")"

FONT="/System/Library/Fonts/Hiragino Sans GB.ttc"
[ -f "$FONT" ] || FONT="/System/Library/Fonts/STHeiti Medium.ttc"

# ---- 0) measure voices, compute timeline, write slogan_tts.ass + timeline.env
python3 build_timeline.py
source ./timeline.env

# ---- 1) audio: two voices (focus) + ONE bell ding + faint pad
ffmpeg -y -v error \
 -i voice_cta.mp3 \
 -i voice_comment.mp3 \
 -i bell_ding.wav \
 -f lavfi -t "${TOTAL}" -i sine=frequency=329.63 \
 -filter_complex "
  [0:a]aformat=channel_layouts=stereo,adelay=${CTA_MS}|${CTA_MS},volume=1.0[vc];
  [1:a]aformat=channel_layouts=stereo,adelay=${COMMENT_MS}|${COMMENT_MS},volume=1.0[vm];
  [2:a]aformat=channel_layouts=stereo,adelay=${BELL_MS}|${BELL_MS},volume=0.45[bell];
  [3]volume=0.022,afade=t=in:d=0.5,afade=t=out:st=${PAD_OUT}:d=0.7[pad];
  [vc][vm][bell][pad]amix=inputs=4:normalize=0,alimiter=limit=0.95,atrim=0:${TOTAL},asetpts=N/SR/TB[aout]
 " -map "[aout]" -ar 48000 -ac 2 sting_tts.wav

# ---- 2) composite (all image inputs looped so the wobble animations run)
ffmpeg -y -v error \
 -loop 1 -t "${TOTAL}" -i bg.png \
 -loop 1 -t "${TOTAL}" -i mascot_raw.png \
 -loop 1 -t "${TOTAL}" -i arrow.png \
 -loop 1 -t "${TOTAL}" -i button.png \
 -loop 1 -t "${TOTAL}" -i button_grey.png \
 -loop 1 -t "${TOTAL}" -i bell.png \
 -loop 1 -t "${TOTAL}" -i comment_card.png \
 -i sting_tts.wav \
 -filter_complex "
  [1:v]scale=-2:780,format=rgba,rotate=a='0.06*sin(2*PI*t*1.9)':ow=rotw(0):oh=roth(0):c=black@0[masc];
  [3:v]drawtext=fontfile='${FONT}':text='訂閱':fontcolor=white:fontsize=60:x=(w-text_w)/2:y=(h-text_h)/2-4,format=rgba,fade=t=in:st=0.10:d=0.15:alpha=1[btnred];
  [4:v]drawtext=fontfile='${FONT}':text='已訂閱':fontcolor=white:fontsize=54:x=(w-text_w)/2:y=(h-text_h)/2-4,format=rgba[btngrey];
  [5:v]rotate=a='if(gte(t,${BELL_T}),0.28*sin(2*PI*(t-${BELL_T})*5)*exp(-2.5*(t-${BELL_T})),0)':ow=rotw(0.3):oh=roth(0.3):c=black@0,fade=t=in:st=${BELL_T}:d=0.12:alpha=1[belv];
  [6:v]drawtext=fontfile='${FONT}':text='你':fontcolor=white:fontsize=46:x=75-text_w/2:y=75-text_h/2-4,drawtext=fontfile='${FONT}':text='@你 · 剛剛':fontcolor=0xAAAAAA:fontsize=28:x=138:y=28,drawtext=fontfile='${FONT}':text='想看〇〇流！':fontcolor=white:fontsize=44:x=138:y=76,format=rgba,fade=t=in:st=${COMMENT_START}:d=0.22:alpha=1[card];
  [0:v]scale=1920:1080,setsar=1[bg0];
  [bg0][masc]overlay=x='(W-w)/2-260+50*sin(2*PI*t*0.9)':y='H-h-50-58*abs(sin(2*PI*t*1.9))'[v1];
  [v1][btnred]overlay=x=1250:y=540:enable='lt(t,${CLICK_T})'[v2];
  [v2][btngrey]overlay=x=1250:y=540:enable='gte(t,${CLICK_T})'[v3];
  [v3][2:v]overlay=x='1000+26*sin(2*PI*t*3)':y=540:enable='lt(t,${CLICK_T}+0.20)'[v4];
  [v4][belv]overlay=x=1672:y=505:enable='gte(t,${BELL_T})'[v5];
  [v5][card]overlay=x=920:y='190+30*max(0,1-(t-${COMMENT_START})/0.3)':enable='gte(t,${COMMENT_START})'[v6];
  [v6]subtitles=f='slogan_tts.ass'[outv]
 " \
 -map "[outv]" -map 7:a \
 -t "${TOTAL}" -r 30 -pix_fmt yuv420p -c:v libx264 -preset medium -crf 18 \
 -c:a aac -ar 48000 -b:a 192k \
 subscribe_v3.mp4

echo "=== done ==="
ffprobe -v error -select_streams v:0 -show_entries stream=width,height,r_frame_rate,pix_fmt,duration -of default=nw=1 subscribe_v3.mp4
ffprobe -v error -select_streams a:0 -show_entries stream=codec_name,sample_rate,channels,duration -of default=nw=1 subscribe_v3.mp4

# Publish as the canonical asset that scripts/append_cta.sh consumes.
cp subscribe_v3.mp4 ../subscribe_cta.mp4
echo "[build_tts] updated canonical: assets/cta/subscribe_cta.mp4"
