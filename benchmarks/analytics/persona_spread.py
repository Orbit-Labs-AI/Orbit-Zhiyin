"""Health check of the persona anchors and weights on a fictional population.

    uv run python -m benchmarks.analytics.persona_spread [--users 300] [--sessions 60] [--seed 7]

Fictional users (``synthetic.persona_population``: four independent latent traits, behaviour
interpolated between invented pole values) are scored by the backend persona. The report lists,
per axis, the 5 / 25 / 50 / 75 / 95 % quantiles, the share inside 45–55, the share on the high
letter and the correlation with the latent trait, plus how many of the 16 types occur.

This is *not* calibration: the pole values are invented, so the check only shows that the
mapping spreads users out (no pile-up at one end or at 50), follows the latent trait and can
reach every type. Real calibration needs consented population data (profiling.md).
"""

from __future__ import annotations

import argparse
import statistics
from collections import Counter, defaultdict

from orbit_backend.uiview import persona
from orbit_backend.uiview import persona_signals as sig

from .synthetic import persona_population

QUANTILES = (0.05, 0.25, 0.5, 0.75, 0.95)


def spread(users: int = 300, sessions: int = 60, seed: int = 7) -> dict:
    values: dict = defaultdict(list)
    pairs: dict = defaultdict(list)
    codes: Counter = Counter()
    for user in persona_population(users, sessions, seed):
        p = persona.persona_from(sig.suff(user["rows"], None))
        codes[p["code"]] += 1
        for a in p["axes"]:
            values[a["k"]].append(a["value"])
            pairs[a["k"]].append((user["traits"][a["k"]], a["value"]))
    axes = {}
    for k in "DIMV":
        v = sorted(values[k])
        n = len(v)
        axes[k] = {
            "quantiles": [round(v[min(n - 1, int(n * q))], 1) for q in QUANTILES],
            "band_share": sum(45 <= x <= 55 for x in v) / n,
            "high_share": sum(x >= 50 for x in v) / n,
            "corr": statistics.correlation([t for t, _ in pairs[k]], [y for _, y in pairs[k]]),
        }
    return {"users": users, "axes": axes, "codes": dict(codes)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--users", type=int, default=300)
    parser.add_argument("--sessions", type=int, default=60)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    out = spread(args.users, args.sessions, args.seed)
    for k, a in out["axes"].items():
        print(f"{k}  q05–q95 {a['quantiles']}  45–55 {a['band_share']:.0%}  "
              f"high {a['high_share']:.0%}  r {a['corr']:.2f}")
    print(f"types {len(out['codes'])}/16:", dict(sorted(out["codes"].items(),
                                                        key=lambda x: -x[1])))


if __name__ == "__main__":
    main()
