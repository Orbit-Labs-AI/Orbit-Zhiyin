"""Bounded command normalization without retaining arbitrary arguments or secrets.

This is a fact parser, never a shell runner. A validation result can describe only
one foreground check (optionally preceded by cd). Compound scripts stay candidates.
"""

import re
import shlex
from pathlib import PurePosixPath

from tandem_data.contract import uid

VERSION = "command-spec-v1"
NO_EXECUTION = {
    "--help",
    "-h",
    "--version",
    "-V",
    "--collect-only",
    "--co",
    "--setup-only",
    "--fixtures",
    "--fixtures-per-test",
    "--markers",
    "--no-run",
    "--list",
    "-list",
    "-test.list",
    "--test.list",
    "--show-settings",
    "--show-files",
    "--dry-run",
}
KINDS = {
    "test": "test",
    "build": "build",
    "check": "check",
    "lint": "lint",
    "typecheck": "typecheck",
    "vet": "check",
}
SAFE_EXECUTABLES = {
    "pytest",
    "ruff",
    "mypy",
    "tsc",
    "cargo",
    "go",
    "pnpm",
    "npm",
    "yarn",
    "bun",
    "python",
    "python3",
    "swift",
    "uv",
}


def _basename(value):
    return PurePosixPath(value).name


def _tokens(command):
    lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|<>\n")
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    return list(lexer)


def _unwrap(args):
    args = list(args)
    while args and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", args[0]):
        args.pop(0)
    if args and _basename(args[0]) == "env":
        return _unwrap(args[1:])
    if args and _basename(args[0]) == "uv" and args[1:2] == ["run"]:
        args = args[2:]
        while args and args[0].startswith("-"):
            if args[0] in ("--locked", "--frozen", "--no-sync", "--offline", "--no-project"):
                args.pop(0)
            elif args[0] in ("--project", "--directory", "--python", "--package") and len(args) > 1:
                args = args[2:]
            else:
                return []
        return _unwrap(args)
    if (
        args
        and re.fullmatch(r"python(?:\d+(?:\.\d+)?)?", _basename(args[0]))
        and args[1:2] == ["-m"]
    ):
        return args[2:]
    if args and _basename(args[0]) in ("pnpm", "npm", "yarn", "bun"):
        executable, rest = args[0], args[1:]
        while rest and rest[0].startswith("-"):
            if (
                rest[0] in ("--filter", "-F", "--dir", "-C", "--prefix", "--workspace", "-w")
                and len(rest) > 1
            ):
                rest = rest[2:]
            elif rest[0].startswith(("--filter=", "--dir=", "--prefix=")) or rest[0] in (
                "--recursive",
                "-r",
                "--silent",
            ):
                rest = rest[1:]
            else:
                return []
        if rest[:1] == ["exec"]:
            return _unwrap(rest[1:])
        if rest[:1] == ["run"]:
            rest = rest[1:]
        return [executable, *rest]
    return args


def _validation(args):
    if not args or any(a.split("=", 1)[0] in NO_EXECUTION for a in args):
        return None
    executable = _basename(args[0])
    if executable == "pytest":
        return "test"
    if executable == "ruff" and args[1:2] == ["check"]:
        return "lint"
    if executable == "mypy" or executable == "tsc" and "--noEmit" in args:
        return "typecheck"
    if executable in ("cargo", "go", "swift", "pnpm", "npm", "yarn", "bun") and len(args) > 1:
        return KINDS.get(args[1])
    return None


def command_spec(command, *, cwd=None, project_id=None):
    """Keep a complete direct check distinct from a command mention or truncated head."""
    if not isinstance(command, str) or not command.strip():
        return None
    spec = {
        "schema_version": VERSION,
        "executable": None,
        "subcommand": None,
        "cwd": cwd,
        "argv_digest": uid("argv", command),
        "command_complete": False,
        "validation_kind": None,
        "validation_target": None,
        "validation_scope": {"project_id": project_id, "coverage": "unspecified"},
        "identification_source": "complete_command_input",
        "missing_reason": None,
    }
    if "$(" in command or "`" in command or "${" in command:
        spec["missing_reason"] = "shell_expansion"
        return spec
    try:
        args = _tokens(command)
        # Native command items sometimes contain the shell argv rather than its
        # inner script. Preserve the argv quoting before peeling the shell once.
        if (
            len(args) == 3
            and _basename(args[0]) in ("sh", "bash", "zsh")
            and args[1] in ("-c", "-lc", "-ic")
        ):
            args = _tokens(args[2])
    except ValueError:
        spec["missing_reason"] = "malformed_command"
        return spec
    segments, current = [], []
    for index, token in enumerate(args):
        if token in ("&&", ";", "\n"):
            if current:
                segments.append(current)
                current = []
            elif token != "\n":
                spec["missing_reason"] = "malformed_command"
                return spec
            if index == len(args) - 1 and token == "&&":
                spec["missing_reason"] = "malformed_command"
                return spec
        elif token in ("&", "||", "|", "|&") or any(c in token for c in ("<", ">")):
            spec["missing_reason"] = "compound_or_redirected_command"
            return spec
        else:
            current.append(token)
    if current:
        segments.append(current)
    if not segments:
        spec["missing_reason"] = "empty_command"
        return spec
    # cd must be guarded by &&: with ';', a failed directory change could run a
    # check in the wrong project. Do not manufacture a validation scope.
    if (
        len(segments) == 2
        and segments[0][:1] == ["cd"]
        and len(segments[0]) == 2
        and ";" not in args
        and "\n" not in args
    ):
        directory = segments[0][1]
        spec["cwd"] = str(PurePosixPath(cwd or ".") / directory)
        segments = segments[1:]
    if len(segments) != 1:
        spec["missing_reason"] = "multiple_commands"
        return spec
    normalized = _unwrap(segments[0])
    if not normalized or normalized[0].startswith("$"):
        spec["missing_reason"] = "unresolved_executable"
        return spec
    executable = _basename(normalized[0])
    subcommand = normalized[1] if len(normalized) > 1 and normalized[1] in KINDS else None
    spec.update(
        executable=executable if executable in SAFE_EXECUTABLES else "other",
        subcommand=subcommand,
        command_complete=True,
        validation_kind=_validation(normalized),
        validation_target={
            "argv_digest": uid("validation_target", normalized[1:]),
            "scope": "command_arguments",
        },
    )
    if spec["validation_kind"] is None:
        spec["missing_reason"] = "not_an_executed_validation_command"
    return spec
