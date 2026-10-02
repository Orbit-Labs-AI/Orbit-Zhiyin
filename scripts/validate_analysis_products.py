"""Compatibility entry point; evaluation implementation lives in evals.analytics.products."""

import subprocess
import sys
from pathlib import Path

if __name__ == "__main__":
    raise SystemExit(
        subprocess.call(
            [sys.executable, "-m", "evals.analytics.products", *sys.argv[1:]],
            cwd=Path(__file__).resolve().parents[1],
        )
    )
