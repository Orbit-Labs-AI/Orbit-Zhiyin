#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"
case "${1:-all}" in
  all)
    uv sync --locked --all-packages --dev
    pnpm --filter @tandem/connectors check
    uv run --no-sync ruff check packages/backend/src packages/backend/tests packages/data/src packages/data/tests packages/catalog/src packages/catalog/tests tests scripts evals benchmarks apps/desktop
    uv run --no-sync ruff format --check packages/data/src packages/data/tests
    uv run --no-sync pytest -q -n auto -m "not serial"
    uv run --no-sync pytest -q -m serial
    swift test --package-path packages/catalog-macos
    pnpm --filter @tandem/prototype-lite check
    pnpm --filter @tandem/prototype-advance check
    uv run --no-sync python scripts/check-repository.py
    bash scripts/check-installed.sh
    git diff --check
    ;;
  integration)
    pnpm --filter @tandem/connectors build
    uv run --locked pytest -q -n auto tests/integration tests/e2e
    ;;
  journey)
    # Real gateway + real UI journey (Playwright, mac-14 project), then — on macOS, when
    # JOURNEY_MACOS_APP=1 — build Orbit.app and smoke-check its frozen tandem-helper.
    bash scripts/check-app-journey.sh
    if [ "${JOURNEY_MACOS_APP:-0}" = 1 ]; then
      [ "$(uname)" = Darwin ] || { echo "JOURNEY_MACOS_APP=1 needs macOS" >&2; exit 2; }
      uv run --no-sync python apps/desktop/build.py
      uv run --no-sync python scripts/check-macos-app.py --app .local/macos-build/Orbit.app
    fi
    ;;
  *)
    echo "Usage: bash scripts/check.sh [all|integration|journey]" >&2
    exit 2
    ;;
esac
