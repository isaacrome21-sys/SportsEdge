"""F5 team-total ladders and Either-Pitcher ladders (research candidate).

Coherence with the full-game run model
--------------------------------------
The frozen full-game model (``v7_distribution``, independent team NB) scores
each team's regulation runs as NB(r=V8_INDEPENDENT_TEAM_DISPERSION_R, mean mu)
after ``calibrated_full_game_means``. NB is a Gamma(r, mu/r)-mixed Poisson. If
the inning-level intensity is shared within a team-game and a fraction ``s`` of
it falls in innings 1-5, then F5 | lam ~ Poisson(s*lam) and late | lam ~
Poisson((1-s)*lam). So F5 ~ NB(r, s*mu), and F5 + late reproduces the full-game
NB(r, mu) exactly (tested). No 5/9 scaling: ``s`` is the strictly-prior
empirical F5 run share (``fit_f5_share``).

Scope and guards
----------------
* F5 team totals: main 1.5, alternates 0.5..4.5, both OVER and UNDER, with
  explicit push mass on whole-number lines. The game does not settle (NO_ACTION)
  when fewer than 5 full innings are completed.
* The F5 *game* total is NOT_OFFERED_ON_DK and is refused here.
* Either-Pitcher ladders give P(max(A, B) > line) from two independent pitcher
  PMFs. Book proposition and void semantics are unvalidated, so the status stays
  RESEARCH_ONLY and settlement is a structural helper only.
* Inputs are means only. Disabled factors (ERA/form/rest/weather adjustments)
  are rejected if passed. ``play_authority`` is always False. Nothing here
  changes F5 ``eligible=false`` or ``config/deployments.json``.
"""
from __future__ import annotations

from datetime import datetime
from math import exp, isfinite, lgamma, log
from typing import Any, Mapping, Sequence

from .v7_distribution import V8_INDEPENDENT_TEAM_DISPERSION_R, calibrated_full_game_means

VERSION = "mlb_f5_team_total_ladder_v1_20261013"
F5_TEAM_TOTAL_MAIN_LINE = 1.5
F5_TEAM_TOTAL_LINES = (0.5, 1.5, 2.5, 3.5, 4.5)
F5_GAME_TOTAL_STATUS = "NOT_OFFERED_ON_DK"
DISABLED_FACTOR_KEYS = frozenset({"era_adj", "form_adj", "rest_adj", "weather_adj", "pitcher_form_adj",
                                  "bullpen_form_adj", "umpire_adj"})
MIN_SHARE_GAMES = 30
SUPPORT = 40


class F5LadderError(ValueError):
    pass


def _pos(v: Any, name: str) -> float:
    if isinstance(v, bool):
        raise F5LadderError(f"{name} must be numeric")
    try:
        x = float(v)
    except (TypeError, ValueError) as exc:
        raise F5LadderError(f"{name} must be numeric") from exc
    if not isfinite(x) or x <= 0:
        raise F5LadderError(f"{name} must be finite > 0")
    return x


def nb_pmf(mean: float, r: float = V8_INDEPENDENT_TEAM_DISPERSION_R, support: int = SUPPORT) -> list[float]:
    p = r / (r + mean)
    out = [exp(lgamma(k + r) - lgamma(r) - lgamma(k + 1) + r * log(p) + k * log(1 - p)) for k in range(support)]
    out[-1] += max(0.0, 1.0 - sum(out))
    return out


def fit_f5_share(games: Sequence[Mapping[str, Any]], *, as_of: datetime) -> dict:
    """Ratio of F5 runs to regulation runs over completed games strictly before as_of."""
    prior = sorted((g for g in games if g["start"] < as_of and g.get("completed_innings", 9) >= 9),
                   key=lambda g: (g["start"], str(g.get("game_id"))))
    if len(prior) < MIN_SHARE_GAMES:
        raise F5LadderError(f"F5 share requires >= {MIN_SHARE_GAMES} strictly-prior games")
    f5 = sum(int(g["away_f5"]) + int(g["home_f5"]) for g in prior)
    reg = sum(int(g["away_reg"]) + int(g["home_reg"]) for g in prior)
    if reg <= 0 or not 0 < f5 <= reg:
        raise F5LadderError("invalid F5 share history")
    return {"share": f5 / reg, "games": len(prior)}


def _ou(pmf: Sequence[float], line: float) -> dict:
    over = sum(p for k, p in enumerate(pmf) if k > line + 1e-12)
    push = sum(p for k, p in enumerate(pmf) if abs(k - line) < 1e-12)
    return {"line": line, "over": over, "under": 1.0 - over - push, "push": push}


def price_f5_team_totals(model_input: Mapping[str, Any]) -> dict:
    bad = DISABLED_FACTOR_KEYS & set(model_input)
    if bad:
        raise F5LadderError("disabled factors not allowed: " + ",".join(sorted(bad)))
    if str(model_input.get("market", "F5_TEAM_TOTALS")).upper() in {"F5_TOTALS", "F5_GAME_TOTAL"}:
        return {"status": "BLOCKED", "reason": F5_GAME_TOTAL_STATUS, "play_authority": False}
    share = _pos(model_input.get("f5_share"), "f5_share")
    if share >= 1:
        raise F5LadderError("f5_share must be < 1")
    away_mu, home_mu = calibrated_full_game_means(_pos(model_input.get("away_mean_runs"), "away_mean_runs"),
                                                  _pos(model_input.get("home_mean_runs"), "home_mean_runs"))
    lines = tuple(float(x) for x in model_input.get("lines", F5_TEAM_TOTAL_LINES))
    for x in lines:
        if not isfinite(x) or x < 0 or (x * 2) != int(x * 2):
            raise F5LadderError("lines must be >= 0 on half-run steps")
    out = {"version": VERSION, "status": "RESEARCH_ONLY", "play_authority": False,
           "main_line": F5_TEAM_TOTAL_MAIN_LINE, "f5_share": share,
           "dispersion_r": V8_INDEPENDENT_TEAM_DISPERSION_R, "teams": {}}
    for side, mu in (("AWAY", away_mu), ("HOME", home_mu)):
        pmf = nb_pmf(share * mu)
        out["teams"][side] = {"full_game_mean": mu, "f5_mean": share * mu,
                              "ladder": [_ou(pmf, x) for x in lines]}
    return out


def settle_f5_team_total(*, team_f5_runs: int, line: float, side: str, completed_innings: float) -> str:
    if completed_innings < 5:
        return "NO_ACTION"
    side = side.upper()
    if side not in {"OVER", "UNDER"}:
        raise F5LadderError("side must be OVER or UNDER")
    if abs(team_f5_runs - line) < 1e-12:
        return "PUSH"
    return "WIN" if (team_f5_runs > line) == (side == "OVER") else "LOSS"


def _pitcher_pmf(raw: Any, name: str) -> list[float]:
    if not isinstance(raw, Sequence) or len(raw) == 0:
        raise F5LadderError(f"{name} PMF required")
    pmf = [float(p) for p in raw]
    if any(not isfinite(p) or p < 0 for p in pmf) or abs(sum(pmf) - 1) > 1e-9:
        raise F5LadderError(f"{name} PMF must be a probability vector")
    return pmf


def either_pitcher_ladder(away_pmf: Sequence[float], home_pmf: Sequence[float], lines: Sequence[float]) -> dict:
    """P(max(A,B) > line), P(max == line) for each line; independent pitchers."""
    a, b = _pitcher_pmf(away_pmf, "away"), _pitcher_pmf(home_pmf, "home")
    n = max(len(a), len(b))
    a, b = a + [0.0] * (n - len(a)), b + [0.0] * (n - len(b))
    ca = [sum(a[: k + 1]) for k in range(n)]
    cb = [sum(b[: k + 1]) for k in range(n)]
    cmax = [ca[k] * cb[k] for k in range(n)]
    pmax = [cmax[0]] + [cmax[k] - cmax[k - 1] for k in range(1, n)]
    rows = [{"line": float(x), **{k: v for k, v in _ou(pmax, float(x)).items() if k != "line"}} for x in lines]
    return {"version": VERSION, "status": "RESEARCH_ONLY", "play_authority": False,
            "semantics": "MAX_OF_TWO_INDEPENDENT_PITCHERS", "book_settlement": "UNVALIDATED", "ladder": rows}


def settle_either_pitcher_max(*, away_value: float, home_value: float, line: float, side: str) -> str:
    m = max(away_value, home_value)
    if abs(m - line) < 1e-12:
        return "PUSH"
    return "WIN" if (m > line) == (side.upper() == "OVER") else "LOSS"
