#!/usr/bin/env bash
# Synthetic regression by default; an explicit --db opts in to snapshot diagnostics.
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"
if command -v uv >/dev/null 2>&1; then
  RUN_PYTHON=(uv run --locked python)
elif [[ -x "$REPO_ROOT/.venv/bin/python" ]]; then
  RUN_PYTHON=("$REPO_ROOT/.venv/bin/python")
  echo 'uv is not on PATH; using the existing checkout .venv without syncing dependencies.' >&2
else
  echo 'Install uv and run bash scripts/bootstrap.sh first.' >&2
  exit 2
fi
if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  echo 'Without arguments: run Preference and Instruction regression tests.'
  echo 'With --db: also diagnose an existing canonical snapshot read-only.'
  exec "${RUN_PYTHON[@]}" -m evals.analytics.preference_local --help
fi
"${RUN_PYTHON[@]}" -m pytest -q \
  packages/backend/tests/analytics/instruction \
  packages/backend/tests/analytics/test_preference.py \
  packages/backend/tests/analytics/test_preference_evidence.py \
  packages/backend/tests/analytics/test_preference_local.py \
  packages/backend/tests/analytics/test_semantic_quality.py \
  packages/backend/tests/analytics/test_semantic_functional.py
if [[ $# -gt 0 ]]; then
  "${RUN_PYTHON[@]}" -m evals.analytics.preference_local "$@"
fi
