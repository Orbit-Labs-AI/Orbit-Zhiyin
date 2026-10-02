"""Build an offline .app with a bundled Python runtime and Advance UI."""

import os
import plistlib
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / ".local/macos-build"
APP = OUTPUT / "Tandem.app"


def run(*args):
    subprocess.run(list(map(str, args)), cwd=ROOT, check=True)


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    run("node", "prototypes/advance/build.mjs")
    identity = os.environ.get("TANDEM_SIGN_IDENTITY", "-")
    run(
        "uv",
        "run",
        "--with",
        "pyinstaller==6.22.3",
        "pyinstaller",
        "--noconfirm",
        "--clean",
        "--name",
        "tandem-server",
        "--onedir",
        "--distpath",
        OUTPUT / "dist",
        "--workpath",
        OUTPUT / "work",
        "--specpath",
        OUTPUT,
        "--collect-all",
        "tandem_data",
        "--collect-all",
        "tandem_backend",
        "--collect-all",
        "tandem_catalog",
        "--copy-metadata",
        "scikit-learn",
        "--copy-metadata",
        "numpy",
        "--copy-metadata",
        "scipy",
        "--copy-metadata",
        "tandem-backend",
        "--copy-metadata",
        "tandem-data",
        "--copy-metadata",
        "tandem-catalog",
        "--copy-metadata",
        "jieba",
        "--hidden-import",
        "uvicorn.logging",
        "--hidden-import",
        "uvicorn.loops.auto",
        "--hidden-import",
        "uvicorn.protocols.http.h11_impl",
        "--hidden-import",
        "uvicorn.lifespan.on",
        *(["--codesign-identity", identity] if identity != "-" else []),
        "apps/desktop/server_entry.py",
    )
    if APP.exists():
        shutil.rmtree(APP)
    contents = APP / "Contents"
    (contents / "MacOS").mkdir(parents=True)
    resources = contents / "Resources"
    resources.mkdir()
    shutil.copytree(OUTPUT / "dist/tandem-server", resources / "backend", symlinks=True)
    shutil.copy2(ROOT / "prototypes/advance/tandem-demo.html", resources / "tandem-demo.html")
    run(
        "xcrun",
        "swiftc",
        "-O",
        "-target", "arm64-apple-macos15.0",
        "-framework",
        "AppKit",
        "-framework",
        "WebKit",
        "-framework",
        "Security",
        "apps/desktop/Tandem.swift",
        "-o",
        contents / "MacOS/Tandem",
    )
    with (contents / "Info.plist").open("wb") as handle:
        plistlib.dump(
            {
                "CFBundleName": "Tandem",
                "CFBundleDisplayName": "Tandem",
                "CFBundleIdentifier": "ai.actionmesh.tandem",
                "CFBundleExecutable": "Tandem",
                "CFBundlePackageType": "APPL",
                "CFBundleShortVersionString": "0.3.0",
                "CFBundleVersion": "1",
                "LSMinimumSystemVersion": "15.0",
                "NSHighResolutionCapable": True,
                "NSAppTransportSecurity": {"NSAllowsLocalNetworking": True},
            },
            handle,
        )
    flags = [] if identity == "-" else ["--options", "runtime", "--timestamp"]
    run("codesign", "--force", "--sign", identity, *flags, APP)
    run("codesign", "--verify", "--deep", "--strict", APP)
    archive = OUTPUT / "Tandem.zip"
    run("ditto", "-c", "-k", "--keepParent", APP, archive)
    profile = os.environ.get("TANDEM_NOTARY_PROFILE")
    if profile:
        run("xcrun", "notarytool", "submit", archive, "--keychain-profile", profile, "--wait")
        run("xcrun", "stapler", "staple", APP)
        run("ditto", "-c", "-k", "--keepParent", APP, archive)
    print(APP)


if __name__ == "__main__":
    main()
