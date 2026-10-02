#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"
case "${1:-all}" in
  all)
    uv sync --locked --all-packages --dev
    pnpm --filter @tandem/connectors check
    uv run --no-sync ruff check packages/backend/src packages/backend/tests packages/data/src packages/data/tests tests scripts evals benchmarks
    uv run --no-sync ruff format --check packages/data/src packages/data/tests
    uv run --no-sync pytest -q
    pnpm --filter @tandem/prototype-lite check
    pnpm --filter @tandem/prototype-advance check
    uv run --no-sync python scripts/check-repository.py
    bash scripts/check-installed.sh
    git diff --check
    ;;
  integration)
    pnpm --filter @tandem/connectors build
    uv run --locked pytest -q tests/integration tests/e2e
    ;;
  *)
    echo "Usage: bash scripts/check.sh [all|integration]" >&2
    exit 2
    ;;
esac
