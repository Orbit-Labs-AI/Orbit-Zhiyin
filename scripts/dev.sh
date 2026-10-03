#!/usr/bin/env bash
# Current product entrypoint: local API. UI prototypes remain separate.
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"
exec uv run --locked orbit "$@" serve
