"""One outcome estimate for every uiview page (A1 facts rows, A3 list, A3 detail).

Agent logs carry no user verdict, so this is an *estimate* from log evidence only, and its
labels never claim the user gave up:

* ``live``  - the session is running (realtime snapshot).
* ``fail``  - shown as 「疑似中断」: the last human turn (or the session) ended with a stopped
  status (failed / error / interrupted / aborted / cancelled / rejected). This is direct log
  evidence that the final request did not finish, not a judgement of the whole session.
* ``part``  - shown as 「需返工」: the session ends in an unresolved failure streak
  (``TAIL_FAILED`` consecutive failed tool calls) or the user spent a large share of messages
  redirecting the agent (correction density, below).
* ``ok``    - the last turn / session completed or the last turn produced a final reply.
* ``None``  - no evidence either way (never guessed as ``ok``).

Correction density = lexical correction messages / human messages. User corrections are the
standard dialogue-level failure signal (Hirschberg, Litman & Swerts 2004, "Prosodic and other
cues to speech recognition failures", Speech Communication 43; Litman et al. 2006 on
correction-aware dialogue success). A raw count is length-biased (3 corrections in 200 messages
is routine steering), so the rule uses the density with a small-count floor. The two numbers
are heuristics pending calibration on labelled sessions, not fitted values:

* ``REWORK_DENSITY = 1/3``: at least one in three human messages corrects the agent.
* ``REWORK_MIN_CORR = 2``: a single lexical hit (often a false positive such as 「改成」 in a
  normal request) never decides the outcome.
* ``TAIL_FAILED = 3``: the three last tool calls all failed, matching the repeated-failure
  rule (three identical failures) used by the trajectory moments.
"""

from __future__ import annotations

from collections.abc import Sequence

STOPPED = frozenset(("failed", "error", "interrupted", "aborted", "cancelled", "rejected"))
DONE = frozenset(("completed", "success", "succeeded"))
REWORK_DENSITY = 1 / 3
REWORK_MIN_CORR = 2
TAIL_FAILED = 3
FAILED_CALL = frozenset(("failed",))
LABELS = {"ok": "完成", "part": "需返工", "fail": "疑似中断", "live": "进行中"}


def estimate(*, live: bool = False, last_turn: str | None = None,
             session_status: str | None = None, corr: int | None = None,
             msgs: int | None = None, tail: Sequence[str | None] | None = None,
             has_final: bool | None = None) -> str | None:
    """Outcome estimate; see the module docstring for the rules and their basis."""
    if live:
        return "live"
    if last_turn in STOPPED or (last_turn is None and session_status in STOPPED):
        return "fail"
    last = list(tail or [])[-TAIL_FAILED:]
    if len(last) == TAIL_FAILED and all(s in FAILED_CALL for s in last):
        return "part"
    if corr is not None and msgs and corr >= REWORK_MIN_CORR and corr / msgs >= REWORK_DENSITY:
        return "part"
    if last_turn in DONE or session_status in DONE or has_final:
        return "ok"
    return None
