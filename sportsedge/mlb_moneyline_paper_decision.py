"""Freeze pregame PAPER decisions for the governed MLB MONEYLINE forward lane.

This module is deliberately downstream of market-blind Model_P. It consumes one
already-frozen prediction plus paired DraftKings prices only to decide whether a
PAPER bet would have qualified under the precollection edge/devig policy. It has
no settlement or outcome input and always stakes zero units.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from math import isfinite
from pathlib import Path
import re
from typing import Any, Iterable, Mapping

from .devig import DevigError, devig_with_policy
from .edge_floors import (
    DEFAULT_EDGE_FLOOR_CONFIG,
    load_edge_floor_config,
    require_frozen_devig_policy,
    require_frozen_edge_floor,
)
from .mlb_moneyline_forward_lane import (
    MLBMoneylineForwardLaneError,
    load_forward_lane_binding,
)
from .truth_gate import american_to_decimal

DECISION_VERSION = "mlb_moneyline_paper_decision_v1"
TARGET_MINUTES_BEFORE = 30.0
EARLY_TOLERANCE_MINUTES = 6.0


class MLBMoneylinePaperDecisionError(ValueError):
    pass


def _ts(value: Any, field: str) -> datetime:
    try:
        out = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError as exc:
        raise MLBMoneylinePaperDecisionError(f"{field}: invalid timestamp") from exc
    if out.tzinfo is None or out.utcoffset() is None:
        raise MLBMoneylinePaperDecisionError(f"{field}: timezone required")
    return out.astimezone(timezone.utc)


def _prob(value: Any, field: str = "model_p") -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise MLBMoneylinePaperDecisionError(f"{field} invalid") from exc
    if not isfinite(out) or not 0.0 < out < 1.0:
        raise MLBMoneylinePaperDecisionError(f"{field} invalid")
    return out


def _norm_team(value: Any) -> str:
    text = re.sub(r"[^a-z0-9 ]+", " ", str(value or "").lower())
    return " ".join(text.split())


def _canonical_sha256(value: Mapping[str, Any]) -> str:
    raw = json.dumps(
        dict(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _module_sha256() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _american(value: Any, field: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise MLBMoneylinePaperDecisionError(f"{field} invalid") from exc
    american_to_decimal(out)
    return out


def _paired_prices(row: Mapping[str, Any]) -> tuple[float, float]:
    ml = row.get("moneyline")
    if not isinstance(ml, Mapping) or ml.get("status") != "OK":
        raise MLBMoneylinePaperDecisionError("paired moneyline required")
    return (
        _american(ml.get("home_price_american"), "home_price_american"),
        _american(ml.get("away_price_american"), "away_price_american"),
    )


def _canonical_pair(game_pk: int, home_odds: float, away_odds: float) -> tuple[dict[str, Any], dict[str, Any]]:
    common = {
        "game_id": str(game_pk),
        "period": "FG",
        "market": "MONEYLINE",
        "entity_id": str(game_pk),
        "book_key": "draftkings",
        "is_alternate": False,
        "line": 0.0,
    }
    return (
        {**common, "side": "HOME", "american_odds": home_odds},
        {**common, "side": "AWAY", "american_odds": away_odds},
    )


def _ev(model_p: float, american_odds: float) -> float:
    dec = american_to_decimal(american_odds)
    return model_p * (dec - 1.0) - (1.0 - model_p)


def _authority_false() -> dict[str, bool]:
    return {
        "promotion_authority": False,
        "deployment_change_allowed": False,
        "staking_change_allowed": False,
        "official_change_allowed": False,
    }


def _binding_fields(binding: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "lane_id": binding["lane_id"],
        "lane_definition_sha256": binding["lane_definition_sha256"],
        "market_definition_sha256": binding["market_definition_sha256"],
        "policy_id": binding["policy_id"],
        "policy_sha256": binding["policy_sha256"],
        "policy_manifest_sha256": binding["policy_manifest_sha256"],
        "edge_floor_config_sha256": binding["edge_floor_config_sha256"],
    }


def _validate_prediction(prediction: Mapping[str, Any]) -> tuple[int, datetime, datetime, float, str, str, str]:
    if prediction.get("market") != "MONEYLINE" or prediction.get("market_blind") is not True:
        raise MLBMoneylinePaperDecisionError("market-blind MONEYLINE prediction required")
    if prediction.get("promotion_authority") is not False:
        raise MLBMoneylinePaperDecisionError("prediction authority flag invalid")
    if str(prediction.get("model_side") or "").upper() != "HOME":
        raise MLBMoneylinePaperDecisionError("fixed HOME reference prediction required")
    try:
        game_pk = int(prediction.get("game_pk"))
    except (TypeError, ValueError) as exc:
        raise MLBMoneylinePaperDecisionError("prediction game_pk invalid") from exc
    start = _ts(prediction.get("event_start_ts"), "event_start_ts")
    generated = _ts(prediction.get("prediction_generated_at_utc"), "prediction_generated_at_utc")
    feature_asof = _ts(prediction.get("feature_asof_ts"), "feature_asof_ts")
    if not feature_asof < start or not generated < start:
        raise MLBMoneylinePaperDecisionError("prediction PIT violation")
    p_home = _prob(prediction.get("model_p"))
    home = _norm_team(prediction.get("home_team"))
    away = _norm_team(prediction.get("away_team"))
    if not home or not away or home == away:
        raise MLBMoneylinePaperDecisionError("prediction team identity invalid")
    artifact = str(prediction.get("model_artifact_sha256") or "").lower()
    if len(artifact) != 64 or any(ch not in "0123456789abcdef" for ch in artifact):
        raise MLBMoneylinePaperDecisionError("model_artifact_sha256 invalid")
    return game_pk, start, generated, p_home, home, away, artifact


def _matching_quotes(
    *,
    quotes: Iterable[Mapping[str, Any]],
    home: str,
    away: str,
    start: datetime,
    generated: datetime,
    artifact: str,
    freeze_now: datetime,
) -> list[tuple[float, datetime, Mapping[str, Any]]]:
    matches: list[tuple[float, datetime, Mapping[str, Any]]] = []
    for row in quotes:
        if str(row.get("sportsbook") or "").lower() != "draftkings":
            continue
        if _norm_team(row.get("home_team")) != home or _norm_team(row.get("away_team")) != away:
            continue
        if row.get("promotion_authority") is not False:
            raise MLBMoneylinePaperDecisionError("quote authority flag invalid")
        if str(row.get("model_artifact_sha256") or "").lower() != artifact:
            raise MLBMoneylinePaperDecisionError("model artifact mismatch")
        q_start = _ts(row.get("scheduled_start_utc"), "scheduled_start_utc")
        if abs((q_start - start).total_seconds()) > 1.0:
            raise MLBMoneylinePaperDecisionError("event start identity mismatch")
        observed = _ts(row.get("observed_at_utc"), "observed_at_utc")
        if not generated <= observed < start:
            raise MLBMoneylinePaperDecisionError("quote chronology violation")
        if observed > freeze_now:
            raise MLBMoneylinePaperDecisionError("future quote cannot enter decision")
        _paired_prices(row)
        minutes_before = (start - observed).total_seconds() / 60.0
        if TARGET_MINUTES_BEFORE <= minutes_before <= TARGET_MINUTES_BEFORE + EARLY_TOLERANCE_MINUTES:
            matches.append((minutes_before, observed, row))
    return matches


def _missed_record(
    *,
    prediction: Mapping[str, Any],
    binding: Mapping[str, Any],
    freeze_now: datetime,
    start: datetime,
    reason: str,
) -> dict[str, Any]:
    return {
        "schema_version": DECISION_VERSION,
        "status": "BLOCKED_MISSED_DECISION_FREEZE",
        "state": "BLOCKED",
        "evidence_counts": False,
        "graded_bet": False,
        "stake_units": 0.0,
        "reason": reason,
        "game_pk": int(prediction["game_pk"]),
        "away_team": prediction.get("away_team"),
        "home_team": prediction.get("home_team"),
        "event_start_ts": start.isoformat(),
        "decision_frozen_at_utc": freeze_now.isoformat(),
        "decision_minutes_before_start": round((start - freeze_now).total_seconds() / 60.0, 4),
        "model_artifact_sha256": prediction.get("model_artifact_sha256"),
        "prediction_record_sha256": _canonical_sha256(prediction),
        "decision_input_contract": "PREDICTION_PLUS_PREGAME_PRICE_ONLY_NO_SETTLEMENT_INPUT",
        "outcome_or_postgame_data_consumed": False,
        "decision_module_sha256": _module_sha256(),
        **_binding_fields(binding),
        **_authority_false(),
    }


def freeze_paper_decision(
    *,
    prediction: Mapping[str, Any],
    quotes: Iterable[Mapping[str, Any]],
    now: datetime,
    binding: Mapping[str, Any] | None = None,
    floor_config_path: str = DEFAULT_EDGE_FLOOR_CONFIG,
) -> dict[str, Any]:
    """Freeze one pregame PAPER decision or return a non-persistable waiting state.

    A valid decision can only be frozen while the wall clock itself is still in
    the frozen 30-36 minute early-only window. A previously captured quote cannot
    be turned into a graded decision after that window has passed.
    """
    freeze_now = _ts(now, "now")
    lane = dict(binding or load_forward_lane_binding())
    if lane.get("promotion_authority") is not False:
        raise MLBMoneylinePaperDecisionError("lane authority flag invalid")
    game_pk, start, generated, p_home, home, away, artifact = _validate_prediction(prediction)
    minutes_until_start = (start - freeze_now).total_seconds() / 60.0

    if minutes_until_start > TARGET_MINUTES_BEFORE + EARLY_TOLERANCE_MINUTES:
        return {
            "status": "DECISION_NOT_DUE",
            "promotion_authority": False,
            "game_pk": game_pk,
            "minutes_before_start": round(minutes_until_start, 4),
        }

    matching = _matching_quotes(
        quotes=quotes,
        home=home,
        away=away,
        start=start,
        generated=generated,
        artifact=artifact,
        freeze_now=freeze_now,
    )

    if minutes_until_start < TARGET_MINUTES_BEFORE:
        return _missed_record(
            prediction=prediction,
            binding=lane,
            freeze_now=freeze_now,
            start=start,
            reason="DECISION_WINDOW_ELAPSED_BEFORE_IMMUTABLE_PAPER_DECISION",
        )
    if freeze_now >= start:
        return _missed_record(
            prediction=prediction,
            binding=lane,
            freeze_now=freeze_now,
            start=start,
            reason="EVENT_STARTED_BEFORE_IMMUTABLE_PAPER_DECISION",
        )
    if not matching:
        return {
            "status": "WAITING_FOR_ADMISSIBLE_DECISION_QUOTE",
            "promotion_authority": False,
            "game_pk": game_pk,
            "minutes_before_start": round(minutes_until_start, 4),
        }

    # Smallest minutes-before value is the observation closest to the frozen T30
    # target while remaining at-or-before (early side of) the target.
    matching.sort(key=lambda item: (item[0], item[1]))
    quote_minutes, quote_observed, decision_quote = matching[0]
    home_odds, away_odds = _paired_prices(decision_quote)
    home_quote, away_quote = _canonical_pair(game_pk, home_odds, away_odds)

    floor_cfg = load_edge_floor_config(floor_config_path)
    floor = require_frozen_edge_floor(market="moneyline", sport="MLB", config=floor_cfg)
    devig_policy = require_frozen_devig_policy(config=floor_cfg)
    floor_policy = (floor_cfg.get("truth_gate") or {}).get("floor_policy") or {}
    try:
        longshot_floor = float(floor_policy.get("longshot_or_one_sided_floor"))
    except (TypeError, ValueError) as exc:
        raise MLBMoneylinePaperDecisionError("longshot floor invalid") from exc

    try:
        home_devig = devig_with_policy(home_quote, away_quote, policy=devig_policy)
        away_devig = devig_with_policy(away_quote, home_quote, policy=devig_policy)
    except DevigError as exc:
        raise MLBMoneylinePaperDecisionError(str(exc)) from exc
    if home_devig.longshot_triggered != away_devig.longshot_triggered:
        raise MLBMoneylinePaperDecisionError("paired longshot trigger mismatch")

    base_floor = float(floor.value_probability_points)
    effective_floor = max(base_floor, longshot_floor) if home_devig.longshot_triggered else base_floor
    p_away = 1.0 - p_home
    candidates = [
        {
            "side": "HOME",
            "model_p": p_home,
            "american_odds": home_odds,
            "market_fair_probability": float(home_devig.fair_probability_for_decision),
            "edge_probability_points": p_home - float(home_devig.fair_probability_for_decision),
            "ev_per_dollar": _ev(p_home, home_odds),
            "devig_method": home_devig.selected.method,
        },
        {
            "side": "AWAY",
            "model_p": p_away,
            "american_odds": away_odds,
            "market_fair_probability": float(away_devig.fair_probability_for_decision),
            "edge_probability_points": p_away - float(away_devig.fair_probability_for_decision),
            "ev_per_dollar": _ev(p_away, away_odds),
            "devig_method": away_devig.selected.method,
        },
    ]
    candidates.sort(key=lambda row: (float(row["edge_probability_points"]), float(row["ev_per_dollar"]), row["side"]), reverse=True)
    best = candidates[0]
    qualifies = (
        float(best["edge_probability_points"]) > effective_floor
        and float(best["ev_per_dollar"]) > 0.0
    )
    status = "PAPER_BET_FROZEN" if qualifies else "PAPER_PASS_FROZEN"

    record = {
        "schema_version": DECISION_VERSION,
        "status": status,
        "state": "PAPER",
        "evidence_counts": bool(qualifies),
        "graded_bet": bool(qualifies),
        "stake_units": 0.0,
        "sport": "MLB",
        "market": "MONEYLINE",
        "sportsbook": "draftkings",
        "game_pk": game_pk,
        "slate_date": start.date().isoformat(),
        "slate_cluster_policy": "UTC_EVENT_START_DATE",
        "away_team": prediction.get("away_team"),
        "home_team": prediction.get("home_team"),
        "event_start_ts": start.isoformat(),
        "model_reference_side": "HOME",
        "model_p_home": p_home,
        "model_p_away": p_away,
        "model_artifact_sha256": artifact,
        "prediction_generated_at_utc": generated.isoformat(),
        "feature_asof_ts": prediction.get("feature_asof_ts"),
        "prediction_record_sha256": _canonical_sha256(prediction),
        "decision_frozen_at_utc": freeze_now.isoformat(),
        "decision_minutes_before_start": round(minutes_until_start, 4),
        "decision_quote_observed_at_utc": quote_observed.isoformat(),
        "decision_quote_minutes_before_start": round(quote_minutes, 4),
        "decision_provider_event_id": decision_quote.get("provider_event_id"),
        "decision_capture_observation_id": decision_quote.get("capture_observation_id"),
        "decision_raw_sha256": decision_quote.get("raw_sha256"),
        "decision_quote_record_sha256": _canonical_sha256(decision_quote),
        "home_price_american": home_odds,
        "away_price_american": away_odds,
        "home_market_fair_probability": float(home_devig.fair_probability_for_decision),
        "away_market_fair_probability": float(away_devig.fair_probability_for_decision),
        "candidate_sides": candidates,
        "selected_side": best["side"] if qualifies else None,
        "selected_model_p": float(best["model_p"]) if qualifies else None,
        "selected_price_american": float(best["american_odds"]) if qualifies else None,
        "selected_market_fair_probability": float(best["market_fair_probability"]) if qualifies else None,
        "selected_edge_probability_points": float(best["edge_probability_points"]) if qualifies else None,
        "selected_ev_per_dollar": float(best["ev_per_dollar"]) if qualifies else None,
        "best_candidate_side": best["side"],
        "best_candidate_edge_probability_points": float(best["edge_probability_points"]),
        "best_candidate_ev_per_dollar": float(best["ev_per_dollar"]),
        "base_edge_floor_probability_points": base_floor,
        "effective_edge_floor_probability_points": effective_floor,
        "longshot_floor_probability_points": longshot_floor,
        "longshot_triggered": bool(home_devig.longshot_triggered),
        "devig_policy_id": devig_policy.policy_id,
        "devig_sensitivity_spread_probability_points": float(
            max(
                home_devig.sensitivity_spread_probability_points,
                away_devig.sensitivity_spread_probability_points,
            )
        ),
        "decision_policy": "T30_TARGET_EARLY_ONLY_PLUS_6_MIN; FREEZE_WALL_CLOCK_MUST_REMAIN_30_TO_36_MIN_PRESTART",
        "decision_input_contract": "PREDICTION_PLUS_PREGAME_PRICE_ONLY_NO_SETTLEMENT_INPUT",
        "outcome_or_postgame_data_consumed": False,
        "decision_module_sha256": _module_sha256(),
        **_binding_fields(lane),
        **_authority_false(),
    }
    try:
        from .mlb_moneyline_forward_lane import require_record_binding

        require_record_binding(record, lane)
    except MLBMoneylineForwardLaneError as exc:
        raise MLBMoneylinePaperDecisionError(str(exc)) from exc
    return record
