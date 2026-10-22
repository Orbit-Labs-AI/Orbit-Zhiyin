"""Session (timezone, timezone_source) must satisfy the migration CHECK for any event order.

L3 derivation used to let a later ``timezone_source="unknown"`` event erase the source of an
earlier reported zone, and a zone without a source kept the initial ``"unknown"``. One dirty
Codex ``turn_context`` therefore made the whole source's derived publication fail on the
session CHECK (reported as "the analysis service did not respond" in the UI).
"""

import pytest

from orbit_data.analysis_input import AnalysisScope, read_analysis
from orbit_data.connectors import MAPPERS
from orbit_data.connectors.base import BaseMapper, Mapping
from orbit_data.contract import canonical
from orbit_data.pipeline import SESSION_TABLES
from orbit_data.reduce import derive
from orbit_data.store import Store

NY = "America/New_York"


def pairs(store):
    """The stored session timezone pairs; a row violating the CHECK cannot be inserted."""
    return [tuple(row) for row in store.db.execute("SELECT timezone, timezone_source FROM session")]


def assert_invariant(store):
    rows = pairs(store)
    assert rows
    for timezone, source in rows:
        assert source in ("reported", "local_inferred", "unknown")
        assert (timezone is None) == (source == "unknown"), (timezone, source)


class MetaMapper(BaseMapper):
    """Synthetic connector: one native record per metadata event, in capture order."""

    def map(self, record):
        data = record.data
        self.session_uid = self.store.identity(
            record.source_id, data["session"], record.relative_path
        )
        attrs = {"kind": "main", "native_id": data["session"], **data["attrs"]}
        return Mapping([self.make(record, "session.meta", "synthetic.meta", attrs=attrs)])


def capture_meta(tmp_path, monkeypatch, events):
    """Store one synthetic session from metadata events, then derive it."""
    monkeypatch.setitem(MAPPERS, "pi", MetaMapper)
    store = Store(tmp_path / "data")
    source = store.add_source("pi", tmp_path / "source")
    rows = [{"type": "synthetic", "session": "s", "attrs": attrs} for attrs in events]
    store.capture_stream(source, "s.jsonl", [(canonical(row) + "\n").encode() for row in rows])
    store.rebuild()
    return store


@pytest.mark.parametrize(
    ("events", "expected"),
    [
        # (a) The reported trigger: metadata carries timezone_source but no zone.
        ([{"timezone_source": "unknown"}], (None, "unknown")),
        # No timezone metadata at all leaves the pair unknown, never a dangling source.
        ([{}], (None, "unknown")),
        # (b) A zone whose event says source "unknown" is still reported evidence.
        ([{"timezone": NY, "timezone_source": "unknown"}], (NY, "reported")),
        # (b) Arrival order: a later zone-less event must not erase an earlier zone's source.
        (
            [{"timezone": NY, "timezone_source": "reported"}, {"timezone_source": "unknown"}],
            (NY, "reported"),
        ),
        # (b) A later unrelated metadata event is not a reset either.
        (
            [{"timezone": NY, "timezone_source": "reported"}, {"cwd": "/elsewhere"}],
            (NY, "reported"),
        ),
        # (c) A zone without a source is reported evidence.
        ([{"timezone": "Europe/Berlin"}], ("Europe/Berlin", "reported")),
        # (d) A value ZoneInfo cannot resolve is not a usable zone name.
        ([{"timezone": "Mars/Base", "timezone_source": "reported"}], (None, "unknown")),
        # (e) Explicit sources survive.
        (
            [{"timezone": "Asia/Shanghai", "timezone_source": "reported"}],
            ("Asia/Shanghai", "reported"),
        ),
        (
            [{"timezone": "Asia/Shanghai", "timezone_source": "local_inferred"}],
            ("Asia/Shanghai", "local_inferred"),
        ),
        # Blank or non-string zones are empty, never a reported zone.
        ([{"timezone": " ", "timezone_source": "reported"}], (None, "unknown")),
        ([{"timezone": 42, "timezone_source": "reported"}], (None, "unknown")),
    ],
    ids=[
        "null-zone-unknown-source",
        "no-timezone-metadata",
        "zone-unknown-source",
        "later-lone-unknown",
        "later-unrelated-event",
        "zone-without-source",
        "invalid-iana",
        "reported-preserved",
        "local-inferred-preserved",
        "blank-zone",
        "non-string-zone",
    ],
)
def test_metadata_combinations_normalize_at_insert(tmp_path, monkeypatch, events, expected):
    with capture_meta(tmp_path, monkeypatch, events) as store:
        assert pairs(store) == [expected]
        assert_invariant(store)


def codex_session(session, *timezones):
    """One Codex session; a ``None`` entry is a turn_context without a timezone.

    Codex writes ``timezone_source="reported"`` beside a real zone and ``"unknown"`` beside
    the missing one (``connectors/codex.py``), so this is the real event-order trigger.
    """
    rows = [
        {
            "type": "session_meta",
            "timestamp": "2026-10-02T00:00:00Z",
            "payload": {
                "id": session,
                "session_id": session,
                "cwd": "/missing/demo",
                "model_provider": "openai",
            },
        }
    ]
    for index, timezone in enumerate(timezones):
        payload = {"turn_id": f"t{index}", "model": "test-model"}
        if timezone is not None:
            payload["timezone"] = timezone
        rows.append(
            {
                "type": "turn_context",
                "timestamp": f"2026-10-02T00:00:{index + 1:02d}Z",
                "payload": payload,
            }
        )
    return rows


def rebuild_codex(tmp_path, sessions):
    store = Store(tmp_path / "data")
    source = store.add_source("codex", tmp_path / "source")
    for session, timezones in sessions:
        raw = "".join(canonical(row) + "\n" for row in codex_session(session, *timezones))
        store.capture_stream(source, f"{session}.jsonl", [raw.encode()])
    store.rebuild()
    return store


def test_codex_zone_then_zone_less_turn_context_publishes(tmp_path):
    """The reported trigger: a reported zone followed by a turn_context without one."""
    with rebuild_codex(tmp_path, [("s", (NY, None))]) as store:
        assert pairs(store) == [(NY, "reported")]
        assert_invariant(store)


def test_one_dirty_session_does_not_fail_the_whole_source(tmp_path):
    """A dirty session must not abort the publication of its clean peers."""
    sessions = [("clean", ("Europe/Berlin",)), ("dirty", (NY, None))]
    with rebuild_codex(tmp_path, sessions) as store:
        assert sorted(pairs(store)) == sorted([("Europe/Berlin", "reported"), (NY, "reported")])
        assert_invariant(store)


def test_scoped_derive_keeps_the_invariant(tmp_path):
    """``derive(..., scoped=True, sessions=...)`` shares the insert site."""
    with rebuild_codex(tmp_path, [("s", (NY, None))]) as store:
        source_id = store.db.execute("SELECT source_id FROM source").fetchone()[0]
        store.db.execute(
            "CREATE TEMP TABLE IF NOT EXISTS rebuild_scope(source_id TEXT PRIMARY KEY)"
        )
        store.db.execute("INSERT OR IGNORE INTO rebuild_scope VALUES(?)", (source_id,))
        # What a closure rebuild leaves before deriving: events stay, derived rows are gone.
        for table in SESSION_TABLES:
            if table != "event":
                store.db.execute(f"DELETE FROM {table}")
        store.db.execute("DELETE FROM event_context")
        derive(store, scoped=True, sessions="SELECT session_uid FROM session_identity")
        assert pairs(store) == [(NY, "reported")]
        assert_invariant(store)


def test_bounded_analysis_input_rebuild_normalizes_metadata(tmp_path):
    """The historical (until_ts) rebuild reconstructs the same normalized pair from events."""
    with rebuild_codex(tmp_path, [("s", ("",))]) as store:
        home = store.home
    bounded = read_analysis(home, AnalysisScope("UTC", until_ts=1790985600000))["sessions"]
    assert [(session["timezone"], session["timezone_source"]) for session in bounded] == [
        (None, "unknown")
    ]
