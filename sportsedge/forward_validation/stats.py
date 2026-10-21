"""Forward-validation statistics — proven mechanics, reused with attribution.

Two functions in this module are copied VERBATIM from the frozen NFL props
Part 2 package (research/nfl_props_part2_20261018/), because the standing
rule for this program is to reuse the frozen test's proven mechanics rather
than re-derive them:

- ``boot`` — the game-clustered block bootstrap from
  ``eval_nfl_props_calibration_v1.py`` (the hash-pinned Part 2 evaluator,
  sha256 66de56155e3c36f90c1f39c648b24e724328ec86056dee0e9adbed57281bc25b;
  SEED / RESAMPLES constants travel with it). The pinned evaluator file is
  NOT modified or imported by this package; a framework test asserts this
  copy returns identical output to the pinned original on fixed inputs.
- ``american_to_decimal`` / ``devig_pair`` — the multiplicative de-vig from
  ``price_nfl_props_part2.py`` (same package; the pricing runner whose
  ``load_evaluator`` enforces the pin above).

Everything else in this package is new, generic machinery.
"""
from __future__ import annotations

import numpy as np

# --- verbatim from eval_nfl_props_calibration_v1.py (pinned, see header) ---
SEED, RESAMPLES = 20261017, 2000


def boot(vals, blocks):
    vals = np.asarray(vals, float)
    keys = sorted(set(blocks))
    idx = {k: n for n, k in enumerate(keys)}
    bi = np.array([idx[b] for b in blocks])
    sums, cnts = np.zeros(len(keys)), np.zeros(len(keys))
    np.add.at(sums, bi, vals)
    np.add.at(cnts, bi, 1)
    rng = np.random.default_rng(SEED)
    s = rng.integers(0, len(keys), size=(RESAMPLES, len(keys)))
    m = sums[s].sum(1) / cnts[s].sum(1)
    lo, hi = np.percentile(m, [2.5, 97.5])
    return {"mean": float(vals.mean()), "ci95_lo": float(lo), "ci95_hi": float(hi),
            "n": int(len(vals)), "n_blocks": len(keys)}


# --- verbatim from price_nfl_props_part2.py (see header) ---

def american_to_decimal(price: float) -> float:
    price = float(price)
    if price > 0:
        return 1.0 + price / 100.0
    if price < 0:
        return 1.0 + 100.0 / abs(price)
    raise ValueError("american price of 0 is not a price")


def devig_pair(over_price: float, under_price: float) -> tuple[float, float]:
    """Multiplicative de-vig of a paired two-sided quote -> (p_over, p_under)."""
    qo = 1.0 / american_to_decimal(over_price)
    qu = 1.0 / american_to_decimal(under_price)
    tot = qo + qu
    return qo / tot, qu / tot


# --- new in this package ---

def raw_implied(price: float) -> float:
    """Raw implied probability of a single American price (no de-vig).
    Used for YES_ONLY markets, exactly as the locked anytime-TD test does:
    a one-sided board has nothing to de-vig against."""
    return 1.0 / american_to_decimal(price)
