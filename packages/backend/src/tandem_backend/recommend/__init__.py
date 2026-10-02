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
    from .outcomes import mark_reverted as _mark

    return _mark(*args, **kwargs)


__all__ = ["mark_reverted", "recommend", "register_tracking", "run", "trial_method"]
