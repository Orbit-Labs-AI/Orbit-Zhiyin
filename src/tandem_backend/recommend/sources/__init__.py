"""Offline adapters for reviewed records; no fetching or execution on ingestion."""

from .normalize import catalog_resource, legacy_item, normalize_item

__all__ = ["catalog_resource", "legacy_item", "normalize_item"]
