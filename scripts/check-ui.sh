#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"
pnpm --filter @tandem/prototype-lite check
if [ -z "${LIVE_GATEWAY:-}" ]; then
  # Specs gated on a real gateway skip themselves without LIVE_GATEWAY; say so explicitly.
  trap 'echo "NOTE: LIVE_GATEWAY unset — specs gated on LIVE_GATEWAY (app-journey, live-r3-gateway, live-s7 and live-s2 real-gateway smoke) were SKIPPED; the skipped count above includes them. Run: bash scripts/check.sh journey" >&2' EXIT
fi
pnpm --filter @tandem/prototype-advance test "$@"
