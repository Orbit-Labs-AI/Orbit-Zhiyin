#!/usr/bin/env bash
# Constructed regression suite + native fixtures + optional read-only real sessions.
set -euo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"
export UV_CACHE_DIR="${UV_CACHE_DIR:-${TMPDIR:-/tmp}/tandem-uv-cache}"
uv sync --project packages/data --locked --dev
uv run --project packages/data ruff check packages/data/src packages/data/tests
uv run --project packages/data ruff format --check packages/data/src packages/data/tests
uv run --project packages/data pytest packages/data/tests -q
uv build --project packages/data
uv run --project packages/data python -m tandem_data.validation "$@"
