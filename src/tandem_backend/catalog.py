"""Verified source metadata is distinct from unmeasured effectiveness."""

import json
from importlib.resources import files


def skills() -> list[dict]:
    return json.loads(files("tandem_backend").joinpath("data/skills.json").read_text())
