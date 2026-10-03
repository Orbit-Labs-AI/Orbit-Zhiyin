#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"
if [[ ! -x .venv/bin/python ]]; then
  echo "缺少 .venv/bin/python；先按仓库测试指南准备 Python 3.13 环境。" >&2
  exit 1
fi
BENCHMARK_DATA_HOME=.local/backend-nine-hour/current-data
if [[ ! -f "$BENCHMARK_DATA_HOME/tandem.db" ]]; then
  BENCHMARK_DATA_HOME=.local/backend-nine-hour/p0-data
fi
exec .venv/bin/python -m evals.benchmark.local --home "$BENCHMARK_DATA_HOME" "$@"
