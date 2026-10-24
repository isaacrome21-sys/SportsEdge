"""Live in-game repricing: current game state -> model probabilities.

GAME markets first (ML / SPREAD / TOTAL), per Isaac's Phase 6 spec.
Player props are NOT priced here -- see sportsedge.live_run_it for the
explicit NOT_WIRED reason codes.

Method (documented, verifiable, research-only):
  - The pregame score means (home_mean, away_mean) are the verified
    pregame estimates reconstructed as of kickoff
    (sportsedge.live_run_it pins the pregame context clock just before
    kickoff; see artifacts.free_models.score_means).
  - MLB: remaining scoring per team ~ independent Poisson with the
    pregame mean scaled by the fraction of that team's batting outs
    still remaining. Final score = current score + remaining draws.
    Extras: each team is granted one additional half-inning at its
    per-out pregame rate, re-evaluated every half-inning (stated
    assumption, validated in the harness replay).
  - NFL/CFB: remaining scoring follows the same Normal margin/total
    process as the pregame model (artifacts.free_models.model_probability),
    with means scaled by the fraction of regulation time remaining and
    standard deviations scaled by sqrt(f). At f = 1 (kickoff) the live
    repricing is EXACTLY the pregame model -- a unit-tested invariant.
    Overtime is BLOCKED (LIVE_OT_DYNAMICS_UNMODELED): sudden-death /
    alternating-possession dynamics are not modeled and a degenerate
    zero-time model would emit false certainties.

Market-blind: the live line/price NEVER enters the model -- only the
current state and the pregame means. This is required by LIVE_POLICY_V1's
forbidden-feature list. Isaac's supplied live line is used only to
compute EV against the model probability downstream.

State fields parsed but NOT priced (NOT_WIRED with reasons, surfaced on
every priced row):
  - MLB bases/outs/count, current batter/pitcher identities
  - NFL/CFB down/distance/yard line/possession/timeouts
See NOT_WIRED_LIVE_FIELDS below.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from math import erf, isfinite, sqrt
from pathlib import Path
from typing import Any, Mapping

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from artifacts.free_models import bounded, cdf as _normal_cdf, poisson

from .live_state import (
    FOOTBALL_REGULATION_SECONDS,
    FootballGameState,
    LiveStateError,
    MLBGameState,
)


class LiveRepriceError(ValueError):
    """Fail-closed repricing error. The message is the reason code."""


# State fields that are parsed into the state model and shown on research
# cards, but that do NOT enter pricing. Each carries an explicit reason.
NOT_WIRED_LIVE_FIELDS: tuple[tuple[str, str], ...] = (
    ("mlb_bases_outs_count",
     "LIVE_BASES_OUTS_COUNT_NOT_PRICED: within-inning run expectancy from "
     "bases/outs/count is not wired; repricing scales by team outs "
     "remaining only. Requires a validated base-out run-expectancy matrix "
     "from free play-by-play (queued)."),
    ("mlb_batter_pitcher",
     "LIVE_BATTER_PITCHER_NOT_PRICED: current batter/pitcher identities are "
     "parsed for display; matchup or bullpen adjustments are not wired."),
    ("football_down_distance_yardline_possession",
     "LIVE_EP_NOT_PRICED: down/distance/yard line/possession are parsed for "
     "display; no expected-points adjustment is wired. Requires a validated "
     "EP model trained on free play-by-play (queued behind the harness)."),
    ("football_timeouts",
     "LIVE_TIMEOUTS_NOT_PRICED: timeout and clock-management effects "
     "(hurry-up, kneel-downs) are not wired."),
    ("live_first_inning_markets",
     "LIVE_FIRST_INNING_DEFERRED: live NRFI/YRFI and other live first-inning "
     "derivatives are deferred until Phase 1 core first-inning work lands; "
     "not duplicated here."),
)


@dataclass(frozen=True)
class LiveReprice:
    sport: str
    market: str
    side: str
    line: float | None
    model_p: float
    push_p: float
    # Human-readable state summary used in the research card.
    state_summary: str
    # Fraction of the game remaining (time for football, team-outs for MLB).
    remaining_fraction: float
    home_mean: float
    away_mean: float
    # NOT_WIRED (field, reason) pairs that applied to this reprice.
    not_wired: tuple[tuple[str, str], ...] = field(default_factory=tuple)
    assumptions: tuple[str, ...] = field(default_factory=tuple)

    def validate(self) -> None:
        if not (0.0 <= self.model_p <= 1.0) or not isfinite(self.model_p):
            raise LiveRepriceError("MODEL_P_OUT_OF_RANGE")
        if not (0.0 <= self.push_p < 1.0) or not isfinite(self.push_p):
            raise LiveRepriceError("PUSH_P_OUT_OF_RANGE")


# ---------------------------------------------------------------------------
# MLB
# ---------------------------------------------------------------------------

def mlb_outs_used(state: MLBGameState) -> tuple[int, int]:
    """(away_outs_used, home_outs_used) from inning/half/outs. Fail closed."""
    if state.inning is None or state.half is None or state.outs is None:
        raise LiveRepriceError("LIVE_STATE_INCOMPLETE:inning/half/outs")
    inning = state.inning
    if inning < 1:
        raise LiveRepriceError("LIVE_STATE_INCOMPLETE:inning")
    if state.half == "top":
        # Away is batting now.
        return (inning - 1) * 3 + state.outs, (inning - 1) * 3
    # half == "bottom": away has finished this inning, home is batting.
    return inning * 3, (inning - 1) * 3 + state.outs


def mlb_remaining_means(state: MLBGameState, home_mean: float,
                        away_mean: float) -> tuple[float, float, float, str]:
    """Return (rem_home, rem_away, remaining_fraction, assumption_note)."""
    for name, value in (("home_mean", home_mean), ("away_mean", away_mean)):
        if not isfinite(value) or value < 0.2:
            raise LiveRepriceError(f"IMPLAUSIBLE_SCORE_MEAN:{name}")
    away_used, home_used = mlb_outs_used(state)
    if state.inning is not None and state.inning > 9:
        # Extras: one additional half-inning per team at the per-out
        # pregame rate, re-evaluated every half-inning (stated assumption).
        if state.half == "top":
            rem_away = away_mean * max(0, 3 - state.outs) / 27.0
            rem_home = away_mean * 0.0 + home_mean * 3 / 27.0
        else:
            rem_away = away_mean * 3 / 27.0
            rem_home = home_mean * max(0, 3 - state.outs) / 27.0
        note = ("EXTRAS_ONE_HALF_INNING_EACH_AT_PRE_GAME_RATE: "
                "stated assumption, re-evaluated each half-inning")
    else:
        rem_away = away_mean * max(0, 27 - away_used) / 27.0
        rem_home = home_mean * max(0, 27 - home_used) / 27.0
        note = "REMAINING_SCALED_BY_TEAM_OUTS_REMAINING"
        if rem_away == 0.0 and rem_home == 0.0 and state.is_live():
            # Regulation outs exhausted but the feed still says live
            # (e.g. between bottom 9th and top 10th): grant the extras
            # half-inning rather than emitting a degenerate tie.
            rem_away = away_mean * 3 / 27.0
            rem_home = home_mean * 3 / 27.0
            note = ("REGULATION_OUTS_EXHAUSTED_STILL_LIVE: "
                    "extras half-inning granted (stated assumption)")
    remaining_fraction = (max(0, 27 - away_used) + max(0, 27 - home_used)) / 54.0
    return rem_home, rem_away, min(1.0, remaining_fraction), note


def _mlb_market_probability(market: str, side: str, line: float | None,
                            home_score: int, away_score: int,
                            rem_home: float, rem_away: float
                            ) -> tuple[float, float]:
    """Poisson convolution of current score + remaining scoring.

    Mirrors artifacts.free_models.model_probability's MLB branch with the
    current score as an offset. A simulated regulation tie splits 0.5/0.5,
    the same stated approximation as the pregame model.
    """
    a, b = poisson(rem_home), poisson(rem_away)
    win = push = 0.0
    for h, ph in enumerate(a):
        for aw, pa in enumerate(b):
            hs, aws = home_score + h, away_score + aw
            if market == "TOTAL":
                score = hs + aws
                target = (score - line if side == "OVER" else line - score)
            else:
                score = (hs - aws if side == "HOME" else aws - hs)
                target = score + (line if market == "SPREAD" else 0)
            if target > 1e-9:
                win += ph * pa
            elif abs(target) <= 1e-9:
                push += ph * pa
    if market == "ML":
        win += push * 0.5
        push = 0.0
    return bounded(win, 0, 1), bounded(push, 0, 1)


def reprice_mlb(state: MLBGameState, home_mean: float, away_mean: float,
                market: str, side: str, line: float | None = None) -> LiveReprice:
    market = str(market).upper()
    side = str(side).upper()
    if market not in ("ML", "SPREAD", "TOTAL"):
        raise LiveRepriceError(f"UNSUPPORTED_LIVE_MARKET:{market}")
    if market == "TOTAL" and side not in ("OVER", "UNDER"):
        raise LiveRepriceError("SIDE_MARKET_MISMATCH")
    if market in ("ML", "SPREAD") and side not in ("HOME", "AWAY"):
        raise LiveRepriceError("SIDE_MARKET_MISMATCH")
    if market != "ML" and line is None:
        raise LiveRepriceError("LINE_REQUIRED")
    if not state.is_live():
        raise LiveRepriceError(f"GAME_NOT_LIVE:{state.status}")
    state.validate()

    rem_home, rem_away, frac, note = mlb_remaining_means(state, home_mean, away_mean)
    model_p, push_p = _mlb_market_probability(
        market, side, line, state.home_score, state.away_score, rem_home, rem_away)
    summary = (f"{state.away_team} {state.away_score} @ {state.home_team} "
               f"{state.home_score}, {state.half} {state.inning}, {state.outs} out")
    out = LiveReprice(
        sport="MLB", market=market, side=side, line=line,
        model_p=model_p, push_p=push_p, state_summary=summary,
        remaining_fraction=frac, home_mean=home_mean, away_mean=away_mean,
        not_wired=(NOT_WIRED_LIVE_FIELDS[0], NOT_WIRED_LIVE_FIELDS[1],
                   NOT_WIRED_LIVE_FIELDS[4]),
        assumptions=(
            note,
            "REMAINING_RUNS_INDEPENDENT_POISSON_AT_PRE_GAME_RATE",
            "REGULATION_TIE_SPLITS_HALF: stated approximation, as pregame",
            "MARKET_BLIND: live line/price never enters the model",
        ),
    )
    out.validate()
    return out


# ---------------------------------------------------------------------------
# NFL / CFB
# ---------------------------------------------------------------------------

# (sd_total, sd_margin) mirror artifacts.free_models.PRIORS; kept local so a
# future priors change cannot silently alter live repricing without updating
# the f=1 equivalence test.
_FOOTBALL_SDS = {
    "NFL": (13.5, 13.7),
    "CFB": (18.5, 19.0),
}


def football_remaining_fraction(state: FootballGameState) -> float:
    """Fraction of regulation time remaining. Fail closed."""
    if state.quarter is None or state.clock_seconds is None:
        raise LiveRepriceError("LIVE_STATE_INCOMPLETE:quarter/clock")
    if state.is_overtime():
        raise LiveRepriceError(
            "LIVE_OT_DYNAMICS_UNMODELED: overtime sudden-death / "
            "alternating-possession scoring is not modeled; a degenerate "
            "zero-time model would emit false certainties")
    elapsed = (state.quarter - 1) * 900 + (900 - state.clock_seconds)
    if elapsed < 0 or elapsed > FOOTBALL_REGULATION_SECONDS:
        raise LiveRepriceError("LIVE_STATE_INCOMPLETE:clock_implausible")
    return max(0.0, (FOOTBALL_REGULATION_SECONDS - elapsed)
               / FOOTBALL_REGULATION_SECONDS)


def _normal_market_probability(market: str, side: str, line: float | None,
                               mean: float, sd: float) -> tuple[float, float]:
    """Normal margin/total read-out.

    Mirrors artifacts.free_models.model_probability's non-MLB branch with
    an explicit sd (the pregame branch uses the fixed prior sds). The
    f=1 equivalence with the pregame model is unit-tested.
    """
    if market == "TOTAL":
        sign = 1 if side == "OVER" else -1
        decision = line
    else:
        sign = 1
        decision = -line if market == "SPREAD" else 0
    whole = market != "ML" and line is not None and float(line).is_integer()
    push = (_normal_cdf(decision + 0.5, mean, sd)
            - _normal_cdf(decision - 0.5, mean, sd)) if whole else 0.0
    cut = decision + (0.5 if whole else 0)
    win = (1 - _normal_cdf(cut, mean, sd)) if sign > 0 else _normal_cdf(
        decision - (0.5 if whole else 0), mean, sd)
    return bounded(win, 0, 1), bounded(push, 0, 1)


def reprice_football(state: FootballGameState, home_mean: float,
                     away_mean: float, market: str, side: str,
                     line: float | None = None) -> LiveReprice:
    market = str(market).upper()
    side = str(side).upper()
    if market not in ("ML", "SPREAD", "TOTAL"):
        raise LiveRepriceError(f"UNSUPPORTED_LIVE_MARKET:{market}")
    if market == "TOTAL" and side not in ("OVER", "UNDER"):
        raise LiveRepriceError("SIDE_MARKET_MISMATCH")
    if market in ("ML", "SPREAD") and side not in ("HOME", "AWAY"):
        raise LiveRepriceError("SIDE_MARKET_MISMATCH")
    if market != "ML" and line is None:
        raise LiveRepriceError("LINE_REQUIRED")
    if not state.is_live():
        raise LiveRepriceError(f"GAME_NOT_LIVE:{state.status}")
    state.validate()

    try:
        sd_total, sd_margin = _FOOTBALL_SDS[state.sport]
    except KeyError as exc:
        raise LiveRepriceError(f"UNSUPPORTED_SPORT:{state.sport}") from exc
    for name, value in (("home_mean", home_mean), ("away_mean", away_mean)):
        if not isfinite(value) or value < 0.2:
            raise LiveRepriceError(f"IMPLAUSIBLE_SCORE_MEAN:{name}")

    frac = football_remaining_fraction(state)
    scale = sqrt(frac)
    margin_now = state.home_score - state.away_score
    total_now = state.home_score + state.away_score
    if market == "TOTAL":
        mean = total_now + (home_mean + away_mean) * frac
        sd = sd_total * scale
    else:
        signed = 1.0 if side == "HOME" else -1.0
        mean = signed * margin_now + signed * (home_mean - away_mean) * frac
        sd = sd_margin * scale
        # For ML/SPREAD the read-out is phrased from the selected side's
        # perspective; TOTAL keeps the natural orientation.
    if market == "TOTAL":
        model_p, push_p = _normal_market_probability(
            market, side, line, mean, sd)
    elif state.sport == "NFL":
        # Lane 1 (#2384): NFL sides price on the same key-number margin
        # distribution as pregame (artifacts/free_models.model_probability),
        # so the at-kickoff == pregame invariant holds exactly.
        from sportsedge.sports.nfl import side_margin_model as nfl_side_model
        home_final = margin_now + (home_mean - away_mean) * frac
        nfl_sd = nfl_side_model.MARGIN_SD * scale
        if not (nfl_sd > 0):
            raise LiveRepriceError("NFL_SIDE_NO_TIME_REMAINING")
        try:
            model_p, push_p, _ = nfl_side_model.price_side(
                market, side, line, home_final, sd=nfl_sd)
        except ValueError as exc:
            raise LiveRepriceError(str(exc)) from exc
    else:
        # mean is already oriented to the selected side, so the read-out
        # always uses the HOME-oriented branch with the original line
        # (decision = -line for SPREAD, 0 for ML -- same as pregame).
        model_p, push_p = _normal_market_probability(
            market, "HOME", line, mean, sd)

    clock = state.clock_display or f"{state.clock_seconds}s"
    summary = (f"{state.away_team} {state.away_score} @ {state.home_team} "
               f"{state.home_score}, Q{state.quarter} {clock}")
    out = LiveReprice(
        sport=state.sport, market=market, side=side, line=line,
        model_p=model_p, push_p=push_p, state_summary=summary,
        remaining_fraction=frac, home_mean=home_mean, away_mean=away_mean,
        not_wired=(NOT_WIRED_LIVE_FIELDS[2], NOT_WIRED_LIVE_FIELDS[3],
                   NOT_WIRED_LIVE_FIELDS[4]),
        assumptions=(
            "REMAINING_SCORING_NORMAL_MARGIN_TOTAL_PROCESS",
            "MEAN_SCALED_BY_TIME_REMAINING_SD_SCALED_BY_SQRT",
            "AT_KICKOFF_EQUALS_PREGAME_MODEL: unit-tested invariant",
            "OVERTIME_BLOCKED_NOT_MODELED",
            "MARKET_BLIND: live line/price never enters the model",
        ),
    )
    out.validate()
    return out


__all__ = [
    "NOT_WIRED_LIVE_FIELDS",
    "LiveReprice",
    "LiveRepriceError",
    "football_remaining_fraction",
    "mlb_outs_used",
    "mlb_remaining_means",
    "reprice_football",
    "reprice_mlb",
]
