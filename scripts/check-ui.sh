#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"
pnpm --filter @orbit/prototype-lite check
pnpm --filter @orbit/prototype-advance test "$@"
