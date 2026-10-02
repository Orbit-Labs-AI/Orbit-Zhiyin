#!/usr/bin/env bash
# Build workspace distributions and run outside the checkout without editable installs.
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CHECK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/tandem-installed.XXXXXX")"
trap 'rm -rf "$CHECK_DIR"' EXIT
cd "$REPO_ROOT"
uv build --all-packages --out-dir "$CHECK_DIR/wheels"
uv export --frozen --no-dev --no-emit-workspace --format requirements-txt --output-file "$CHECK_DIR/requirements.txt" > /dev/null
uv venv --python 3.13 "$CHECK_DIR/venv"
uv pip install --python "$CHECK_DIR/venv/bin/python" --requirement "$CHECK_DIR/requirements.txt" "$CHECK_DIR"/wheels/tandem_data-*.whl "$CHECK_DIR"/wheels/tandem_catalog-*.whl
cd "$CHECK_DIR"
"$CHECK_DIR/venv/bin/python" -I -c 'import importlib.util; assert importlib.util.find_spec("tandem_backend") is None'
env -u PYTHONPATH "$CHECK_DIR/venv/bin/tandem-catalog" --home "$CHECK_DIR/catalog" init > /dev/null
env -u PYTHONPATH "$CHECK_DIR/venv/bin/tandem-catalog" --home "$CHECK_DIR/catalog" sync --source tandem-seeds > /dev/null
env -u PYTHONPATH "$CHECK_DIR/venv/bin/tandem-catalog" --home "$CHECK_DIR/catalog" verify
uv pip install --python "$CHECK_DIR/venv/bin/python" --no-deps "$CHECK_DIR"/wheels/tandem_backend-*.whl
env -u PYTHONPATH "$CHECK_DIR/venv/bin/tandem" demo --output "$CHECK_DIR/demo"
env -u PYTHONPATH "$CHECK_DIR/venv/bin/tandem" --home "$CHECK_DIR/demo/data" analytics --no-text --output "$CHECK_DIR/analytics.json"
env -u PYTHONPATH "$CHECK_DIR/venv/bin/tandem" --home "$CHECK_DIR/demo/data" analysis-report --output "$CHECK_DIR/ui-report"
env -u PYTHONPATH "$CHECK_DIR/venv/bin/tandem" --home "$CHECK_DIR/demo/data" analysis-history --output "$CHECK_DIR/history.json"
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

"$CHECK_DIR/venv/bin/python" -I - <<'PY'
import json
import tempfile
from importlib.resources import files
from pathlib import Path

from tandem_backend.services.gateway import Gateway

root = files("tandem_backend")
schemas = sorted(p.name for p in root.joinpath("appdb/schema").iterdir() if p.name.endswith(".sql"))
assert len(schemas) >= 8, schemas
templates = root.joinpath("ai/assets/templates")
json.loads(templates.joinpath("manifest.json").read_text())
assert any(d.name == "hooks" and any(d.iterdir()) for d in templates.iterdir() if d.is_dir())
with tempfile.TemporaryDirectory() as home:
    gateway = Gateway(Path(home), discovery=lambda: [])
    gateway.app(token="installed-check-token-0123456789-abcdef", port=1)
    gateway.close()
print(f"Gateway builds from installed wheel with {len(schemas)} app.db schemas and AI templates")
PY
