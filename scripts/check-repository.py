"""Verify checked-in documentation links and workspace ownership rules."""

import json
import re
import struct
import subprocess
import sys
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
    errors += check_logo()
    if errors:
        raise SystemExit("\n".join(errors))
    print("Documentation links and workspace ownership checks passed")


def check_logo():
    """Logo vectors must match orbit-spec.json; every raster in the kit manifest must exist at its size."""
    logo = ROOT / "docs/design/logo"
    run = subprocess.run([sys.executable, logo / "generate.py", "--check"], cwd=ROOT, capture_output=True, text=True)
    errors = [] if run.returncode == 0 else [f"logo: {(run.stderr or run.stdout).strip()}"]
    for item in json.loads((logo / "kit/manifest.json").read_text())["files"]:
        path = logo / "kit" / item["file"]
        if not path.is_file():
            errors.append(f"logo kit: missing {item['file']} (run node docs/design/logo/export.mjs)")
        elif path.suffix == ".png" and struct.unpack(">II", path.read_bytes()[16:24]) != (item["width"], item["height"]):
            errors.append(f"logo kit: {item['file']} is not {item['width']}x{item['height']}")
    return errors


if __name__ == "__main__":
    check()
