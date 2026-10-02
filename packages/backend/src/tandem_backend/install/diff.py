"""Line diffs for install previews, in the row model of the UI (``51-install.js``).

Each row is ``{'n', 'op', 'text'}``: ``op`` is ``'+'`` (added), ``'-'`` (removed),
``' '`` (context) or ``'ai'`` (added line that came from an AI slot). ``n`` is the 1-based
line number in *after*; removed lines have ``n=None`` (they do not exist after the write).
With a finite ``context`` a skipped stretch is marked by one ``{'op': ' ', 'gap': True}``
row whose text is ``'…'``.
"""

from __future__ import annotations

from difflib import SequenceMatcher


def _rows(a: list[str], b: list[str], context: int | None, ai: set[int]) -> list[dict]:
    sm = SequenceMatcher(None, a, b, autojunk=False)
    groups = [sm.get_opcodes()] if context is None else list(sm.get_grouped_opcodes(context))
    rows: list[dict] = []
    for gi, group in enumerate(groups):
        if gi or (group and (group[0][1] > 0 or group[0][3] > 0)):
            rows.append({"n": None, "op": " ", "text": "…", "gap": True})
        for tag, i1, i2, j1, j2 in group:
            if tag == "equal":
                rows += [{"n": j1 + k + 1, "op": " ", "text": b[j1 + k]} for k in range(j2 - j1)]
                continue
            rows += [{"n": None, "op": "-", "text": a[i]} for i in range(i1, i2)]
            rows += [{"n": j + 1, "op": "ai" if j + 1 in ai else "+", "text": b[j]}
                     for j in range(j1, j2)]
    if context is not None and groups and groups[-1]:
        last = groups[-1][-1]
        if last[2] < len(a) or last[4] < len(b):
            rows.append({"n": None, "op": " ", "text": "…", "gap": True})
    return rows


def line_diff(before: str, after: str, *, context: int | None = 3,
              ai_lines: set[int] | None = None) -> dict:
    """Diff two texts. A new file (``before == ''``) yields only ``+``/``ai`` rows."""
    a, b = before.splitlines(), after.splitlines()
    rows = _rows(a, b, context, set(ai_lines or ()))
    adds = sum(1 for r in rows if r["op"] in ("+", "ai"))
    dels = sum(1 for r in rows if r["op"] == "-")
    return {"lines": rows, "adds": adds, "dels": dels}


def three_way(base: str, ours: str, current: str) -> dict:
    """Shown when an undo is refused: what we wrote vs what is there now, both from base.

    ``lines`` interleaves both diffs, each row tagged ``side`` = ``ours`` | ``current``.
    """
    o = line_diff(base, ours, context=2)["lines"]
    c = line_diff(base, current, context=2)["lines"]
    lines = [{**r, "side": "ours"} for r in o] + [{**r, "side": "current"} for r in c]
    return {"lines": lines, "ours": o, "current": c}
