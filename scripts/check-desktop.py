"""Build fixtures, exercise the real desktop HTTP process and capture UI acceptance."""

import json
import os
import secrets
import subprocess
import sys
import tempfile
from pathlib import Path

from tandem_data.validation.fixtures import create_sources

from tandem_backend.cli import demo_home

ROOT = Path(__file__).resolve().parents[1]


def main():
    output = ROOT / ".local/desktop-checks"
    output.mkdir(parents=True, exist_ok=True)
    run = Path(tempfile.mkdtemp(prefix="run-", dir=output))
    roots = create_sources(run / "sources")
    roots["codex"] = demo_home(run / "codex")
    for path in (roots["codex"] / "sessions").glob("*.jsonl"):
        with path.open("a") as handle:
            handle.write(
                json.dumps(
                    {
                        "type": "world_state",
                        "timestamp": "2026-01-01T00:00:11Z",
                        "payload": {
                            "state": {"model": "fixture-model", "cwd": "/fictional/project"}
                        },
                    }
                )
                + "\n"
            )
    (run / "sources.json").write_text(json.dumps({k: str(v) for k, v in roots.items()}))
    env = {
        **os.environ,
        "TANDEM_API_TOKEN": secrets.token_hex(32),
        "TANDEM_TEST_SOURCES": str(run / "sources.json"),
        "TANDEM_SCREENSHOTS": str(run / "screenshots"),
    }
    subprocess.run(["node", "docs/design/demo/build.mjs"], cwd=ROOT, check=True)
    with (run / "server.log").open("w") as log:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "tandem_backend.desktop",
                "--home",
                str(run / "data"),
                "--assets",
                str(ROOT / "docs/design/demo/tandem-demo.html"),
                "--discovery-manifest",
                str(run / "sources.json"),
            ],
            cwd=ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=log,
            text=True,
        )
        try:
            port = json.loads(process.stdout.readline())["port"]
            env["TANDEM_DESKTOP_TEST_URL"] = f"http://127.0.0.1:{port}"
            subprocess.run(
                [
                    "pnpm",
                    "exec",
                    "playwright",
                    "test",
                    "tests/desktop.spec.mjs",
                    "--project=mac-14",
                    "--workers=1",
                ],
                cwd=ROOT / "docs/design/demo",
                env=env,
                check=True,
            )
        finally:
            process.terminate()
            process.wait(timeout=60)
    print(run)


if __name__ == "__main__":
    main()
