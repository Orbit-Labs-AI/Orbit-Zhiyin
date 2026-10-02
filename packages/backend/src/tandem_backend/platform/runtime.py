"""``Platform``: the gateway's observability and maintenance hub (``gw.platform``)."""

from __future__ import annotations

import logging
import time

from . import logs, telemetry
from .collection import Collection
from .maintenance import Maintenance
from .notify import Notifier
from .revisions import EtagRules, RevisionRegistry
from .settings import PlatformSettings
from .telemetry import Telemetry

TERMINAL = frozenset({"completed", "partial", "cancelled", "failed", "interrupted"})
DATA_ROUTES = ("/v1/sessions", "/v1/projects", "/v1/sources", "/v1/inventory")


class Platform:
    def __init__(self, gw, *, maintenance_tick_s: float = 5.0):
        self.gw = gw
        self.home = gw.home
        self.appdb = gw.appdb
        self.started_at = time.time()
        self.settings = PlatformSettings(self.appdb)
        self.telemetry = Telemetry(self.appdb, self.settings)
        self.revisions = RevisionRegistry()
        self.etag_rules = EtagRules()
        self.health_cache: tuple[float, dict] | None = None
        self.appdb_check: dict | None = None
        self.slow_ms, self.slow_log = 500, True
        self.refresh()
        self.maintenance = Maintenance(self, tick_s=maintenance_tick_s)
        self.notifier = Notifier(gw)
        self.collection = Collection(gw)
        self.job_started: dict[str, float] = {}
        revisions = getattr(gw, "revisions", None)
        if revisions is not None:
            def data_rev():
                value = revisions.value  # Two dict reads; no lock needed for a cache tag.
                rev = value.get("data_rev")
                return None if rev is None else f"{rev}.{value.get('inventory_rev') or 0}"

            for prefix in DATA_ROUTES:
                self.etag_rules.add(prefix, data_rev)
        self.started = False
        self.log_handler = None
        from . import _set_platform

        _set_platform(self)

    def refresh(self) -> None:
        """Apply settings to hot-path attributes (after any settings change)."""
        cfg = self.settings.get("telemetry")
        self.telemetry.configure(cfg)
        self.slow_ms = cfg.get("slow_ms", 500)
        self.slow_log = self.settings.flag("slow_log")
        self.health_cache = None

    def start(self) -> None:
        if self.started:
            return
        self.started = True
        try:
            self.log_handler = logs.setup_logging(self.home,
                                                  json_logs=self.settings.flag("json_logs"))
        except OSError:
            pass  # Logging is best-effort; the gateway still serves.
        telemetry.install(self.telemetry)
        self.maintenance.start()
        self.notifier.start()
        logs.log_event("gateway_started", home="~")

    def close(self) -> None:
        self.maintenance.stop()
        try:
            self.telemetry.flush(force=True)
        except Exception:  # noqa: BLE001 - shutdown proceeds regardless.
            logs.log.exception("final telemetry flush failed", extra={"ev": "flush_failed"})
        self.notifier.close()
        if telemetry.active() is self.telemetry:
            telemetry.install(None)
        if self.log_handler is not None:
            logs.log_event("gateway_stopped")
            logs.teardown(self.log_handler)
            self.log_handler = None
        from . import _set_platform, get_platform

        if get_platform() is self:
            _set_platform(None)

    def observe(self, topic: str, event: str, data: dict) -> None:
        """Bus tap (worker reader threads): must stay non-blocking and never raise."""
        try:
            if topic == "job" and data.get("id"):
                status = data.get("status")
                if status == "running":
                    self.job_started.setdefault(data["id"], time.monotonic())
                elif status in TERMINAL:
                    t0 = self.job_started.pop(data["id"], None)
                    if t0 is not None:
                        telemetry.record("job.duration", (time.monotonic() - t0) * 1000,
                                         kind=data.get("kind"), status=status)
                    if status in ("failed", "interrupted"):
                        code = (data.get("error") or {}).get("code") or "unknown"
                        telemetry.record("error", 1, area="job", code=code)
            elif topic == "service" and data.get("state") == "degraded":
                logs.log_event("service_degraded", logging.WARNING, name=data.get("name"))
            self.notifier.observe(topic, event, data)
        except Exception:  # noqa: BLE001
            logs.log.exception("platform observe failed", extra={"ev": "observe_failed"})
