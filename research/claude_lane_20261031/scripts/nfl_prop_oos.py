"""2025-fit / 2026-test check of the props calibration shift (method record; scratch paths)."""
import importlib.util
import json
from pathlib import Path

import numpy as np

_spec = importlib.util.spec_from_file_location(
    "nfl_prop_research_pricer", Path(__file__).with_name("nfl_prop_research_pricer.py")
)
_pricer = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_pricer)
ev, pr, cvs, grid = _pricer.ev, _pricer.pr, _pricer.cvs, _pricer.grid


def in_band(r):
    return (r[:, 0] > 0.35) & (r[:, 0] < 0.65)


def brier(r, s):
    return np.mean((np.clip(r[in_band(r), 0] + s, 0, 1) - r[in_band(r), 1]) ** 2)


def rows(a, m, cfg, season):
    out = []
    for _s, mu, y in a[a[:, 0] == season]:
        for off in (-0.15, 0, 0.15):
            L = np.floor(mu * (1 + off)) + 0.5
            p = pr.p_over_for(ev, mu, cvs[m], cfg["count"], L, grid)
            out.append((p, float(y > L)))
    return np.array(out)


B = json.load(open("bias.json"))
for m, v in B.items():
    cfg = ev.MARKETS[m]
    a = np.array(v)
    tr, te = rows(a, m, cfg, 2025), rows(a, m, cfg, 2026)
    shift = (tr[in_band(tr), 1] - tr[in_band(tr), 0]).mean()
    raw = (te[in_band(te), 1] - te[in_band(te), 0]).mean()
    fix = (te[in_band(te), 1] - (te[in_band(te), 0] + shift)).mean()
    print(
        f"{m:10} shift fit on 2025 {shift:+.3f} | 2026 miss raw {raw:+.3f} -> fixed {fix:+.3f}"
        f" | Brier 2026 raw {brier(te, 0):.4f} fixed {brier(te, shift):.4f} n={in_band(te).sum()}"
    )
