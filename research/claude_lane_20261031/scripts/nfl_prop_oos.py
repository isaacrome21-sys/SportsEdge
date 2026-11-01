"""2025-fit / 2026-test check of the props calibration shift (method record; scratch paths).

Guards (review 5726665611 on #2979): a market with no in-band 2025 rows or no in-band 2026
rows is reported as SKIPPED with the reason, never printed as a numeric result; every printed
number is checked finite. `python nfl_prop_oos.py --self-test` runs synthetic regressions
without the pricer or data.
"""
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np

LO, HI = 0.35, 0.65


def as_rows(out):
    """Always a (n, 2) float array, including n == 0 (np.array([]) would be 1-D)."""
    return np.asarray(out, dtype=float).reshape(-1, 2)


def in_band(r):
    r = as_rows(r)
    return (r[:, 0] > LO) & (r[:, 0] < HI)


def brier(r, s):
    r = as_rows(r)
    b = r[in_band(r)]
    return float(np.mean((np.clip(b[:, 0] + s, 0, 1) - b[:, 1]) ** 2))


def evaluate(tr, te):
    """Return (result_dict, None) or (None, skip_reason). Never returns NaN numbers."""
    tr, te = as_rows(tr), as_rows(te)
    btr, bte = tr[in_band(tr)], te[in_band(te)]
    if len(btr) == 0:
        return None, f"SKIPPED: 0 in-band 2025 rows (of {len(tr)})"
    if len(bte) == 0:
        return None, f"SKIPPED: 0 in-band 2026 rows (of {len(te)})"
    shift = float((btr[:, 1] - btr[:, 0]).mean())
    res = {
        "shift": shift,
        "raw": float((bte[:, 1] - bte[:, 0]).mean()),
        "fix": float((bte[:, 1] - (bte[:, 0] + shift)).mean()),
        "brier_raw": brier(te, 0.0),
        "brier_fix": brier(te, shift),
        "n_train": int(len(btr)),
        "n_test": int(len(bte)),
    }
    bad = [k for k, v in res.items() if not np.isfinite(v)]
    if bad:
        return None, f"SKIPPED: non-finite {bad}"
    return res, None


def self_test():
    # ChatGPT repro: 0 train in-band -> must skip, not NaN
    res, why = evaluate([[0.9, 1], [0.1, 0]], [[0.5, 1], [0.6, 0]])
    assert res is None and "2025" in why, why
    # empty season (1-D empty array case)
    res, why = evaluate([], [[0.5, 1]])
    assert res is None and "2025" in why, why
    res, why = evaluate([[0.5, 1]], [])
    assert res is None and "2026" in why, why
    # 0 test in-band
    res, why = evaluate([[0.5, 1]], [[0.9, 1]])
    assert res is None and "2026" in why, why
    # valid case: numbers finite and exact
    res, why = evaluate([[0.5, 1], [0.4, 0]], [[0.5, 1], [0.6, 0]])
    assert why is None
    assert abs(res["shift"] - 0.05) < 1e-12 and res["n_test"] == 2
    assert all(np.isfinite(v) for v in res.values())
    print("self-test: 5/5 ok")


def main(bias_path="bias.json"):
    spec = importlib.util.spec_from_file_location(
        "nfl_prop_research_pricer", Path(__file__).with_name("nfl_prop_research_pricer.py")
    )
    pricer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pricer)
    ev, pr, cvs, grid = pricer.ev, pricer.pr, pricer.cvs, pricer.grid

    def rows(a, m, cfg, season):
        out = []
        for _s, mu, y in a[a[:, 0] == season]:
            for off in (-0.15, 0, 0.15):
                L = np.floor(mu * (1 + off)) + 0.5
                p = pr.p_over_for(ev, mu, cvs[m], cfg["count"], L, grid)
                out.append((p, float(y > L)))
        return as_rows(out)

    B = json.load(open(bias_path))
    for m, v in B.items():
        cfg = ev.MARKETS[m]
        a = np.asarray(v, dtype=float).reshape(-1, 3)
        res, why = evaluate(rows(a, m, cfg, 2025), rows(a, m, cfg, 2026))
        if why:
            print(f"{m:10} {why}")
            continue
        print(
            f"{m:10} shift fit on 2025 {res['shift']:+.3f} | 2026 miss raw {res['raw']:+.3f}"
            f" -> fixed {res['fix']:+.3f} | Brier 2026 raw {res['brier_raw']:.4f}"
            f" fixed {res['brier_fix']:.4f} n={res['n_test']}"
        )


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
    else:
        main(*[a for a in sys.argv[1:] if not a.startswith("-")])
