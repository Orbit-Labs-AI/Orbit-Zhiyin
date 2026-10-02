"""Effective program heads of shell command lines.

``command_head`` is a feature/vocabulary key, so it must name the program that did the work:
``cd /repo && git status`` is ``git status``, ``/bin/zsh -lc 'pytest -q'`` is ``pytest`` and
``S=/tmp/x; ls $S`` is ``ls``. Heads never contain assignments, absolute paths or arguments
other than a recognised subcommand word.
"""

from __future__ import annotations

import re
import shlex

SHELLS = frozenset({"sh", "bash", "zsh", "dash", "ksh", "fish", "pwsh", "powershell"})
# Segments that only change shell state; the next segment holds the real program.
STATE_ONLY = frozenset(
    {
        "cd",
        "pushd",
        "popd",
        "export",
        "set",
        "unset",
        "source",
        ".",
        "alias",
        "shopt",
        "ulimit",
        "umask",
        "trap",
        "local",
        "declare",
        "typeset",
        "readonly",
        "true",
        ":",
        "wait",
    }
)
# Wrappers whose first non-option argument is the real program.
PREFIXES = frozenset(
    {
        "env",
        "sudo",
        "time",
        "nohup",
        "exec",
        "command",
        "builtin",
        "nice",
        "timeout",
        "stdbuf",
        "caffeinate",
        "xargs",
    }
)
# Shell grammar words: either a segment header to drop or a keyword in front of a command.
HEADERS = frozenset(
    {"for", "while", "until", "case", "select", "function", "esac", "done", "fi", "}", ")", "in"}
)
LEADERS = frozenset({"do", "then", "else", "elif", "if", "!", "{", "(", "time"})
SUBCOMMANDS = frozenset(
    {
        "git",
        "uv",
        "pnpm",
        "npm",
        "yarn",
        "docker",
        "cargo",
        "go",
        "gh",
        "kubectl",
        "brew",
        "pip",
        "pip3",
        "bun",
        "deno",
        "make",
        "swift",
        "xcodebuild",
        "poetry",
        "dotnet",
        "tandem",
    }
)
SEPARATORS = frozenset({"&&", "||", ";", "|", "&", "|&", ";;", "(", ")", "\n"})
_ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(\[[^\]]*\])?\+?=")
_WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]*")
_SUBWORD = re.compile(r"[a-z][a-z0-9:_-]*")
# Options that take a separate value for programs with subcommands (git -C <dir> status).
_VALUE_OPTIONS = {
    "git": {"-C", "-c", "--git-dir", "--work-tree", "--namespace"},
    "uv": {"--directory", "--project", "--python", "-p"},
    "pnpm": {"-C", "--dir", "--filter", "-F"},
    "npm": {"--prefix", "-w"},
    "docker": {"-H", "--context", "-c"},
    "cargo": {"-C", "--manifest-path"},
    "make": {"-C", "-f"},
    "gh": {"-R", "--repo"},
}


def _tokens(command: str) -> list[str]:
    lexer = shlex.shlex(command.replace("\r", "\n"), posix=True, punctuation_chars=";&|()")
    lexer.whitespace = " \t"
    lexer.whitespace_split = True
    lexer.commenters = ""
    tokens = []
    for token in lexer:
        if "\n" in token:
            parts = token.split("\n")
            for index, part in enumerate(parts):
                if index:
                    tokens.append("\n")
                if part:
                    tokens.append(part)
        else:
            tokens.append(token)
    return tokens


def _segments(tokens):
    segment = []
    for token in tokens:
        if token in SEPARATORS:
            if segment:
                yield segment
            segment = []
        else:
            segment.append(token)
    if segment:
        yield segment


def _program(word: str) -> str | None:
    """Basename of an executable word, or None when it is not a literal program name."""
    if not word or word[0] in "$`'\"<>" or "=" in word:
        return None
    base = word.rstrip("/").rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    return base if _WORD.fullmatch(base) else None


def _segment_head(words, depth, joined=True):
    index = 0
    while index < len(words) and (words[index] in LEADERS or _ASSIGNMENT.match(words[index])):
        index += 1
    while index < len(words):
        word = words[index]
        name = _program(word)
        if name is None:
            if _ASSIGNMENT.match(word):
                index += 1
                continue
            return None
        if name in HEADERS or name in STATE_ONLY:
            return None
        if name in PREFIXES:
            index += 1
            # Options and their values (timeout 30s, env -u VAR) and assignments.
            while index < len(words) and (
                words[index].startswith("-")
                or _ASSIGNMENT.match(words[index])
                or (name in ("timeout", "nice") and words[index][:1].isdigit())
            ):
                if words[index] in ("-u", "-n", "-s", "-k", "-C", "-g") and name != "xargs":
                    index += 1
                index += 1
            continue
        if name in SHELLS:
            payload = _shell_payload(words[index + 1 :], joined)
            if payload is not None:
                return command_head(payload, depth + 1) if depth < 3 else None
            # A shell running a script file: report the script.
            rest = [w for w in words[index + 1 :] if not w.startswith("-")]
            return (_program(rest[0]) if rest else None) or name
        return _with_subcommand(name, words[index + 1 :])
    return None


def _shell_payload(arguments, joined=False):
    """The -c script. ``joined``: a display string whose argv was joined without quoting
    (Codex writes ``/bin/zsh -lc git status --short``), so the script is all remaining words."""
    for position, word in enumerate(arguments):
        if (word.startswith("-") and not word.startswith("--") and "c" in word[1:]) or word in (
            "-Command",
            "-command",
        ):
            rest = arguments[position + 1 :]
            if not rest:
                return None
            return shlex.join(rest) if joined and len(rest) > 1 else rest[0]
        if not word.startswith("-"):
            return None
    return None


def _with_subcommand(name, rest):
    if name not in SUBCOMMANDS:
        return name
    takes_value = _VALUE_OPTIONS.get(name, set())
    index = 0
    while index < len(rest) and rest[index].startswith("-"):
        index += 2 if rest[index] in takes_value else 1
    if index < len(rest) and _SUBWORD.fullmatch(rest[index]) and len(rest[index]) <= 40:
        return name + " " + rest[index]
    return name


def command_head(command, depth: int = 0) -> str | None:
    """First effective program of a shell command (str or argv list); never a path."""
    if isinstance(command, list):
        if not command or not all(isinstance(word, str) for word in command):
            return None
        words = command
        if _program(words[0]) in SHELLS:
            payload = _shell_payload(words[1:])
            if payload is not None:
                return command_head(payload, depth + 1) if depth < 3 else None
        return _segment_head(words, depth, joined=False)
    if not isinstance(command, str) or not command.strip():
        return None
    try:
        tokens = _tokens(command)
    except ValueError:
        # Unbalanced quotes or heredocs: fall back to whitespace words of the first line.
        tokens = command.strip().split("\n", 1)[0].split()
    for segment in _segments(tokens):
        head = _segment_head(segment, depth)
        if head:
            return head
    return None
