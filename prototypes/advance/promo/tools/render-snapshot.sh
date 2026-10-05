#!/bin/bash
# Render one promo version from a committed snapshot, so uncommitted edits in the working checkout never leak into it.
#   bash prototypes/advance/promo/tools/render-snapshot.sh <ver> <commit> [out-dir]
#   -> <out-dir>/orbit-promo-<ver>.mp4 + orbit-promo-<ver>-small.mp4 (720p), log in <out-dir>/render-<ver>.log
# out-dir defaults to <repo>/.work/promo (ignored, never committed). Needs pnpm, uv, ffmpeg.
set -euo pipefail
VER=$1; COMMIT=$2
ROOT=$(git -C "$(dirname "$0")" rev-parse --show-toplevel)
MAIN=$(dirname "$(git -C "$ROOT" rev-parse --path-format=absolute --git-common-dir)")   # main checkout: .work lives there
OUTDIR=$(mkdir -p "${3:-$MAIN/.work/promo}" && cd "${3:-$MAIN/.work/promo}" && pwd)
SNAP="$MAIN/.work/wt-render-$VER"
OUT="$OUTDIR/orbit-promo-$VER.mp4"; SMALL="$OUTDIR/orbit-promo-$VER-small.mp4"
exec > >(tee -a "$OUTDIR/render-$VER.log") 2>&1
echo "[render] $VER @ $COMMIT  $(date '+%F %T')"
if [ -d "$SNAP" ]; then git -C "$ROOT" worktree remove --force "$SNAP"; fi
git -C "$ROOT" worktree add --detach "$SNAP" "$COMMIT"
trap 'git -C "$ROOT" worktree remove --force "$SNAP"' EXIT
cd "$SNAP" && pnpm install --frozen-lockfile --prefer-offline > /dev/null
cd "$SNAP/prototypes/advance"
node build.mjs > /dev/null
uv run --with numpy --with scipy python promo/music.py
python3 "$SNAP/scripts/heavy.py" node promo/render.mjs --out "$OUT"
ffmpeg -y -loglevel error -i "$OUT" -vf "scale=1280:720:flags=lanczos" -c:v libx264 -preset slow -crf 26 \
  -c:a aac -b:a 128k -movflags +faststart "$SMALL"
echo "[render] done $(date '+%F %T')"
ffprobe -v error -show_entries format=duration -of csv=p=0 "$OUT"
ls -la "$OUT" "$SMALL"
