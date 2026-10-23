"""NFL period-line research engine (Grok lane, SCREEN only).

Families: first-half, second-half (includes overtime) and quarter 1-4
moneyline (3-way home/tie/away), spread and total.

Inputs: per-game period rows built from the official nflverse
play_by_play_{season}.csv.gz releases already on the box and hashed in
research/grok_nfl_period_lines_screen_20261023/SOURCES.json.  No quotes, no
market inputs, no EV.  Point-in-time: team ratings use only games dated
strictly before the priced game; the outcome pool uses only seasons strictly
before the priced game's season.

Construction (declared a priori, nothing fitted):
  rating   team points for/against in the period per game, current season
           (weight 1) + previous season (weight PREV_W), shrunk toward the
           league per-side mean with SHRINK_G pseudo-games.
  mu       home = L_home + (off_home - L) + (def_away - L); away likewise.
  pmf      empirical joint pool of (home, away) period points from earlier
           seasons; margin and total pmfs are that pool's pmfs shifted by
           (mu - pool mean), split linearly between the two neighbouring
           integer shifts.
Fail-closed: unknown period, malformed rows, team with < MIN_TEAM_GAMES
history, empty pool, non-finite numbers or bool/str lines raise
NflPeriodLinesError.

Governance: SCREEN, NOT_VALIDATED, eligible=false, play_allowed=false.
Research only.
"""
from __future__ import annotations

import hashlib
import math
from typing import Any, Iterable, Mapping

from sportsedge.screen_only_guard import ScreenOnlyGuardError, checked_require, lock_module, require_screen_only

ENGINE_ID = "NFL_PERIOD_LINES_EMPIRICAL"
ENGINE_VERSION = "nfl_period_lines_empirical_v1_20261023"
GOVERNANCE = {"state": "SCREEN", "validation_status": "NOT_VALIDATED",
              "eligible": False, "play_allowed": False}
PERIODS = ("q1", "q2", "q3", "q4", "h1", "h2")
PREV_W = 0.5
SHRINK_G = 6.0
MIN_TEAM_GAMES = 3
# Families SCREEN_WORSE_THAN_NAIVE in research/grok_nfl_period_lines_screen_20261023/
# screen_results_v1.json; they refuse with a coded NAIVE_FAIL instead of pricing.
NAIVE_FAIL_FAMILIES = frozenset({"Q1_MONEYLINE", "Q2_MONEYLINE", "Q3_MONEYLINE",
                                 "Q4_MONEYLINE", "Q1_TOTAL", "Q3_TOTAL", "Q4_TOTAL"})
# t256: pinned sha256 of the sorted family list; every read is checked (ruling C).
_NAIVE_FAIL_SHA256 = "ec535bb6e87d2f3fa9b6cd3988a625f3f5183c51f9edc7b33e086855935df678"


def _naive_fail():
    v = globals().get("NAIVE_FAIL_FAMILIES")
    if not isinstance(v, frozenset) or hashlib.sha256(
            "\n".join(sorted(v)).encode()).hexdigest() != _NAIVE_FAIL_SHA256:
        raise ScreenOnlyGuardError("SCREEN_ONLY_GUARD:NAIVE_FAIL_FAMILIES_TAMPERED")
    return v


class NflPeriodLinesError(ValueError):
    pass


def _int(v, what):
    if isinstance(v, bool) or not isinstance(v, int) or v < 0:
        raise NflPeriodLinesError(f"MALFORMED_{what}")
    return v


def _date(v, what):
    if not isinstance(v, str) or len(v) != 10 or v[4] != "-" or v[7] != "-":
        raise NflPeriodLinesError(f"{what}_DATE_INVALID")
    return v


def _rows(history: Iterable[Mapping[str, Any]], period: str) -> list:
    out = []
    for r in history:
        try:
            out.append((_date(r["date"], "HISTORY"), int(r["season"]), r["home"], r["away"],
                        _int(r[f"{period}_h"], "POINTS"), _int(r[f"{period}_a"], "POINTS")))
        except KeyError as e:
            raise NflPeriodLinesError(f"HISTORY_FIELD_MISSING:{e.args[0]}") from None
        except (TypeError, ValueError) as e:
            if isinstance(e, NflPeriodLinesError):
                raise
            raise NflPeriodLinesError("HISTORY_ROW_MALFORMED") from None
    return out


def _pmf(values) -> dict:
    n = len(values)
    out: dict = {}
    for v in values:
        out[v] = out.get(v, 0.0) + 1.0 / n
    return out


def _shift(pmf: dict, d: float) -> dict:
    if not math.isfinite(d):
        raise NflPeriodLinesError("NON_FINITE_SHIFT")
    lo = math.floor(d); w = d - lo
    out: dict = {}
    for k, p in pmf.items():
        out[k + lo] = out.get(k + lo, 0.0) + p * (1 - w)
        out[k + lo + 1] = out.get(k + lo + 1, 0.0) + p * w
    return {k: v for k, v in out.items() if v > 0}


def price_period(history: Iterable[Mapping[str, Any]], *, date: str, season: int,
                 home: str, away: str, period: str) -> dict:
    """Priced output with NAIVE_FAIL families removed and coded."""
    return _price_period(history, date=date, season=season, home=home, away=away,
                         period=period)


def price_period_unrestricted(history: Iterable[Mapping[str, Any]], *, date: str, season: int,
                              home: str, away: str, period: str) -> dict:
    """Screen-only: every family, including NAIVE_FAIL ones. Guarded by screen_only()."""
    out = _price_period(history, date=date, season=season, home=home, away=away,
                        period=period, allow_refused=True)
    out["screen_only_unrestricted"] = True
    return out


def _price_period(history: Iterable[Mapping[str, Any]], *, date: str, season: int,
                  home: str, away: str, period: str, allow_refused: bool = False) -> dict:
    """Single pricing path. Strips NAIVE_FAIL families unless allow_refused=True,
    which is only honoured inside screen_only()."""
    if not isinstance(allow_refused, bool):
        raise NflPeriodLinesError("ALLOW_REFUSED_MUST_BE_BOOL")
    if allow_refused:
        checked_require("_price_period(allow_refused=True)")
    if period not in PERIODS:
        raise NflPeriodLinesError(f"UNKNOWN_PERIOD:{period}")
    if isinstance(season, bool) or not isinstance(season, int):
        raise NflPeriodLinesError("SEASON_REQUIRED_INT")
    _date(date, "GAME")
    if not isinstance(home, str) or not isinstance(away, str) or not home or home == away:
        raise NflPeriodLinesError("TEAMS_INVALID")
    rows = _rows(history, period)
    pool = [r for r in rows if r[1] < season]
    if not pool:
        raise NflPeriodLinesError("EMPTY_OUTCOME_POOL")
    pit = [r for r in rows if r[0] < date and r[1] in (season, season - 1)]
    if not pit:
        raise NflPeriodLinesError("EMPTY_RATING_POOL")
    L_h = sum(r[4] for r in pit) / len(pit)
    L_a = sum(r[5] for r in pit) / len(pit)
    L = (L_h + L_a) / 2

    def rating(team):
        f = a = w = 0.0
        for r in pit:
            wt = 1.0 if r[1] == season else PREV_W
            if r[2] == team:
                f += wt * r[4]; a += wt * r[5]; w += wt
            elif r[3] == team:
                f += wt * r[5]; a += wt * r[4]; w += wt
        if w < MIN_TEAM_GAMES * PREV_W:
            raise NflPeriodLinesError(f"TEAM_HISTORY_INSUFFICIENT:{team}")
        return (f + SHRINK_G * L) / (w + SHRINK_G), (a + SHRINK_G * L) / (w + SHRINK_G)

    oh, dh = rating(home); oa, da = rating(away)
    mu_h = L_h + (oh - L) + (da - L)
    mu_a = L_a + (oa - L) + (dh - L)
    margins = [r[4] - r[5] for r in pool]; totals = [r[4] + r[5] for r in pool]
    m_pmf = _shift(_pmf(margins), (mu_h - mu_a) - sum(margins) / len(margins))
    t_pmf = _shift(_pmf(totals), (mu_h + mu_a) - sum(totals) / len(totals))
    t_pmf = _floor_at_zero(t_pmf)
    ml = {"home": sum(p for k, p in m_pmf.items() if k > 0),
          "tie": m_pmf.get(0, 0.0),
          "away": sum(p for k, p in m_pmf.items() if k < 0)}
    out = {"engine_id": ENGINE_ID, "engine_version": ENGINE_VERSION, "period": period,
           "mu_home": mu_h, "mu_away": mu_a, "margin_pmf": m_pmf, "total_pmf": t_pmf,
           "moneyline_3way": ml, "governance": dict(GOVERNANCE)}
    if allow_refused:
        return out
    refused = {}
    if f"{period.upper()}_TOTAL" in _naive_fail():
        del out["total_pmf"]
        refused["total"] = f"NAIVE_FAIL:{period.upper()}_TOTAL"
    ml_fam = f"{period.upper()}_MONEYLINE"
    if ml_fam in _naive_fail():
        # Everything that can rebuild the refused moneyline goes: the 3-way price, the
        # full margin pmf, and the team means (mean shift + public history = margin pmf).
        for key in ("moneyline_3way", "margin_pmf", "mu_home", "mu_away"):
            del out[key]
        refused["moneyline"] = f"NAIVE_FAIL:{ml_fam}"
        # Grok ruling 2026-10-23 (Option 1): any public quarter spread plus the public
        # history pins the one-parameter margin shift (bisection) and so the moneyline.
        refused["spread"] = f"NAIVE_FAIL:{ml_fam}_DERIVABLE"
    out["refused"] = refused
    return out


def _period_of(priced) -> str:
    if not isinstance(priced, Mapping) or "period" not in priced:
        raise NflPeriodLinesError("PERIOD_MISSING")
    period = priced["period"]
    if not isinstance(period, str) or period not in PERIODS:
        raise NflPeriodLinesError(f"UNKNOWN_PERIOD:{period!r}")
    return period


def _floor_at_zero(pmf: dict) -> dict:
    out: dict = {}
    for k, p in pmf.items():
        out[max(k, 0)] = out.get(max(k, 0), 0.0) + p
    return out


def _line(v) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise NflPeriodLinesError("LINE_REQUIRED_FINITE_NUMBER")
    if abs(v * 2 - round(v * 2)) > 1e-9:
        raise NflPeriodLinesError("LINE_NOT_HALF_POINT")
    return float(v)


def total_probs(priced: dict, line) -> dict:
    """P(over / push / under) for a period total line."""
    L = _line(line)
    period = _period_of(priced)
    if f"{period.upper()}_TOTAL" in _naive_fail() and not priced.get("screen_only_unrestricted"):
        raise NflPeriodLinesError(f"NAIVE_FAIL:{period.upper()}_TOTAL")
    if "total_pmf" not in priced:
        raise NflPeriodLinesError(priced.get("refused", {}).get("total", "TOTAL_PMF_MISSING"))
    pmf = priced["total_pmf"]
    return {"over": sum(p for k, p in pmf.items() if k > L), "push": pmf.get(L, 0.0) if L.is_integer() else 0.0,
            "under": sum(p for k, p in pmf.items() if k < L)}


def spread_probs(priced: dict, home_line) -> dict:
    """Home spread (e.g. -3.5): P(home covers / push / away covers)."""
    L = _line(home_line)
    period = _period_of(priced)
    ml_fam = f"{period.upper()}_MONEYLINE"
    if ml_fam in _naive_fail():
        # Every quarter spread is refused (Grok ruling 2026-10-23, Option 1): with the
        # public history, any spread price rebuilds the refused moneyline.
        raise NflPeriodLinesError(f"NAIVE_FAIL:{ml_fam}_DERIVABLE")
    if "margin_pmf" not in priced:
        raise NflPeriodLinesError("MARGIN_PMF_MISSING")
    pmf = priced["margin_pmf"]
    return {"home": sum(p for k, p in pmf.items() if k + L > 0),
            "push": sum(p for k, p in pmf.items() if k + L == 0),
            "away": sum(p for k, p in pmf.items() if k + L < 0)}


# t256: refuse rebinding the guard hook and the refused-family set (rulings B, C).
lock_module(__name__, {"NAIVE_FAIL_FAMILIES", "_NAIVE_FAIL_SHA256", "_naive_fail",
                       require_screen_only.__name__, checked_require.__name__, lock_module.__name__})
