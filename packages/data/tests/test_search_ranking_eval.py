"""Constructed ranking evaluation for orbit_data.search scoring constants.

Each case is a pairwise judgement written from the product intent, independently of the
scoring code: hit = (hit_type, age_days or None for unknown, relevance). bm25 relevance
lies in [1, 2) (search._bm25_rel); LIKE matches are 1.0. ``better`` must outrank ``worse``.
The grid test records which parameter values satisfy every judgement, so the chosen
constants in search.py are one point of that feasible set rather than a guess.
"""

import itertools

from orbit_data import search as search_module

DAY = search_module.DAY_MS
NOW = 1_000 * DAY

CASES = [
    # Same age and strength: deliberate names first, then the project, then exact
    # identifiers (command head, touched file), then free message text.
    ("title over project", ("title", 0, 1.0), ("project", 0, 1.0)),
    ("project over command", ("project", 0, 1.0), ("command", 0, 1.0)),
    ("project over file", ("project", 0, 1.0), ("file", 0, 1.0)),
    ("command over message", ("command", 0, 1.0), ("message", 0, 1.0)),
    ("file over message", ("file", 0, 1.0), ("message", 0, 1.0)),
    # A session named for the query a month ago beats a passing mention today.
    ("month-old title over today's weak message", ("title", 30, 1.0), ("message", 0, 1.0)),
    # ...but a strong message today beats a title from a year ago.
    ("today's strong message over year-old title", ("message", 0, 1.9), ("title", 365, 1.0)),
    # Recency orders hits of equal type and strength.
    ("yesterday over last month", ("message", 1, 1.0), ("message", 30, 1.0)),
    ("last quarter over last year", ("command", 90, 1.0), ("command", 365, 1.0)),
    # Relevance outweighs a week of age within a type.
    ("strong week-old over weak today", ("message", 7, 1.9), ("message", 0, 1.1)),
    # Archived work stays findable by name: a two-year-old title still beats a weak
    # message from two months ago (needs a non-zero decay floor).
    ("archived title over stale weak message", ("title", 730, 1.0), ("message", 60, 1.0)),
    # Unknown age is never favoured over a dated hit of the same kind.
    ("dated half-year over unknown age", ("message", 180, 1.0), ("message", None, 1.0)),
]


def hit(spec):
    kind, age, rel = spec
    return {"hit_type": kind, "ts": None if age is None else NOW - age * DAY, "rel": rel}


def failures(weights, half_life, floor):
    params = {"WEIGHTS": weights, "HALF_LIFE_DAYS": half_life, "DECAY_FLOOR": floor}
    saved = {name: getattr(search_module, name) for name in params}
    try:
        for name, value in params.items():
            setattr(search_module, name, value)
        return [
            name
            for name, better, worse in CASES
            if not search_module._score(hit(better), NOW) > search_module._score(hit(worse), NOW)
        ]
    finally:
        for name, value in saved.items():
            setattr(search_module, name, value)


def test_shipped_constants_satisfy_every_judgement():
    assert (
        failures(search_module.WEIGHTS, search_module.HALF_LIFE_DAYS, search_module.DECAY_FLOOR)
        == []
    )


GRID = {
    "title": (1.5, 2.0, 3.0, 4.0),
    "project": (1.25, 2.0, 2.5),
    "identifier": (1.0, 1.5, 2.0),
    "half_life": (7.0, 14.0, 30.0, 60.0, 90.0),
    "floor": (0.0, 0.1, 0.25, 0.5),
}


def feasible():
    found = []
    for title, project, ident, half_life, floor in itertools.product(*GRID.values()):
        weights = {
            "title": title,
            "project": project,
            "command": ident,
            "file": ident,
            "message": 1.0,
        }
        if not failures(weights, half_life, floor):
            found.append((title, project, ident, half_life, floor))
    return found


def test_grid_bounds_the_constants():
    found = feasible()
    # floor 0 sends a two-year-old title to ~0, below a stale weak message (hand check:
    # 3 x 0.5^(730/30) ~ 0 < 1 x 0.5^2 = 0.25), so every feasible point keeps a floor.
    assert all(floor > 0 for *_, floor in found)
    # With identifiers strictly above messages (> 1.0) and projects above identifiers,
    # titles at 1.5 or 2.0 cannot also stay above projects on this grid.
    assert {title for title, *_ in found} == {3.0, 4.0}
    # The shipped point is feasible; 30 days is the middle of the feasible half-lives
    # (7..90 all appear), 0.25 the floor most points accept.
    assert (3.0, 2.0, 1.5, 30.0, 0.25) in found
    assert {half_life for _, _, _, half_life, _ in found} == set(GRID["half_life"])
