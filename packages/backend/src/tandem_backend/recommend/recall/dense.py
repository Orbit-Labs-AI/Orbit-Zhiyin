"""Status of semantic (embedding) recall in the service stack: not configured.

No model is downloaded or called. The engine-v2 stack has its own lexical fallback
(``recall/hashed.py``, route ``hashed_lexical``), and real E5 vectors live in
``packages/catalog``; this module only reports that the service stack has none.
"""

FIELDS = ("task", "trigger", "capability")


def status() -> dict[str, object]:
    return {"enabled": False, "status": "disabled", "fields": list(FIELDS),
            "reason": "No embedding backend is configured; offline recall remains available."}
