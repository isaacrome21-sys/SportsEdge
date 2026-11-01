"""2025-fit / 2026-test check of the props calibration shift (method record; scratch inputs).

Usage: python nfl_prop_oos.py PRICER_PY BIAS_JSON
  PRICER_PY  path to nfl_prop_research_pricer.py (loaded as a module; its
             import-time setup builds ev, pr, cvs, grid from scratch data)
  BIAS_JSON  per-market [[season, mu, actual], ...] rows from the bias run
Refuses clearly if either scratch input is missing. Research only.

Guards (reviews 5726665611 and 5726872447 on #2979):
- every input row is validated BEFORE the (0.35, 0.65) band filter: p must be finite and in
  [0, 1], y must be exactly 0 or 1; any malformed row makes the whole market INVALID (no
  numeric result is printed, rows are never silently dropped);
- a market with no in-band 2025 rows or no in-band 2026 rows is reported as SKIPPED;
- every printed number is checked finite;
- (review 5727284389 on #2995) raw BIAS_JSON rows are validated BEFORE any season filter or
  `actual > L` comparison: each row must be exactly [season, mu, actual], all finite, with
  season 2025 or 2026; anything else (NaN/Inf actuals, NaN or other seasons, ragged or text
  rows) makes the market INVALID instead of being laundered into 0/1 labels or dropped.
`python nfl_prop_oos.py --self-test` runs synthetic regressions without the pricer or data.
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


def validate(r, label):
    """Return None if every row is well formed, else an INVALID reason. Runs before banding."""
    r = as_rows(r)
    p, y = r[:, 0], r[:, 1]
    bad_p = ~np.isfinite(p) | (p < 0) | (p > 1)
    bad_y = ~np.isin(y, (0.0, 1.0))  # NaN/inf/2/-1 all fail
    if bad_p.any() or bad_y.any():
        return (f"INVALID: {label} has {int(bad_p.sum())} bad p and {int(bad_y.sum())} bad y"
                f" of {len(r)} rows")
    return None


def in_band(r):
    r = as_rows(r)
    return (r[:, 0] > LO) & (r[:, 0] < HI)


def brier(r, s):
    r = as_rows(r)
    b = r[in_band(r)]
    return float(np.mean((np.clip(b[:, 0] + s, 0, 1) - b[:, 1]) ** 2))


SEASONS = (2025.0, 2026.0)


def validate_raw(v):
    """Return (array (n, 3), None) or (None, INVALID reason). Runs before any filter/compare."""
    try:
        a = np.asarray(v, dtype=float)
    except (TypeError, ValueError) as exc:
        return None, f"INVALID: raw rows not numeric ({type(exc).__name__})"
    if a.size == 0:
        return a.reshape(-1, 3), None
    if a.ndim != 2 or a.shape[1] != 3:
        return None, f"INVALID: raw rows must be [season, mu, actual], got shape {a.shape}"
    bad_fin = ~np.isfinite(a).all(axis=1)
    bad_season = ~np.isin(a[:, 0], SEASONS)  # NaN season fails here too
    if bad_fin.any() or bad_season.any():
        return None, (f"INVALID: raw rows have {int(bad_fin.sum())} non-finite and"
                      f" {int(bad_season.sum())} bad-season of {len(a)}")
    return a, None


def market_rows(v, p_fn):
    """Validate raw rows, then build (p, y) per season. p_fn(mu, L) -> P(over L)."""
    a, why = validate_raw(v)
    if why:
        return None, None, why

    def season_rows(season):
        out = []
        for _s, mu, y in a[a[:, 0] == season]:
            for off in (-0.15, 0.0, 0.15):
                L = np.floor(mu * (1 + off)) + 0.5
                out.append((p_fn(mu, L), float(y > L)))
        return as_rows(out)

    return season_rows(2025.0), season_rows(2026.0), None


def evaluate(tr, te):
    """Return (result_dict, None) or (None, reason). Never returns NaN numbers."""
    tr, te = as_rows(tr), as_rows(te)
    for r, label in ((tr, "2025"), (te, "2026")):
        why = validate(r, label)
        if why:
            return None, why
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
    n = 0

    def check(cond, msg):
        nonlocal n
        assert cond, msg
        n += 1

    # review 5726665611: 0 train in-band -> skip, not NaN
    res, why = evaluate([[0.9, 1], [0.1, 0]], [[0.5, 1], [0.6, 0]])
    check(res is None and "2025" in why, why)
    # empty seasons (1-D empty array case)
    res, why = evaluate([], [[0.5, 1]])
    check(res is None and "2025" in why, why)
    res, why = evaluate([[0.5, 1]], [])
    check(res is None and "2026" in why, why)
    # 0 test in-band
    res, why = evaluate([[0.5, 1]], [[0.9, 1]])
    check(res is None and "2026" in why, why)
    # review 5726872447 repros: malformed rows must invalidate, not be dropped by the band
    res, why = evaluate([[0.5, 1], [np.nan, 1]], [[0.5, 1]])
    check(res is None and why.startswith("INVALID: 2025"), why)
    res, why = evaluate([[0.5, 1]], [[0.5, 1], [np.inf, 0]])
    check(res is None and why.startswith("INVALID: 2026"), why)
    res, why = evaluate([[0.5, 1], [-0.2, 0]], [[0.5, 1]])
    check(res is None and why.startswith("INVALID: 2025"), why)
    res, why = evaluate([[0.5, 2]], [[0.5, 1]])
    check(res is None and why.startswith("INVALID: 2025"), why)
    res, why = evaluate([[0.5, 1]], [[0.5, np.nan]])
    check(res is None and why.startswith("INVALID: 2026"), why)
    res, why = evaluate([[1.5, 1]], [[0.5, 1]])
    check(res is None and why.startswith("INVALID"), why)
    # valid case: numbers finite and exact; boundary p=0 and p=1 are legal (out of band)
    res, why = evaluate([[0.5, 1], [0.4, 0], [0.0, 0], [1.0, 1]], [[0.5, 1], [0.6, 0]])
    check(why is None, why)
    check(abs(res["shift"] - 0.05) < 1e-12 and res["n_train"] == 2 and res["n_test"] == 2,
          res)
    check(all(np.isfinite(v) for v in res.values()), res)
    # review 5727284389 repros (#2995): raw NaN/+Inf/-Inf actuals must not become 0/1 labels
    fake_p = lambda mu, L: 0.5  # noqa: E731  synthetic pricer, research test only
    for bad in (np.nan, np.inf, -np.inf):
        tr, te, why = market_rows([[2025, 25.0, bad], [2026, 25.0, 30.0]], fake_p)
        check(tr is None and why.startswith("INVALID: raw"), why)
    # NaN / unknown season is INVALID, not silently dropped by the equality filter
    for bad_season in (np.nan, 2024, 2025.5):
        tr, te, why = market_rows([[bad_season, 25.0, 30.0], [2026, 25.0, 30.0]], fake_p)
        check(tr is None and why.startswith("INVALID: raw"), why)
    # non-finite mu, ragged, text and wrong-width rows are INVALID, not a crash
    for bad_rows in ([[2025, np.nan, 30.0]], [[2025, 25.0]], [[2025, 25.0, 30.0], [2026, 1.0]],
                     [[2025, "x", 30.0]], [[2025, 25.0, 30.0, 1.0]]):
        tr, te, why = market_rows(bad_rows, fake_p)
        check(tr is None and why is not None and why.startswith("INVALID: raw"), (bad_rows, why))
    # end to end: one bad raw actual makes the whole market INVALID through evaluate's caller path
    v = [[2025, 25.0, 30.0], [2025, 25.0, 20.0], [2026, 25.0, 30.0], [2026, 25.0, np.inf]]
    tr, te, why = market_rows(v, fake_p)
    check(tr is None and "1 non-finite" in why, why)
    # valid raw rows: 3 lines per game, exact labels, then evaluate gives finite numbers
    tr, te, why = market_rows([[2025, 25.0, 30.0], [2026, 25.0, 27.0]], fake_p)  # L 21.5/25.5/28.5
    check(why is None and tr.shape == (3, 2) and te.shape == (3, 2), (why, tr, te))
    check(tr[:, 1].tolist() == [1.0, 1.0, 1.0] and te[:, 1].tolist() == [1.0, 1.0, 0.0],
          (tr, te))
    res, why = evaluate(tr, te)
    check(why is None and all(np.isfinite(x) for x in res.values()), (res, why))
    # empty market is still SKIPPED (not INVALID, not NaN)
    tr, te, why = market_rows([], fake_p)
    check(why is None, why)
    res, why = evaluate(tr, te)
    check(res is None and why.startswith("SKIPPED"), why)
    print(f"self-test: {n}/{n} ok")


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
    for m, v in bias.items():
        cfg = ev.MARKETS[m]

        def p_fn(mu, L, m=m, cfg=cfg):
            return pr.p_over_for(ev, mu, cvs[m], cfg["count"], L, grid)

        tr, te, why = market_rows(v, p_fn)
        if not why:
            res, why = evaluate(tr, te)
        if why:
            print(f"{m:10} {why}")
            continue
        print(
            f"{m:10} shift fit on 2025 {res['shift']:+.3f} | 2026 miss raw {res['raw']:+.3f}"
            f" -> fixed {res['fix']:+.3f} | Brier 2026 raw {res['brier_raw']:.4f}"
            f" fixed {res['brier_fix']:.4f} n={res['n_test']}"
        )
    return 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
        raise SystemExit(0)
    raise SystemExit(main(sys.argv))
