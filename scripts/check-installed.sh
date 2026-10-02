#!/usr/bin/env bash
# Build both distributions and run outside the checkout without editable installs.
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CHECK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/tandem-installed.XXXXXX")"
trap 'rm -rf "$CHECK_DIR"' EXIT
cd "$REPO_ROOT"
uv build --all-packages --out-dir "$CHECK_DIR/wheels"
uv export --frozen --no-dev --no-emit-workspace --format requirements-txt --output-file "$CHECK_DIR/requirements.txt" > /dev/null
uv venv --python 3.13 "$CHECK_DIR/venv"
uv pip install --python "$CHECK_DIR/venv/bin/python" --requirement "$CHECK_DIR/requirements.txt" "$CHECK_DIR"/wheels/*.whl
cd "$CHECK_DIR"
env -u PYTHONPATH "$CHECK_DIR/venv/bin/tandem" demo --output "$CHECK_DIR/demo"
env -u PYTHONPATH "$CHECK_DIR/venv/bin/tandem" --home "$CHECK_DIR/demo/data" analytics --no-text --output "$CHECK_DIR/analytics.json"
env -u PYTHONPATH "$CHECK_DIR/venv/bin/tandem" evaluate --output "$CHECK_DIR/evaluation.json"
env -u PYTHONPATH "$CHECK_DIR/venv/bin/tandem-data" --help > /dev/null
"$CHECK_DIR/venv/bin/python" -I -c 'from tandem_backend.api import create_app; from tandem_backend.application.reports import build_report; from tandem_data.service import ImportService; print("Installed API, service and package resources verified")'

"$CHECK_DIR/venv/bin/python" -I - <<'PY'
import json
from importlib.resources import files
from tandem_backend.recommend.catalog import load_catalog
from tandem_backend.recommend.contracts import FAMILIES
from tandem_backend.recommend.schema import catalog_schema

resources = files("tandem_backend").joinpath("data/recommend")
for family in FAMILIES:
    assert resources.joinpath(family + ".json").is_file()
    assert json.loads(resources.joinpath(family + ".schema.json").read_text()) == catalog_schema(family)
load_catalog()
print("Seven recommendation catalogs and schemas verified in installed wheel")
PY
