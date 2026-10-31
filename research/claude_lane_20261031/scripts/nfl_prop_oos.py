"""2025-fit / 2026-test check of the props calibration shift (method record; scratch inputs).

Usage: python nfl_prop_oos.py PRICER_PY BIAS_JSON
  PRICER_PY  path to nfl_prop_research_pricer.py (loaded as a module; its
             import-time setup builds ev, pr, cvs, grid from scratch data)
  BIAS_JSON  per-market [[season, mu, actual], ...] rows from the bias run
Refuses clearly if either scratch input is missing. Research only.
"""
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np


def load_pricer(path: Path):
    if not path.is_file():
        raise SystemExit(f"SCRATCH_PRICER_MISSING: {path}")
    spec = importlib.util.spec_from_file_location("nfl_prop_research_pricer", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main(argv) -> int:
    if len(argv) != 3:
        raise SystemExit(__doc__)
    pricer = load_pricer(Path(argv[1]))
    bias_path = Path(argv[2])
    if not bias_path.is_file():
        raise SystemExit(f"SCRATCH_BIAS_MISSING: {bias_path}")
    ev, pr, cvs, grid = pricer.ev, pricer.pr, pricer.cvs, pricer.grid
    bias = json.loads(bias_path.read_text())
    for market, values in bias.items():
        cfg = ev.MARKETS[market]
        arr = np.array(values)

        def rows(season):
            out = []
            for _s, mu, y in arr[arr[:, 0] == season]:
                for off in (-0.15, 0.0, 0.15):
                    line = np.floor(mu * (1 + off)) + 0.5
                    p = pr.p_over_for(ev, mu, cvs[market], cfg["count"], line, grid)
                    out.append((p, float(y > line)))
            return np.array(out)

        train, test = rows(2025), rows(2026)

        def near_even(r):
            return (r[:, 0] > 0.35) & (r[:, 0] < 0.65)

        shift = (train[near_even(train), 1] - train[near_even(train), 0]).mean()
        k = near_even(test)
        raw = (test[k, 1] - test[k, 0]).mean()
        fixed = (test[k, 1] - (test[k, 0] + shift)).mean()

        def brier(r, s):
            m = near_even(r)
            return np.mean((np.clip(r[m, 0] + s, 0, 1) - r[m, 1]) ** 2)

        print(f"{market:10} shift fit on 2025 {shift:+.3f} | 2026 miss raw {raw:+.3f} -> fixed {fixed:+.3f} "
              f"| Brier 2026 raw {brier(test, 0):.4f} fixed {brier(test, shift):.4f} n={int(k.sum())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
