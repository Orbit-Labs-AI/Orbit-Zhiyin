"""AI module: engines (the user's own Claude Code / Codex, optional API key), consent,
isolation, the job runner and its ledger. Other modules call ``service(gw).run(...)``;
this package never imports recommend / install / features.
"""

from .errors import AIUnavailable
from .isolation import is_tandem_ai_session
from .service import AIService, service

__all__ = ["AIService", "AIUnavailable", "is_tandem_ai_session", "service"]
