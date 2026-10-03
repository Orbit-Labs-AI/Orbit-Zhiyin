"""Real E5 model test: runs when a local model exists, never downloads one.

The model comes from TANDEM_TEST_E5_DIR or the same discovery the app uses
(<TANDEM_HOME>/models, ~/Library/Application Support/Tandem/models). Without it the test is
skipped: CI has no 135 MB model and unit tests must not reach the network.
"""

import os
from pathlib import Path

import pytest

from tandem_catalog import embedding_model
from tandem_catalog.contracts import MatchRequest, Record, Resource, SourceSpec
from tandem_catalog.search import search
from tandem_catalog.store import CatalogStore
from tandem_catalog.vectors import LocalE5Encoder, index_embeddings

from .test_storage import publish


def _model_dir():
    if os.environ.get("TANDEM_TEST_E5_DIR"):
        return Path(os.environ["TANDEM_TEST_E5_DIR"])
    return embedding_model.discover(embedding_model.default_roots())


def _runtime():
    try:
        import onnxruntime  # noqa: F401
        import tokenizers  # noqa: F401
    except ImportError:
        return False
    return True


MODEL = _model_dir()
pytestmark = [
    pytest.mark.skipif(MODEL is None, reason="no local multilingual-e5-small (set TANDEM_TEST_E5_DIR or run "
                                             "`python -m tandem_catalog model-download --allow`)"),
    pytest.mark.skipif(not _runtime(), reason="onnxruntime/tokenizers not installed (uv sync --extra embeddings)"),
]


def test_local_multilingual_recall(tmp_path):
    encoder = LocalE5Encoder(MODEL)
    store = CatalogStore(tmp_path / "catalog.db")
    store.register([SourceSpec(source_id="primary", kind="bundle", url="bundled:test")])
    documents = {
        "debug": "Systematic debugging: reproduce a failing test, investigate its root cause, and verify the fix.",
        "web": "Build accessible web interfaces: keyboard navigation, screen reader labels, semantic HTML and contrast.",
        "paper": "Verify citations in scientific papers. Check the original sources and whether each claim is supported.",
    }
    rows = [Record(native_id=key, resource=Resource(item_id=key, type="skill", name=key, summary=value, url="https://example.org"))
            for key, value in documents.items()]
    publish(store, rows)
    assert index_embeddings(store, encoder)["pending"] == 0
    for query, expected in [("排查自动化测试反复失败的原因", "debug"), ("改善网页的无障碍访问", "web"), ("核对论文中的引用是否真实", "paper")]:
        result = search(store, MatchRequest(text=query, limit=1), encoder)
        assert result["items"][0]["item_id"] == expected
        assert result["vector"]["status"] == "ready"


def test_e5_cosines_are_positive_and_related_pairs_rank_first():
    """E5's 0.01-temperature training puts even unrelated pairs high (model card FAQ 3)."""
    encoder = LocalE5Encoder(MODEL)
    docs = encoder.encode(["PostgreSQL MCP server: run SQL queries against your database",
                           "Create slide decks with brand colors and speaker notes"])
    query = encoder.encode(["postgres database"], query=True)[0]
    related, unrelated = docs @ query
    assert unrelated > 0.5 and related > unrelated
