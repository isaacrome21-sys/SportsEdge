"""NFL game-scoring research engines (Grok lane, SCREEN only).

Families (DK keys): TEAM_TOTAL_TOUCHDOWNS, TOTAL_TOUCHDOWNS (game),
WINNING_MARGIN (bands), RACE_TO_POINTS (10/15/20/25/30).

Inputs: per-game rows built from the official nflverse release
(play_by_play_{season}.csv.gz + nfldata games.csv), hashed in
research/grok_nfl_game_scoring_screen_20261022/SOURCES.json.  No quotes,
no market inputs, no EV.  Point-in-time: only games whose date is
strictly before the priced game's date are used.

Construction (declared a priori):
  team TD rate   off/def TDs per game, current + previous season games
                 (previous season down-weighted PREV_W), shrunk toward the
                 league mean with SHRINK_G pseudo-games.
  lambda         league_side_mean * (off/league) * (opp_def/league),
                 side = home/away league means (home edge carried there).
  TD counts      Poisson(lambda); game total = Poisson(sum).
  margin         mu = (pts ratings, same construction) home - away;
                 margin pmf = empirical PIT residual distribution of
                 (actual - mu) from earlier seasons, shifted by mu.
  race-to-N      P(neither) = PIT league rate; P(home first | someone)
                 = logistic(RACE_BETA[N] * mu_margin + home_logit_N),
                 both fitted on strictly earlier seasons only.
Fail-closed: unknown team, < MIN_TEAM_GAMES history, empty league pool,
non-PIT rows, or degenerate probabilities raise NflGameScoringError.

Governance: SCREEN / RESEARCH_UNSCREENED, NOT_VALIDATED, eligible=false,
play_allowed=false.  Not in any owner registry.  Research only.
"""
from __future__ import annotations

import math
from datetime import date as _date
from typing import Any, Iterable, Mapping, Sequence

ENGINE_ID = "NFL_GAME_SCORING_EMPIRICAL"
ENGINE_VERSION = "nfl_game_scoring_empirical_v1_20261022"
GOVERNANCE = {"state": "SCREEN", "validation_status": "NOT_VALIDATED",
              "eligible": False, "play_allowed": False}
PREV_W = 0.5
SHRINK_G = 4.0
MIN_TEAM_GAMES = 3
MAX_TD = 15
RACE_NS = (10, 15, 20, 25, 30)
MARGIN_BANDS = ((1, 6), (7, 12), (13, 18), (19, 24), (25, 30), (31, 99))


class NflGameScoringError(ValueError):
    pass


def _pit(rows: Iterable[Mapping[str, Any]], date: str) -> list:
    if not isinstance(date, str) or len(date) != 10:
        raise NflGameScoringError("GAME_DATE_REQUIRED_YYYY-MM-DD")
    out = []
    for r in rows:
        d = r.get("date")
        if not isinstance(d, str) or len(d) != 10:
            raise NflGameScoringError("HISTORY_DATE_INVALID")
        if d < date:
            out.append(r)
    if not out:
        raise NflGameScoringError("EMPTY_LEAGUE_POOL")
    return out


def _poisson(lam: float) -> list:
    if not (lam > 0 and math.isfinite(lam)):
        raise NflGameScoringError("DEGENERATE_LAMBDA")
    p = [math.exp(-lam)]
    for k in range(1, MAX_TD + 1):
        p.append(p[-1] * lam / k)
    p[-1] += max(0.0, 1.0 - math.fsum(p))
    return p


def _team_rating(hist, team, season, key_for, key_against):
    """Shrunk per-game for/against for team (current + prev season)."""
    sf = sa = w = 0.0
    n_cur = 0
    for r in hist:
        if r["season"] not in (season, season - 1):
            continue
        for side, opp in (("home", "away"), ("away", "home")):
            if r[side] != team:
                continue
            wt = 1.0 if r["season"] == season else PREV_W
            sf += wt * r[f"{side}_{key_for}"]
            sa += wt * r[f"{opp}_{key_for}"]
            w += wt
            n_cur += 1
    if n_cur < MIN_TEAM_GAMES:
        raise NflGameScoringError(f"TEAM_HISTORY_INSUFFICIENT:{team}:{n_cur}")
    return sf, sa, w


def _league(hist, season, key):
    pool = [r for r in hist if r["season"] in (season, season - 1)]
    if not pool:
        raise NflGameScoringError("EMPTY_LEAGUE_POOL")
    h = sum(r[f"home_{key}"] for r in pool) / len(pool)
    a = sum(r[f"away_{key}"] for r in pool) / len(pool)
    return h, a


def _finite_num(v) -> bool:
    return (isinstance(v, (int, float)) and not isinstance(v, bool)
            and math.isfinite(v))


def _check_inputs(hist, home, away, season, key):
    if home == away:
        raise NflGameScoringError(f"HOME_EQUALS_AWAY:{home!r}")
    if not isinstance(season, int) or isinstance(season, bool):
        raise NflGameScoringError(f"SEASON_INVALID:{season!r}")
    for r in hist:
        if r.get("season") not in (season, season - 1):
            continue
        for f in (f"home_{key}", f"away_{key}"):
            if not _finite_num(r.get(f)):
                raise NflGameScoringError(f"HISTORY_VALUE_INVALID:{f}:{r.get(f)!r}")


def expected(hist, home, away, season, key):
    _check_inputs(hist, home, away, season, key)
    lh, la = _league(hist, season, key)
    lm = (lh + la) / 2.0
    if lm <= 0:
        raise NflGameScoringError("DEGENERATE_LEAGUE_MEAN")
    out = {}
    for t in (home, away):
        f, a, w = _team_rating(hist, t, season, key, None)
        out[t] = ((f + SHRINK_G * lm) / (w + SHRINK_G) / lm,
                  (a + SHRINK_G * lm) / (w + SHRINK_G) / lm)
    return (lh * out[home][0] * out[away][1],
            la * out[away][0] * out[home][1])


def _parse_date(d, code: str) -> _date:
    """Strict YYYY-MM-DD via date.fromisoformat (round-trip checked)."""
    try:
        if not isinstance(d, str) or len(d) != 10:
            raise ValueError
        out = _date.fromisoformat(d)
        if out.isoformat() != d:
            raise ValueError
    except ValueError:
        raise NflGameScoringError(
            f"{code}:{d!r} (GAME_DATE_REQUIRED_YYYY-MM-DD)") from None
    return out


def season_for_date(d: _date) -> int:
    """NFL season label: games Mar-Dec belong to that year; Jan-Feb
    (late regular season / playoffs) to the previous year."""
    return d.year if d.month >= 3 else d.year - 1


def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _validate_history(history) -> list:
    rows, seen = list(history), set()
    for r in rows:
        for f in ("game_id", "home", "away"):
            if not isinstance(r.get(f), str) or not r.get(f):
                raise NflGameScoringError(f"HISTORY_VALUE_INVALID:{f}")
        if not _is_int(r.get("season")):
            raise NflGameScoringError("HISTORY_VALUE_INVALID:season")
        for f in ("home_td", "away_td", "home_pts", "away_pts"):
            v = r.get(f)
            ok = (_is_int(v) or (isinstance(v, float) and math.isfinite(v)
                                 and v == math.floor(v)))
            if not ok or v < 0:
                raise NflGameScoringError(f"HISTORY_VALUE_INVALID:{f}:{v!r}")
        if r["game_id"] in seen:
            raise NflGameScoringError(f"HISTORY_DUPLICATE_GAME_ID:{r['game_id']}")
        seen.add(r["game_id"])
        if r["home"] == r["away"]:
            raise NflGameScoringError(f"HISTORY_HOME_EQUALS_AWAY:{r['game_id']}")
        d = _parse_date(r.get("date"), "HISTORY_DATE_INVALID")
        if season_for_date(d) != r["season"]:
            raise NflGameScoringError(
                f"HISTORY_SEASON_DATE_MISMATCH:{r['game_id']}")
    return rows


def price_tds(history, *, home, away, season, date) -> dict:
    d = _parse_date(date, "GAME_DATE_INVALID")
    if home == away:
        raise NflGameScoringError(f"HOME_EQUALS_AWAY:{home!r}")
    if not _is_int(season) or season_for_date(d) != season:
        raise NflGameScoringError(f"SEASON_DATE_MISMATCH:{season!r}:{date}")
    hist = _pit(_validate_history(history), date)
    lh, la = expected(hist, home, away, season, "td")
    ph, pa = _poisson(lh), _poisson(la)
    tot = _poisson(lh + la)
    return {"engine": ENGINE_ID, "version": ENGINE_VERSION, **GOVERNANCE,
            "lambda_home": lh, "lambda_away": la,
            "home_td_pmf": ph, "away_td_pmf": pa, "total_td_pmf": tot}


def p_over(pmf: Sequence[float], line: float) -> float:
    if not (_finite_num(line) and line == math.floor(line) + 0.5 and line > 0):
        raise NflGameScoringError("LINE_MUST_BE_POSITIVE_HALF_POINT")
    if int(math.floor(line)) + 1 >= len(pmf):
        # t235: beyond the pmf support (tail folded into the last cell) the
        # answer would be a manufactured exact 0.0 -> refuse.
        raise NflGameScoringError(f"LINE_ABOVE_SUPPORT:{line}")
    return math.fsum(pmf[int(math.floor(line)) + 1:])


def margin_mu(hist, home, away, season) -> float:
    lh, la = expected(hist, home, away, season, "pts")
    return lh - la


def residuals(history, season_before: int, mu_fn) -> list:
    """PIT residuals actual-mu over seasons < season_before."""
    res = []
    for r in history:
        if r["season"] >= season_before:
            continue
        try:
            mu = mu_fn(r)
        except NflGameScoringError:
            continue
        res.append(r["home_pts"] - r["away_pts"] - mu)
    if len(res) < 100:
        raise NflGameScoringError("RESIDUAL_POOL_INSUFFICIENT")
    return res


def margin_band_probs(mu: float, res: Sequence[float]) -> dict:
    """{('H'|'A', lo, hi): p} plus 'TIE'; empirical residual shift,
    rounded to integer margins."""
    if not _finite_num(mu):
        raise NflGameScoringError(f"MARGIN_MU_NONFINITE:{mu!r}")
    res = list(res)
    if len(res) < 100:                       # same floor as residuals()
        raise NflGameScoringError("RESIDUAL_POOL_INSUFFICIENT")
    if not all(_finite_num(e) for e in res):
        raise NflGameScoringError("RESIDUAL_VALUE_INVALID")
    counts: dict = {}
    for e in res:
        m = int(round(mu + e))
        if m == 0:
            k = "TIE"
        else:
            side = "H" if m > 0 else "A"
            a = abs(m)
            k = next((side, lo, hi) for lo, hi in MARGIN_BANDS if lo <= a <= hi)
        counts[k] = counts.get(k, 0) + 1
    n = len(res)
    keys = [(s, lo, hi) for s in "HA" for lo, hi in MARGIN_BANDS] + ["TIE"]
    # add-one smoothing so no observed band is ever priced at 0
    return {k: (counts.get(k, 0) + 1) / (n + len(keys)) for k in keys}


def _logistic(x):
    return 1.0 / (1.0 + math.exp(-x))


def fit_race(train: Sequence[tuple], n_iter: int = 200) -> tuple:
    """train: [(mu_margin, home_first:0/1)] -> (beta, intercept) by
    Newton logistic regression; fail-closed on tiny pools."""
    if len(train) < 100:
        raise NflGameScoringError("RACE_TRAIN_INSUFFICIENT")
    b = c = 0.0
    for _ in range(n_iter):
        g0 = g1 = h00 = h01 = h11 = 0.0
        for x, y in train:
            p = _logistic(b * x + c)
            g0 += (y - p) * x; g1 += y - p
            w = p * (1 - p)
            h00 += w * x * x; h01 += w * x; h11 += w
        det = h00 * h11 - h01 * h01
        if det <= 0:
            raise NflGameScoringError("RACE_FIT_DEGENERATE")
        b += (h11 * g0 - h01 * g1) / det
        c += (h00 * g1 - h01 * g0) / det
    return b, c


def race_probs(mu: float, fit: tuple, p_neither: float) -> dict:
    if not _finite_num(mu):
        raise NflGameScoringError(f"RACE_MU_NONFINITE:{mu!r}")
    if not (isinstance(fit, tuple) and len(fit) == 2 and all(_finite_num(x) for x in fit)):
        raise NflGameScoringError("RACE_FIT_NONFINITE")
    if not (_finite_num(p_neither) and 0.0 <= p_neither < 1.0):
        raise NflGameScoringError("RACE_NEITHER_INVALID")
    ph = _logistic(fit[0] * mu + fit[1])
    return {"H": (1 - p_neither) * ph, "A": (1 - p_neither) * (1 - ph),
            "NEITHER": p_neither}
