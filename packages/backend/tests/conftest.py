"""Backend-wide test isolation.

``sessionops.exclusion``, ``appdata.sources_scope`` and ``uiview.insight`` keep a
process-level provider that a Gateway (``routes_settings`` / ``routes_sessionops`` /
``Gateway.__init__``) installs and only some fixtures unbind. A test that builds a gateway and fails before its teardown, or forgets to unbind, would leak
a provider reading a closed app.db into later tests in the same xdist worker: exclusion then
fails closed (503) and source scopes change, far from the cause. Reset them around every test.

Sub-directory conftests keep their own names; tests that ``from conftest import ...`` still
get the nearest one (pytest re-imports ``conftest`` per directory).
"""

from __future__ import annotations

import pytest

from tandem_backend.appdata import sources_scope
from tandem_backend.sessionops import exclusion
from tandem_backend.uiview import insight


@pytest.fixture(autouse=True)
def _reset_process_providers():
    exclusion.set_provider(None)
    sources_scope.set_provider(None)
    insight.set_ai_provider(None)
    yield
    exclusion.set_provider(None)
    sources_scope.set_provider(None)
    insight.set_ai_provider(None)
