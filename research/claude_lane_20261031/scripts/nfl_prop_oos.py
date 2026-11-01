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
  rows) makes the market INVALID instead of being laundered into 0/1 labels or dropped;
- (review 5727663452 on #2995) original raw cell types are checked BEFORE any float
  coercion: every cell must be a JSON number (int/float), never bool, str, null or nested;
  JSON `true` or "30" makes the market INVALID instead of becoming 1.0 / 30.0;
- (review 5727926064 on #2995) every raw cell must have |x| <= RAW_ABS_MAX (1e6), checked on
  the original Python number before float coercion, so a JSON int like 10**400 or mu=1.7e308
  makes the market INVALID instead of an uncaught OverflowError or an Inf line L; every
  generated line L must be finite; every pricer output p_fn(mu, L) must itself be a real
  int/float (not bool, str, None) before it is stored, else the market is INVALID;
- (review 5728331427 on #2995) the pricer output p goes through the same magnitude check on
  the original number before float(p), so p=10**400 makes the market INVALID instead of an
  uncaught OverflowError that aborts every market. Raw cells and pricer outputs share one
  helper, _number_or_reason(), so the two paths cannot drift apart again.
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
RAW_ABS_MAX = 1e6  # no season, prop mean, prop outcome or probability is anywhere near this


def _raw_cell_ok(c):
    """A raw cell must be a real int/float (JSON number). bool and str are refused before any
    coercion, so `true` -> 1.0 and "30" -> 30.0 can never be laundered (review 5727663452)."""
    return isinstance(c, (int, float, np.integer, np.floating)) and not isinstance(
        c, (bool, np.bool_))


def _number_or_reason(c):
    """Type and magnitude check on the ORIGINAL value, before any float coercion.

    Returns None if c is a real number with |c| <= RAW_ABS_MAX (NaN and +/-Inf pass here and
    are refused by the later finite / range checks), else a short reason. Python compares a
    huge int with a float exactly, so this never overflows (reviews 5727926064, 5728331427).
    """
    if not _raw_cell_ok(c):
        return f"type {type(c).__name__}"
    if abs(c) > RAW_ABS_MAX and abs(c) != float("inf"):
        return f"beyond +/-{RAW_ABS_MAX:g}"
    return None


def validate_raw(v):
    """Return (array (n, 3), None) or (None, INVALID reason). Runs before any filter/compare."""
    if not isinstance(v, (list, tuple)):
        return None, f"INVALID: raw rows must be a list, got {type(v).__name__}"
    for i, row in enumerate(v):
        if not isinstance(row, (list, tuple)) or len(row) != 3:
            return None, f"INVALID: raw rows must be [season, mu, actual], row {i} is {row!r}"
        bad = [type(c).__name__ for c in row if not _raw_cell_ok(c)]
        if bad:
            return None, f"INVALID: raw row {i} has non-numeric cell type(s) {bad}"
        if any(_number_or_reason(c) for c in row):
            return None, f"INVALID: raw row {i} has a cell beyond +/-{RAW_ABS_MAX:g}"
    if len(v) == 0:
        return np.empty((0, 3)), None
    a = np.asarray(v, dtype=float)
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
                if not np.isfinite(L):
                    return None, f"INVALID: non-finite line L from mu={mu!r}"
                p = p_fn(mu, L)
                if isinstance(p, np.ndarray) and p.ndim == 0 and p.dtype.kind in "fiu":
                    p = p.item()  # a 0-d numeric array from a vectorised pricer is a scalar
                bad = _number_or_reason(p)
                if bad:
                    return None, f"INVALID: pricer returned {bad}, not a usable number"
                out.append((float(p), float(y > L)))
        return as_rows(out), None

    tr, why = season_rows(2025.0)
    if why:
        return None, None, why
    te, why = season_rows(2026.0)
    if why:
        return None, None, why
    return tr, te, None


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
    # review 5727663452 repros (#2995): bool / numeric-string raw cells are refused by type
    for bad_rows in ([[2025, 25.0, True]], [[2025, 25.0, "30"]], [[True, 25.0, 30.0]],
                     [[2025, False, 30.0]], [["2025", 25.0, 30.0]], [[2025, 25.0, None]],
                     [[2025, 25.0, [30.0]]], [(2025, 25.0, np.bool_(True))]):
        tr, te, why = market_rows(bad_rows, fake_p)
        check(tr is None and why is not None and why.startswith("INVALID: raw"), (bad_rows, why))
    # the same refusal end to end, from JSON text as main() reads it
    tr, te, why = market_rows(json.loads('[[2025, 25.0, 30.0], [2026, 25.0, true]]'), fake_p)
    check(tr is None and "bool" in why, why)
    tr, te, why = market_rows(json.loads('[[2025, 25.0, 30.0], [2026, 25.0, "30"]]'), fake_p)
    check(tr is None and "str" in why, why)
    # non-list market payloads are INVALID, not iterated character by character
    for bad_v in ("2025,25,30", {"a": 1}, None, 3):
        tr, te, why = market_rows(bad_v, fake_p)
        check(tr is None and why.startswith("INVALID: raw"), (bad_v, why))
    # integer JSON numbers (int season/actual) stay legal
    tr, te, why = market_rows(json.loads('[[2025, 25, 30], [2026, 25, 27]]'), fake_p)
    check(why is None and tr.shape == (3, 2), why)
    # review 5727926064 repros (#2995): huge JSON ints / near-max floats are INVALID, not a
    # crash or an Inf line, and pricer outputs are type-checked before coercion
    big = json.loads('[[2025, 25.0, 30.0], [2026, 25.0, ' + '1' + '0' * 400 + ']]')
    tr, te, why = market_rows(big, fake_p)
    check(tr is None and why.startswith("INVALID: raw") and "beyond" in why, why)
    for bad_rows in ([[2025, 1.7e308, 30.0]], [[2025, 25.0, -1e7]], [[10 ** 400, 25.0, 30.0]]):
        tr, te, why = market_rows(bad_rows, fake_p)
        check(tr is None and why.startswith("INVALID: raw"), (bad_rows, why))
    ok = [[2025, 25.0, 30.0], [2026, 25.0, 27.0]]
    for bad_p in (lambda mu, L: "0.5", lambda mu, L: True, lambda mu, L: None,  # noqa: E731
                  lambda mu, L: np.bool_(False), lambda mu, L: [0.5]):  # noqa: E731
        tr, te, why = market_rows(ok, bad_p)
        check(tr is None and why.startswith("INVALID: pricer"), why)
    # review 5728331427 repro (#2995): a huge-int pricer output is INVALID for that market,
    # not an uncaught OverflowError from float(p); same for a huge negative int
    for huge in (10 ** 400, -(10 ** 400), 10 ** 7):
        tr, te, why = market_rows(ok, lambda mu, L, h=huge: h)
        check(tr is None and why.startswith("INVALID: pricer") and "beyond" in why, why)
    # ...and main()'s per-market loop keeps going: a huge-int market next to a good one
    outs = {}
    for m, pf in (("bad", lambda mu, L: 10 ** 400), ("good", fake_p)):
        tr, te, why = market_rows(ok, pf)
        if not why:
            _res, why = evaluate(tr, te)
        outs[m] = why
    check(outs["bad"].startswith("INVALID: pricer") and outs["good"] is None, outs)
    # pricer NaN / Inf / out-of-range floats pass the magnitude check but are refused by
    # validate() in evaluate(), so no numeric result is printed
    for odd in (float("nan"), float("inf"), 1.5, -0.1):
        tr, te, why = market_rows(ok, lambda mu, L, o=odd: o)
        check(why is None, why)
        res, why = evaluate(tr, te)
        check(res is None and why.startswith("INVALID"), (odd, why))
    # integer pricer outputs 0 / 1 stay legal (in range, out of band)
    tr, te, why = market_rows(ok, lambda mu, L: 1)
    check(why is None and tr.shape == (3, 2), why)
    # a numpy float pricer output stays legal
    tr, te, why = market_rows(ok, lambda mu, L: np.float64(0.5))
    check(why is None and tr.shape == (3, 2), why)
    tr, te, why = market_rows(ok, lambda mu, L: np.array(0.5))
    check(why is None and tr.shape == (3, 2), why)
    tr, te, why = market_rows(ok, lambda mu, L: np.array("0.5"))
    check(tr is None and why.startswith("INVALID: pricer"), why)
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
