"""Desktop helper entry point. One loopback socket and one private application home."""

import argparse
import json
import os
import socket
import threading
from pathlib import Path

import uvicorn
from tandem_data.paths import default_home

from tandem_backend.app_api import create_desktop_app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--home", type=Path, default=default_home())
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()
    token = os.environ.get("TANDEM_API_TOKEN", "")
    app = create_desktop_app(args.home, token, args.assets)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", args.port))
        listener.set_inheritable(True)
        listener.listen(128)
        print(json.dumps({"port": listener.getsockname()[1]}), flush=True)
        config = uvicorn.Config(
            app, log_level="warning", access_log=False, timeout_graceful_shutdown=30
        )
        server = uvicorn.Server(config)
        parent = int(os.environ.get("TANDEM_PARENT_PID", "0"))
        stopped = threading.Event()

        def watch_parent():
            while not stopped.wait(1):
                if os.getppid() != parent:
                    server.should_exit = True
                    return

        if parent:
            threading.Thread(target=watch_parent, daemon=True).start()
        try:
            server.run(sockets=[listener])
        finally:
            stopped.set()


if __name__ == "__main__":
    main()
