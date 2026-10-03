"""AI module: engines (the user's own Claude Code / Codex, optional API key), consent,
isolation, the job runner and its ledger. Other modules call ``service(gw).run(...)``;
this package never imports recommend / install / features.
"""

from .errors import AIUnavailable
from .isolation import is_orbit_ai_session
from .service import AIService, service

__all__ = ["AIService", "AIUnavailable", "auto_facet_new", "auto_overview", "is_orbit_ai_session", "service"]


def auto_facet_new(gw, limit: int = 20) -> dict:
    """Scheduler hook: queue a facet job for new sessions when the user enabled it."""
    from .auto import auto_facet_new as run

    return run(gw, limit)


def auto_overview(gw) -> dict:
    """Import hook: queue the default AI overview when the user enabled it."""
    from .auto import auto_overview as run

    return run(gw)
