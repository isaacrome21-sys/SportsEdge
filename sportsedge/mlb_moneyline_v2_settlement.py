"""Complete MLB MONEYLINE V2 evidence from an immutable pregame PAPER bet.

The decision already exists before outcomes. Settlement is downstream-only: it
cannot choose a side, change Model_P, change the entry quote, or turn a PAPER pass
into a graded bet. Missing closes remain graded in the checkpoint denominator but
are excluded from CLV exactly as Promotion Evidence Policy V2 requires.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from math import isfinite
import re
from typing import Any, Iterable, Mapping

from .devig import DevigError, devig_with_policy
from .edge_floors import load_edge_floor_config, require_frozen_devig_policy
from .mlb_moneyline_forward_lane import (
    MLBMoneylineForwardLaneError,
    load_forward_lane_binding,
    require_record_binding,
)
from .truth_gate import american_to_decimal

EVIDENCE_VERSION = "mlb_moneyline_forward_evidence_v2"


class MLBMoneylineV2SettlementError(ValueError):
    pass


def _ts(value: Any, field: str) -> datetime:
    try:
        out = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError as exc:
        raise MLBMoneylineV2SettlementError(f"{field}: invalid timestamp") from exc
    if out.tzinfo is None or out.utcoffset() is None:
        raise MLBMoneylineV2SettlementError(f"{field}: timezone required")
    return out.astimezone(timezone.utc)


def _prob(value: Any, field: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise MLBMoneylineV2SettlementError(f"{field} invalid") from exc
    if not isfinite(out) or not 0.0 < out < 1.0:
        raise MLBMoneylineV2SettlementError(f"{field} invalid")
    return out


def _norm_team(value: Any) -> str:
    text = re.sub(r"[^a-z0-9 ]+", " ", str(value or "").lower())
    return " ".join(text.split())


def _canonical_sha256(value: Mapping[str, Any]) -> str:
    raw = json.dumps(
        dict(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _american(value: Any, field: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise MLBMoneylineV2SettlementError(f"{field} invalid") from exc
    american_to_decimal(out)
    return out


def _prices(row: Mapping[str, Any]) -> tuple[float, float]:
    ml = row.get("moneyline")
    if not isinstance(ml, Mapping) or ml.get("status") != "OK":
        raise MLBMoneylineV2SettlementError("paired moneyline required")
    return (
        _american(ml.get("home_price_american"), "home_price_american"),
        _american(ml.get("away_price_american"), "away_price_american"),
    )


def _pair(game_pk: int, home_odds: float, away_odds: float) -> tuple[dict[str, Any], dict[str, Any]]:
    base = {
        "game_id": str(game_pk),
        "period": "FG",
        "market": "MONEYLINE",
        "entity_id": str(game_pk),
        "book_key": "draftkings",
        "is_alternate": False,
        "line": 0.0,
    }
    return (
        {**base, "side": "HOME", "american_odds": home_odds},
        {**base, "side": "AWAY", "american_odds": away_odds},
    )


def _ev(model_p: float, odds: float) -> float:
    dec = american_to_decimal(odds)
    return model_p * (dec - 1.0) - (1.0 - model_p)


def _near(a: Any, b: Any, tolerance: float = 1e-10) -> bool:
    try:
        return abs(float(a) - float(b)) <= tolerance
    except (TypeError, ValueError):
        return False


def complete_v2_evidence(
    *,
    decision: Mapping[str, Any],
    prediction: Mapping[str, Any],
    quotes: Iterable[Mapping[str, Any]],
    settlement: Mapping[str, Any],
    binding: Mapping[str, Any] | None = None,
    floor_config_path: str = "config/truth_gate_floors.json",
) -> dict[str, Any]:
    lane = dict(binding or load_forward_lane_binding())
    try:
        require_record_binding(decision, lane)
    except MLBMoneylineForwardLaneError as exc:
        raise MLBMoneylineV2SettlementError(str(exc)) from exc
    if decision.get("status") != "PAPER_BET_FROZEN" or decision.get("state") != "PAPER":
        raise MLBMoneylineV2SettlementError("only frozen PAPER bets can become graded V2 evidence")
    if decision.get("graded_bet") is not True or decision.get("evidence_counts") is not True:
        raise MLBMoneylineV2SettlementError("graded PAPER bet flags invalid")
    if float(decision.get("stake_units", -1)) != 0.0:
        raise MLBMoneylineV2SettlementError("PAPER decision must have zero stake")
    if decision.get("outcome_or_postgame_data_consumed") is not False:
        raise MLBMoneylineV2SettlementError("decision outcome-visibility flag invalid")

    try:
        game_pk = int(decision.get("game_pk"))
    except (TypeError, ValueError) as exc:
        raise MLBMoneylineV2SettlementError("decision game_pk invalid") from exc
    if int(prediction.get("game_pk", -1)) != game_pk:
        raise MLBMoneylineV2SettlementError("prediction identity mismatch")
    if _canonical_sha256(prediction) != str(decision.get("prediction_record_sha256") or ""):
        raise MLBMoneylineV2SettlementError("prediction bytes/canonical identity mismatch")
    artifact = str(decision.get("model_artifact_sha256") or "")
    if str(prediction.get("model_artifact_sha256") or "") != artifact:
        raise MLBMoneylineV2SettlementError("model artifact mismatch")

    start = _ts(decision.get("event_start_ts"), "event_start_ts")
    if _ts(prediction.get("event_start_ts"), "prediction event_start_ts") != start:
        raise MLBMoneylineV2SettlementError("prediction start mismatch")
    frozen = _ts(decision.get("decision_frozen_at_utc"), "decision_frozen_at_utc")
    entry_observed = _ts(decision.get("decision_quote_observed_at_utc"), "decision_quote_observed_at_utc")
    if not entry_observed <= frozen < start:
        raise MLBMoneylineV2SettlementError("decision freeze chronology invalid")
    freeze_minutes = (start - frozen).total_seconds() / 60.0
    entry_minutes = (start - entry_observed).total_seconds() / 60.0
    if not 30.0 <= freeze_minutes <= 36.0:
        raise MLBMoneylineV2SettlementError("decision freeze outside frozen T30 early-only window")
    if not 30.0 <= entry_minutes <= 36.0:
        raise MLBMoneylineV2SettlementError("entry quote outside frozen T30 early-only window")

    selected = str(decision.get("selected_side") or "").upper()
    if selected not in {"HOME", "AWAY"}:
        raise MLBMoneylineV2SettlementError("selected side invalid")
    p_home = _prob(decision.get("model_p_home"), "model_p_home")
    p_away = _prob(decision.get("model_p_away"), "model_p_away")
    if abs((p_home + p_away) - 1.0) > 1e-10:
        raise MLBMoneylineV2SettlementError("model probabilities do not complement")
    selected_p = p_home if selected == "HOME" else p_away
    if not _near(selected_p, decision.get("selected_model_p")):
        raise MLBMoneylineV2SettlementError("selected Model_P mismatch")

    entry_home_odds = _american(decision.get("home_price_american"), "home_price_american")
    entry_away_odds = _american(decision.get("away_price_american"), "away_price_american")
    entry_home, entry_away = _pair(game_pk, entry_home_odds, entry_away_odds)
    cfg = load_edge_floor_config(floor_config_path)
    policy = require_frozen_devig_policy(config=cfg)
    candidate, opposite = (entry_home, entry_away) if selected == "HOME" else (entry_away, entry_home)
    try:
        entry_devig = devig_with_policy(candidate, opposite, policy=policy)
    except DevigError as exc:
        raise MLBMoneylineV2SettlementError(str(exc)) from exc
    entry_fair = float(entry_devig.fair_probability_for_decision)
    selected_odds = entry_home_odds if selected == "HOME" else entry_away_odds
    edge = selected_p - entry_fair
    ev = _ev(selected_p, selected_odds)
    if not _near(entry_fair, decision.get("selected_market_fair_probability")):
        raise MLBMoneylineV2SettlementError("entry fair probability mismatch")
    if not _near(edge, decision.get("selected_edge_probability_points")):
        raise MLBMoneylineV2SettlementError("entry edge mismatch")
    if not _near(ev, decision.get("selected_ev_per_dollar")):
        raise MLBMoneylineV2SettlementError("entry EV mismatch")
    if edge <= float(decision.get("effective_edge_floor_probability_points", 1.0)) or ev <= 0:
        raise MLBMoneylineV2SettlementError("frozen PAPER bet no longer satisfies its frozen entry rule")

    home = _norm_team(decision.get("home_team"))
    away = _norm_team(decision.get("away_team"))
    provider_event_id = str(decision.get("decision_provider_event_id") or "")
    close_candidates: list[tuple[datetime, Mapping[str, Any]]] = []
    for row in quotes:
        if str(row.get("sportsbook") or "").lower() != "draftkings":
            continue
        if _norm_team(row.get("home_team")) != home or _norm_team(row.get("away_team")) != away:
            continue
        if str(row.get("model_artifact_sha256") or "") != artifact:
            raise MLBMoneylineV2SettlementError("close quote model artifact mismatch")
        if str(row.get("provider_event_id") or "") != provider_event_id:
            raise MLBMoneylineV2SettlementError("close provider event identity mismatch")
        q_start = _ts(row.get("scheduled_start_utc"), "close scheduled_start_utc")
        if abs((q_start - start).total_seconds()) > 1.0:
            raise MLBMoneylineV2SettlementError("close event start identity mismatch")
        observed = _ts(row.get("observed_at_utc"), "close observed_at_utc")
        if not entry_observed <= observed < start:
            continue
        _prices(row)
        close_candidates.append((observed, row))

    close_status = "MISSING"
    close_observed_at = None
    close_minutes_before = None
    close_home_odds = None
    close_away_odds = None
    close_fair = None
    clv_pp = None
    model_directed_close_edge_pp = None
    close_raw_sha256 = None
    close_capture_observation_id = None
    if close_candidates:
        close_candidates.sort(key=lambda item: item[0])
        close_observed, close_row = close_candidates[-1]
        ch, ca = _prices(close_row)
        hq, aq = _pair(game_pk, ch, ca)
        cc, co = (hq, aq) if selected == "HOME" else (aq, hq)
        try:
            close_devig = devig_with_policy(cc, co, policy=policy)
        except DevigError as exc:
            raise MLBMoneylineV2SettlementError(str(exc)) from exc
        close_status = "AVAILABLE"
        close_observed_at = close_observed.isoformat()
        close_minutes_before = round((start - close_observed).total_seconds() / 60.0, 4)
        close_home_odds = ch
        close_away_odds = ca
        close_fair = float(close_devig.fair_probability_for_decision)
        clv_pp = close_fair - entry_fair
        model_directed_close_edge_pp = selected_p - close_fair
        close_raw_sha256 = close_row.get("raw_sha256")
        close_capture_observation_id = close_row.get("capture_observation_id")

    if int(settlement.get("game_pk", -1)) != game_pk:
        raise MLBMoneylineV2SettlementError("settlement identity mismatch")
    if str(settlement.get("status") or "").upper() != "FINAL":
        raise MLBMoneylineV2SettlementError("FINAL settlement required")
    try:
        home_score = int(settlement.get("home_score"))
        away_score = int(settlement.get("away_score"))
    except (TypeError, ValueError) as exc:
        raise MLBMoneylineV2SettlementError("settlement score invalid") from exc
    if home_score == away_score:
        raise MLBMoneylineV2SettlementError("MLB final cannot be tied")
    won = home_score > away_score if selected == "HOME" else away_score > home_score
    paper_profit_per_1u = (american_to_decimal(selected_odds) - 1.0) if won else -1.0

    return {
        "schema_version": EVIDENCE_VERSION,
        "status": "FORWARD_EVIDENCE_COMPLETE_V2",
        "state": "PAPER",
        "graded_bet": True,
        "evidence_counts": True,
        "stake_units": 0.0,
        "promotion_authority": False,
        "deployment_change_allowed": False,
        "staking_change_allowed": False,
        "official_change_allowed": False,
        "lane_id": decision["lane_id"],
        "lane_definition_sha256": decision["lane_definition_sha256"],
        "market_definition_sha256": decision["market_definition_sha256"],
        "policy_id": decision["policy_id"],
        "policy_sha256": decision["policy_sha256"],
        "policy_manifest_sha256": decision["policy_manifest_sha256"],
        "edge_floor_config_sha256": decision["edge_floor_config_sha256"],
        "game_pk": game_pk,
        "slate_date": decision.get("slate_date"),
        "away_team": decision.get("away_team"),
        "home_team": decision.get("home_team"),
        "event_start_ts": start.isoformat(),
        "model_artifact_sha256": artifact,
        "selected_side": selected,
        "model_side": selected,
        "model_p": selected_p,
        "entry_model_p": selected_p,
        "entry_home_odds": entry_home_odds,
        "entry_away_odds": entry_away_odds,
        "entry_selected_odds": selected_odds,
        "entry_fair_probability": entry_fair,
        "entry_edge_probability_points": edge,
        "entry_ev_per_dollar": ev,
        "effective_edge_floor_probability_points": decision.get("effective_edge_floor_probability_points"),
        "decision_frozen_at_utc": frozen.isoformat(),
        "decision_quote_observed_at_utc": entry_observed.isoformat(),
        "decision_provider_event_id": provider_event_id,
        "decision_raw_sha256": decision.get("decision_raw_sha256"),
        "decision_record_sha256": _canonical_sha256(decision),
        "close_status": close_status,
        "close_observed_at_utc": close_observed_at,
        "close_minutes_before_start": close_minutes_before,
        "close_home_odds": close_home_odds,
        "close_away_odds": close_away_odds,
        "close_selected_fair_probability": close_fair,
        "clv_probability_points": clv_pp,
        "clv_metric": "SELECTED_SIDE_CLOSE_FAIR_PROBABILITY_MINUS_ENTRY_FAIR_PROBABILITY",
        "model_directed_close_edge_probability_points": model_directed_close_edge_pp,
        "close_raw_sha256": close_raw_sha256,
        "close_capture_observation_id": close_capture_observation_id,
        "settlement_status": "FINAL",
        "settlement_home_score": home_score,
        "settlement_away_score": away_score,
        "outcome": 1 if won else 0,
        "paper_profit_units_per_1u": paper_profit_per_1u,
        "paper_roi_fraction_per_1u": paper_profit_per_1u,
        "close_coverage_value": 1 if close_status == "AVAILABLE" else 0,
        "missing_close_counts_in_checkpoint_denominator": True,
        "missing_close_excluded_from_clv": close_status != "AVAILABLE",
        "devig_policy_id": policy.policy_id,
    }
