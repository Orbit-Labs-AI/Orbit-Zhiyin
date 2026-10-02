#!/usr/bin/env bash
# Reproduce preference counterfactuals and conditional savings without live logs.
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"
if command -v uv > /dev/null 2>&1; then
  exec uv run --locked python -m evals.recommendation.validation "$@"
fi
if [[ -x .venv/bin/python ]]; then
  .venv/bin/python -c 'import sys; assert sys.version_info[:2] == (3, 13), "Run uv sync --locked --all-packages --dev with Python 3.13 first"'
  exec .venv/bin/python -m evals.recommendation.validation "$@"
fi
echo "Run uv sync --locked --all-packages --dev with Python 3.13 first." >&2
exit 1
