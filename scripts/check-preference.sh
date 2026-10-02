#!/usr/bin/env bash
# Synthetic regression by default; an explicit --db opts in to snapshot diagnostics.
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"
if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  echo 'Without arguments: run Preference and Instruction regression tests.'
  echo 'With --db: also diagnose an existing canonical snapshot read-only.'
  exec uv run --locked python -m evals.analytics.preference_local --help
fi
uv run --locked pytest -q \
  packages/backend/tests/analytics/instruction \
  packages/backend/tests/analytics/test_preference.py \
  packages/backend/tests/analytics/test_preference_evidence.py \
  packages/backend/tests/analytics/test_preference_local.py \
  packages/backend/tests/analytics/test_semantic_quality.py \
  packages/backend/tests/analytics/test_semantic_functional.py
if [[ $# -gt 0 ]]; then
  uv run --locked python -m evals.analytics.preference_local "$@"
fi
