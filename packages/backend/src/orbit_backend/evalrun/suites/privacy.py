"""EV-14: nothing secret leaves the machine in an AI context pack.

Clearly fake secrets are planted in session text, tool arguments, file paths and rule text; the
pack is built the way ``AIService.preview`` builds it (``ai.pack.build`` with scope, selection,
goal and slots) and the final payload is searched for every planted value.
"""

from __future__ import annotations

import json

from ..contract import Check, EvalContext, SuiteResult

ID = "privacy"
TITLE = "Privacy: redaction of AI context packs"
EV = ("EV-14",)

# data class -> fake values (every one is obviously synthetic)
SECRETS = {
    "api_key": ["sk-test-0000000000000000FAKE", "ghp_FAKE0000000000000000000"],
    "aws_key": ["AKIAFAKE0000EXAMPLE0"],
    "bearer": ["Bearer faketoken0000000000.abc"],
    "email": ["someone.fake@example.com"],
    "home_path": ["/Users/example"],
    "ssh_key": ["-----BEGIN OPENSSH PRIVATE KEY-----"],
    "url_auth": ["fakeuser:fakepass0000@"],
}
DISABLED_MARK = "only-in-evidence-item-7f3a"
TASK = {"task_id": "eval.privacy", "prompt_version": "eval-1",
        "pack_items": [("goal", True), ("evidence", True), ("tool_evidence", True),
                       ("sessions", True), ("existing_rules", True)]}


def _slots() -> dict:
    s = {k: v[0] for k, v in SECRETS.items()}
    return {
        "evidence": [{"kind": "human", "ref_id": "ev-1", "session_uid": "s-1",
                      "text": f"my key is {s['api_key']} and mail {s['email']} ({DISABLED_MARK})"},
                     {"kind": "error", "ref_id": "ev-2", "session_uid": "s-1",
                      "text": f"auth failed: Authorization: {s['bearer']}\n{s['ssh_key']}"}],
        "tool_evidence": {"commands": [
            f"curl -H 'Authorization: {s['bearer']}' https://{s['url_auth']}api.example.com/x",
            f"export AWS_ACCESS_KEY_ID={s['aws_key']}",
            f"gh auth login --with-token {SECRETS['api_key'][1]}"]},
        "sessions": [{"session_uid": "s-1", "title": "fix login",
                      "files": [f"{s['home_path']}/proj/.env", f"{s['home_path']}/.ssh/id_ed25519"],
                      "cwd": f"{s['home_path']}/proj"}],
        "existing_rules": [{"path_label": "~/.claude/CLAUDE.md", "anchor_hash": "0" * 16,
                            "text": f"# Rules\napi_key = \"{s['api_key']}\"\nowner {s['email']}"}],
    }


def _planted(value) -> dict[str, int]:
    text = json.dumps(value, ensure_ascii=False)
    return {k: sum(text.count(v) for v in vals) for k, vals in SECRETS.items()}


def _build(build, tmp, selection=None):
    # same keyword arguments as AIService._pack (reads/appdb absent: every item comes from slots)
    return build(TASK, reads=None, appdb=None, home=tmp, scope=None, selection=selection,
                 goal=f"why does login fail for {SECRETS['email'][0]}", goal_source="manual",
                 params={}, slots=_slots())


def run(ctx: EvalContext) -> SuiteResult:
    try:
        from ...ai.pack import build  # noqa: PLC0415
        from ...ai.redact import est_tokens  # noqa: PLC0415
    except ImportError as error:
        return SuiteResult(ID, skipped=f"ai.pack unavailable: {error}")
    checks: list[Check] = []
    pack = _build(build, ctx.tmp)
    planted = _planted({**_slots(), "goal": SECRETS["email"][0]})
    leaked = _planted(pack["content"])
    for cls in SECRETS:
        checks.append(Check(f"privacy.leak.{cls}", leaked[cls] == 0, value=leaked[cls],
                            threshold=0, detail=f"planted {planted[cls]}"))
    total_planted, total_leaked = sum(planted.values()), sum(leaked.values())
    checks.append(Check("privacy.redaction_hits", pack["redaction_hits"] >= total_planted,
                        value=pack["redaction_hits"], threshold=total_planted))

    enabled = [i for i in pack["items"] if i["enabled"]]
    exact = all(i["tokens"] == est_tokens(pack["content"][i["key"]]) for i in enabled)
    checks.append(Check("privacy.token_total", exact and pack["total_tokens"] == sum(
        i["tokens"] for i in enabled), value=pack["total_tokens"]))

    off = _build(build, ctx.tmp, {"items": {"evidence": False}})
    ev = next(i for i in pack["items"] if i["key"] == "evidence")
    text = json.dumps(off["content"], ensure_ascii=False)
    ok = ("evidence" not in off["content"] and DISABLED_MARK not in text
          and off["total_tokens"] == pack["total_tokens"] - ev["tokens"])
    checks.append(Check("privacy.disabled_item_excluded", ok,
                        detail=f"tokens {pack['total_tokens']} -> {off['total_tokens']}"))

    again = _build(build, ctx.tmp)
    stable = again["preview_digest"] == pack["preview_digest"]
    changed = off["preview_digest"] != pack["preview_digest"]
    checks.append(Check("privacy.digest_stable", stable and changed,
                        detail=f"stable={stable} changes_on_toggle={changed}"))
    return SuiteResult(ID, checks, metrics={"planted": total_planted, "leaked": total_leaked,
                                            "hits": pack["redaction_hits"]})
