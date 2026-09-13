from __future__ import annotations

from dataclasses import dataclass, asdict
import hashlib
import json
import math
from typing import Any, Iterable, Mapping, Sequence


class MLBRefinementError(ValueError):
    pass


def _finite(value: Any, field: str, *, lo: float | None = None, hi: float | None = None) -> float:
    if isinstance(value, bool):
        raise MLBRefinementError(f"{field} must be numeric")
    try:
        x = float(value)
    except (TypeError, ValueError) as exc:
        raise MLBRefinementError(f"{field} must be numeric") from exc
    if not math.isfinite(x):
        raise MLBRefinementError(f"{field} must be finite")
    if lo is not None and x < lo:
        raise MLBRefinementError(f"{field} below minimum")
    if hi is not None and x > hi:
        raise MLBRefinementError(f"{field} above maximum")
    return x


def _clip(x: float, lo: float, hi: float) -> float:
    return min(hi, max(lo, x))


def _sha(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


@dataclass(frozen=True)
class VerifiedSelection:
    market: str
    entity: str
    side: str
    line: float
    american_odds: int
    sportsbook: str
    observed_at: str

    @property
    def identity_key(self) -> str:
        return _sha(asdict(self))


def verified_selection(row: Mapping[str, Any]) -> VerifiedSelection:
    market = str(row.get("market") or "").strip().upper()
    entity = str(row.get("entity_name") or row.get("entity") or "").strip()
    side = str(row.get("side") or "").strip().upper()
    sportsbook = str(row.get("sportsbook") or row.get("book_key") or "").strip()
    observed_at = str(row.get("retrieved_at") or row.get("observed_at") or "").strip()
    if not all((market, entity, side, sportsbook, observed_at)):
        raise MLBRefinementError("selection identity requires market/entity/side/sportsbook/observed_at")
    line = _finite(row.get("line"), "line")
    odds_raw = row.get("american_odds")
    if isinstance(odds_raw, bool):
        raise MLBRefinementError("american_odds must be numeric")
    try:
        odds = int(odds_raw)
    except (TypeError, ValueError) as exc:
        raise MLBRefinementError("american_odds must be integer-like") from exc
    if -100 < odds < 100:
        raise MLBRefinementError("invalid American odds")
    return VerifiedSelection(market, entity, side, line, odds, sportsbook, observed_at)


def assert_unique_ladder(rows: Iterable[Mapping[str, Any]]) -> tuple[VerifiedSelection, ...]:
    """Fail closed if a player/market/side/line is bound to conflicting prices.

    Screenshot transcription and ladder UIs are especially vulnerable to attaching
    the adjacent rung's price to a threshold. This contract requires the complete
    player + market + side + line + odds identity before a quote can be used.
    """
    seen: dict[tuple[str, str, str, float, str, str], VerifiedSelection] = {}
    out: list[VerifiedSelection] = []
    for row in rows:
        selection = verified_selection(row)
        key = (
            selection.market,
            selection.entity.lower(),
            selection.side,
            selection.line,
            selection.sportsbook.lower(),
            selection.observed_at,
        )
        prior = seen.get(key)
        if prior is not None and prior.american_odds != selection.american_odds:
            raise MLBRefinementError("AMBIGUOUS_LADDER_PRICE")
        if prior is None:
            seen[key] = selection
            out.append(selection)
    return tuple(out)


@dataclass(frozen=True)
class FirstInningHazard:
    top3_xwoba: float
    top3_iso: float
    top3_bb_rate: float
    top3_barrel_rate: float
    starter_first_inning_bb_rate: float
    starter_first_inning_hr_rate: float
    starter_first_time_through_woba: float
    platoon_advantage_share: float
    first_inning_power_index: float
    lineup_confirmed: float
    hazard_score: float


def first_inning_hazard(*, top3_xwoba: Any, top3_iso: Any, top3_bb_rate: Any,
                        top3_barrel_rate: Any, starter_first_inning_bb_rate: Any,
                        starter_first_inning_hr_rate: Any, starter_first_time_through_woba: Any,
                        platoon_advantage_share: Any, first_inning_power_index: Any = 1.0,
                        lineup_confirmed: bool = True) -> FirstInningHazard:
    xwoba = _finite(top3_xwoba, "top3_xwoba", lo=0, hi=1)
    iso = _finite(top3_iso, "top3_iso", lo=0, hi=1)
    bb = _finite(top3_bb_rate, "top3_bb_rate", lo=0, hi=1)
    barrel = _finite(top3_barrel_rate, "top3_barrel_rate", lo=0, hi=1)
    sp_bb = _finite(starter_first_inning_bb_rate, "starter_first_inning_bb_rate", lo=0, hi=1)
    sp_hr = _finite(starter_first_inning_hr_rate, "starter_first_inning_hr_rate", lo=0, hi=1)
    fto = _finite(starter_first_time_through_woba, "starter_first_time_through_woba", lo=0, hi=1)
    platoon = _finite(platoon_advantage_share, "platoon_advantage_share", lo=0, hi=1)
    power = _finite(first_inning_power_index, "first_inning_power_index", lo=.5, hi=1.5)

    # Research score only. Inputs are centered on neutral MLB-like reference values;
    # coefficients intentionally produce a bounded diagnostic score, not a promoted
    # probability. Fit/calibration must happen separately on point-in-time data.
    raw = (
        1.35 * (xwoba - .320)
        + 0.90 * (iso - .160)
        + 0.80 * (bb - .085)
        + 1.10 * (barrel - .070)
        + 0.75 * (sp_bb - .085)
        + 1.25 * (sp_hr - .030)
        + 1.10 * (fto - .320)
        + 0.20 * (platoon - .50)
        + 0.55 * (power - 1.0)
    )
    if not lineup_confirmed:
        raw += 0.04  # uncertainty penalty: never make an NRFI stronger on a projected lineup
    score = _clip(0.50 + raw, 0.0, 1.0)
    return FirstInningHazard(xwoba, iso, bb, barrel, sp_bb, sp_hr, fto, platoon, power,
                             float(bool(lineup_confirmed)), score)


@dataclass(frozen=True)
class StarterLeash:
    avg_pitches_3: float
    max_pitches_5: float
    starts_95plus_10: float
    pitches_per_pa_5: float
    outs_per_start_5: float
    bullpen_rest_index: float
    manager_hook_index: float
    leash_score: float


def starter_leash(*, avg_pitches_3: Any, max_pitches_5: Any, starts_95plus_10: Any,
                  pitches_per_pa_5: Any, outs_per_start_5: Any,
                  bullpen_rest_index: Any, manager_hook_index: Any) -> StarterLeash:
    avg3 = _finite(avg_pitches_3, "avg_pitches_3", lo=0, hi=150)
    max5 = _finite(max_pitches_5, "max_pitches_5", lo=0, hi=160)
    p95 = _finite(starts_95plus_10, "starts_95plus_10", lo=0, hi=1)
    ppa = _finite(pitches_per_pa_5, "pitches_per_pa_5", lo=2, hi=8)
    outs = _finite(outs_per_start_5, "outs_per_start_5", lo=0, hi=27)
    bullpen = _finite(bullpen_rest_index, "bullpen_rest_index", lo=0, hi=1)
    hook = _finite(manager_hook_index, "manager_hook_index", lo=0, hi=1)
    raw = (
        0.28 * ((avg3 - 88) / 20)
        + 0.18 * ((max5 - 100) / 20)
        + 0.22 * (p95 - .40)
        - 0.28 * ((ppa - 3.9) / 1.0)
        + 0.28 * ((outs - 16.5) / 6.0)
        - 0.16 * (bullpen - .50)
        - 0.30 * (hook - .50)
    )
    score = _clip(0.50 + raw, 0.0, 1.0)
    return StarterLeash(avg3, max5, p95, ppa, outs, bullpen, hook, score)


@dataclass(frozen=True)
class StrikeoutExpectation:
    expected_batters_faced: float
    batter_weighted_k_probability: float
    pitch_quality_multiplier: float
    expected_strikeouts: float


def pitcher_k_expectation(*, expected_batters_faced: Any,
                          batter_k_probabilities: Sequence[Any],
                          batter_pa_weights: Sequence[Any] | None = None,
                          pitch_quality_multiplier: Any = 1.0) -> StrikeoutExpectation:
    bf = _finite(expected_batters_faced, "expected_batters_faced", lo=0, hi=45)
    probs = [_finite(v, "batter_k_probability", lo=0, hi=1) for v in batter_k_probabilities]
    if not probs:
        raise MLBRefinementError("batter_k_probabilities must be non-empty")
    if batter_pa_weights is None:
        weights = [1.0] * len(probs)
    else:
        if len(batter_pa_weights) != len(probs):
            raise MLBRefinementError("batter_pa_weights length mismatch")
        weights = [_finite(v, "batter_pa_weight", lo=0) for v in batter_pa_weights]
    total_weight = sum(weights)
    if total_weight <= 0:
        raise MLBRefinementError("batter_pa_weights must sum positive")
    weighted_p = sum(p * w for p, w in zip(probs, weights)) / total_weight
    quality = _finite(pitch_quality_multiplier, "pitch_quality_multiplier", lo=.5, hi=1.5)
    expected = bf * _clip(weighted_p * quality, 0.0, 1.0)
    return StrikeoutExpectation(bf, weighted_p, quality, expected)


@dataclass(frozen=True)
class WeatherEffects:
    run_environment_index: float
    first_inning_power_index: float
    roof_certainty: float
    source_disagreement: float


def weather_effects(*, park_run_factor: Any, park_hr_factor: Any, temperature_f: Any,
                    wind_out_mph: Any, humidity_pct: Any, roof_closed: bool,
                    roof_certainty: Any = 1.0, source_disagreement: Any = 0.0) -> WeatherEffects:
    run_factor = _finite(park_run_factor, "park_run_factor", lo=.5, hi=1.5)
    hr_factor = _finite(park_hr_factor, "park_hr_factor", lo=.5, hi=1.8)
    temp = _finite(temperature_f, "temperature_f", lo=-20, hi=140)
    wind = _finite(wind_out_mph, "wind_out_mph", lo=-50, hi=50)
    humidity = _finite(humidity_pct, "humidity_pct", lo=0, hi=100)
    certainty = _finite(roof_certainty, "roof_certainty", lo=0, hi=1)
    disagreement = _finite(source_disagreement, "source_disagreement", lo=0, hi=1)
    if roof_closed:
        wind = 0.0
        temp_component = 0.0
    else:
        temp_component = (temp - 72.0) / 100.0
    run_index = _clip(run_factor + .010 * wind + .22 * temp_component + .0008 * (humidity - 50), .65, 1.40)
    power_index = _clip(hr_factor + .018 * wind + .30 * temp_component, .60, 1.55)
    # disagreement widens uncertainty rather than flipping the physical direction
    shrink = 1.0 - 0.35 * disagreement
    run_index = 1.0 + (run_index - 1.0) * shrink
    power_index = 1.0 + (power_index - 1.0) * shrink
    return WeatherEffects(run_index, power_index, certainty, disagreement)


@dataclass(frozen=True)
class ConflictAssessment:
    flags: tuple[str, ...]
    confidence_multiplier: float


def conflict_assessment(*, nrfi_requested: bool = False,
                        hitter_attack_signal: float = 0.0,
                        first_inning_hazard_score: float | None = None,
                        model_disagreement: float = 0.0,
                        lineup_confirmed: bool = True,
                        weather_source_disagreement: float = 0.0) -> ConflictAssessment:
    attack = _finite(hitter_attack_signal, "hitter_attack_signal", lo=0, hi=1)
    disagreement = _finite(model_disagreement, "model_disagreement", lo=0, hi=1)
    weather_disagreement = _finite(weather_source_disagreement, "weather_source_disagreement", lo=0, hi=1)
    hazard = None if first_inning_hazard_score is None else _finite(first_inning_hazard_score, "first_inning_hazard_score", lo=0, hi=1)
    flags: list[str] = []
    penalty = 0.0
    if nrfi_requested and attack >= .65:
        flags.append("NRFI_HITTER_ATTACK_CONFLICT")
        penalty += .12
    if nrfi_requested and hazard is not None and hazard >= .60:
        flags.append("NRFI_FIRST_INNING_HAZARD_CONFLICT")
        penalty += .18
    if disagreement >= .35:
        flags.append("MODEL_DISAGREEMENT")
        penalty += .12 * disagreement
    if not lineup_confirmed:
        flags.append("LINEUP_UNCONFIRMED")
        penalty += .10
    if weather_disagreement >= .30:
        flags.append("WEATHER_SOURCE_DISAGREEMENT")
        penalty += .08 * weather_disagreement
    return ConflictAssessment(tuple(flags), _clip(1.0 - penalty, .50, 1.0))


def research_adjusted_edge(*, model_probability: Any, fair_market_probability: Any,
                           confidence_multiplier: Any) -> float:
    model_p = _finite(model_probability, "model_probability", lo=0, hi=1)
    fair_p = _finite(fair_market_probability, "fair_market_probability", lo=0, hi=1)
    mult = _finite(confidence_multiplier, "confidence_multiplier", lo=0, hi=1)
    raw_edge = model_p - fair_p
    # Penalties can only shrink an edge toward zero; they can never create one.
    return raw_edge * mult
