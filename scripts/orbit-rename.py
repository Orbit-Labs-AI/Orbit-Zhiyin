#!/usr/bin/env python3
"""Rename the old working name Tandem to Orbit in tracked paths and text (one-shot, idempotent).

main was renamed on 2026-10-03. A branch started before that runs this script at its own root, commits the
result, then merges main: the merge then only shows real conflicts instead of one per renamed identifier.

    python3 scripts/orbit-rename.py           # rename paths and rewrite text in tracked files
    python3 scripts/orbit-rename.py --check   # list what is left; exit 1 when anything is

Afterwards run ``uv lock`` and ``pnpm install --lockfile-only`` (the lock files are skipped here) and rebuild
generated files (``node prototypes/advance/build.mjs``).

Kept as written: third-party code, the lock files, GitHub permalinks to old commits, the file of another branch
named in old plans, lines about the rename itself (改名前 / 暂定名) and lines marked ``orbit-rename: keep``
(the compatibility code that still reads the legacy names).
"""

import os
import re
import subprocess
import sys
from pathlib import Path

WORDS = {"TANDEM": "ORBIT", "Tandem": "Orbit", "tandem": "orbit"}
NAME = re.compile("|".join(WORDS))
KEEP_TOKEN = re.compile(
    r"https://github\.com/\S+?/(?:blob|tree|commit)/[0-9a-f]{7,40}[^\s)\]>\"'`|]*"  # permalinks to old trees
    r"|apps/macos/Tandem\.swift"  # a file on feat/data-app-integration, cited by old plans
)
KEEP_LINE = re.compile(r"orbit-rename: keep|改名前|暂定名")
SKIP_PREFIX = ("third_party/",)
SKIP_FILE = {"uv.lock", "pnpm-lock.yaml", "scripts/orbit-rename.py"}


def tracked(root: Path) -> list[str]:
    out = subprocess.check_output(["git", "ls-files", "-z"], cwd=root)
    return [p for p in out.decode().split("\0") if p and not p.startswith(SKIP_PREFIX) and p not in SKIP_FILE]


def rename(text: str) -> str:
    return NAME.sub(lambda m: WORDS[m.group(0)], text)


def rewrite(text: str) -> str:
    lines = text.splitlines(keepends=True)
    for i, line in enumerate(lines):
        if not NAME.search(line) or KEEP_LINE.search(line):
            continue
        kept: list[str] = []

        def hold(m: re.Match) -> str:
            kept.append(m.group(0))
            return f"\0{len(kept) - 1}\0"

        line = rename(KEEP_TOKEN.sub(hold, line))
        lines[i] = re.sub("\0(\\d+)\0", lambda m: kept[int(m.group(1))], line)
    return "".join(lines)


def text_of(path: Path) -> str | None:
    if path.is_symlink() or not path.is_file():
        return None
    data = path.read_bytes()
    if b"\0" in data[:8192]:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def leftovers(root: Path) -> list[str]:
    found = []
    for name in tracked(root):
        if NAME.search(name):
            found.append(f"{name}: path")
        text = text_of(root / name)
        for no, line in enumerate((text or "").splitlines(), 1):
            if NAME.search(KEEP_TOKEN.sub("", line)) and not KEEP_LINE.search(line):
                found.append(f"{name}:{no}: {line.strip()[:160]}")
    return found


def main() -> int:
    root = Path(subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True).strip())
    if "--check" in sys.argv[1:]:
        found = leftovers(root)
        print("\n".join(found) if found else "no Tandem names left")
        return 1 if found else 0
    files = tracked(root)
    moves = {old: rename(old) for old in files if NAME.search(old)}
    clash = sorted(new for new in moves.values() if (root / new).exists() and new not in moves)
    if clash:
        print("refusing to overwrite existing paths:\n  " + "\n  ".join(clash), file=sys.stderr)
        return 2
    changed = 0
    for name in files:
        path = root / name
        text = text_of(path)
        if text is not None and (new := rewrite(text)) != text:
            path.write_text(new, encoding="utf-8")
            changed += 1
    for old, new in moves.items():
        (root / new).parent.mkdir(parents=True, exist_ok=True)
        os.rename(root / old, root / new)
    for start in range(0, len(moves), 200):
        batch = list(moves.items())[start:start + 200]
        subprocess.check_call(["git", "rm", "--cached", "-q", "--", *[old for old, _ in batch]], cwd=root)
        subprocess.check_call(["git", "add", "--", *[new for _, new in batch]], cwd=root)
    subprocess.check_call(["git", "add", "-u"], cwd=root)
    # Old package directories may only hold caches now; drop them so imports cannot find a stale tree.
    for old in sorted({str(Path(o).parent) for o in moves}, key=len, reverse=True):
        directory = root / old
        while directory != root and directory.is_dir():
            if NAME.search(str(directory.relative_to(root))):
                for cache in [c for c in directory.iterdir() if c.name == "__pycache__"]:
                    for item in cache.iterdir():
                        item.unlink()
                    cache.rmdir()
            if any(directory.iterdir()):
                break
            directory.rmdir()
            directory = directory.parent
    print(f"rewrote {changed} files, moved {len(moves)} paths; next: uv lock, pnpm install --lockfile-only, rebuild")
    return 0


if __name__ == "__main__":
    sys.exit(main())
