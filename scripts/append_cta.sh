#!/usr/bin/env bash
# Append the channel subscribe CTA clip to the end of a burnt battle segment,
# so the CTA plays right after that battle (mid-roll). Feed the COMBINED clip
# to video2yt-merge as that chapter — the CTA rides inside the chapter, so each
# chapter still satisfies YouTube's >=10s rule and no extra chapter is created.
#
# Usage:
#   scripts/append_cta.sh <segment.mp4> [output.mp4]
#   CTA_CLIP=/path/to/other_cta.mp4 scripts/append_cta.sh seg.mp4   # override clip
#
# Default output: <segment_stem>_cta.mp4 next to the input.
#
# Re-encode concat (filter-level), NOT stream copy. The old `-f concat -c copy`
# join left the output's post-demux timestamps at the mercy of both files'
# container metadata: on flyflag (2026-06-10) the join produced a BACKWARD pts
# reset (dts 1433.87s -> 6.23s), which merge's fps=30 normalization cannot heal
# (it only fills forward gaps) — concat then silently dropped the segment tail
# + the whole CTA. Filter-level concat rebuilds timestamps from zero, so the
# output is monotonic by construction. Costs a full re-encode (~5min for a
# 24-min segment); output matches the burn spec (1920x1080 30fps h264 yuv420p
# + AAC 48k) so merge strict mode passes. A duration check still guards the end.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CTA="${CTA_CLIP:-$REPO_ROOT/assets/cta/subscribe_cta.mp4}"

seg="${1:?usage: append_cta.sh <segment.mp4> [output.mp4]}"
out="${2:-${seg%.*}_cta.mp4}"

[ -f "$seg" ] || { echo "[append_cta] segment not found: $seg" >&2; exit 1; }
[ -f "$CTA" ] || { echo "[append_cta] CTA clip not found: $CTA" >&2; exit 1; }

vparams() { ffprobe -v error -select_streams v:0 -show_entries stream=width,height,r_frame_rate,pix_fmt,codec_name -of default=nw=1:nk=1 "$1" | paste -sd' ' -; }
aparams() { ffprobe -v error -select_streams a:0 -show_entries stream=codec_name,sample_rate,channels -of default=nw=1:nk=1 "$1" | paste -sd' ' -; }
fdur()    { ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 "$1"; }

sv="$(vparams "$seg")"; sa="$(aparams "$seg")"
cv="$(vparams "$CTA")"; ca="$(aparams "$CTA")"
echo "[append_cta] segment : V[$sv] A[$sa]"
echo "[append_cta] cta     : V[$cv] A[$ca]"

ffmpeg -y -v error -i "$seg" -i "$CTA" -filter_complex "
 [0:v]fps=30,setpts=PTS-STARTPTS[v0];
 [1:v]fps=30,setpts=PTS-STARTPTS[v1];
 [0:a]aresample=48000,asetpts=PTS-STARTPTS[a0];
 [1:a]aresample=48000,asetpts=PTS-STARTPTS[a1];
 [v0][a0][v1][a1]concat=n=2:v=1:a=1[v][a]
" -map "[v]" -map "[a]" \
  -c:v libx264 -preset medium -crf 20 -pix_fmt yuv420p -r 30 \
  -c:a aac -b:a 192k -ar 48000 \
  "$out"

ds="$(fdur "$seg")"; dc="$(fdur "$CTA")"; do_="$(fdur "$out")"
python3 - "$ds" "$dc" "$do_" "$out" <<'PY'
import sys
ds, dc, do, out = float(sys.argv[1]), float(sys.argv[2]), float(sys.argv[3]), sys.argv[4]
exp = ds + dc
ok = abs(do - exp) < 0.6
print(f"[append_cta] {ds:.2f}s + {dc:.2f}s = {exp:.2f}s ; output={do:.2f}s -> {'OK' if ok else 'MISMATCH'}")
if not ok:
    print("[append_cta] duration mismatch — concat likely failed; do NOT feed this to merge.", file=sys.stderr)
    sys.exit(2)
PY

echo "[append_cta] wrote $out"
echo "[append_cta] -> feed THIS as the battle-1 --segment to video2yt-merge"
