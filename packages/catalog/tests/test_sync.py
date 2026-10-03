import json
import threading
from pathlib import Path

from orbit_catalog.contracts import Page, Record, Resource, SourceSpec
from orbit_catalog.network import FetchError, HttpClient
from orbit_catalog.store import CatalogStore
from orbit_catalog.sync import CatalogSync

from .test_network import FakeOpener, client
from .test_storage import record

FIXTURES = Path(__file__).parent / "fixtures"


def make_store(tmp_path, *ids):
    store = CatalogStore(tmp_path / "catalog.db")
    store.register([SourceSpec(source_id=i, kind="bundle", url="bundled:test", priority=90 - n) for n, i in enumerate(ids)])
    return store


def test_sources_fetch_concurrently_and_keep_source_order(tmp_path):
    store = make_store(tmp_path, "a", "b", "c")
    barrier = threading.Barrier(3, timeout=5)  # Deadlocks unless all three fetch at once.

    class Adapter:
        def __init__(self, spec, http):
            self.spec = spec

        def fetch_page(self, checkpoint, state):
            barrier.wait()
            return Page(records=[record(self.spec.source_id + "-item")], complete=True, revision="r1")

    results = CatalogSync(store, None, connector_factory=Adapter).sync(concurrency=3)
    assert [r["source_id"] for r in results] == ["a", "b", "c"]
    assert all(r["status"] == "completed" for r in results) and store.stats()["items"] == 3


def test_one_failing_source_does_not_affect_others(tmp_path):
    store = make_store(tmp_path, "good", "bad")

    class Adapter:
        def __init__(self, spec, http):
            self.spec = spec

        def fetch_page(self, checkpoint, state):
            if self.spec.source_id == "bad":
                raise FetchError("http_503", 60)
            return Page(records=[record("ok")], complete=True)

    results = {r["source_id"]: r for r in CatalogSync(store, None, connector_factory=Adapter).sync()}
    assert results["good"]["status"] == "completed" and results["bad"]["status"] == "failed"
    assert results["bad"]["error"] == "http_503"
    again = {r["source_id"]: r["status"] for r in CatalogSync(store, None, connector_factory=Adapter).sync()}
    assert again == {"good": "not_due", "bad": "not_due"}


def test_cancellation_is_shared_by_all_workers(tmp_path):
    store = make_store(tmp_path, "a", "b")
    calls = []

    class Adapter:
        def __init__(self, *_):
            pass

        def fetch_page(self, checkpoint, state):
            calls.append(1)
            return Page(records=[], complete=True)

    results = CatalogSync(store, None, connector_factory=Adapter).sync(cancelled=lambda: True)
    assert {r["status"] for r in results} == {"paused"} and not calls


class KnownStore:
    """Wraps a real store and exposes the optional P1 `known_resources` hook."""

    def __init__(self, store, known):
        self._store, self.known, self.asked = store, known, []

    def __getattr__(self, name):
        return getattr(self._store, name)

    def known_resources(self, source_id):
        self.asked.append(source_id)
        return self.known


def test_known_resources_reach_connector_and_reuse_skips_fetching(tmp_path):
    stored = Resource(item_id="x", type="skill", name="x", url="https://example.org", metadata={"blob_sha": "s1"})
    store = KnownStore(make_store(tmp_path, "a"), {"x": ("s1", stored, {})})
    fetched = []

    class Adapter:
        def __init__(self, *_):
            pass

        def fetch_page(self, checkpoint, state):
            known = state["known"]
            records = []
            for native_id, current_sha in (("x", "s1"), ("y", "s2")):
                hit = known.get(native_id)
                if hit and hit[0] == current_sha:
                    records.append(Record(native_id=native_id, resource=hit[1]))
                else:
                    fetched.append(native_id)
                    records.append(record(native_id))
            return Page(records=records, complete=True)

    assert CatalogSync(store, None, connector_factory=Adapter).sync()[0]["status"] == "completed"
    assert store.asked == ["a"] and fetched == ["y"]


def test_local_source_is_never_fetched(tmp_path):
    store = make_store(tmp_path, "a")
    sources = store.sources()

    class FakeStore(KnownStore):
        def sources(self):
            return sources + [{**sources[0], "source_id": "local", "spec": {**sources[0]["spec"], "kind": "local"}}]

    seen = []

    class Adapter:
        def __init__(self, spec, http):
            seen.append(spec.source_id)

        def fetch_page(self, checkpoint, state):
            return Page(records=[], complete=True)

    results = CatalogSync(FakeStore(store, {}), None, connector_factory=Adapter).sync()
    assert seen == ["a"] and [r["source_id"] for r in results] == ["a"]


def test_benchmarks_resolve_against_models_imported_in_same_run(tmp_path):
    store = CatalogStore(tmp_path / "catalog.db")
    store.register([
        SourceSpec(source_id="swe-bench", kind="swe_bench", url="https://example.org", priority=99,
                   config={"file": str(FIXTURES / "swe_bench_mini.json")}),
        SourceSpec(source_id="models-dev", kind="models_dev", url="https://models.dev/api.json", priority=10,
                   config={"file": str(FIXTURES / "models_dev_mini.json")}),
    ])
    results = CatalogSync(store, None).sync(concurrency=2)
    assert [r["status"] for r in results] == ["completed", "completed"]
    with store.connect(True) as conn:
        rows = dict(conn.execute("SELECT json_extract(result,'$.model_id'), json_extract(result,'$.canonical_model_id') "
                                 "FROM benchmark_result").fetchall())
    assert rows["Claude 3.5 Sonnet (20241022)"] == "anthropic/claude-3-5-sonnet-20241022"
    assert rows["GPT-5 (32k thinking)"] == "openai/gpt-5"
    assert rows["Totally New Model"] is None
    # A later benchmark-only refresh still resolves through the stored model rows.
    assert "anthropic/claude-3-5-sonnet-20241022" in CatalogSync(store, None)._stored_models()
    assert CatalogSync(store, None).sync(["swe-bench"], force=True)[0]["status"] == "completed"


def run_cli(capsys, *argv):
    from orbit_catalog.cli import main
    try:
        main(list(argv))
        code = 0
    except SystemExit as exc:
        code = exc.code
    return code, json.loads(capsys.readouterr().out)


def test_cli_import_file_loads_fixture_without_network(tmp_path, capsys):
    code, result = run_cli(capsys, "--home", str(tmp_path), "import-file", "--source", "models-dev",
                           "--file", str(FIXTURES / "models_dev_mini.json"))
    assert code == 0 and result[0]["status"] == "completed"
    assert CatalogStore(tmp_path / "catalog.db").stats()["items"] == 4


def test_cli_offline_sync_uses_cache_only(tmp_path, capsys):
    body = (FIXTURES / "litellm_mini.json").read_bytes()
    url = "https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json"
    HttpClient(tmp_path / "catalog-http-cache", opener=FakeOpener((body, {"ETag": '"x"'}))).get(url)
    code, result = run_cli(capsys, "--home", str(tmp_path), "sync", "--source", "litellm", "--source", "models-dev",
                           "--offline", "--concurrency", "2")
    status = {r["source_id"]: (r["status"], r.get("error")) for r in result}
    assert status["litellm"] == ("completed", None)
    assert status["models-dev"] == ("failed", "not_cached") and code == 1


class EndlessAdapter:
    """A registry whose pagination never completes (recs-B14)."""

    def __init__(self, spec, http, delay=0.02):
        self.spec, self.http, self.delay = spec, http, delay

    def fetch_page(self, checkpoint, state):
        import time

        time.sleep(self.delay)
        n = int(checkpoint.get("n", 0)) + 1
        return Page(records=[record(f"item-{n}")], complete=False, checkpoint={"n": n})


def endless_store(tmp_path, **config):
    store = CatalogStore(tmp_path / "catalog.db")
    store.register([SourceSpec(source_id="reg", kind="mcp", url="https://registry.example/v0/servers",
                               priority=50, config=config)])
    return store


def test_time_budget_pauses_endless_pagination_and_resumes(tmp_path):
    import time

    store = endless_store(tmp_path, max_seconds=0.3)
    started = time.monotonic()
    (result,) = CatalogSync(store, None, connector_factory=EndlessAdapter).sync(force=True, max_pages=400)
    assert time.monotonic() - started < 3
    assert result["status"] == "paused" and result["stopped"] == "time_budget"
    first = result["pages_done"]
    assert 0 < first < 120
    assert store.stats()["items"] == first  # staged pages published before pausing
    (again,) = CatalogSync(store, None, connector_factory=EndlessAdapter).sync(force=True, max_pages=400)
    assert again["status"] == "paused" and store.stats()["items"] == first + again["pages_done"]


def test_cancel_interrupts_retry_backoff_without_failing_the_source(tmp_path):
    import time

    store = endless_store(tmp_path)
    http, opener = client(tmp_path / "http", 503, sleep=time.sleep)

    class Adapter:
        def __init__(self, spec, http):
            self.http = http

        def fetch_page(self, checkpoint, state):
            self.http.json("https://models.dev/api.json")
            raise AssertionError("unreachable: every response is 503")

    cancel = threading.Event()
    threading.Timer(0.3, cancel.set).start()
    started = time.monotonic()
    (result,) = CatalogSync(store, http, connector_factory=Adapter).sync(force=True, cancelled=cancel.is_set)
    assert time.monotonic() - started < 3  # back-off would otherwise wait 1+2+4+8 s
    assert result["status"] == "paused" and result["stopped"] == "cancelled", result
    source = next(s for s in store.sources() if s["source_id"] == "reg")
    assert source["failures"] == 0 and source["error"] is None
