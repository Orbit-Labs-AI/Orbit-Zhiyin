"""The real route and recommender consume a synthetic analytics store boundary."""

from fastapi.testclient import TestClient
from test_recommend_pipeline import correction_bundle, ready_item, write_family

from tandem_backend.analytics.service import analyze_bundle
from tandem_backend.api import create_app


def test_api_preferences_benefits_and_validation_reach_the_real_pipeline(tmp_path, monkeypatch):
    directory = tmp_path / "catalog"
    directory.mkdir()
    write_family(directory, "skills", [ready_item(v, preference_support={"detail": [v]}) for v in ("brief", "detailed")])
    monkeypatch.setattr("tandem_backend.analytics.service.analyze_store",
                        lambda store, scope, with_text: analyze_bundle(correction_bundle(), scope, with_text))
    with TestClient(create_app(db=tmp_path / "synthetic.sqlite", recommendation_catalog=directory)) as client:
        route = "/v1/analytics/recommendations"
        payload = {"family": "skills", "context": {"preferences": [{"dimension": "detail", "value": "detailed"}]}}
        response = client.post(route, json=payload)
        assert response.status_code == 200
        card = response.json()["bottleneck_recommendations"]["recommendations"][0]
        assert card["resource_id"] == "detailed"
        scenario = {"resource_id": card["resource_id"], "signal_id": card["signal_id"],
                    "reduction": {"low": .2, "high": .4}, "minutes_per_occurrence": {"low": 10., "high": 10.},
                    "setup_minutes": {"low": 0., "high": 0.}, "extra_minutes_per_window": {"low": 0., "high": 0.},
                    "basis": "Synthetic API acceptance"}
        payload["context"]["benefit_scenarios"] = [scenario]
        response = client.post(route, json=payload)
        assert response.status_code == 200
        estimate = response.json()["bottleneck_recommendations"]["recommendations"][0]["benefit_estimate"]
        assert estimate["estimates"][0]["time_minutes"]["net_savings"] == {"low": 6., "high": 12.}
        scenario["reduction"]["high"] = 1.1
        assert client.post(route, json=payload).status_code == 422
        payload["context"].pop("benefit_scenarios")
        payload["context"]["preferences"][0]["scope"] = "project"
        assert client.post(route, json=payload).status_code == 422
