#!/bin/bash
# Rebuild assets/branding/outro_subscribe.mp4 (7.5 s 片尾小鈴鐺 CTA).
# 女老板 bottom-centre-left, bell icon right-centre, cursor flies in (2.4→3.9 s),
# clicks at 4.0 s → bell shakes (decaying rotate) + Mixkit ding. Subtitle top.
# Voice: video2yt-tts on outro_script.txt → outro.mp3; SRT hand-timed (outro.srt).
set -e
cd "$(dirname "$0")"
REPO="$(cd ../../.. && pwd)"
ffmpeg -v error -y -i outro.mp3 -af "apad=pad_dur=3.2" -ar 48000 -ac 2 outro_padded.wav
uv run --project "$REPO" python - <<'PY'
from pathlib import Path
from video2yt import compose
ass=compose.srt_to_ass(srt_text=Path('outro.srt').read_text(encoding='utf-8'),video_width=1920,video_height=1080,font_face='Hiragino Sans GB',font_size=60,position='top',outline_px=3,shadow_px=0,margin_l=80,margin_r=80,margin_v=110,max_lines=2,bold=True)
Path('_outro.sub.ass').write_text(ass,encoding='utf-8')
PY
DUR=$(ffprobe -v error -show_entries format=duration -of csv=p=0 outro_padded.wav)
ffmpeg -v error -y -framerate 30 -loop 1 -i "$REPO/assets/branding/anime_sketch/tavern_bg_pastel.png" -framerate 30 -loop 1 -i "$REPO/assets/branding/anime_sketch/mascot.png" -framerate 30 -loop 1 -i bell_red.png -framerate 30 -loop 1 -i cursor.png -i outro_padded.wav -i "$REPO/assets/cta/src/bell_ding.wav" -filter_complex "[0:v]scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,setsar=1[bg];[1:v]scale=-2:820,format=rgba,rotate=a='0.045*sin(2*PI*t*0.7)':ow=rotw(0.045):oh=roth(0.045):c=black@0[masc];[2:v]scale=-2:340,format=rgba,rotate=a='if(gte(t,4.0),0.35*sin(2*PI*(t-4.0)*5)*exp(-(t-4.0)*2.2),0)':ow=rotw(0.35):oh=roth(0.35):c=black@0[bell];[3:v]format=rgba[cur];[bg][masc]overlay=x='420+16*sin(2*PI*t*0.5)':y='1080-h-24-26*abs(sin(2*PI*t*0.85))'[v1];[v1][bell]overlay=x=1330-w/2:y=520-h/2[v2];[v2][cur]overlay=x='if(lt(t,3.9),1720-(1720-1360)*max(0,(t-2.4))/1.5,1360)':y='if(lt(t,3.9),960-(960-560)*max(0,(t-2.4))/1.5,560)+if(between(t,3.92,4.08),10,0)':enable='gte(t,2.4)'[v3];[v3]subtitles=f='_outro.sub.ass':force_style='PrimaryColour=&H00312C28,OutlineColour=&H00F5FAFC,Outline=3,Shadow=0'[outv];[5:a]adelay=4000|4000,volume=0.7[ding];[4:a][ding]amix=inputs=2:duration=first:normalize=0,aformat=channel_layouts=stereo[outa]" -map "[outv]" -map "[outa]" -t "$DUR" -r 30 -pix_fmt yuv420p -c:v libx264 -preset medium -crf 18 -c:a aac -b:a 160k -ar 48000 -ac 2 -movflags +faststart "$REPO/assets/branding/outro_subscribe.mp4"
echo "wrote $REPO/assets/branding/outro_subscribe.mp4"
