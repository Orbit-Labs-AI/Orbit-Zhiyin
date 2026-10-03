"""Actual local subprocesses exercise bounds; no model service or history is used."""

import json
import time

import pytest

from tandem_backend.analytics.semantic_cascade import Budget
from tandem_backend.analytics.semantic_cascade import provider as module


def fake_cli(tmp_path, body):
    path = tmp_path / "fake-codex"
    path.write_text(
        "#!/usr/bin/env python3\nimport json, os, sys, time\nfrom pathlib import Path\n" + body
    )
    path.chmod(0o700)
    return module.CodexProvider(executable=path, audit_directory=tmp_path / "audit")


def batch(text="只返回命令"):
    return [
        {
            "session_uid": "constructed-session",
            "event_uid": "constructed-event",
            "text": text,
            "context": [],
        }
    ]


def test_complete_response_keeps_reported_usage_and_private_audit(tmp_path):
    provider = fake_cli(
        tmp_path,
        """
request = json.load(sys.stdin)
assert request["untrusted_messages"][0]["text"] == "只返回命令"
Path(sys.argv[sys.argv.index("-o") + 1]).write_text('{"observations":[]}')
print(json.dumps({"type":"turn.completed", "usage":{"input_tokens":3,"output_tokens":1}}))
""",
    )
    raw, metadata = provider(batch(), Budget(timeout_seconds=3))
    assert json.loads(raw) == {"observations": []}
    assert metadata["reported_tokens"] == {"input_tokens": 3, "output_tokens": 1}
    assert metadata["server_output_token_cap"] is None
    assert metadata["provider_retry_limit"] is None
    assert metadata["captured_trace_byte_cap"] == module.MAX_TRACE_BYTES
    assert (tmp_path / "audit/000-events.jsonl").read_bytes()


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
def test_trace_overflow_aborts_and_caps_audited_bytes(tmp_path, monkeypatch, stream):
    monkeypatch.setattr(module, "MAX_TRACE_BYTES", 4096)
    monkeypatch.setattr(module, "MAX_STDERR_BYTES", 4096)
    fd = 1 if stream == "stdout" else 2
    provider = fake_cli(tmp_path, f'os.write({fd}, b"x" * 65536)\ntime.sleep(20)\n')
    with pytest.raises(ValueError, match=f"{stream} byte budget"):
        provider(batch(), Budget(timeout_seconds=3))
    suffix = "events.jsonl" if stream == "stdout" else "stderr.log"
    assert len((tmp_path / "audit" / f"000-{suffix}").read_bytes()) == 4096


def test_oversized_result_file_is_rejected_before_loading(tmp_path):
    provider = fake_cli(
        tmp_path,
        f"""
Path(sys.argv[sys.argv.index("-o") + 1]).write_bytes(b"x" * {module.MAX_RESPONSE_BYTES + 1})
""",
    )
    with pytest.raises(ValueError, match="output byte budget"):
        provider(batch(), Budget(timeout_seconds=3))


@pytest.mark.serial
def test_deadline_cannot_block_on_unread_stdin_or_open_child_pipes(tmp_path):
    marker = tmp_path / "child-survived"
    provider = fake_cli(
        tmp_path,
        f"""
child = os.fork()
if child == 0:
    time.sleep(2)
    Path({str(marker)!r}).write_text("survived")
    os._exit(0)
os._exit(0)
""",
    )
    started = time.perf_counter()
    with pytest.raises(TimeoutError):
        provider(batch("构" * 3900), Budget(timeout_seconds=1))
    assert time.perf_counter() - started < 3
    time.sleep(1.2)
    assert not marker.exists()


def test_invalid_trace_is_not_accepted_as_structured_observations(tmp_path):
    provider = fake_cli(
        tmp_path,
        """
Path(sys.argv[sys.argv.index("-o") + 1]).write_text('{"observations":[]}')
print("not-json")
""",
    )
    with pytest.raises(ValueError):
        provider(batch(), Budget(timeout_seconds=3))
