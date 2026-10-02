"""Verify checked-in documentation links and workspace ownership rules."""

import re
import subprocess
from pathlib import Path
from urllib.parse import unquote, urlsplit

from markdown_it import MarkdownIt

ROOT = Path(__file__).resolve().parents[1]


def check():
    files = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT, text=True,
    ).splitlines()
    errors = []
    parser = MarkdownIt()
    submodules = re.findall(r"^\s*path = (.+)$", (ROOT / ".gitmodules").read_text(), re.M)
    for name in sorted(set(files)):
        path = ROOT / name
        if not path.is_file() or path.suffix != ".md":
            continue
        for token in parser.parse(path.read_text()):
            for child in token.children or []:
                if child.type not in ("link_open", "image"):
                    continue
                target = child.attrGet("href" if child.type == "link_open" else "src")
                parts = urlsplit(target)
                if parts.scheme or parts.netloc or not parts.path:
                    continue
                destination = (path.parent / unquote(parts.path)).resolve()
                # Referenced source submodules are optional and never boot dependencies.
                if any(destination.is_relative_to(ROOT / sub) for sub in submodules):
                    continue
                if not destination.exists():
                    errors.append(f"{name}: missing local link {target}")
    expected = {"uv.lock", "pnpm-lock.yaml"}
    locks = {p for p in files if Path(p).name in expected and (ROOT / p).is_file()}
    if locks != expected:
        errors.append(f"workspace locks must be {sorted(expected)}, found {sorted(locks)}")
    for retired in ("src", "docs/backend", "docs/plan", "docs/design/demo"):
        if (ROOT / retired).exists() and any(p.is_file() for p in (ROOT / retired).rglob("*")):
            errors.append(f"retired directory contains files: {retired}")
    if errors:
        raise SystemExit("\n".join(errors))
    print("Documentation links and workspace ownership checks passed")


if __name__ == "__main__":
    check()
