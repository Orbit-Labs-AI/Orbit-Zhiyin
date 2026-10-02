"""Recommendation pipeline; the historic profile API remains compatible.

``run`` / ``register_tracking`` / ``mark_reverted`` are lazy wrappers so importing this
package never pulls in the gateway stack.
"""

from .legacy import recommend, trial_method


def run(*args, **kwargs):
    """Reuse or build a persisted recommendation run (see ``recommend.runs.run``)."""
    from .runs import run as _run

    return _run(*args, **kwargs)


def register_tracking(*args, **kwargs):
    """Called by the install module after apply (see ``recommend.outcomes``)."""
    from .outcomes import register_tracking as _register

    return _register(*args, **kwargs)


def mark_reverted(*args, **kwargs):
    """``mark_reverted(appdb, install_id, at)``: stops tracking, records a system
    ``not_useful/reverted`` label and hides the card; install needs no separate label."""
    from .outcomes import mark_reverted as _mark

    return _mark(*args, **kwargs)


def label(appdb, candidate_id: str, value: str, reason: str | None = None, *,
          labeler: str = "system", now: int | None = None) -> str:
    """Record a candidate label from another module (e.g. install ``useful``); returns label_id."""
    import time

    from .store import add_label

    with appdb.write() as conn:
        label_id, _ = add_label(conn, "candidate", candidate_id, value, reason, labeler=labeler,
                                now=now or int(time.time() * 1000))
    return label_id


__all__ = ["label", "mark_reverted", "recommend", "register_tracking", "run", "trial_method"]
