"""Worker sections run the recommendation pipeline once per request (audit AP-22)."""

import pytest
from cache_fixtures import build_home

from tandem_backend.analytics import service as analytics_service
from tandem_backend.analytics.cache import clear_memory_cache
from tandem_backend.data_access.store import CanonicalStore
from tandem_backend.recommend import service as recommend_service
from tandem_backend.services.sections import ResultMemo, compute_section


@pytest.fixture
def counted(tmp_path, monkeypatch):
    clear_memory_cache()
    home, _ = build_home(tmp_path, 6)
    calls = []
    original = recommend_service.recommend

    def counting(*args, **kwargs):
        calls.append(kwargs.get("context"))
        return original(*args, **kwargs)

    monkeypatch.setattr(recommend_service, "recommend", counting)
    monkeypatch.setattr(analytics_service, "recommend_resources", counting)
    yield CanonicalStore(home), calls
    clear_memory_cache()


@pytest.mark.parametrize("name,params", [
    ("recommendations", {"context": {"agent": "codex"}, "limit": 6}),
    ("recommendations", {"context": {"agent": "generic"}, "limit": 3}),
    ("presentation", {"target_agent": "codex"}),
])
def test_custom_request_does_not_also_compute_the_default_set(counted, name, params):
    store, calls = counted
    compute_section(name, store, analytics_service.Scope(), params, ResultMemo())
    assert len(calls) == 1


@pytest.mark.parametrize("name,params", [
    ("recommendations", {"context": {"agent": "generic"}, "limit": 6}),  # what the GET route sends
    ("recommendations", {}),
    ("presentation", {"target_agent": "generic"}),
])
def test_default_request_reuses_the_analysis_set(counted, name, params):
    store, calls = counted
    body = compute_section(name, store, analytics_service.Scope(), params, ResultMemo())
    assert len(calls) == 1 and calls[0] is None  # only the analysis' own default call
    if name == "recommendations":
        # Same answer as rerunning the pipeline on the recommendation-free analysis.
        base = analytics_service.analyze_sections(
            store, analytics_service.Scope(),
            [n for n in analytics_service.SECTIONS if n != "bottleneck_recommendations"])
        assert body["bottleneck_recommendations"] == recommend_service.recommend(base, context={"agent": "generic"})
