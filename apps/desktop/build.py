"""Build Orbit.app: native Swift host + frozen tandem-helper gateway + single-file Advance UI.

Usage (from the repository root, after ``bash scripts/bootstrap.sh``):

    uv run python apps/desktop/build.py            # full build -> .local/macos-build/
    uv run python apps/desktop/build.py --skip-helper   # reuse the last PyInstaller output

Outputs in ``.local/macos-build/``: ``Orbit.app``, ``Orbit-0.0.2-arm64.zip`` and
``Orbit-0.0.2-arm64.dmg``. Signing is ad-hoc unless ``TANDEM_SIGN_IDENTITY`` names a
Developer ID identity; ``TANDEM_NOTARY_PROFILE`` additionally notarizes and staples.
"""

from __future__ import annotations

import argparse
import os
import plistlib
import re
import shutil
import struct
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = ROOT / "apps/desktop"
OUTPUT = ROOT / ".local/macos-build"
NAME = "Orbit"
VERSION = "0.0.2"
BUILD = "2"
BUNDLE_ID = "ai.actionmesh.orbit"
MIN_MACOS = "14.0"  # swiftc target, LSMinimumSystemVersion and the ceiling for bundled Mach-O minos
APP = OUTPUT / f"{NAME}.app"
ARTIFACT = f"{NAME}-{VERSION}-arm64"
LOGO = ROOT / "docs/design/logo"
PYINSTALLER = "pyinstaller==6.22.3"

COLLECT_ALL = ["tandem_backend", "tandem_data", "tandem_catalog", "jieba"]
COLLECT_DATA = ["jsonschema_specifications"]
COPY_METADATA = ["tandem-backend", "tandem-data", "tandem-catalog", "scikit-learn", "numpy",
                 "scipy", "jieba", "fastapi", "pydantic", "uvicorn", "jsonschema"]
HIDDEN_IMPORTS = ["uvicorn.logging", "uvicorn.loops", "uvicorn.loops.auto", "uvicorn.protocols",
                  "uvicorn.protocols.http", "uvicorn.protocols.http.auto",
                  "uvicorn.protocols.http.h11_impl", "uvicorn.protocols.websockets",
                  "uvicorn.protocols.websockets.auto", "uvicorn.lifespan", "uvicorn.lifespan.on",
                  "tandem_backend.services.worker_ingest", "tandem_backend.services.worker_analysis",
                  "tandem_backend.services.gateway", "tandem_backend.api.routes"]
EXCLUDES = ["tkinter", "matplotlib", "IPython", "pytest", "onnxruntime", "tokenizers", "torch"]


def run(*args, **kwargs):
    print("+", " ".join(map(str, args)), flush=True)
    subprocess.run(list(map(str, args)), cwd=ROOT, check=True, **kwargs)


def build_ui(resources: Path) -> None:
    """Single-file Advance UI (Lite is a sidebar switch inside it). The page uses only macOS
    system fonts (SF Pro / PingFang SC / SF Mono), so nothing is inlined and it works offline."""
    target = resources / "orbit.html"
    run("node", "prototypes/advance/build.mjs", "--out", target)
    if "fonts.googleapis" in target.read_text(encoding="utf-8"):
        raise SystemExit("orbit.html: unexpected remote font link")


def build_helper() -> Path:
    args = ["uv", "run", "--with", PYINSTALLER, "pyinstaller", "--noconfirm", "--clean",
            "--name", "tandem-helper", "--onedir", "--console",
            "--distpath", OUTPUT / "dist", "--workpath", OUTPUT / "work", "--specpath", OUTPUT,
            "--target-arch", "arm64", "--osx-bundle-identifier", f"{BUNDLE_ID}.helper"]
    for name in COLLECT_ALL:
        args += ["--collect-all", name]
    for name in COLLECT_DATA:
        args += ["--collect-data", name]
    for name in COPY_METADATA:
        args += ["--copy-metadata", name]
    for name in HIDDEN_IMPORTS:
        args += ["--hidden-import", name]
    for name in EXCLUDES:
        args += ["--exclude-module", name]
    run(*args, HERE / "server_entry.py")
    return OUTPUT / "dist/tandem-helper"


def build_host(contents: Path) -> None:
    run("xcrun", "swiftc", "-O", "-target", f"arm64-apple-macos{MIN_MACOS}", "-framework", "AppKit",
        "-framework", "WebKit", "-framework", "Security", "-framework", "UserNotifications", HERE / "Orbit.swift",
        "-o", contents / f"MacOS/{NAME}")


def build_icon(resources: Path) -> None:
    """Orbit.icns from the published artwork, rendered verbatim (never redrawn)."""
    work = OUTPUT / "icon"
    shutil.rmtree(work, ignore_errors=True)
    iconset = work / "Orbit.iconset"
    iconset.mkdir(parents=True)
    renderer = work / "render_svg"
    run("xcrun", "swiftc", "-O", HERE / "render_svg.swift", "-o", renderer)
    # Every size is orbit-icon.svg scaled as a whole, so the mark stays proportional to the 1024 icon.
    for points in (16, 32, 128, 256, 512):
        for scale in (1, 2):
            px = points * scale
            name = f"icon_{points}x{points}{'@2x' if scale == 2 else ''}.png"
            target = iconset / name
            if px == 1024:
                shutil.copy2(LOGO / "orbit-icon.png", target)
            else:
                run(renderer, LOGO / "orbit-icon.svg", target, px)
    run("iconutil", "-c", "icns", iconset, "-o", resources / f"{NAME}.icns")
    # Menu-bar status item: orbit-mark.svg rendered verbatim at its own aspect ratio
    # (used as a template image, so only its alpha matters). 16 pt tall, @1x and @2x.
    box = re.search(r'viewBox="[\d.]+ [\d.]+ ([\d.]+) ([\d.]+)"',
                    (LOGO / "orbit-mark.svg").read_text()).groups()
    width = round(16 * float(box[0]) / float(box[1]))
    for scale, suffix in ((1, ""), (2, "@2x")):
        run(renderer, LOGO / "orbit-mark.svg", resources / f"StatusIcon{suffix}.png",
            width * scale, 16 * scale)


def write_plist(contents: Path) -> None:
    with (contents / "Info.plist").open("wb") as handle:
        plistlib.dump({
            "CFBundleName": NAME,
            "CFBundleDisplayName": NAME,
            "CFBundleIdentifier": BUNDLE_ID,
            "CFBundleExecutable": NAME,
            "CFBundleIconFile": NAME,
            "CFBundlePackageType": "APPL",
            "CFBundleShortVersionString": VERSION,
            "CFBundleVersion": BUILD,
            "CFBundleDevelopmentRegion": "zh_CN",
            "LSMinimumSystemVersion": MIN_MACOS,
            "LSApplicationCategoryType": "public.app-category.developer-tools",
            "NSHighResolutionCapable": True,
            "NSHumanReadableCopyright": "ActionMesh AI",
            "NSAppTransportSecurity": {"NSAllowsLocalNetworking": True},
        }, handle)


def _macho_minos(data: bytes) -> list[tuple[int, int]]:
    """macOS minimum versions declared by a thin or fat Mach-O image (empty if not Mach-O)."""
    if data[:4] in (b"\xca\xfe\xba\xbe", b"\xca\xfe\xba\xbf"):
        wide = data[3] == 0xbf
        count = struct.unpack_from(">I", data, 4)[0]
        if count > 32:  # Java class files share the 0xcafebabe magic
            return []
        found = []
        for index in range(count):
            if wide:
                offset, size = struct.unpack_from(">QQ", data, 8 + index * 32 + 8)
            else:
                offset, size = struct.unpack_from(">II", data, 8 + index * 20 + 8)
            found += _macho_minos(data[offset:offset + size])
        return found
    if data[:4] not in (b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe"):
        return []
    ncmds = struct.unpack_from("<I", data, 16)[0]
    cursor = 32 if data[0] == 0xcf else 28
    found = []
    for _ in range(ncmds):
        cmd, size = struct.unpack_from("<II", data, cursor)
        if cmd == 0x32 and struct.unpack_from("<I", data, cursor + 8)[0] == 1:  # LC_BUILD_VERSION, macOS
            version = struct.unpack_from("<I", data, cursor + 12)[0]
        elif cmd == 0x24:  # LC_VERSION_MIN_MACOSX
            version = struct.unpack_from("<I", data, cursor + 8)[0]
        else:
            cursor += size
            continue
        found.append((version >> 16, (version >> 8) & 0xFF))
        cursor += size
    return found


def check_minos(bundle: Path) -> None:
    """Fail the build if any bundled binary needs a newer macOS than MIN_MACOS.

    The helper's floor comes from third-party wheels (numpy/scipy ship 14.0 today), so a
    dependency bump can silently drop older systems; this keeps that visible.
    """
    limit = tuple(map(int, MIN_MACOS.split(".")))
    offenders, scanned = [], 0
    for path in sorted(bundle.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        with path.open("rb") as handle:
            if handle.read(4) not in (b"\xca\xfe\xba\xbe", b"\xca\xfe\xba\xbf",
                                      b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe"):
                continue
        versions = _macho_minos(path.read_bytes())
        scanned += bool(versions)
        newest = max(versions, default=(0, 0))
        if newest > limit:
            offenders.append(f"  {newest[0]}.{newest[1]}  {path.relative_to(bundle)}")
    if offenders:
        raise SystemExit(f"binaries require macOS newer than {MIN_MACOS}:\n" + "\n".join(offenders))
    print(f"minos check: {scanned} Mach-O files <= macOS {MIN_MACOS}", flush=True)


def sign(identity: str) -> None:
    flags = [] if identity == "-" else ["--options", "runtime", "--timestamp"]
    run("codesign", "--force", "--deep", "--sign", identity, *flags, APP)
    run("codesign", "--verify", "--deep", "--strict", "--verbose=2", APP)


def package() -> None:
    archive = OUTPUT / f"{ARTIFACT}.zip"
    archive.unlink(missing_ok=True)
    run("ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", APP, archive)
    dmg = OUTPUT / f"{ARTIFACT}.dmg"
    dmg.unlink(missing_ok=True)
    with tempfile.TemporaryDirectory(dir=OUTPUT) as stage:
        run("ditto", APP, Path(stage) / APP.name)
        os.symlink("/Applications", Path(stage) / "Applications")
        run("hdiutil", "create", "-volname", NAME, "-srcfolder", stage, "-ov", "-format", "UDZO", dmg)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--skip-helper", action="store_true", help="reuse .local/macos-build/dist")
    args = parser.parse_args()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    helper = OUTPUT / "dist/tandem-helper" if args.skip_helper else build_helper()
    if not (helper / "tandem-helper").exists():
        raise SystemExit(f"missing helper build at {helper}")
    shutil.rmtree(APP, ignore_errors=True)
    contents = APP / "Contents"
    (contents / "MacOS").mkdir(parents=True)
    resources = contents / "Resources"
    resources.mkdir()
    shutil.copytree(helper, resources / "backend", symlinks=True)
    build_ui(resources)
    build_icon(resources)
    build_host(contents)
    write_plist(contents)
    check_minos(APP)
    identity = os.environ.get("TANDEM_SIGN_IDENTITY", "-")
    sign(identity)
    profile = os.environ.get("TANDEM_NOTARY_PROFILE")
    if profile and identity != "-":
        notarize = OUTPUT / f"{ARTIFACT}-notarize.zip"
        run("ditto", "-c", "-k", "--keepParent", APP, notarize)
        run("xcrun", "notarytool", "submit", notarize, "--keychain-profile", profile, "--wait")
        run("xcrun", "stapler", "staple", APP)
    package()
    print(APP)


if __name__ == "__main__":
    main()
