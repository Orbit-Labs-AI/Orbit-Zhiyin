"""Verify checked-in documentation links, docs navigation and workspace ownership rules.

Only files tracked by git (``git ls-files --cached``, which includes staged new files) are
checked: untracked scratch in a working checkout (for example a local ``docs/plan`` draft) is
not part of the repository and must not fail ``pnpm check:docs``.

Checks:
- local Markdown links in tracked ``.md`` files resolve (optional source submodules exempt);
- the workspace has exactly one ``uv.lock`` and one ``pnpm-lock.yaml``;
- retired directories contain no tracked files;
- every tracked ``docs/**/*.md`` is reachable from ``docs/README.md`` through local links
  (directly or via a section README), as AGENTS.md requires new documents to be registered
  in the navigation.
"""

import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

from markdown_it import MarkdownIt

ROOT = Path(__file__).resolve().parents[1]
RETIRED = ("src", "docs/backend", "docs/plan", "docs/design/demo")
NAVIGATION = "docs/README.md"
# Tracked documents not yet linked from the navigation, with the owner follow-up. The check
# fails once one becomes reachable, so the entry is removed together with the registration.
UNREGISTERED = {
    "docs/development/mac-app.md": "development: link from docs/README.md",
    "docs/modules/data/import-performance.md": "data: link from the data module README",
    "docs/plans/ui-backend-parity.md": "plans: link from docs/README.md plans section",
}


def tracked(root: Path) -> list[str]:
    return subprocess.check_output(["git", "ls-files", "--cached"], cwd=root, text=True).splitlines()


def local_links(root: Path, name: str, parser: MarkdownIt):
    path = root / name
    for token in parser.parse(path.read_text()):
        for child in token.children or []:
            if child.type not in ("link_open", "image"):
                continue
            target = child.attrGet("href" if child.type == "link_open" else "src")
            parts = urlsplit(target)
            if parts.scheme or parts.netloc or not parts.path:
                continue
            yield target, (path.parent / unquote(parts.path)).resolve()


def navigation_reachable(root: Path, files: set[str], parser: MarkdownIt) -> set[str]:
    if NAVIGATION not in files:
        return set()
    seen, todo = {NAVIGATION}, [NAVIGATION]
    resolved_root = root.resolve()
    while todo:
        for _, destination in local_links(root, todo.pop(), parser):
            if destination.is_dir():
                destination = destination / "README.md"
            try:
                name = destination.relative_to(resolved_root).as_posix()
            except ValueError:
                continue
            if name in files and name.endswith(".md") and name not in seen:
                seen.add(name)
                todo.append(name)
    return seen


def check(root: Path = ROOT, unregistered: dict[str, str] | None = None) -> list[str]:
    unregistered = UNREGISTERED if unregistered is None else unregistered
    files = sorted(set(tracked(root)))
    errors = []
    parser = MarkdownIt()
    gitmodules = root / ".gitmodules"
    submodules = re.findall(r"^\s*path = (.+)$", gitmodules.read_text(), re.M) \
        if gitmodules.is_file() else []
    for name in files:
        if not name.endswith(".md") or not (root / name).is_file():
            continue
        for target, destination in local_links(root, name, parser):
            # Referenced source submodules are optional and never boot dependencies.
            if any(destination.is_relative_to(root / sub) for sub in submodules):
                continue
            if not destination.exists():
                errors.append(f"{name}: missing local link {target}")
    expected = {"uv.lock", "pnpm-lock.yaml"}
    locks = {p for p in files if Path(p).name in expected and (root / p).is_file()}
    if locks != expected:
        errors.append(f"workspace locks must be {sorted(expected)}, found {sorted(locks)}")
    for retired in RETIRED:
        if any(p.startswith(retired + "/") for p in files):
            errors.append(f"retired directory contains tracked files: {retired}")
    docs = {p for p in files if p.startswith("docs/") and p.endswith(".md")}
    reachable = navigation_reachable(root, set(files), parser)
    for name in sorted(docs - reachable - set(unregistered)):
        errors.append(f"{name}: not linked from {NAVIGATION} (register it in the docs navigation)")
    for name in sorted(set(unregistered) & reachable):
        errors.append(f"{name}: now registered, remove it from UNREGISTERED in check-repository.py")
    return errors


def main() -> int:
    errors = check()
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print("Documentation links, navigation and workspace ownership checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
