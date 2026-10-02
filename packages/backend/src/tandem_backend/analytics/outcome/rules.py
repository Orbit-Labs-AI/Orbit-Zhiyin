"""Conservative validation-command and exact-coverage rules."""

import re
import shlex

VALIDATION_KINDS = {"test", "build", "check", "lint", "typecheck"}


RESULTS = {"passed", "failed", "interrupted", "unknown"}


COMMAND_SCOPES = {"command", "command_return", "command_transport"}


SCOPE_KEYS = {"project_id", "artifact_uid", "artifact_revision", "coverage"}


def _command_kind(call):
    """Recognize an explicitly complete direct command, never a mention/head only."""
    command = call.get("command_head") or ""
    if (call.get("command_complete") is not True or call.get("is_wrapper")
            or call.get("kind") != "shell" or re.search(r"[;&|<>`$\n]", command)):
        return None
    try:
        args = shlex.split(command)
    except ValueError:
        return None
    if not args or any(a in ("--help", "-h", "--version", "-V", "--collect-only", "--co", "--setup-only",
                            "--fixtures", "--fixtures-per-test", "--markers", "--no-run", "--list", "-list",
                            "--show-settings", "--show-files") for a in args):
        return None
    executable = args[0].replace("\\", "/").rsplit("/", 1)[-1]
    if executable == "pytest" or (executable in ("python", "python3") and args[1:3] == ["-m", "pytest"]):
        return "test"
    if executable == "ruff" and args[1:2] == ["check"]:
        return "lint"
    if executable == "mypy" or (executable == "tsc" and "--noEmit" in args):
        return "typecheck"
    if executable in ("cargo", "go") and len(args) > 1:
        return {"test": "test", "build": "build", "check": "check", "vet": "check"}.get(args[1])
    return None


def _scope_equal(a, b):
    if not isinstance(a, dict) or not isinstance(b, dict) or not SCOPE_KEYS <= a.keys() or not SCOPE_KEYS <= b.keys():
        return False
    if any(not a[k] or not b[k] for k in SCOPE_KEYS):
        return False
    if a["coverage"] not in ("full", "subset") or b["coverage"] not in ("full", "subset"):
        return False
    if any(s["coverage"] == "subset" and not (s.get("files") or s.get("test_ids")) for s in (a, b)):
        return False
    # Exact coverage is conservative: no subset-to-full or version extrapolation.
    def normalized(scope):
        return {k: sorted(v) if isinstance(v, list) else v for k, v in scope.items()}
    return normalized(a) == normalized(b)
