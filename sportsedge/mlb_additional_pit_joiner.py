"""Join the seven additional MLB PIT quote families into canonical observations.

PR #131 archives these markets after exact provider-event/player binding. The
original PR #129 joiner is intentionally count-prop-specific, so this module keeps
that path unchanged while giving the additional archive an equally strict join.
No settlement outcome is trusted from upstream input; it is derived from verified
official facts only after book-rule evidence passes.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from .additional_mlb_odds_source import CANONICAL_MARKETS
from .mlb_pit_joiner import (
    MLBPITJoinError,
    _MISSING_RULE_CLASS,
    _SYNTHETIC_CLASS,
    _LIVE_FACT_CLASS,
    _LIVE_MODEL_CLASS,
    _LIVE_RULE_CLASS,
    _duplicate_keys,
    _fact_index,
    _index_unique,
    _line_key,
    _model_index,
    _required_rules_by_market,
    _rules_hash,
    _rules_match_sportsbook,
    asdict_compat,
    observation_key,
)
from .mlb_pit_observation import content_sha256, normalize_pit_observation
from .mlb_settlement_evidence import (
    canonical_bytes,
    classify_observation_settlement,
    official_fact_coverage,
)
from .moneyline_settlement import (
    MoneylineSettlementType,
    declared_moneyline_settlement_type,
    settle_moneyline,
)
from .odds_api_source import EVENT_TIME_TOLERANCE_SECONDS, normalize_name
from .f5_derived_readouts import (
    ANY_OTHER as _F5_ANY_OTHER,
    F5DerivedReadoutError,
    parse_btts_rung,
    parse_correct_score_selection,
    parse_margin_band,
)

ARCHIVE_TYPE = "MLB_ADDITIONAL_PIT_QUOTES"
_BINARY_MARKETS = frozenset({"FIRST_HOME_RUN", "PITCHER_RECORD_WIN"})
_MISSING_RAW_PARTICIPANT = "PROVIDER_PARTICIPANT_RAW_IDENTITY_NOT_ARCHIVED"
_F5_TIE_POLICY_MISSING = "F5_MONEYLINE_TIE_POLICY_NOT_NORMALIZED"
_FIRST_HOME_RUN_NO_HR_POLICY_MISSING = "FIRST_HOME_RUN_NO_HR_POLICY_NOT_NORMALIZED"


def _parse_ts(value: Any, name: str) -> datetime:
    text = str(value or "").strip().replace("Z", "+00:00")
    if not text:
        raise MLBPITJoinError(f"{name} required")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError as exc:
        raise MLBPITJoinError(f"{name} invalid") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise MLBPITJoinError(f"{name} timezone required")
    return dt.astimezone(timezone.utc)


def _verify_archive(payload: Mapping[str, Any]) -> tuple[str, str, list[Mapping[str, Any]]]:
    if str(payload.get("archive_type") or "") != ARCHIVE_TYPE:
        raise MLBPITJoinError(f"{ARCHIVE_TYPE} archive required")
    source_class = str(payload.get("evidence_class") or "").upper()
    if source_class not in {"LIVE_PROVIDER_QUOTE_ARCHIVE", _SYNTHETIC_CLASS}:
        raise MLBPITJoinError("archive evidence_class unsupported")
    digest = str(payload.get("payload_sha256") or "").lower()
    if len(digest) != 64:
        raise MLBPITJoinError("archive payload_sha256 required")
    without_hash = {k: v for k, v in payload.items() if k != "payload_sha256"}
    if content_sha256(without_hash) != digest:
        raise MLBPITJoinError("ARCHIVE_PAYLOAD_HASH_MISMATCH")
    quotes = payload.get("quotes")
    if not isinstance(quotes, list):
        raise MLBPITJoinError("archive quotes must be list")
    return source_class, digest, quotes


def _bind_odds_api_event(quote: Mapping[str, Any], games: Iterable[Mapping[str, Any]]) -> str:
    event = quote.get("provider_event_snapshot")
    if not isinstance(event, Mapping):
        raise MLBPITJoinError("PROVIDER_EVENT_SNAPSHOT_REQUIRED")
    event_hash = str(quote.get("provider_event_sha256") or "").lower()
    if len(event_hash) != 64 or content_sha256(dict(event)) != event_hash:
        raise MLBPITJoinError("PROVIDER_EVENT_HASH_MISMATCH")

    event_id = str(event.get("id") or "").strip()
    quote_event_id = str(quote.get("provider_event_id") or "").strip()
    if not event_id or not quote_event_id or event_id != quote_event_id:
        raise MLBPITJoinError("PROVIDER_EVENT_ID_SNAPSHOT_MISMATCH")

    away = normalize_name(event.get("away_team"))
    home = normalize_name(event.get("home_team"))
    if not away or not home or away == home:
        raise MLBPITJoinError("PROVIDER_EVENT_TEAM_IDENTITY_MISSING")
    commence = _parse_ts(event.get("commence_time"), "provider_event.commence_time")

    matches: list[str] = []
    for game in games:
        if not isinstance(game, Mapping):
            continue
        if normalize_name(game.get("away_name")) != away or normalize_name(game.get("home_name")) != home:
            continue
        start = _parse_ts(game.get("first_pitch_ts"), "game_candidate.first_pitch_ts")
        if abs((start - commence).total_seconds()) > EVENT_TIME_TOLERANCE_SECONDS:
            continue
        game_id = str(game.get("game_id") or "").strip()
        if game_id:
            matches.append(game_id)
    unique = set(matches)
    if not unique:
        raise MLBPITJoinError("PROVIDER_EVENT_GAME_NOT_FOUND")
    if len(unique) != 1:
        raise MLBPITJoinError("PROVIDER_EVENT_GAME_AMBIGUOUS")
    return next(iter(unique))


def _verify_snapshot_reproduces_game(snapshot: Mapping[str, Any], game: Mapping[str, Any]) -> None:
    checks = {
        "game_id": str(snapshot.get("game_id") or "") == str(game.get("game_id") or ""),
        "away_team_id": str(snapshot.get("away_team_id") or "") == str(game.get("away_team_id") or ""),
        "home_team_id": str(snapshot.get("home_team_id") or "") == str(game.get("home_team_id") or ""),
        "away_team_name": normalize_name(snapshot.get("away_team_name")) == normalize_name(game.get("away_name")),
        "home_team_name": normalize_name(snapshot.get("home_team_name")) == normalize_name(game.get("home_name")),
    }
    for field, valid in checks.items():
        if not valid:
            raise MLBPITJoinError(f"CANONICAL_GAME_SNAPSHOT_REPRODUCTION_MISMATCH:{field}")

    snapshot_start = _parse_ts(
        snapshot.get("first_pitch_at"), "canonical_game_snapshot.first_pitch_at"
    )
    game_start = _parse_ts(game.get("first_pitch_ts"), "game_candidate.first_pitch_ts")
    if abs((snapshot_start - game_start).total_seconds()) > EVENT_TIME_TOLERANCE_SECONDS:
        raise MLBPITJoinError("CANONICAL_GAME_SNAPSHOT_REPRODUCTION_MISMATCH:first_pitch_at")


def _verify_archive_identity(
    quote: Mapping[str, Any], game_id: str, game: Mapping[str, Any]
) -> str:
    if str(quote.get("game_id") or "") != str(game_id):
        raise MLBPITJoinError("ARCHIVED_CANONICAL_GAME_MISMATCH")
    snapshot = quote.get("canonical_game_snapshot")
    snapshot_hash = str(quote.get("canonical_game_snapshot_sha256") or "").lower()
    if not isinstance(snapshot, Mapping) or len(snapshot_hash) != 64:
        raise MLBPITJoinError("CANONICAL_GAME_SNAPSHOT_REQUIRED")
    if content_sha256(dict(snapshot)) != snapshot_hash:
        raise MLBPITJoinError("CANONICAL_GAME_SNAPSHOT_HASH_MISMATCH")
    if str(snapshot.get("game_id") or "") != str(game_id):
        raise MLBPITJoinError("CANONICAL_GAME_SNAPSHOT_ID_MISMATCH")
    _verify_snapshot_reproduces_game(snapshot, game)

    snapshot_first_pitch = _parse_ts(
        snapshot.get("first_pitch_at"), "canonical_game_snapshot.first_pitch_at"
    )
    quote_first_pitch = _parse_ts(quote.get("first_pitch_at"), "quote.first_pitch_at")
    if quote_first_pitch != snapshot_first_pitch:
        raise MLBPITJoinError("ARCHIVED_FIRST_PITCH_SNAPSHOT_MISMATCH")
    quote_ts = _parse_ts(
        quote.get("quote_retrieved_at") or quote.get("retrieved_at"),
        "quote_retrieved_at",
    )
    game_first_pitch = _parse_ts(game.get("first_pitch_ts"), "game_candidate.first_pitch_ts")
    if quote_ts >= game_first_pitch:
        raise MLBPITJoinError("QUOTE_NOT_PREGAME_CANONICAL")
    if quote_ts >= snapshot_first_pitch:
        raise MLBPITJoinError("QUOTE_NOT_PREGAME_ARCHIVED_SNAPSHOT")

    entity_id = str(quote.get("entity_id") or "").strip()
    if not entity_id:
        raise MLBPITJoinError("CANONICAL_ENTITY_ID_REQUIRED")
    binding = {
        "provider_event_id": str(quote.get("provider_event_id") or ""),
        "provider_event_sha256": str(quote.get("provider_event_sha256") or ""),
        "canonical_game_id": str(game_id),
        "canonical_entity_id": entity_id,
        "canonical_game_snapshot_sha256": snapshot_hash,
        "resolver_contract": "EXACT_NORMALIZED_TEAM_TIME_AND_PARTICIPANT_IDENTITY",
    }
    binding_hash = str(quote.get("identity_binding_sha256") or "").lower()
    if len(binding_hash) != 64 or content_sha256(binding) != binding_hash:
        raise MLBPITJoinError("IDENTITY_BINDING_HASH_MISMATCH")
    return entity_id


def _verify_entity(
    *,
    market: str,
    entity_id: str,
    game: Mapping[str, Any],
    player_candidates: list[Mapping[str, Any]],
) -> None:
    if market in {"F5_MONEYLINE", "F5_RUN_LINE"}:
        team_ids = {str(game.get("away_team_id") or ""), str(game.get("home_team_id") or "")}
        if entity_id not in team_ids:
            raise MLBPITJoinError("CANONICAL_TEAM_ENTITY_NOT_REPRODUCIBLE")
        return
    if market in {"F5_TOTALS", "NRFI", "YRFI"}:
        if entity_id != str(game.get("game_id") or ""):
            raise MLBPITJoinError("CANONICAL_GAME_ENTITY_NOT_REPRODUCIBLE")
        return
    if market in _BINARY_MARKETS:
        matches = {
            str(row.get("player_id") or "")
            for row in player_candidates
            if isinstance(row, Mapping) and str(row.get("player_id") or "") == entity_id
        }
        if len(matches) != 1:
            raise MLBPITJoinError("CANONICAL_PLAYER_ENTITY_NOT_REPRODUCIBLE")
        return
    raise MLBPITJoinError("ADDITIONAL_MARKET_IDENTITY_UNSUPPORTED")


def _binary_identity_ambiguity(
    *,
    quote: Mapping[str, Any],
    market: str,
    entity_id: str,
    player_candidates: list[Mapping[str, Any]],
) -> list[str]:
    if market not in _BINARY_MARKETS:
        return []
    provider_name = str(quote.get("provider_participant_name") or "").strip()
    if not provider_name:
        return [_MISSING_RAW_PARTICIPANT]
    normalized = normalize_name(provider_name)
    stored_normalized = str(quote.get("provider_participant_name_normalized") or "").strip()
    if stored_normalized and stored_normalized != normalized:
        raise MLBPITJoinError("PROVIDER_PARTICIPANT_NORMALIZATION_MISMATCH")
    matches = [
        row
        for row in player_candidates
        if isinstance(row, Mapping)
        and str(row.get("player_id") or "") == entity_id
        and normalize_name(row.get("player_name")) == normalized
    ]
    if len(matches) != 1:
        raise MLBPITJoinError("PROVIDER_PARTICIPANT_IDENTITY_NOT_REPRODUCIBLE")
    return []


def _binary_outcome(event_true: bool, side: Any) -> str:
    direction = str(side or "").upper()
    if direction not in {"YES", "NO"}:
        raise MLBPITJoinError("BINARY_SIDE_MUST_BE_YES_OR_NO")
    won = event_true if direction == "YES" else not event_true
    return "WIN" if won else "LOSS"


def _f5_moneyline_outcome(
    facts: Mapping[str, Any],
    side: Any,
    *,
    settlement_type: MoneylineSettlementType | None = None,
) -> str:
    f5 = facts.get("f5")
    if not isinstance(f5, Mapping):
        raise MLBPITJoinError("F5_FACTS_MISSING")
    away = float(f5["away_runs"])
    home = float(f5["home_runs"])
    direction = str(side or "").upper()
    if direction in {"HOME", "HOME_ML"}:
        selected, other = home, away
    elif direction in {"AWAY", "AWAY_ML"}:
        selected, other = away, home
    else:
        raise MLBPITJoinError("F5_MONEYLINE_SIDE_INVALID")
    if selected == other:
        # A tie is settleable only under an explicitly declared
        # settlement type (sportsedge.moneyline_settlement): TWO_WAY
        # pushes, THREE_WAY makes the team selection lose to the DRAW
        # selection. Undeclared keeps the historical fail-closed code.
        if settlement_type is None:
            raise MLBPITJoinError(_F5_TIE_POLICY_MISSING)
        return settle_moneyline(
            settlement_type, side=direction,
            selected_runs=selected, other_runs=other)
    return "WIN" if selected > other else "LOSS"


def _f5_run_line_outcome(facts: Mapping[str, Any], line: Any, side: Any) -> str:
    f5 = facts.get("f5")
    if not isinstance(f5, Mapping):
        raise MLBPITJoinError("F5_FACTS_MISSING")
    away = float(f5["away_runs"])
    home = float(f5["home_runs"])
    spread = float(line)
    direction = str(side or "").upper()
    if direction in {"HOME", "HOME_RL"}:
        selected, other = home, away
    elif direction in {"AWAY", "AWAY_RL"}:
        selected, other = away, home
    else:
        raise MLBPITJoinError("F5_RUN_LINE_SIDE_INVALID")
    adjusted = selected + spread
    if abs(adjusted - other) <= 1e-12:
        return "PUSH"
    return "WIN" if adjusted > other else "LOSS"


def _f5_total_outcome(facts: Mapping[str, Any], line: Any, side: Any) -> str:
    f5 = facts.get("f5")
    if not isinstance(f5, Mapping):
        raise MLBPITJoinError("F5_FACTS_MISSING")
    total = float(f5["away_runs"]) + float(f5["home_runs"])
    threshold = float(line)
    direction = str(side or "").upper()
    if direction not in {"OVER", "UNDER"}:
        raise MLBPITJoinError("F5_TOTAL_SIDE_INVALID")
    if abs(total - threshold) <= 1e-12:
        return "PUSH"
    won = total > threshold if direction == "OVER" else total < threshold
    return "WIN" if won else "LOSS"


# Derived F5 settlement (matrix M14/M15): outcomes derive from the
# same facts["f5"] score slice as the four canonical F5 markets, with
# the selection grammars shared with the pricing read-out layer
# (sportsedge.f5_derived_readouts), so a selection means the same
# thing at intake and at settlement.

def _f5_score(facts: Mapping[str, Any]) -> tuple[float, float]:
    f5 = facts.get("f5")
    if not isinstance(f5, Mapping):
        raise MLBPITJoinError("F5_FACTS_MISSING")
    return float(f5["away_runs"]), float(f5["home_runs"])


def _f5_btts_outcome(facts: Mapping[str, Any], line: Any, side: Any) -> str:
    away, home = _f5_score(facts)
    try:
        rung = parse_btts_rung(line)
    except F5DerivedReadoutError as exc:
        raise MLBPITJoinError(f"F5_BTTS_RUNG_INVALID: {exc}") from exc
    return _binary_outcome(away >= rung and home >= rung, side)


def _f5_winning_margin_outcome(facts: Mapping[str, Any], side: Any) -> str:
    away, home = _f5_score(facts)
    try:
        band = parse_margin_band(side)
    except F5DerivedReadoutError as exc:
        raise MLBPITJoinError(f"F5_WINNING_MARGIN_SELECTION_INVALID: {exc}") from exc
    margin = int(home - away)
    return "WIN" if band.contains(margin) else "LOSS"


def _f5_correct_score_outcome(facts: Mapping[str, Any], side: Any) -> str:
    away, home = _f5_score(facts)
    try:
        parsed = parse_correct_score_selection(side)
    except F5DerivedReadoutError as exc:
        raise MLBPITJoinError(f"F5_CORRECT_SCORE_SELECTION_INVALID: {exc}") from exc
    if parsed[0] == _F5_ANY_OTHER:
        # The catch-all wins iff the realized score is none of the
        # market's other quoted cells -- a fact about the whole
        # selection set, which a single settlement row cannot carry.
        # Fail closed by name rather than guessing the set.
        raise MLBPITJoinError("F5_CORRECT_SCORE_ANY_OTHER_REQUIRES_SELECTION_SET")
    return "WIN" if (int(away), int(home)) == (parsed[1], parsed[2]) else "LOSS"


# Period (first-3 / first-7 innings) settlement, the F3/F7 counterpart
# of the F5 functions above: outcomes derive from the cumulative score
# through the period's completed innings, carried on facts["f3"] /
# facts["f7"] in the same {away_runs, home_runs} shape as facts["f5"].
_PERIOD_FACT_KEY_BY_MARKET = {
    "F3_MONEYLINE": "f3", "F3_RUN_LINE": "f3", "F3_TOTALS": "f3",
    "F7_MONEYLINE": "f7", "F7_RUN_LINE": "f7", "F7_TOTALS": "f7",
}
PERIOD_MONEYLINE_TIE_POLICY_MISSING = {
    "F3_MONEYLINE": "F3_MONEYLINE_TIE_POLICY_NOT_NORMALIZED",
    "F7_MONEYLINE": "F7_MONEYLINE_TIE_POLICY_NOT_NORMALIZED",
}
_PERIOD_TEAM_TOTAL_FACT_KEY = {"F3_TEAM_TOTALS": "f3", "F7_TEAM_TOTALS": "f7"}


def _period_team_total_outcome(facts: Mapping[str, Any], entity_id: str,
                               line: Any, side: Any, *, fact_key: str,
                               tag: str) -> str:
    """Period team total over facts[fact_key], whose slice carries the
    team identity ({away_runs, home_runs, away_team_id, home_team_id})
    -- the same settlement semantics the catalog module's
    _team_total_outcome applies over facts["f5"] for F5_TEAM_TOTALS."""
    period = facts.get(fact_key)
    if not isinstance(period, Mapping):
        raise MLBPITJoinError(f"{tag}_FACTS_MISSING")
    away_id = str(period.get("away_team_id") or "").strip()
    home_id = str(period.get("home_team_id") or "").strip()
    if not away_id or not home_id or away_id == home_id:
        raise MLBPITJoinError(f"{tag}_TEAM_SCORE_IDENTITY_MISSING")
    entity = str(entity_id or "").strip()
    if entity == away_id:
        runs = float(period["away_runs"])
    elif entity == home_id:
        runs = float(period["home_runs"])
    else:
        raise MLBPITJoinError(f"{tag}_TEAM_TOTAL_ENTITY_ID_NOT_IN_GAME")
    threshold = float(line)
    direction = str(side or "").upper()
    if abs(runs - threshold) <= 1e-12:
        return "PUSH"
    if direction == "OVER":
        return "WIN" if runs > threshold else "LOSS"
    if direction == "UNDER":
        return "WIN" if runs < threshold else "LOSS"
    raise MLBPITJoinError(f"{tag}_TEAM_TOTAL_SIDE_INVALID")


def _period_score(facts: Mapping[str, Any], fact_key: str, tag: str) -> tuple[float, float]:
    period = facts.get(fact_key)
    if not isinstance(period, Mapping):
        raise MLBPITJoinError(f"{tag}_FACTS_MISSING")
    return float(period["away_runs"]), float(period["home_runs"])


def _period_moneyline_outcome(
    facts: Mapping[str, Any],
    side: Any,
    *,
    fact_key: str,
    tag: str,
    settlement_type: MoneylineSettlementType | None = None,
) -> str:
    away, home = _period_score(facts, fact_key, tag)
    direction = str(side or "").upper()
    if direction in {"HOME", "HOME_ML"}:
        selected, other = home, away
    elif direction in {"AWAY", "AWAY_ML"}:
        selected, other = away, home
    else:
        raise MLBPITJoinError(f"{tag}_MONEYLINE_SIDE_INVALID")
    if selected == other:
        # Same fail-closed tie discipline as F5: a tie settles only
        # under an explicitly declared settlement type.
        if settlement_type is None:
            raise MLBPITJoinError(
                PERIOD_MONEYLINE_TIE_POLICY_MISSING[f"{tag}_MONEYLINE"])
        return settle_moneyline(
            settlement_type, side=direction,
            selected_runs=selected, other_runs=other)
    return "WIN" if selected > other else "LOSS"


def _period_run_line_outcome(facts: Mapping[str, Any], line: Any, side: Any,
                             *, fact_key: str, tag: str) -> str:
    away, home = _period_score(facts, fact_key, tag)
    spread = float(line)
    direction = str(side or "").upper()
    if direction in {"HOME", "HOME_RL"}:
        selected, other = home, away
    elif direction in {"AWAY", "AWAY_RL"}:
        selected, other = away, home
    else:
        raise MLBPITJoinError(f"{tag}_RUN_LINE_SIDE_INVALID")
    adjusted = selected + spread
    if abs(adjusted - other) <= 1e-12:
        return "PUSH"
    return "WIN" if adjusted > other else "LOSS"


def _period_total_outcome(facts: Mapping[str, Any], line: Any, side: Any,
                          *, fact_key: str, tag: str) -> str:
    away, home = _period_score(facts, fact_key, tag)
    total = away + home
    threshold = float(line)
    direction = str(side or "").upper()
    if direction not in {"OVER", "UNDER"}:
        raise MLBPITJoinError(f"{tag}_TOTAL_SIDE_INVALID")
    if abs(total - threshold) <= 1e-12:
        return "PUSH"
    won = total > threshold if direction == "OVER" else total < threshold
    return "WIN" if won else "LOSS"


def _policy_ambiguity(
    facts: Mapping[str, Any],
    market: str,
    *,
    sportsbook: Any = None,
) -> list[str]:
    reasons: list[str] = []
    if market in PERIOD_MONEYLINE_TIE_POLICY_MISSING:
        period = facts.get(_PERIOD_FACT_KEY_BY_MARKET[market])
        if isinstance(period, Mapping) and "away_runs" in period and "home_runs" in period:
            if float(period["away_runs"]) == float(period["home_runs"]):
                # A tied period moneyline is ambiguous only while the
                # book's settlement type is undeclared (mirrors F5).
                if declared_moneyline_settlement_type(
                        market, sportsbook) is None:
                    reasons.append(PERIOD_MONEYLINE_TIE_POLICY_MISSING[market])
    if market == "F5_MONEYLINE":
        f5 = facts.get("f5")
        if isinstance(f5, Mapping) and "away_runs" in f5 and "home_runs" in f5:
            if float(f5["away_runs"]) == float(f5["home_runs"]):
                # A tied F5 moneyline is ambiguous only while the
                # book's settlement type is undeclared. A verified
                # declaration (e.g. DraftKings TWO_WAY, ties push)
                # defines the settlement, so no ambiguity is recorded.
                if declared_moneyline_settlement_type(
                        market, sportsbook) is None:
                    reasons.append(_F5_TIE_POLICY_MISSING)
    elif market == "FIRST_HOME_RUN":
        first_hr = facts.get("first_home_run")
        if isinstance(first_hr, Mapping) and first_hr.get("occurred") is False:
            reasons.append(_FIRST_HOME_RUN_NO_HR_POLICY_MISSING)
    return reasons


def _derive_outcome(
    facts: Mapping[str, Any],
    market: str,
    entity_id: str,
    line: Any,
    side: Any,
    *,
    sportsbook: Any = None,
) -> str:
    if market == "F5_MONEYLINE":
        return _f5_moneyline_outcome(
            facts, side,
            settlement_type=declared_moneyline_settlement_type(
                market, sportsbook))
    if market == "F5_RUN_LINE":
        return _f5_run_line_outcome(facts, line, side)
    if market == "F5_TOTALS":
        return _f5_total_outcome(facts, line, side)
    if market == "F5_BOTH_TEAMS_TO_SCORE":
        return _f5_btts_outcome(facts, line, side)
    if market == "F5_WINNING_MARGIN":
        return _f5_winning_margin_outcome(facts, side)
    if market == "F5_CORRECT_SCORE":
        return _f5_correct_score_outcome(facts, side)
    if market in _PERIOD_TEAM_TOTAL_FACT_KEY:
        fact_key = _PERIOD_TEAM_TOTAL_FACT_KEY[market]
        return _period_team_total_outcome(
            facts, entity_id, line, side,
            fact_key=fact_key, tag=market.split("_", 1)[0])
    if market in _PERIOD_FACT_KEY_BY_MARKET:
        fact_key = _PERIOD_FACT_KEY_BY_MARKET[market]
        tag = market.split("_", 1)[0]
        if market.endswith("_MONEYLINE"):
            return _period_moneyline_outcome(
                facts, side, fact_key=fact_key, tag=tag,
                settlement_type=declared_moneyline_settlement_type(
                    market, sportsbook))
        if market.endswith("_RUN_LINE"):
            return _period_run_line_outcome(
                facts, line, side, fact_key=fact_key, tag=tag)
        return _period_total_outcome(
            facts, line, side, fact_key=fact_key, tag=tag)
    if market in {"NRFI", "YRFI"}:
        first = facts.get("first_inning")
        if not isinstance(first, Mapping):
            raise MLBPITJoinError("FIRST_INNING_FACTS_MISSING")
        value = first.get("nrfi") if market == "NRFI" else first.get("yrfi")
        if type(value) is not bool:
            raise MLBPITJoinError("FIRST_INNING_BINARY_FACT_MISSING")
        normalized_side = "YES" if str(side or "").upper() in {"NRFI", "YRFI"} else side
        return _binary_outcome(value, normalized_side)
    if market == "FIRST_HOME_RUN":
        first_hr = facts.get("first_home_run")
        if not isinstance(first_hr, Mapping) or type(first_hr.get("occurred")) is not bool:
            raise MLBPITJoinError("FIRST_HOME_RUN_FACT_MISSING")
        if first_hr.get("occurred") is False:
            raise MLBPITJoinError(_FIRST_HOME_RUN_NO_HR_POLICY_MISSING)
        event_true = str(first_hr.get("batter_id") or "") == entity_id
        return _binary_outcome(event_true, side)
    if market == "PITCHER_RECORD_WIN":
        winner = facts.get("winning_pitcher")
        if not isinstance(winner, Mapping) or not str(winner.get("pitcher_id") or ""):
            raise MLBPITJoinError("WINNING_PITCHER_FACT_MISSING")
        return _binary_outcome(str(winner.get("pitcher_id")) == entity_id, side)
    raise MLBPITJoinError("ADDITIONAL_SETTLEMENT_INTERPRETER_MISSING")


def join_additional_archive(
    *,
    archive_payload: Mapping[str, Any],
    game_candidates: Iterable[Mapping[str, Any]],
    player_candidates_by_game: Mapping[str, Iterable[Mapping[str, Any]]],
    model_rows: Iterable[Mapping[str, Any]],
    official_fact_reports: Iterable[Mapping[str, Any]],
    settlement_rows: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    source_class, quote_source_hash, quotes = _verify_archive(archive_payload)
    games = [dict(row) for row in game_candidates if isinstance(row, Mapping)]
    game_by_id = _index_unique(games, "game_id")
    players_by_game = {
        str(game_id): [dict(row) for row in rows if isinstance(row, Mapping)]
        for game_id, rows in player_candidates_by_game.items()
    }
    model_idx = _model_index(model_rows)
    fact_idx = _fact_index(official_fact_reports)
    settlement_list = [dict(row) for row in settlement_rows if isinstance(row, Mapping)]
    settlement_idx = _index_unique(settlement_list, "observation_key")
    settlement_duplicates = _duplicate_keys(settlement_list, "observation_key")
    required_rules_by_market = _required_rules_by_market()

    joined: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for source_index, quote in enumerate(quotes):
        if not isinstance(quote, Mapping):
            failures.append({"source_index": source_index, "reason": "QUOTE_NOT_OBJECT"})
            continue
        try:
            if quote.get("pit_eligible") is not True:
                raise MLBPITJoinError("QUOTE_NOT_PIT_ELIGIBLE")
            market = str(quote.get("market") or "").upper()
            if market not in CANONICAL_MARKETS:
                raise MLBPITJoinError("ADDITIONAL_ARCHIVE_MARKET_REQUIRED")

            game_id = _bind_odds_api_event(quote, games)
            game = game_by_id.get(game_id)
            if game is None:
                raise MLBPITJoinError("CANONICAL_GAME_ROW_NOT_UNIQUE")
            entity_id = _verify_archive_identity(quote, game_id, game)
            candidates = players_by_game.get(game_id, [])
            _verify_entity(market=market, entity_id=entity_id, game=game, player_candidates=candidates)
            identity_ambiguity = _binary_identity_ambiguity(
                quote=quote,
                market=market,
                entity_id=entity_id,
                player_candidates=candidates,
            )

            model_key = (
                game_id,
                market,
                entity_id,
                _line_key(quote.get("line")),
                str(quote.get("side") or "").upper(),
            )
            model = model_idx.get(model_key)
            if model is None:
                raise MLBPITJoinError("MODEL_ROW_NOT_FOUND_OR_AMBIGUOUS")
            model_class = str(model.get("evidence_class") or "").strip().upper()
            if model_class not in {_LIVE_MODEL_CLASS, _SYNTHETIC_CLASS}:
                raise MLBPITJoinError("MODEL_EVIDENCE_CLASS_REQUIRED")

            fact_report = fact_idx.get(game_id)
            if fact_report is None:
                raise MLBPITJoinError("OFFICIAL_FACT_REPORT_NOT_FOUND_OR_AMBIGUOUS")
            fact_class = str(fact_report.get("evidence_class") or "").strip().upper()
            if fact_class not in {_LIVE_FACT_CLASS, _SYNTHETIC_CLASS}:
                raise MLBPITJoinError("OFFICIAL_FACT_EVIDENCE_CLASS_REQUIRED")
            facts = fact_report.get("facts")
            if not isinstance(facts, Mapping):
                raise MLBPITJoinError("OFFICIAL_FACTS_PAYLOAD_MISSING")
            facts_hash = str(fact_report.get("facts_sha256") or "").lower()
            if len(facts_hash) != 64 or hashlib.sha256(canonical_bytes(dict(facts))).hexdigest() != facts_hash:
                raise MLBPITJoinError("OFFICIAL_FACTS_HASH_MISMATCH")

            quote_ts = str(quote.get("quote_retrieved_at") or quote.get("retrieved_at") or "")
            obs_key = observation_key(
                game_id=game_id,
                market=market,
                entity_id=entity_id,
                line=quote.get("line"),
                side=quote.get("side"),
                book_key=quote.get("book_key"),
                quote_ts=quote_ts,
            )
            if obs_key in settlement_duplicates:
                raise MLBPITJoinError("SETTLEMENT_EVIDENCE_AMBIGUOUS")
            settlement = settlement_idx.get(obs_key)

            required_rules = required_rules_by_market.get(market)
            if required_rules is None:
                raise MLBPITJoinError("SETTLEMENT_RULE_CONTRACT_MISSING")
            sportsbook = str(quote.get("sportsbook") or "DraftKings")
            if settlement is None:
                rule_class = _MISSING_RULE_CLASS
                rule_evidence: Mapping[str, Any] | None = None
                ambiguity_reasons = list(identity_ambiguity)
                void_reasons: list[str] = []
            else:
                rule_class = str(settlement.get("evidence_class") or "").strip().upper()
                if rule_class not in {_LIVE_RULE_CLASS, _SYNTHETIC_CLASS}:
                    raise MLBPITJoinError("BOOK_RULE_EVIDENCE_CLASS_REQUIRED")
                candidate = settlement.get("book_rule_evidence")
                rule_evidence = candidate if isinstance(candidate, Mapping) else None
                ambiguity_reasons = [
                    *identity_ambiguity,
                    *[str(x) for x in settlement.get("ambiguity_reasons", ()) if str(x)],
                ]
                void_reasons = [str(x) for x in settlement.get("void_reasons", ()) if str(x)]

            book_valid, _ = _rules_match_sportsbook(
                required_rules=required_rules,
                evidence=rule_evidence,
                sportsbook=sportsbook,
            )
            rules_hash = _rules_hash(
                required_rules=required_rules,
                evidence=rule_evidence,
                sportsbook=sportsbook,
            )
            fact_state = str((official_fact_coverage(facts).get(market) or {}).get("state") or "OFFICIAL_FACTS_MISSING")
            ambiguity_reasons = [
                *ambiguity_reasons,
                *_policy_ambiguity(facts, market, sportsbook=sportsbook),
            ]
            settlement_state = classify_observation_settlement(
                official_fact_state=fact_state,
                book_rules_validated=book_valid,
                ambiguity_reasons=ambiguity_reasons,
            )
            if settlement_state == "SETTLEMENT_ELIGIBLE" and void_reasons:
                settlement_state = "VOID"

            settled_outcome = None
            if settlement_state == "SETTLEMENT_ELIGIBLE":
                settled_outcome = _derive_outcome(
                    facts, market, entity_id, quote.get("line"),
                    quote.get("side"), sportsbook=sportsbook,
                )

            raw = {
                "market": market,
                "game_id": game_id,
                "entity_id": entity_id,
                "quote_ts": quote_ts,
                "first_pitch_ts": quote.get("first_pitch_at"),
                "line": quote.get("line"),
                "side": quote.get("side"),
                "sportsbook": sportsbook,
                "book_key": quote.get("book_key") or "draftkings",
                "source_evidence_class": source_class,
                "model_evidence_class": model_class,
                "official_fact_evidence_class": fact_class,
                "book_rule_evidence_class": rule_class,
                "quote_source_hash": quote_source_hash,
                "provider_event_hash": quote.get("provider_event_sha256"),
                "identity_binding_hash": quote.get("identity_binding_sha256"),
                "history_asof_ts": model.get("history_asof_ts"),
                "history_source_hash": model.get("history_source_hash"),
                "model_input_hash": model.get("model_input_hash"),
                "official_facts_hash": facts_hash,
                "settlement_rules_hash": rules_hash,
                "settlement_state": settlement_state,
                "settled_outcome": settled_outcome,
                "candidate_p": model.get("candidate_p"),
                "incumbent_p": model.get("incumbent_p"),
            }
            normalized = normalize_pit_observation(raw)
            joined.append({"observation_key": obs_key, "source_index": source_index, **asdict_compat(normalized)})
        except Exception as exc:
            failures.append(
                {
                    "source_index": source_index,
                    "provider_event_id": quote.get("provider_event_id"),
                    "market": quote.get("market"),
                    "entity_id": quote.get("entity_id"),
                    "reason": f"{type(exc).__name__}:{exc}",
                }
            )

    return {
        "schema_version": 1,
        "archive_type": ARCHIVE_TYPE,
        "archive_payload_sha256": quote_source_hash,
        "source_quote_count": len(quotes),
        "joined_observation_count": len(joined),
        "failure_count": len(failures),
        "observations": joined,
        "failures": failures,
    }
