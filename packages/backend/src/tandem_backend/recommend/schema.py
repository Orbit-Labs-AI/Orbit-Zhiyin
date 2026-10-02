"""Export the same contracts used by ingestion for catalogue authors."""

import json
from pathlib import Path

from .contracts import FAMILIES, CatalogEnvelope, RecommendationItem
from .families import SCHEMAS


def catalog_schema(family=None):
    if family is not None and family not in FAMILIES:
        raise ValueError("Unknown family")
    envelope = CatalogEnvelope.model_json_schema()
    item = RecommendationItem.model_json_schema()
    definitions = item.pop("$defs", {})
    if family is not None:
        item["properties"]["family"] = {"const": family, "type": "string"}
        details = SCHEMAS[family].model_json_schema()
        definitions.update(details.pop("$defs", {}))
        item["properties"]["family_features"] = details
        envelope["properties"]["family"] = {"const": family, "type": "string"}
    envelope["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    envelope["required"] = ["schema_version", "family", "items"]
    envelope["$defs"] = {**definitions, "RecommendationItem": item}
    envelope["properties"]["items"]["items"] = {"$ref": "#/$defs/RecommendationItem"}
    return envelope


def write_schemas(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    for family in FAMILIES:
        (directory / (family + ".schema.json")).write_text(
            json.dumps(catalog_schema(family), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
