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
# Stream-copy concat (no re-encode of the long battle) — both inputs already
# share the burn output spec (1920x1080 30fps h264 yuv420p + AAC 48k), so the
# join is lossless. A duration check catches any silent concat failure.
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
if [ "$sv" != "$cv" ] || [ "$sa" != "$ca" ]; then
  echo "[append_cta] WARNING: stream params differ — stream-copy concat may glitch at the join." >&2
  echo "[append_cta]          If the output desyncs, re-encode the segment to the burn spec first." >&2
fi

list="$(mktemp)"
seg_abs="$(cd "$(dirname "$seg")" && pwd)/$(basename "$seg")"
printf "file '%s'\nfile '%s'\n" "$seg_abs" "$CTA" > "$list"
ffmpeg -y -v error -f concat -safe 0 -i "$list" -c copy "$out"
rm -f "$list"

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
