"""Shared report use case for the CLI and local API."""

from ..profiling.analysis import analyze
from ..recommendation.catalog import resources
from ..recommendation.recommend import recommend
from ..reporting.narrative import explain


def build_report(store, *, project_id=None, model=None, before=None, scene=None,
                 recommendation_scene="auto", audience="user", catalog_cache=None):
    data = analyze(store, project_id, model, before, scene)
    suggestions = recommend(data, recommendation_scene, catalog=resources(catalog_cache))
    return data, explain(data, suggestions, audience)
