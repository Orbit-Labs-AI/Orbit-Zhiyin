#!/usr/bin/env bash
# Synthetic validation by default. Real sources require explicit --real arguments.
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"
uv sync --locked --all-packages --dev
uv run --no-sync ruff check packages/data/src packages/data/tests
uv run --no-sync ruff format --check packages/data/src packages/data/tests
uv run --no-sync pytest packages/data/tests -q
uv build --package orbit-data
uv run --no-sync python -m orbit_data.validation "$@"
