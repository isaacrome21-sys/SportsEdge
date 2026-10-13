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
  explicit push mass on whole-number lines.
* F5 *game* total availability is per event only, read from the #2136 DK
  reconciliation (``f5_game_total_offering``). UNKNOWN when uninspected; never
  globally NOT_OFFERED. Model probabilities and market data stay separate.
* Settlement is UNVERIFIED_DK_RULES (fail closed): structural outcomes only,
  never a grade, until a live DK rules page is captured (``DK_RULES_REQUIRED``).
* Training games count only once FINAL and their linescore is available
  (recorded end time, else start + 6h) at or before the cutoff.
* Either-Pitcher ladders give P(max(A, B) > line) from two independent pitcher
  PMFs. Book proposition and void semantics are unvalidated, so the status stays
  RESEARCH_ONLY and settlement is a structural helper only.
* Inputs are means only. Disabled factors (ERA/form/rest/weather adjustments)
  are rejected if passed. ``play_authority`` is always False. Nothing here
  changes F5 ``eligible=false`` or ``config/deployments.json``.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from math import exp, isfinite, lgamma, log
from typing import Any, Mapping, Sequence

from .v7_distribution import V8_INDEPENDENT_TEAM_DISPERSION_R, calibrated_full_game_means

VERSION = "mlb_f5_team_total_ladder_v1_20261013"
F5_TEAM_TOTAL_MAIN_LINE = 1.5
F5_TEAM_TOTAL_LINES = (0.5, 1.5, 2.5, 3.5, 4.5)
SETTLEMENT_STATUS = "UNVERIFIED_DK_RULES"
DK_RULES_REQUIRED = (
    "F5 team total: action rule when the game is shortened, suspended or ends before 5 full innings "
    "(including a home team leading after 4.5)",
    "F5: whether listed-pitcher changes void the bet",
    "Either-Pitcher: the exact proposition (max of the two, either-over, or combined), and push on whole lines",
    "Either-Pitcher: void/action when one or both listed pitchers do not start, or are removed early",
    "Either-Pitcher: whether stats count from relief appearances",
)
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


FINAL_AVAILABILITY_BUFFER = timedelta(hours=6)


def final_available_at(game: Mapping[str, Any]) -> datetime | None:
    """When the FINAL linescore is known: recorded end time, else start + 6h buffer."""
    if game.get("final_at") is not None:
        return game["final_at"]
    if game.get("start") is None:
        return None
    return game["start"] + FINAL_AVAILABILITY_BUFFER


def is_trainable(game: Mapping[str, Any], as_of: datetime) -> bool:
    if str(game.get("status", "FINAL")).upper() != "FINAL":
        return False
    t = final_available_at(game)
    return t is not None and t <= as_of


def fit_f5_share(games: Sequence[Mapping[str, Any]], *, as_of: datetime) -> dict:
    """F5/regulation run ratio over games FINAL (and linescore available) by as_of."""
    prior = sorted((g for g in games if is_trainable(g, as_of) and g.get("completed_innings", 9) >= 9),
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
    if str(model_input.get("market", "F5_TEAM_TOTALS")).upper() != "F5_TEAM_TOTALS":
        raise F5LadderError("only F5_TEAM_TOTALS is priced here")
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
           "kind": "MODEL_PROBABILITY_ONLY", "market_baseline": "MISSING",
           "settlement_status": SETTLEMENT_STATUS,
           "main_line": F5_TEAM_TOTAL_MAIN_LINE, "f5_share": share,
           "dispersion_r": V8_INDEPENDENT_TEAM_DISPERSION_R, "teams": {}}
    for side, mu in (("AWAY", away_mu), ("HOME", home_mu)):
        pmf = nb_pmf(share * mu)
        out["teams"][side] = {"full_game_mean": mu, "f5_mean": share * mu,
                              "ladder": [_ou(pmf, x) for x in lines]}
    return out


def f5_game_total_offering(reconciliation: Mapping[str, Any] | None, *, event_id: str) -> dict:
    """Per-event F5 game-total offering from a #2136 DK reconciliation. Never universal.

    Only market availability is reported; no probability or price is produced here.
    """
    base = {"market": "F5_TOTALS", "event_id": event_id, "scope": "PER_EVENT", "market_baseline": "MISSING"}
    if not reconciliation:
        return {**base, "availability": "UNKNOWN", "reason": "EVENT_NOT_INSPECTED"}
    if str(reconciliation.get("event_id")) != str(event_id) or reconciliation.get("schema") != "DK_EVENT_COVERAGE_RECONCILIATION_V1":
        return {**base, "availability": "UNKNOWN", "reason": "LEDGER_EVENT_MISMATCH"}
    row = next((r for r in reconciliation.get("rows") or [] if r.get("market") == "F5_TOTALS"), None)
    if row is None:
        return {**base, "availability": "UNKNOWN", "reason": "MARKET_NOT_IN_LEDGER"}
    avail = row.get("availability")
    mapped = {"OFFERED_ON_THIS_EVENT": "OFFERED_ON_THIS_EVENT",
              "NOT_OFFERED_ON_THIS_EVENT": "NOT_OFFERED_ON_THIS_EVENT"}.get(avail, "UNKNOWN")
    return {**base, "availability": mapped, "ledger_availability": avail,
            "observed_at_utc": reconciliation.get("observed_at_utc")}


def _settled(structural: str, **extra: Any) -> dict:
    # Fail closed: the structural outcome is a research label, never a grade.
    return {"settlement_status": SETTLEMENT_STATUS, "structural_outcome": structural,
            "authoritative": False, "grade": None, **extra}


def settle_f5_team_total(*, team_f5_runs: int, line: float, side: str, completed_innings: float) -> dict:
    side = side.upper()
    if side not in {"OVER", "UNDER"}:
        raise F5LadderError("side must be OVER or UNDER")
    if completed_innings < 5:
        return _settled("SHORTENED_RULE_UNVERIFIED")
    if abs(team_f5_runs - line) < 1e-12:
        return _settled("PUSH")
    return _settled("WIN" if (team_f5_runs > line) == (side == "OVER") else "LOSS")


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
            "semantics": "MAX_OF_TWO_INDEPENDENT_PITCHERS", "settlement_status": SETTLEMENT_STATUS,
            "kind": "MODEL_PROBABILITY_ONLY", "market_baseline": "MISSING", "ladder": rows}


def settle_either_pitcher_max(*, away_value: float, home_value: float, line: float, side: str,
                              both_started: bool = True) -> dict:
    if not both_started:
        return _settled("PITCHER_DID_NOT_START_RULE_UNVERIFIED")
    m = max(away_value, home_value)
    if abs(m - line) < 1e-12:
        return _settled("PUSH")
    return _settled("WIN" if (m > line) == (side.upper() == "OVER") else "LOSS")
