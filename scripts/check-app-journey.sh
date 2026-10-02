#!/usr/bin/env bash
# End-to-end App journey against a REAL gateway on a fresh synthetic home.
#   scripts/check-app-journey.sh [--keep] [-- <extra playwright args>]
# Env:
#   FX_RELEASE   dir with fx-env.sh / fx-src (default: <main checkout>/.work/release)
#   FX_PY        python with backend deps (default from fx-env.sh)
#   JOURNEY_SHOTS  screenshot root (default: $FX_RELEASE/shots)
#   JOURNEY_BE_ROOT  backend checkout to run (default: this worktree)
#   JOURNEY_GATEWAY  reuse an already-running gateway (e.g. the frozen tandem-helper in Orbit.app) instead of starting one;
#                    needs TANDEM_TOKEN, and optionally JOURNEY_FAKE_HOME / JOURNEY_DATA_HOME / JOURNEY_GATEWAY_LOG.
#                    The caller owns that gateway's lifecycle; nothing is built, started or cleaned up here.
# The gateway runs THIS worktree's backend (PYTHONPATH) with HOME redirected to an empty temp dir,
# serves the freshly built HTML at /app (--assets), and the spec drives it from the same origin.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
COMMON="$(cd "$ROOT" && git rev-parse --path-format=absolute --git-common-dir)"
FX_RELEASE="${FX_RELEASE:-$(dirname "$COMMON")/.work/release}"
KEEP=0; [ "${1:-}" = "--keep" ] && { KEEP=1; shift; }
[ "${1:-}" = "--" ] && shift
. "$FX_RELEASE/fx-env.sh"
if [ -n "${JOURNEY_GATEWAY:-}" ]; then
  [ -n "${TANDEM_TOKEN:-}" ] || { echo "JOURNEY_GATEWAY needs TANDEM_TOKEN" >&2; exit 1; }
  echo "reusing gateway $JOURNEY_GATEWAY"
  cd "$ROOT/prototypes/advance"
  LIVE_GATEWAY="$JOURNEY_GATEWAY" TANDEM_TOKEN="$TANDEM_TOKEN" JOURNEY_FAKE_HOME="${JOURNEY_FAKE_HOME:-}" \
    JOURNEY_DATA_HOME="${JOURNEY_DATA_HOME:-}" JOURNEY_SRC="$FX_RELEASE/fx-src" JOURNEY_SHOTS="${JOURNEY_SHOTS:-$FX_RELEASE/shots}" \
    JOURNEY_GATEWAY_LOG="${JOURNEY_GATEWAY_LOG:-}" \
    exec pnpm exec playwright test tests/app-journey.spec.mjs --project=mac-14 --workers=1 "$@"
fi
node "$ROOT/prototypes/shared/sync-live.mjs" >/dev/null
node "$ROOT/prototypes/advance/build.mjs" >/dev/null
ASSETS="$ROOT/prototypes/advance/tandem-demo.html"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/orbit-journey.XXXXXX")"
HOME_DIR="$WORK/home"; FAKE_HOME="$WORK/userhome"; mkdir -p "$HOME_DIR" "$FAKE_HOME"
TOKEN="$(python3 -c 'import secrets;print(secrets.token_hex(24))')"
# JOURNEY_BE_ROOT: run another checkout's backend (e.g. a patched copy) against this UI build
BE="${JOURNEY_BE_ROOT:-$ROOT}"
PYP="$BE/packages/backend/src:$BE/packages/data/src:$BE/packages/catalog/src"
env -i PATH="$PATH" HOME="$FAKE_HOME" TMPDIR="${TMPDIR:-/tmp}" LANG=en_US.UTF-8 \
  TANDEM_API_TOKEN="$TOKEN" PYTHONPATH="$PYP" PYTHONDONTWRITEBYTECODE=1 PYTHONWARNINGS=ignore \
  "$FX_PY" -m tandem_backend.services gateway --home "$HOME_DIR" --port 0 --assets "$ASSETS" \
  >"$WORK/gateway.stdout" 2>"$WORK/gateway.log" &
GW_PID=$!
cleanup() {
  kill -TERM "$GW_PID" 2>/dev/null || true
  for _ in $(seq 1 40); do kill -0 "$GW_PID" 2>/dev/null || break; sleep 0.25; done
  kill -KILL "$GW_PID" 2>/dev/null || true
  pkill -f "tandem_backend.services worker .*--home $HOME_DIR" 2>/dev/null || true
  [ "$KEEP" = 1 ] && echo "kept $WORK" || rm -rf "$WORK"
}
trap cleanup EXIT
PORT=""
for _ in $(seq 1 150); do
  if grep -q '"port"' "$WORK/gateway.stdout" 2>/dev/null; then
    PORT="$(python3 -c 'import json,sys;print(json.loads(open(sys.argv[1]).readline())["port"])' "$WORK/gateway.stdout")"; break
  fi
  kill -0 "$GW_PID" 2>/dev/null || { echo "gateway exited:" >&2; tail -20 "$WORK/gateway.log" >&2; exit 1; }
  sleep 0.2
done
[ -n "$PORT" ] || { echo "timeout waiting for gateway port" >&2; exit 1; }
echo "gateway 127.0.0.1:$PORT home=$HOME_DIR fakehome=$FAKE_HOME"
cd "$ROOT/prototypes/advance"
LIVE_GATEWAY="http://127.0.0.1:$PORT" TANDEM_TOKEN="$TOKEN" JOURNEY_FAKE_HOME="$FAKE_HOME" JOURNEY_DATA_HOME="$HOME_DIR" \
  JOURNEY_SRC="$FX_RELEASE/fx-src" JOURNEY_SHOTS="${JOURNEY_SHOTS:-$FX_RELEASE/shots}" JOURNEY_GATEWAY_LOG="$WORK/gateway.log" \
  pnpm exec playwright test tests/app-journey.spec.mjs --project=mac-14 --workers=1 "$@"
