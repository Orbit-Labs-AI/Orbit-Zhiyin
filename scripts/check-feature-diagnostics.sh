#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ ! -x "$REPO_ROOT/.venv/bin/python" ]]; then
  echo "缺少仓库 .venv 中的 Python；请先配置 Python 3.13 环境。" >&2
  exit 1
fi
cd "$REPO_ROOT"
exec "$REPO_ROOT/.venv/bin/python" -m evals.analytics.local_diagnostics "$@"
