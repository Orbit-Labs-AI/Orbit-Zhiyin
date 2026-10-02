"""DT-13 shared feature vocabulary: one ``ns:value`` id space for users and catalog items.

User side starts from ``tandem.db`` ``session_feature`` / ``tool_call``; item side from
``catalog.db`` ``item_feature``. Both map here so overlap is a plain id intersection, and
``to_catalog_pairs`` turns a user id back into ``item_feature`` conditions (items are
never materialized). The command table is shared by AN-05.2 / RC-06 / AI-07.2.
"""

from __future__ import annotations

import fnmatch
import re
from pathlib import PurePosixPath

VOCAB_VERSION = "vocab-1"

NAMESPACES = {
    "tool": "工具类别", "cmd": "命令", "cmdfam": "命令族", "cmdcls": "命令风险",
    "lang": "语言", "fw": "框架", "ftype": "文件类型", "mcp": "MCP 服务",
    "skill": "Skill", "err": "错误类别", "friction": "摩擦", "domain": "领域",
    "sw": "软件", "agent": "Agent", "hook": "Hook",
}

TWO_WORD_HEADS = ("git", "uv", "pnpm", "npm", "docker", "cargo", "gh", "kubectl")

# head -> (family, cls); two-word heads take precedence over the first word.
COMMANDS: dict[str, tuple[str, str]] = {
    **{h: ("fs", "readonly") for h in (
        "ls", "cat", "find", "pwd", "head", "tail", "wc", "which", "tree", "stat", "file",
        "du", "df")},
    **{h: ("fs", "readonly") for h in ("rg", "grep")},
    **{h: ("runtime", "readonly") for h in ("echo", "date", "uname")},
    **{f"git {s}": ("vcs", "readonly") for s in ("status", "diff", "log", "show", "branch")},
    **{f"git {s}": ("vcs", "write") for s in (
        "commit", "add", "checkout", "merge", "rebase", "switch", "stash", "fetch", "pull",
        "worktree", "restore", "tag", "clone")},
    **{f"git {s}": ("vcs", "destructive") for s in ("push", "reset", "clean")},
    "git": ("vcs", "write"),
    "gh": ("vcs", "network"),
    **{h: ("fs", "destructive") for h in ("rm", "rmdir", "dd", "mkfs", "chmod", "chown")},
    "sudo": ("runtime", "destructive"), "kill": ("runtime", "destructive"),
    **{h: ("fs", "write") for h in ("mv", "cp", "mkdir", "touch", "ln", "sed", "tee")},
    **{h: ("net", "network") for h in ("curl", "wget", "ssh", "scp")},
    "docker rm": ("infra", "destructive"), "docker system": ("infra", "destructive"),
    "docker": ("infra", "write"), "kubectl": ("infra", "write"),
    "terraform": ("infra", "write"), "wrangler": ("infra", "write"),
    "npm publish": ("pkg", "destructive"), "pnpm publish": ("pkg", "destructive"),
    **{h: ("pkg", "write") for h in (
        "uv sync", "uv add", "uv pip", "uv lock", "pnpm install", "pnpm add", "npm install",
        "npm i", "pip", "pip3", "brew", "cargo add", "uv", "pnpm", "npm", "yarn", "bun")},
    **{h: ("test", "write") for h in (
        "pytest", "uv run", "pnpm test", "npm test", "cargo test", "jest", "vitest")},
    **{h: ("build", "write") for h in (
        "make", "pnpm build", "npm run", "pnpm run", "cargo build", "cargo", "swift",
        "xcodebuild", "tsc", "go")},
    **{h: ("runtime", "write") for h in ("python", "python3", "node", "deno", "bash", "sh",
                                         "zsh", "npx", "pnpx")},
    **{h: ("editor", "write") for h in ("code", "vim", "nvim", "open")},
}

EXT_LANGUAGE = {
    ".py": "python", ".ts": "typescript", ".tsx": "typescript", ".js": "javascript",
    ".jsx": "javascript", ".swift": "swift", ".rs": "rust", ".go": "go", ".java": "java",
    ".kt": "kotlin", ".rb": "ruby", ".sh": "shell", ".md": "markdown", ".sql": "sql",
    ".json": "json", ".yaml": "yaml", ".yml": "yaml",
}

PATH_MARKERS = {
    "Package.swift": ("fw:swiftpm",), "pyproject.toml": ("lang:python",),
    "next.config.*": ("fw:nextjs",), "vite.config.*": ("fw:vite",),
    "Cargo.toml": ("lang:rust",), "go.mod": ("lang:go",), "Dockerfile": ("sw:docker",),
    "tsconfig.json": ("lang:typescript",), "*.xcodeproj": ("fw:xcode",),
}

FRICTION = {
    "friction:tool_error": ("工具出错", "tool_call.status 为 error/failed 或 exit_code 非 0"),
    "friction:retry_same_call": ("失败后重试", "同会话同工具同命令头，前一次失败且本次仍失败"),
    "friction:approval_wait": ("等待授权", "approval_wait_ms > 0"),
    "friction:readonly_prompted": ("只读命令被询问", "只读命令仍产生授权等待"),
    "friction:destructive_cmd": ("破坏性命令", "命令头属于 destructive 类"),
    "friction:long_tool_wait": ("长时间工具等待", "单次工具调用 duration_ms > 60000"),
}

BROWSER_MCP = re.compile(r"playwright|puppeteer|chrome-devtools|browser")

# catalog item_feature.feature -> namespace (file_type/command handled specially)
CATALOG_NS = {"domain": "domain", "software": "sw", "tool_kind": "tool", "agent": "agent",
              "language": "lang", "framework": "fw", "mcp_server": "mcp",
              "error_class": "err", "friction": "friction"}
NS_CATALOG = {ns: feature for feature, ns in CATALOG_NS.items()}


def norm(value: str) -> str:
    return re.sub(r"\s+", "-", str(value).strip().lower())


def split(fid: str) -> tuple[str, str]:
    ns, _, value = fid.partition(":")
    return ns, value


def command_info(head: str | None) -> dict:
    words = (head or "").strip().split()
    if not words:
        return {"head": "", "family": "other", "cls": "unknown"}
    first = PurePosixPath(words[0]).name
    two = f"{first} {words[1]}" if len(words) > 1 and first in TWO_WORD_HEADS else None
    key = two if two in COMMANDS else first
    family, cls = COMMANDS.get(key, ("other", "unknown"))
    return {"head": two or first, "family": family, "cls": cls}


def _command_ids(head: str) -> list[str]:
    info = command_info(head)
    if not info["head"]:
        return []
    return [f"cmd:{info['head']}", f"cmdfam:{info['family']}", f"cmdcls:{info['cls']}"]


def _ext_ids(ext: str) -> list[str]:
    ext = ext.lower() if ext.startswith(".") else "." + ext.lower()
    out = [f"ftype:{ext}"]
    if ext in EXT_LANGUAGE:
        out.append(f"lang:{EXT_LANGUAGE[ext]}")
    return out


def path_markers(path: str) -> list[str]:
    name = PurePosixPath(path).name
    hits: list[str] = []
    for part in PurePosixPath(path).parts:
        if part.endswith(".xcodeproj"):
            hits.append("fw:xcode")
    for pattern, fids in PATH_MARKERS.items():
        if fnmatch.fnmatchcase(name, pattern):
            hits.extend(fids)
    return list(dict.fromkeys(hits))


def from_session_feature(feature: str, value: str) -> list[str]:
    if feature == "tool_category":
        return [f"tool:{norm(value)}"]
    if feature == "mcp_server":
        out = [f"mcp:{norm(value)}"]
        if BROWSER_MCP.search(value.lower()):
            out.append("tool:browser")
        return out
    if feature == "skill":
        return [f"skill:{norm(value)}"]
    if feature == "command_head":
        return _command_ids(value)
    if feature == "file_extension":
        return _ext_ids(value)
    return []


def from_catalog_feature(feature: str, value: str) -> list[str]:
    if feature == "command":
        return _command_ids(value.split()[0] if value.split() else value)
    if feature == "file_type":
        return _ext_ids(value)
    ns = CATALOG_NS.get(feature)
    if ns is None:
        return []
    if ns == "mcp":
        return from_session_feature("mcp_server", value)
    return [f"{ns}:{norm(value)}"]


def to_catalog_pairs(fid: str) -> list[tuple[str, str]]:
    """Reverse of ``from_catalog_feature``: ``item_feature`` (feature, value) conditions."""
    ns, value = split(fid)
    if ns == "cmd":
        return [("command", value.split()[0])] if value else []
    if ns == "ftype":
        return [("file_type", value)]
    if ns == "lang":
        exts = sorted(e for e, lang in EXT_LANGUAGE.items() if lang == value)
        return [("language", value), *(("file_type", e) for e in exts)]
    if ns == "tool" and value == "browser":
        return [("tool_kind", "browser")]
    feature = NS_CATALOG.get(ns)
    return [(feature, value)] if feature else []


def label(fid: str) -> str:
    if fid in FRICTION:
        return FRICTION[fid][0]
    return split(fid)[1]


def vocab_table() -> dict:
    values: dict[str, set[str]] = {ns: set() for ns in NAMESPACES}
    for head, (family, cls) in COMMANDS.items():
        values["cmd"].add(head)
        values["cmdfam"].add(family)
        values["cmdcls"].add(cls)
    for ext, lang in EXT_LANGUAGE.items():
        values["ftype"].add(ext)
        values["lang"].add(lang)
    for fids in PATH_MARKERS.values():
        for fid in fids:
            ns, value = split(fid)
            values[ns].add(value)
    values["friction"].update(split(f)[1] for f in FRICTION)
    values["tool"].add("browser")
    return {
        "version": VOCAB_VERSION,
        "namespaces": {ns: {"label": lbl, "values": sorted(values[ns])}
                       for ns, lbl in NAMESPACES.items()},
        "commands": [{"head": h, "family": f, "cls": c} for h, (f, c) in sorted(COMMANDS.items())],
        "ext_language": dict(EXT_LANGUAGE),
        "friction": [{"id": fid, "label": lbl, "definition": d}
                     for fid, (lbl, d) in FRICTION.items()],
    }
