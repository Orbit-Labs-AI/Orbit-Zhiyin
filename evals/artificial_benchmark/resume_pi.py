#!/usr/bin/env python3
"""Install an explicit Pi model override before exec, without altering frozen tools."""

import json
import os
import sys
from pathlib import Path


def configure(agent: Path) -> None:
    models = json.loads((agent / "models-store.json").read_text())["kimi-coding"]["models"]
    if len(models) != 1:
        raise ValueError("Resume requires exactly one model")
    model = models[0]
    if model["baseUrl"] != "https://tokendance.space/gateway/v1" \
            or model["id"] != "kimi-k3" or model["api"] != "openai-completions" \
            or model["thinkingLevelMap"]["max"] != "max":
        raise ValueError("Unexpected resume endpoint, model, or reasoning effort")
    config = {"providers": {"kimi-coding": {"baseUrl": model["baseUrl"], "api": model["api"],
                                           "models": [model]}}}
    target = agent / "models.json"
    target.write_text(json.dumps(config) + "\n")
    target.chmod(0o600)


def main() -> None:
    executable = os.environ["ORBIT_BENCH_PI_EXECUTABLE"]
    configure(Path(os.environ["PI_CODING_AGENT_DIR"]))
    os.execv(executable, [executable, *sys.argv[1:]])


if __name__ == "__main__":
    main()
