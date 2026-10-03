import time

import pytest

from tandem_data.contract import canonical
from tandem_data.search import SearchScope, search, snippet
from tandem_data.service import ImportRequest, ImportService
from tandem_data.store import Store, readonly_connection
from tandem_data.validation.fixtures import create_sources

SECRET = "sk-ant-" + "A1b2C3d4E5f6G7h8J9k0"
T0 = 1_790_000_000_000


def _iso(ms):
    import datetime

    return (
        datetime.datetime.fromtimestamp(ms / 1000, datetime.UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[
            :-3
        ]
        + "Z"
    )


def claude_session(root, sid, cwd, t, user_text, *, title=None, tool=None):
    common = {"sessionId": sid, "cwd": cwd, "version": "2.1.0"}
    rows = [
        {
            **common,
            "type": "user",
            "uuid": f"{sid}-u",
            "timestamp": _iso(t),
            "message": {"role": "user", "content": user_text},
        },
    ]
    if title:
        rows.append({**common, "type": "custom-title", "customTitle": title, "timestamp": _iso(t)})
    name, args = tool or ("Bash", {"command": "git status"})
    rows += [
        {
            **common,
            "type": "assistant",
            "uuid": f"{sid}-a",
            "parentUuid": f"{sid}-u",
            "timestamp": _iso(t + 1000),
            "message": {
                "id": f"{sid}-r",
                "model": "fixture-model",
                "stop_reason": "tool_use",
                "content": [
                    {"type": "text", "text": "I will refactor the parser."},
                    {"type": "tool_use", "id": f"{sid}-c", "name": name, "input": args},
                ],
                "usage": {"input_tokens": 10, "output_tokens": 2},
            },
        },
        {
            **common,
            "type": "user",
            "uuid": f"{sid}-o",
            "parentUuid": f"{sid}-a",
            "timestamp": _iso(t + 2000),
            "toolUseResult": {"durationMs": 5},
            "message": {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": f"{sid}-c",
                        "content": "ok",
                        "is_error": False,
                    }
                ],
            },
        },
    ]
    path = root / "projects" / cwd.strip("/").replace("/", "-") / f"{sid}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(canonical(row) + "\n" for row in rows), encoding="utf-8")


def build_home(tmp_path):
    roots = create_sources(tmp_path / "fixtures")
    cc = tmp_path / "cc"
    claude_session(
        cc,
        "s-cn",
        "/work/alpha-service",
        T0,
        f"请修复第 7 个问题，密钥 {SECRET} 不要外泄",
        title="Parser cleanup",
    )
    claude_session(
        cc,
        "s-file",
        "/work/beta-tool",
        T0 + 86_400_000,
        "edit the widget",
        tool=(
            "Edit",
            {
                "file_path": "/work/beta-tool/src/widget_parser.py",
                "old_string": "a",
                "new_string": "b",
            },
        ),
    )
    claude_session(
        cc,
        "s-cmd",
        "/work/beta-tool",
        T0 + 2 * 86_400_000,
        "run the linter",
        tool=("Bash", {"command": "ruff check --fix packages"}),
    )
    home = tmp_path / "home"
    with Store(home) as store:
        service = ImportService(store)
        for agent, root in roots.items():
            service.import_source(ImportRequest(agent, root))
        service.import_source(ImportRequest("claude_code", cc))
        sources = dict(store.db.execute("SELECT agent || ':' || root_path, source_id FROM source"))
    return home, sources, cc


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    return build_home(tmp_path_factory.mktemp("search"))


def hit_types(result):
    return {hit["hit_type"] for hit in result["hits"]}


def test_every_field_kind_is_searchable(built):
    home, _, _ = built
    now = T0 + 3 * 86_400_000
    chinese = search(home, "修复第 7", now_ms=now)
    assert chinese["substring"] and chinese["total"] == 1
    assert chinese["hits"][0]["hit_type"] == "message"
    english = search(home, "refactor", now_ms=now)
    # Migration 008 creates the trigram ``event_search`` table, so substring semantics apply.
    assert english["engine"] == "event_search" and english["substring"]
    assert english["counts"]["message"] == 3
    # command_head keeps the program head only (arguments are not projected).
    assert hit_types(search(home, "ruff", now_ms=now)) == {"command"}
    files = search(home, "widget_parser.py", now_ms=now)
    assert hit_types(files) == {"file"}
    assert files["hits"][0]["snippet"] == "/work/beta-tool/src/widget_parser.py"
    project = search(home, "alpha-service", now_ms=now)
    assert project["counts"]["project"] == 1
    title = search(home, "Parser cleanup", now_ms=now)
    assert title["hits"][0]["hit_type"] == "title"
    # Title event and session column collapse into one hit per session.
    assert title["counts"]["title"] == 1
    assert search(home, "no-such-term-anywhere", now_ms=now)["total"] == 0


def test_snippets_are_redacted(built):
    home, _, _ = built
    result = search(home, "修复第 7")
    text = result["hits"][0]["snippet"]
    assert "修复第 7" in text and SECRET not in text and "<redacted:" in text
    # A raw secret passed to snippet() directly is also removed.
    assert SECRET not in snippet(f"token {SECRET} here", "token")


def test_source_and_time_filters_partition_counts(built):
    home, sources, cc = built
    query = "git status"
    everything = search(home, query)["total"]
    ids = list(sources.values())
    per_source = [search(home, query, SearchScope(source_ids=(sid,)))["total"] for sid in ids]
    assert (
        sum(per_source)
        == everything
        == search(home, query, SearchScope(source_ids=tuple(ids)))["total"]
    )
    cc_id = sources[f"claude_code:{cc.resolve()}"]
    window = SearchScope(source_ids=(cc_id,), from_ts=T0, until_ts=T0 + 86_400_000 + 5000)
    windowed = search(home, "refactor", window)
    assert windowed["total"] == 2
    assert all(T0 <= hit["ts"] <= T0 + 86_400_000 + 5000 for hit in windowed["hits"])
    before = search(home, "refactor", SearchScope(until_ts=T0 - 1))["total"]
    after = search(home, "refactor", SearchScope(from_ts=T0))["total"]
    assert before + after == search(home, "refactor")["total"]


def test_ranking_prefers_titles_and_recent_hits(built):
    home, _, _ = built
    now = T0 + 3 * 86_400_000
    result = search(home, "refactor", now_ms=now)
    stamps = [hit["ts"] for hit in result["hits"]]
    assert stamps == sorted(stamps, reverse=True)
    assert search(home, "parser", now_ms=now)["hits"][0]["hit_type"] == "title"


def test_event_search_table_is_preferred_when_present(built, tmp_path):
    home, _, _ = built
    import shutil

    copy = tmp_path / "copy"
    copy.mkdir()
    with readonly_connection(home / "tandem.db") as source:
        import sqlite3

        target = sqlite3.connect(copy / "tandem.db")
        source.backup(target)
        # Simulate a pre-008 library: no trigram table, only event_fts (unicode61, 001.sql).
        target.executescript(
            "DROP TRIGGER IF EXISTS event_search_ai;"
            "DROP TRIGGER IF EXISTS event_search_ad;"
            "DROP TRIGGER IF EXISTS event_search_au;"
            "DROP TABLE IF EXISTS event_search;"
            "CREATE VIRTUAL TABLE event_fts USING fts5(text, content='event', content_rowid='rowid');"
            "INSERT INTO event_fts(event_fts) VALUES('rebuild');"
        )
        target.close()
    shutil.rmtree(copy / "raw", ignore_errors=True)
    result = search(home, "修复第 7")
    assert result["engine"] == "event_search" and result["total"] == 1
    assert search(home, "efacto")["counts"]["message"] == 3  # trigram substring
    fallback = search(copy, "efacto")
    assert fallback["engine"] == "event_fts"
    assert fallback["counts"]["message"] == 0  # unicode61 tokens only
    assert search(copy, "修复第 7")["total"] == 1  # bounded LIKE fallback
    # Same answer set as the fallback path for a whole-word query.
    assert search(copy, "refactor")["total"] == search(home, "refactor")["total"]


@pytest.mark.parametrize(
    ("query", "scope", "message"),
    [
        ("", None, "empty"),
        ("x" * 201, None, "at most"),
        ("ok", SearchScope(from_ts=2, until_ts=1), "after"),
        ("ok", SearchScope(source_ids=()), "source_ids"),
    ],
)
def test_invalid_requests(built, query, scope, message):
    home, _, _ = built
    with pytest.raises(ValueError, match=message):
        search(home, query, scope)


def test_missing_database(tmp_path):
    with pytest.raises(FileNotFoundError):
        search(tmp_path, "x")


def test_like_wildcards_are_literal(built):
    home, _, _ = built
    assert search(home, "%")["total"] == 0
    underscore = search(home, "_")
    assert underscore["total"] >= 1
    assert all("_" in hit["snippet"] for hit in underscore["hits"])


@pytest.mark.serial
def test_search_is_fast_enough_on_fixture(built):
    home, _, _ = built
    started = time.perf_counter()
    search(home, "修复")
    assert time.perf_counter() - started < 1.0
