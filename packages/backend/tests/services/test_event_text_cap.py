"""Event texts are capped in lists and evidence; the full text is read by range.

Regression: a tool.result with megabytes of output came back whole from
/v1/evidence/{id} (legacy create_app) and in every /v1/sessions/{id}/events page.
"""

from __future__ import annotations

import sqlite3

from conftest import add_codex, run_job, wait_job

from orbit_backend.services.text_cap import cap_event

BIG = "".join(chr(0x41 + i % 26) for i in range(100_000))


def test_cap_event_marks_text_and_details_and_supports_ranges():
    event = {"id": "e", "text": "abcdef", "details": {"args": {"cmd": "x" * 10}, "n": 3}}
    capped = cap_event(event, 4)
    assert capped["text"] == "abcd" and capped["truncated"]
    assert capped["truncated_fields"] == ["text", "details.args.cmd"]
    assert capped["details"]["args"]["cmd"] == "xxxx" and capped["details"]["n"] == 3
    assert capped["text_range"] == {"offset": 0, "length": 4, "total": 6}
    tail = cap_event(event, 4, text_offset=4)
    assert tail["text"] == "ef" and tail["text_range"] == {"offset": 4, "length": 2, "total": 6}
    small = cap_event({"text": "ok", "details": {}}, 100)
    assert small["truncated"] is False and small["truncated_fields"] == []


def test_events_page_and_evidence_cap_long_text(client_factory, codex_root):
    client, gateway = client_factory()
    source = add_codex(client, codex_root)
    assert wait_job(client, run_job(client, "import", [source], phase="head")["id"])[
        "status"] == "completed"
    with sqlite3.connect(gateway.home / "orbit.db") as db:
        event_uid, session_uid = db.execute(
            "SELECT event_uid, session_uid FROM event ORDER BY session_uid, seq LIMIT 1"
        ).fetchone()
        db.execute("UPDATE event SET text=? WHERE event_uid=?", (BIG, event_uid))

    page = client.get(f"/v1/sessions/{session_uid}/events", params={"max_chars": 1000})
    assert page.status_code == 200, page.text
    item = next(e for e in page.json()["items"] if e["id"] == event_uid)
    assert len(item["text"]) == 1000 and item["truncated"] and "text" in item["truncated_fields"]
    assert item["text_range"]["total"] == len(BIG)
    default = client.get(f"/v1/sessions/{session_uid}/events").json()["items"]
    assert len(next(e for e in default if e["id"] == event_uid)["text"]) == 8_000

    evidence = client.get(f"/v1/evidence/{event_uid}")
    assert evidence.status_code == 200, evidence.text
    body = evidence.json()
    assert body["truncated"] and body["text_range"]["total"] == len(BIG)
    collected, offset = "", 0
    while offset < len(BIG):  # Range fetch reassembles the full text.
        part = client.get(f"/v1/evidence/{event_uid}",
                          params={"text_offset": offset, "max_chars": 20_000}).json()
        collected += part["text"]
        offset += part["text_range"]["length"]
    assert collected == BIG
    assert client.get("/v1/evidence/nope").status_code == 404
