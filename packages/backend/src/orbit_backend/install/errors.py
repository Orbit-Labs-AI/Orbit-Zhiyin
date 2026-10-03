"""Install errors. Routes map ``.code`` / ``.http`` / ``.detail`` straight to the response."""

from __future__ import annotations


class InstallError(Exception):
    code: str = "install_error"
    http: int = 400

    def __init__(self, code: str | None = None, message: str | None = None, *,
                 detail: dict | None = None, http: int | None = None) -> None:
        if code:
            self.code = code
        if http is not None:
            self.http = http
        self.detail = detail
        super().__init__(message or self.code)


class OpConflict(InstallError):
    """A format operation cannot merge cleanly (409)."""

    code = "op_conflict"
    http = 409


class StaleError(InstallError):
    """Target files changed since the preview; ``detail={'targets': [idx, ...]}``."""

    code = "preview_stale"
    http = 409


class RiskBlocked(InstallError):
    code = "risk_blocked"
    http = 403


class ApplyFailed(InstallError):
    """Writing failed; ``detail`` carries ``failed_idx`` and ``rolled_back``."""

    code = "apply_failed"
    http = 500


class PlanError(InstallError):
    code = "plan_error"
    http = 422
