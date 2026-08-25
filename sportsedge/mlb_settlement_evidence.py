"""MLB settlement evidence contract.

Official MLB facts prove what happened on the field. They do not, by themselves,
prove how a sportsbook settles a wager. This module keeps those evidence classes
separate and fails closed on missing rule evidence or observation ambiguity.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any, Mapping, Sequence

from .mlb_acceptance_matrix import build_acceptance_matrix


class MLBSettlementEvidenceError(ValueError):
    pass


_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_GAME_MARKETS = {"MONEYLINE", "RUN_LINE", "TOTALS", "TEAM_TOTALS"}
_F5_MARKETS = {"F5_MONEYLINE", "F5_RUN_LINE", "F5_TOTALS", "F5_TEAM_TOTALS"}
_FIRST_INNING_MARKETS = {"NRFI", "YRFI"}
_BATTER_FIELD_BY_MARKET = {
    "HITS": "hits", "HOME_RUNS": "home_runs", "TOTAL_BASES": "total_bases",
    "RBI": "rbi", "RUNS": "runs", "STOLEN_BASES": "stolen_bases",
    "BATTER_BB": "walks", "EXTRA_BASE_HITS": "extra_base_hits",
    "HITS_RUNS_RBIS": "hits_runs_rbis",
    "HITS_RUNS_STOLEN_BASES": "hits_runs_stolen_bases",
    "RUNS_RBIS": "runs_rbis", "HITS_STOLEN_BASES": "hits_stolen_bases",
    "HITS_WALKS_STOLEN_BASES": "hits_walks_stolen_bases",
    "SINGLES": "singles", "DOUBLES": "doubles", "TRIPLES": "triples",
    "BATTER_K": "strikeouts",
}
_PITCHER_FIELD_BY_MARKET = {
    "PITCHER_K": "strikeouts", "PITCHER_OUTS": "outs", "PITCHER_ER": "earned_runs",
    "PITCHER_HITS_ALLOWED": "hits_allowed", "PITCHER_BB": "walks_allowed",
    "PITCHER_HITS_WALKS_ER": "hits_walks_er",
    "EITHER_PITCHER_HITS_ALLOWED": "hits_allowed", "EITHER_PITCHER_BB": "walks_allowed",
    "EITHER_PITCHER_ER": "earned_runs",
}
_SPECIAL_MARKETS = {"FIRST_HOME_RUN", "PITCHER_RECORD_WIN"}


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode("utf-8")


def as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def outs_from_ip(value: Any) -> int:
    text = str(value or "0.0")
    whole, sep, frac = text.partition(".")
    if not sep:
        return int(whole) * 3
    if frac not in {"0", "1", "2"}:
        raise MLBSettlementEvidenceError(f"BAD_INNINGS_PITCHED:{text}")
    return int(whole) * 3 + int(frac)


def batter_fact(player_id: str, stats: Mapping[str, Any]) -> dict[str, Any]:
    hits = as_int(stats.get("hits")); doubles = as_int(stats.get("doubles")); triples = as_int(stats.get("triples")); home_runs = as_int(stats.get("homeRuns"))
    singles = hits - doubles - triples - home_runs
    if singles < 0:
        raise MLBSettlementEvidenceError(f"NEGATIVE_SINGLES:{player_id}")
    total_bases = singles + 2 * doubles + 3 * triples + 4 * home_runs
    rbi = as_int(stats.get("rbi")); runs = as_int(stats.get("runs")); walks = as_int(stats.get("baseOnBalls")); strikeouts = as_int(stats.get("strikeOuts")); stolen_bases = as_int(stats.get("stolenBases"))
    extra_base_hits = doubles + triples + home_runs
    return {
        "player_id": str(player_id), "plate_appearances": as_int(stats.get("plateAppearances")),
        "hits": hits, "singles": singles, "doubles": doubles, "triples": triples,
        "home_runs": home_runs, "total_bases": total_bases, "rbi": rbi, "runs": runs,
        "walks": walks, "strikeouts": strikeouts, "stolen_bases": stolen_bases,
        "extra_base_hits": extra_base_hits, "hits_runs_rbis": hits + runs + rbi,
        "hits_runs_stolen_bases": hits + runs + stolen_bases, "runs_rbis": runs + rbi,
        "hits_stolen_bases": hits + stolen_bases,
        "hits_walks_stolen_bases": hits + walks + stolen_bases,
    }


def pitcher_fact(player_id: str, stats: Mapping[str, Any]) -> dict[str, Any]:
    walks = as_int(stats.get("baseOnBalls")); hits = as_int(stats.get("hits")); earned_runs = as_int(stats.get("earnedRuns")); outs = outs_from_ip(stats.get("inningsPitched"))
    if not 0 <= outs <= 27:
        raise MLBSettlementEvidenceError(f"PITCHER_OUTS_OUT_OF_RANGE:{player_id}:{outs}")
    return {
        "player_id": str(player_id), "walks": walks, "walks_allowed": walks,
        "strikeouts": as_int(stats.get("strikeOuts")), "hits_allowed": hits,
        "earned_runs": earned_runs, "outs": outs, "hits_walks_er": hits + walks + earned_runs,
    }


def _catalog_markets() -> tuple[list[str], dict[str, dict[str, Any]]]:
    matrix = build_acceptance_matrix()
    rows = {str(row["market"]): dict(row) for row in matrix["markets"]}
    markets = sorted(rows)
    declared = _GAME_MARKETS | _F5_MARKETS | _FIRST_INNING_MARKETS | set(_BATTER_FIELD_BY_MARKET) | set(_PITCHER_FIELD_BY_MARKET) | _SPECIAL_MARKETS
    if declared != set(markets):
        raise MLBSettlementEvidenceError(f"official fact coverage mismatch missing={sorted(set(markets)-declared)} extra={sorted(declared-set(markets))}")
    return markets, rows


def _rows_have_field(rows: Any, field: str) -> bool:
    return isinstance(rows, list) and bool(rows) and all(isinstance(row, Mapping) and field in row for row in rows)


def _score_fact_proven(value: Any, *, require_team_ids: bool) -> bool:
    if not isinstance(value, Mapping) or not all(k in value for k in ("away_runs", "home_runs")):
        return False
    if not require_team_ids:
        return True
    return all(str(value.get(k) or "").strip() for k in ("away_team_id", "home_team_id"))


def official_fact_coverage(facts: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    markets, _ = _catalog_markets(); out: dict[str, dict[str, Any]] = {}
    for market in markets:
        proven = False; source_key = ""
        if market in _GAME_MARKETS:
            proven = _score_fact_proven(facts.get("game"), require_team_ids=market == "TEAM_TOTALS")
            source_key = "game.final_score_with_team_identity" if market == "TEAM_TOTALS" else "game.final_score"
        elif market in _F5_MARKETS:
            proven = _score_fact_proven(facts.get("f5"), require_team_ids=market == "F5_TEAM_TOTALS")
            source_key = "f5.score_with_team_identity" if market == "F5_TEAM_TOTALS" else "f5.score"
        elif market in _FIRST_INNING_MARKETS:
            first = facts.get("first_inning"); proven = isinstance(first, Mapping) and all(k in first for k in ("away_runs", "home_runs", "nrfi", "yrfi")); source_key = "first_inning.score"
        elif market in _BATTER_FIELD_BY_MARKET:
            field = _BATTER_FIELD_BY_MARKET[market]; proven = _rows_have_field(facts.get("batters"), field); source_key = f"batters[].{field}"
        elif market in _PITCHER_FIELD_BY_MARKET:
            field = _PITCHER_FIELD_BY_MARKET[market]; proven = _rows_have_field(facts.get("pitchers"), field); source_key = f"pitchers[].{field}"
        elif market == "FIRST_HOME_RUN":
            first_hr = facts.get("first_home_run"); proven = isinstance(first_hr, Mapping) and "occurred" in first_hr and (first_hr.get("occurred") is False or bool(first_hr.get("batter_id"))); source_key = "first_home_run"
        elif market == "PITCHER_RECORD_WIN":
            winner = facts.get("winning_pitcher"); proven = isinstance(winner, Mapping) and bool(winner.get("pitcher_id")); source_key = "winning_pitcher.pitcher_id"
        out[market] = {"state": "OFFICIAL_FACTS_PROVEN" if proven else "OFFICIAL_FACTS_MISSING", "source_key": source_key}
    return out


def _valid_rule_record(value: Any) -> bool:
    if not isinstance(value, Mapping): return False
    sha = str(value.get("source_sha256") or "").lower()
    return bool(str(value.get("status") or "").upper() == "VALIDATED" and str(value.get("sportsbook") or "").strip() and _HEX64.fullmatch(sha) and str(value.get("captured_at_utc") or "").strip() and str(value.get("source_locator") or "").strip())


def validate_book_rules(required_rules: Sequence[str], rule_evidence: Mapping[str, Any] | None) -> tuple[bool, list[str]]:
    evidence = rule_evidence if isinstance(rule_evidence, Mapping) else {}
    missing = [str(rule) for rule in required_rules if not _valid_rule_record(evidence.get(str(rule)))]
    return not missing, missing


def classify_observation_settlement(*, official_fact_state: str, book_rules_validated: bool, ambiguity_reasons: Sequence[str] | None = None) -> str:
    if str(official_fact_state).upper() != "OFFICIAL_FACTS_PROVEN": return "OFFICIAL_FACTS_INCOMPLETE"
    if not book_rules_validated: return "BOOK_SETTLEMENT_UNVALIDATED"
    if [str(x) for x in (ambiguity_reasons or []) if str(x)]: return "AMBIGUOUS_SETTLEMENT"
    return "SETTLEMENT_ELIGIBLE"


def build_settlement_report(facts: Mapping[str, Any], *, source: str, evidence_class: str = "LIVE_OFFICIAL_FACT_PROBE", generated_at_utc: str | None = None, book_rule_evidence: Mapping[str, Any] | None = None) -> dict[str, Any]:
    markets, acceptance_rows = _catalog_markets(); coverage = official_fact_coverage(facts); fact_digest = hashlib.sha256(canonical_bytes(facts)).hexdigest(); market_rows = []
    for market in markets:
        required_rules = [str(x) for x in acceptance_rows[market]["requirements"]["settlement_semantics"]]
        book_valid, missing_rules = validate_book_rules(required_rules, book_rule_evidence); fact_state = str(coverage[market]["state"])
        market_rows.append({
            "market": market, "official_fact_state": fact_state,
            "official_fact_source_key": coverage[market]["source_key"],
            "required_book_rules": required_rules, "book_rules_validated": book_valid,
            "missing_book_rules": missing_rules,
            "settlement_semantics_state": classify_observation_settlement(official_fact_state=fact_state, book_rules_validated=book_valid, ambiguity_reasons=[]),
        })
    fact_complete = all(row["official_fact_state"] == "OFFICIAL_FACTS_PROVEN" for row in market_rows); book_complete = all(bool(row["book_rules_validated"]) for row in market_rows); synthetic = str(evidence_class).upper() == "SYNTHETIC_CONTRACT_TEST"; validation_gate_pass = bool(fact_complete and book_complete and not synthetic)
    return {
        "schema_version": "mlb_settlement_evidence_v3",
        "generated_at_utc": generated_at_utc or datetime.now(timezone.utc).isoformat(),
        "evidence_class": str(evidence_class), "source": str(source),
        "sportsbook_data_used": bool(book_rule_evidence), "market_count": len(markets),
        "official_fact_market_count": sum(row["official_fact_state"] == "OFFICIAL_FACTS_PROVEN" for row in market_rows),
        "book_settlement_validated_market_count": sum(bool(row["book_rules_validated"]) for row in market_rows),
        "official_facts_state": "OFFICIAL_FACTS_PROVEN" if fact_complete else "OFFICIAL_FACTS_PARTIAL",
        "book_settlement_state": "BOOK_SETTLEMENT_VALIDATED" if book_complete else "BOOK_SETTLEMENT_UNVALIDATED",
        "settlement_semantics_validation_gate": "PASS" if validation_gate_pass else "MISSING",
        "counts_as_settlement_semantics_evidence": validation_gate_pass,
        "facts_sha256": fact_digest, "markets": market_rows, "facts": dict(facts),
    }
