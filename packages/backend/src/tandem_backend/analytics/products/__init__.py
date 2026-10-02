"""Stable public entry points for UI analysis products and local acceptance reports."""

from .service import analyze_product_store, build_products, session_page

__all__ = ["analyze_product_store", "build_products", "session_page"]
