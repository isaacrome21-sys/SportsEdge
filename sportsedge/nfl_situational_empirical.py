"""NFL situational game-market research engine (Grok lane, SCREEN only).

Families: SAFETY (any safety in the game, yes/no), DST_TD (any defensive or
special-teams touchdown in the game, yes/no), FIRST_SCORE (home / away scores
first), LARGEST_LEAD (largest lead by either team, overtime included) and
BOTH_TEAMS_TO_SCORE_N (both teams score N+ points, N in 10/15/20/25/30).

Main already has path read-outs for some of these
(core/simulate/situational.py) that need simulated scoring paths, which the
canonical path does not have. This engine supplies an empirical game-level
distribution instead; it does not replace or edit those read-outs.

Inputs: per-game rows built from the nflverse play_by_play_{season}.csv.gz
releases and games.csv already on the box, hashed in
research/grok_nfl_situational_screen_20261023/SOURCES.json.  No quotes, no
market inputs, no EV.  Point-in-time: team ratings use only games dated
strictly before the priced game; outcome pools use only strictly earlier
seasons.

Construction (declared a priori, nothing fitted):
  points rating  team points for/against per game, current season weight 1 +
                 previous season PREV_W, shrunk to the league mean with
                 SHRINK_G pseudo-games; mu_home = L_h + (off_h-L) + (def_a-L).
  SAFETY/DST_TD  per-side Poisson rate L_e * (team_for/L_e) * (opp_against/L_e)
                 with RARE_SHRINK_G pseudo-games; P(yes) = 1 - exp(-sum).
  FIRST_SCORE    P(home first | any score) = mu_home / (mu_home + mu_away).
  LARGEST_LEAD   earlier-season pool pmf shifted by LEAD_BETA*(|mu_h-mu_a| - LEAD_REF).
  BOTH_TEAMS_N   independent sides: earlier-season home (away) points pmf
                 shifted by mu - pool mean; P = P(home>=N) * P(away>=N).
Fail-closed: unknown family/N, malformed rows, < MIN_TEAM_GAMES history, empty
pools, non-finite values or a probability of exactly 0 or 1 raise NflSituationalError.

Governance: SCREEN, NOT_VALIDATED, eligible=false, play_allowed=false.
Research only.
"""
from __future__ import annotations

import math
from typing import Any, Iterable, Mapping

from sportsedge.screen_only_guard import require_screen_only

ENGINE_ID = "NFL_SITUATIONAL_EMPIRICAL"
ENGINE_VERSION = "nfl_situational_empirical_v1_20261023"
GOVERNANCE = {"state": "SCREEN", "validation_status": "NOT_VALIDATED",
              "eligible": False, "play_allowed": False}
FAMILIES = ("SAFETY", "DST_TD", "FIRST_SCORE", "LARGEST_LEAD", "BOTH_TEAMS_TO_SCORE_N")
BOTH_NS = (10, 15, 20, 25, 30)
PREV_W = 0.5
SHRINK_G = 6.0
RARE_SHRINK_G = 30.0
MIN_TEAM_GAMES = 3
LEAD_BETA = 0.5
LEAD_REF = 3.0
# SCREEN_WORSE_THAN_NAIVE in research/grok_nfl_situational_screen_20261023/
# screen_results_v1.json and v2.json; refused with a coded NAIVE_FAIL.
NAIVE_FAIL_FAMILIES = frozenset({"LARGEST_LEAD", "BOTH_TEAMS_TO_SCORE_N_10"})
_INT = ("season", "home_pts", "away_pts", "largest_lead", "safety_h", "safety_a",
        "dst_td_h", "dst_td_a")


class NflSituationalError(ValueError):
    pass


def _date(v, what):
    if not isinstance(v, str) or len(v) != 10 or v[4] != "-" or v[7] != "-":
        raise NflSituationalError(f"{what}_DATE_INVALID")
    return v


def _clean(history):
    out = []
    for r in history:
        try:
            row = {"date": _date(r["date"], "HISTORY"), "home": r["home"], "away": r["away"],
                   "first_score": r["first_score"]}
            for k in _INT:
                v = r[k]
                if isinstance(v, bool) or not isinstance(v, int) or v < 0:
                    raise NflSituationalError(f"MALFORMED_{k.upper()}")
                row[k] = v
        except KeyError as e:
            raise NflSituationalError(f"HISTORY_FIELD_MISSING:{e.args[0]}") from None
        if row["first_score"] not in ("H", "A", "NONE"):
            raise NflSituationalError("MALFORMED_FIRST_SCORE")
        out.append(row)
    return out


def _pmf(vals):
    out: dict = {}
    for v in vals:
        out[v] = out.get(v, 0.0) + 1.0 / len(vals)
    return out


def _shift(pmf, d):
    if not math.isfinite(d):
        raise NflSituationalError("NON_FINITE_SHIFT")
    lo = math.floor(d); w = d - lo; out: dict = {}
    for k, p in pmf.items():
        for kk, pp in ((k + lo, p * (1 - w)), (k + lo + 1, p * w)):
            kk = max(kk, 0)
            out[kk] = out.get(kk, 0.0) + pp
    return {k: v for k, v in out.items() if v > 0}


def _rating(pit, team, season, fh, fa, shrink):
    """(for, against) per game for team; fh/fa = home-side / away-side columns."""
    f = a = w = 0.0
    tot = sum(r[fh] + r[fa] for r in pit) / (2 * len(pit))
    for r in pit:
        wt = 1.0 if int(r["season"]) == season else PREV_W
        if r["home"] == team:
            f += wt * r[fh]; a += wt * r[fa]; w += wt
        elif r["away"] == team:
            f += wt * r[fa]; a += wt * r[fh]; w += wt
    if w < MIN_TEAM_GAMES * PREV_W:
        raise NflSituationalError(f"TEAM_HISTORY_INSUFFICIENT:{team}")
    return (f + shrink * tot) / (w + shrink), (a + shrink * tot) / (w + shrink), tot


def _family_key(family, n):
    return family if family != "BOTH_TEAMS_TO_SCORE_N" else f"{family}_{n}"


def price_situational(history: Iterable[Mapping[str, Any]], *, family: str, date: str,
                      season: int, home: str, away: str, n: int | None = None) -> dict:
    """Pricing entry point: NAIVE_FAIL families refuse with a coded error."""
    if family in FAMILIES and _family_key(family, n) in NAIVE_FAIL_FAMILIES:
        raise NflSituationalError(f"NAIVE_FAIL:{_family_key(family, n)}")
    return _price(history, family=family, date=date, season=season, home=home, away=away, n=n)


def price_situational_unrestricted(history: Iterable[Mapping[str, Any]], *, family: str,
                                   date: str, season: int, home: str, away: str,
                                   n: int | None = None) -> dict:
    """Screen-only: all families incl. NAIVE_FAIL. Guarded by screen_only()."""
    require_screen_only("price_situational_unrestricted")
    out = _price(history, family=family, date=date, season=season, home=home, away=away, n=n)
    out["screen_only_unrestricted"] = True
    return out


def _price(history: Iterable[Mapping[str, Any]], *, family: str, date: str,
           season: int, home: str, away: str, n: int | None = None) -> dict:
    if family not in FAMILIES:
        raise NflSituationalError(f"UNKNOWN_FAMILY:{family}")
    if isinstance(season, bool) or not isinstance(season, int):
        raise NflSituationalError("SEASON_REQUIRED_INT")
    _date(date, "GAME")
    if not isinstance(home, str) or not isinstance(away, str) or not home or home == away:
        raise NflSituationalError("TEAMS_INVALID")
    if family == "BOTH_TEAMS_TO_SCORE_N":
        if isinstance(n, bool) or n not in BOTH_NS:
            raise NflSituationalError("N_NOT_SUPPORTED")
    elif n is not None:
        raise NflSituationalError("N_ONLY_FOR_BOTH_TEAMS")
    rows = _clean(history)
    pit = [r for r in rows if r["date"] < date and r["season"] in (season, season - 1)]
    pool = [r for r in rows if r["season"] < season]
    if not pit:
        raise NflSituationalError("EMPTY_RATING_POOL")
    if not pool:
        raise NflSituationalError("EMPTY_OUTCOME_POOL")
    out = {"engine_id": ENGINE_ID, "engine_version": ENGINE_VERSION, "family": family,
           "governance": dict(GOVERNANCE)}
    if family in ("SAFETY", "DST_TD"):
        c = "safety" if family == "SAFETY" else "dst_td"
        hf, ha, L = _rating(pit, home, season, f"{c}_h", f"{c}_a", RARE_SHRINK_G)
        af, aa, _ = _rating(pit, away, season, f"{c}_h", f"{c}_a", RARE_SHRINK_G)
        if not L > 0:
            raise NflSituationalError("DEGENERATE_LEAGUE_RATE")
        lam = hf * aa / L + af * ha / L
        out["p_yes"] = 1.0 - math.exp(-lam)
        _no_certainty(out)
        return out
    L_h = sum(r["home_pts"] for r in pit) / len(pit)
    L_a = sum(r["away_pts"] for r in pit) / len(pit)
    hf, ha, L = _rating(pit, home, season, "home_pts", "away_pts", SHRINK_G)
    af, aa, _ = _rating(pit, away, season, "home_pts", "away_pts", SHRINK_G)
    mu_h = L_h + (hf - L) + (aa - L); mu_a = L_a + (af - L) + (ha - L)
    if not (mu_h > 0 and mu_a > 0):
        raise NflSituationalError("DEGENERATE_MU")
    out.update(mu_home=mu_h, mu_away=mu_a)
    if family == "FIRST_SCORE":
        none = sum(1 for r in pool if r["first_score"] == "NONE") / len(pool)
        ph = mu_h / (mu_h + mu_a)
        # Conditional on any score; the pool's scoreless-game rate is reported
        # separately (DK settles a scoreless game outside home/away).
        out["probs"] = {"home": ph, "away": 1 - ph}
        out["pool_scoreless_rate"] = none
    elif family == "LARGEST_LEAD":
        out["pmf"] = _shift(_pmf([r["largest_lead"] for r in pool]),
                            LEAD_BETA * (abs(mu_h - mu_a) - LEAD_REF))
    else:
        hp = [r["home_pts"] for r in pool]; ap = [r["away_pts"] for r in pool]
        hpmf = _shift(_pmf(hp), mu_h - sum(hp) / len(hp))
        apmf = _shift(_pmf(ap), mu_a - sum(ap) / len(ap))
        p = sum(v for k, v in hpmf.items() if k >= n) * sum(v for k, v in apmf.items() if k >= n)
        out.update(n=n, p_yes=p)
    _no_certainty(out)
    return out


def _no_certainty(out: dict) -> None:
    vals = [out["p_yes"]] if "p_yes" in out else list(out.get("probs", {}).values())
    for v in vals:
        if not (math.isfinite(v) and 0.0 < v < 1.0):
            raise NflSituationalError("DEGENERATE_PROBABILITY")


def lead_over_under(priced: dict, line) -> dict:
    if priced.get("family") != "LARGEST_LEAD":
        raise NflSituationalError("NOT_LARGEST_LEAD")
    if isinstance(line, bool) or not isinstance(line, (int, float)) or not math.isfinite(line) \
            or abs(line * 2 - round(line * 2)) > 1e-9 or line < 0:
        raise NflSituationalError("LINE_INVALID")
    pmf = priced["pmf"]
    return {"over": sum(p for k, p in pmf.items() if k > line),
            "push": sum(p for k, p in pmf.items() if k == line),
            "under": sum(p for k, p in pmf.items() if k < line)}
