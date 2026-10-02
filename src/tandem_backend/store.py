"""Compatibility import path for old ledgers. Default application reads use data_access."""

from .legacy.store import Store as Store
from .legacy.store import _decode_sample_policy as _decode_sample_policy
from .legacy.store import import_codex as import_codex
