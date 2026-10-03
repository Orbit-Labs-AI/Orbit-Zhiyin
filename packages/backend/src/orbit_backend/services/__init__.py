"""App service layer: one gateway process supervising ingest and analysis workers.

See docs/architecture/app-services.md. The gateway is the only entry point for the UI
(HTTP + SSE); workers talk to it over stdio JSON Lines and own all writes.
"""

CONTRACT = "orbit-app-services-v1"
