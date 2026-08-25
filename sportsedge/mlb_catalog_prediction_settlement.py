"""Catalog-level settlement for immutable MLB prediction-journal rows.

Sportsbook identity and official fact identity are both required. Ambiguous
markets stay UNRESOLVED rather than inheriting guessed sportsbook semantics.
"""
from __future__ import annotations

from datetime import timezone
import hashlib
import json
from math import isfinite
from typing import Any, Mapping

from .mlb_acceptance_matrix import build_acceptance_matrix
from .mlb_additional_pit_joiner import _derive_outcome as _derive_additional_outcome
from .mlb_additional_pit_joiner import _policy_ambiguity
from .mlb_pit_joiner import _derive_count_outcome, _fact_value
from .mlb_settlement_evidence import (
    _PITCHER_FIELD_BY_MARKET,
    build_settlement_report,
    canonical_bytes as settlement_fact_bytes,
    validate_book_rules,
)
from .odds_api_source import normalize_name
from .prediction_journal import JOURNAL_SCHEMA_VERSION
from .runtime import parse_timestamp

CATALOG_SETTLEMENT_SCHEMA_VERSION = "mlb_catalog_prediction_settlement_v1"
CATALOG_REPORT_SCHEMA_VERSION = "mlb_catalog_settlement_evidence_v1"
SYNTHETIC_EVIDENCE_CLASS = "SYNTHETIC_CONTRACT_TEST"
FINAL_RESULTS = frozenset({"WIN", "LOSS", "PUSH"})
GAME_MARKETS = frozenset({"MONEYLINE", "RUN_LINE", "TOTALS", "TEAM_TOTALS"})
ADDITIONAL_MARKETS = frozenset({
    "F5_MONEYLINE", "F5_RUN_LINE", "F5_TOTALS", "NRFI", "YRFI",
    "FIRST_HOME_RUN", "PITCHER_RECORD_WIN",
})
TEAM_TOTAL_MARKETS = frozenset({"TEAM_TOTALS", "F5_TEAM_TOTALS"})
EITHER_PITCHER_MARKETS = frozenset({
    "EITHER_PITCHER_HITS_ALLOWED", "EITHER_PITCHER_BB", "EITHER_PITCHER_ER",
})


class MLBCatalogSettlementError(ValueError):
    pass


def _canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise MLBCatalogSettlementError("settlement payload is not canonical JSON") from exc


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _valid_sha256(value: Any, field: str) -> str:
    text = str(value or "").strip().lower()
    if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text):
        raise MLBCatalogSettlementError(f"{field} must be SHA-256 hex")
    return text


def _line(value: Any) -> float:
    if isinstance(value, bool): raise MLBCatalogSettlementError("prediction line must be finite numeric")
    try: out = float(value)
    except (TypeError, ValueError) as exc: raise MLBCatalogSettlementError("prediction line must be finite numeric") from exc
    if not isfinite(out): raise MLBCatalogSettlementError("prediction line must be finite numeric")
    return out


def _required_rules_by_market() -> dict[str, tuple[str, ...]]:
    return {str(row["market"]): tuple(str(x) for x in row["requirements"]["settlement_semantics"]) for row in build_acceptance_matrix()["markets"]}


def _validated_sportsbook(required_rules: tuple[str, ...], evidence: Mapping[str, Any] | None) -> str | None:
    valid, _ = validate_book_rules(required_rules, evidence)
    if not valid or not isinstance(evidence, Mapping): return None
    books = {normalize_name((evidence.get(rule) or {}).get("sportsbook")) for rule in required_rules if isinstance(evidence.get(rule), Mapping)}
    books.discard("")
    return next(iter(books)) if len(books) == 1 else None


def build_catalog_settlement_report(facts: Mapping[str, Any], *, source: str, evidence_class: str = "LIVE_OFFICIAL_FACT_PROBE", generated_at_utc: str | None = None, book_rule_evidence: Mapping[str, Any] | None = None) -> dict[str, Any]:
    base = build_settlement_report(facts, source=source, evidence_class=evidence_class, generated_at_utc=generated_at_utc, book_rule_evidence=book_rule_evidence)
    rules_by_market = _required_rules_by_market(); rows = []
    for raw in base["markets"]:
        row = dict(raw); market = str(row["market"])
        row["validated_sportsbook_normalized"] = _validated_sportsbook(rules_by_market[market], book_rule_evidence)
        rows.append(row)
    return {**base, "schema_version": CATALOG_REPORT_SCHEMA_VERSION, "markets": rows}


def prediction_journal_sha256(record: Mapping[str, Any]) -> str:
    if not isinstance(record, Mapping): raise MLBCatalogSettlementError("prediction journal must be an object")
    if str(record.get("schema_version") or "") != JOURNAL_SCHEMA_VERSION: raise MLBCatalogSettlementError("unsupported prediction journal schema")
    predictions = record.get("predictions")
    if not isinstance(predictions, list): raise MLBCatalogSettlementError("prediction journal predictions must be a list")
    try: declared = int(record.get("prediction_count"))
    except (TypeError, ValueError) as exc: raise MLBCatalogSettlementError("prediction_count invalid") from exc
    if declared != len(predictions): raise MLBCatalogSettlementError("prediction_count mismatch")
    return _sha256(dict(record))


def _report_game_id(report: Mapping[str, Any]) -> str:
    facts = report.get("facts")
    if not isinstance(facts, Mapping): raise MLBCatalogSettlementError("settlement facts missing")
    game_pk = str(facts.get("game_pk") or "").strip()
    if not game_pk: raise MLBCatalogSettlementError("settlement game_pk missing")
    return game_pk


def _report_index(reports: Mapping[str, Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    if not isinstance(reports, Mapping): raise MLBCatalogSettlementError("settlement_reports_by_game must be an object")
    out = {}
    for supplied, report in reports.items():
        if not isinstance(report, Mapping): raise MLBCatalogSettlementError("settlement report must be an object")
        actual = _report_game_id(report)
        if str(supplied) != actual: raise MLBCatalogSettlementError(f"settlement report key/game mismatch: {supplied}!={actual}")
        if actual in out: raise MLBCatalogSettlementError(f"duplicate settlement report for game {actual}")
        out[actual] = report
    return out


def _market_row(report: Mapping[str, Any], market: str) -> Mapping[str, Any] | None:
    rows = report.get("markets")
    if not isinstance(rows, list): raise MLBCatalogSettlementError("settlement report markets must be a list")
    matches = [row for row in rows if isinstance(row, Mapping) and str(row.get("market") or "").upper() == market]
    if len(matches) > 1: raise MLBCatalogSettlementError(f"duplicate settlement market row: {market}")
    return matches[0] if matches else None


def _prediction_sportsbook(prediction: Mapping[str, Any]) -> str | None:
    sportsbook = normalize_name(prediction.get("sportsbook"))
    if sportsbook: return sportsbook
    return normalize_name(prediction.get("book_key")) or None


def _eligibility(report: Mapping[str, Any], prediction: Mapping[str, Any], market: str) -> tuple[bool, str, str | None]:
    evidence_sha = hashlib.sha256(settlement_fact_bytes(report)).hexdigest()
    if str(report.get("schema_version") or "") != CATALOG_REPORT_SCHEMA_VERSION: return False, "SETTLEMENT_EVIDENCE_SCHEMA_UNSUPPORTED", evidence_sha
    evidence_class = str(report.get("evidence_class") or "").strip().upper()
    if not evidence_class: return False, "SETTLEMENT_EVIDENCE_CLASS_MISSING", evidence_sha
    if evidence_class == SYNTHETIC_EVIDENCE_CLASS: return False, "SYNTHETIC_SETTLEMENT_EVIDENCE_PROHIBITED", evidence_sha
    facts = report.get("facts")
    if not isinstance(facts, Mapping): raise MLBCatalogSettlementError("settlement facts missing")
    reported_facts_sha = _valid_sha256(report.get("facts_sha256"), "facts_sha256")
    if reported_facts_sha != hashlib.sha256(settlement_fact_bytes(facts)).hexdigest(): return False, "SETTLEMENT_FACTS_HASH_MISMATCH", evidence_sha
    row = _market_row(report, market)
    if row is None: return False, "MARKET_SETTLEMENT_ROW_MISSING", evidence_sha
    state = str(row.get("settlement_semantics_state") or "").strip().upper()
    if state != "SETTLEMENT_ELIGIBLE": return False, state or "SETTLEMENT_STATE_MISSING", evidence_sha
    if str(row.get("official_fact_state") or "").strip().upper() != "OFFICIAL_FACTS_PROVEN": return False, "OFFICIAL_FACTS_NOT_PROVEN", evidence_sha
    if row.get("book_rules_validated") is not True: return False, "BOOK_SETTLEMENT_UNVALIDATED", evidence_sha
    prediction_book = _prediction_sportsbook(prediction)
    if prediction_book is None: return False, "PREDICTION_SPORTSBOOK_IDENTITY_MISSING", evidence_sha
    validated_book = str(row.get("validated_sportsbook_normalized") or "").strip()
    if not validated_book: return False, "BOOK_RULE_SPORTSBOOK_IDENTITY_MISSING", evidence_sha
    if prediction_book != validated_book: return False, "BOOK_RULE_SPORTSBOOK_MISMATCH", evidence_sha
    return True, "SETTLEMENT_ELIGIBLE", evidence_sha


def _team_total_outcome(prediction: Mapping[str, Any], score: Mapping[str, Any]) -> str:
    entity_id = str(prediction.get("entity_id") or "").strip(); side = str(prediction.get("side") or "").upper(); line = _line(prediction.get("line"))
    away_id = str(score.get("away_team_id") or "").strip(); home_id = str(score.get("home_team_id") or "").strip()
    if not away_id or not home_id or away_id == home_id: raise MLBCatalogSettlementError("TEAM_SCORE_IDENTITY_MISSING")
    if entity_id == away_id: runs = int(score["away_runs"])
    elif entity_id == home_id: runs = int(score["home_runs"])
    else: raise MLBCatalogSettlementError("TEAM_TOTAL_ENTITY_ID_NOT_IN_GAME")
    if abs(runs - line) <= 1e-12: return "PUSH"
    if side == "OVER": return "WIN" if runs > line else "LOSS"
    if side == "UNDER": return "WIN" if runs < line else "LOSS"
    raise MLBCatalogSettlementError("team-total side unsupported")


def _game_outcome(prediction: Mapping[str, Any], facts: Mapping[str, Any]) -> str:
    game = facts.get("game")
    if not isinstance(game, Mapping): raise MLBCatalogSettlementError("final score missing")
    market = str(prediction.get("market") or "").upper()
    if market == "TEAM_TOTALS": return _team_total_outcome(prediction, game)
    away = int(game["away_runs"]); home = int(game["home_runs"]); side = str(prediction.get("side") or "").upper()
    if market == "MONEYLINE":
        if away == home: raise MLBCatalogSettlementError("MONEYLINE_FINAL_TIE_REQUIRES_BOOK_RULE")
        if side in {"HOME", "HOME_ML"}: return "WIN" if home > away else "LOSS"
        if side in {"AWAY", "AWAY_ML"}: return "WIN" if away > home else "LOSS"
        raise MLBCatalogSettlementError("moneyline side unsupported")
    line = _line(prediction.get("line"))
    if market == "RUN_LINE":
        if side in {"HOME", "HOME_RL"}: margin = home + line - away
        elif side in {"AWAY", "AWAY_RL"}: margin = away + line - home
        else: raise MLBCatalogSettlementError("run-line side unsupported")
        return "PUSH" if abs(margin) <= 1e-12 else ("WIN" if margin > 0 else "LOSS")
    if market == "TOTALS":
        total = away + home
        if abs(total - line) <= 1e-12: return "PUSH"
        if side == "OVER": return "WIN" if total > line else "LOSS"
        if side == "UNDER": return "WIN" if total < line else "LOSS"
        raise MLBCatalogSettlementError("totals side unsupported")
    raise MLBCatalogSettlementError("unsupported game market")


def _pitcher_value(facts: Mapping[str, Any], entity_id: str, market: str) -> float | None:
    field = _PITCHER_FIELD_BY_MARKET.get(market); rows = facts.get("pitchers")
    if field is None or not isinstance(rows, list): return None
    matches = [row for row in rows if isinstance(row, Mapping) and str(row.get("player_id") or "") == entity_id]
    if len(matches) != 1 or field not in matches[0]: return None
    try: return float(matches[0][field])
    except (TypeError, ValueError): return None


def _resolve_prediction(prediction: Mapping[str, Any], facts: Mapping[str, Any]) -> tuple[str, str]:
    market = str(prediction.get("market") or "").strip().upper(); entity_id = str(prediction.get("entity_id") or "").strip(); side = prediction.get("side"); line = prediction.get("line")
    if market in GAME_MARKETS: return _game_outcome(prediction, facts), "OFFICIAL_GAME_FACTS_AND_NORMALIZED_BOOK_RULES"
    if market == "F5_TEAM_TOTALS":
        f5 = facts.get("f5")
        if not isinstance(f5, Mapping): return "UNRESOLVED", "F5_SCORE_MISSING"
        try: return _team_total_outcome(prediction, f5), "OFFICIAL_F5_TEAM_FACTS_AND_NORMALIZED_BOOK_RULES"
        except Exception as exc: return "UNRESOLVED", f"F5_TEAM_TOTAL_SETTLEMENT_ERROR:{exc}"
    if market in ADDITIONAL_MARKETS:
        ambiguity = _policy_ambiguity(facts, market)
        if ambiguity: return "UNRESOLVED", str(ambiguity[0])
        try: return _derive_additional_outcome(facts, market, entity_id, line, side), "OFFICIAL_MARKET_FACTS_AND_NORMALIZED_BOOK_RULES"
        except Exception as exc: return "UNRESOLVED", f"ADDITIONAL_SETTLEMENT_ERROR:{exc}"
    if market in EITHER_PITCHER_MARKETS: return "UNRESOLVED", "EITHER_PITCHER_SETTLEMENT_INTERPRETER_REQUIRED"
    value = _fact_value(facts, market, entity_id)
    if value is None: value = _pitcher_value(facts, entity_id, market)
    if value is None: return "UNRESOLVED", "OFFICIAL_ENTITY_FACT_VALUE_MISSING"
    try: return _derive_count_outcome(value=value, line=line, side=side), "OFFICIAL_COUNT_FACT_AND_NORMALIZED_BOOK_RULES"
    except Exception as exc: return "UNRESOLVED", f"COUNT_SETTLEMENT_ERROR:{exc}"


def _unresolved(prediction: Mapping[str, Any], reason: str, evidence_sha: str | None = None) -> dict[str, Any]:
    return {**dict(prediction), "settlement_result": "UNRESOLVED", "settlement_reason": reason, "settlement_evidence_sha256": evidence_sha}


def build_catalog_prediction_settlement_record(prediction_journal: Mapping[str, Any], *, settlement_reports_by_game: Mapping[str, Mapping[str, Any]], settled_at_utc: Any, expected_prediction_journal_sha256: str | None = None) -> dict[str, Any] | None:
    journal_sha = prediction_journal_sha256(prediction_journal)
    if expected_prediction_journal_sha256 is not None and _valid_sha256(expected_prediction_journal_sha256, "expected_prediction_journal_sha256") != journal_sha:
        raise MLBCatalogSettlementError("prediction journal SHA mismatch")
    source_report_sha = _valid_sha256(prediction_journal.get("source_report_sha256"), "source_report_sha256")
    predictions = prediction_journal.get("predictions"); assert isinstance(predictions, list)
    if not predictions: return None
    reports = _report_index(settlement_reports_by_game); outcomes = []
    for index, raw in enumerate(predictions):
        if not isinstance(raw, Mapping): raise MLBCatalogSettlementError(f"prediction[{index}] must be an object")
        market = str(raw.get("market") or "").strip().upper(); game_id = str(raw.get("game_id") or "").strip()
        if not market or not game_id: raise MLBCatalogSettlementError(f"prediction[{index}] identity incomplete")
        report = reports.get(game_id)
        if report is None: outcomes.append(_unresolved(raw, "GAME_SETTLEMENT_EVIDENCE_MISSING")); continue
        eligible, reason, evidence_sha = _eligibility(report, raw, market)
        if not eligible: outcomes.append(_unresolved(raw, reason, evidence_sha)); continue
        facts = report.get("facts"); assert isinstance(facts, Mapping)
        try: result, result_reason = _resolve_prediction(raw, facts)
        except Exception as exc: result, result_reason = "UNRESOLVED", f"SETTLEMENT_ERROR:{exc}"
        outcomes.append({**dict(raw), "settlement_result": result, "settlement_reason": result_reason, "settlement_evidence_sha256": evidence_sha})
    resolved = sum(row["settlement_result"] in FINAL_RESULTS for row in outcomes); unresolved = len(outcomes) - resolved
    return {
        "schema_version": CATALOG_SETTLEMENT_SCHEMA_VERSION,
        "prediction_journal_schema_version": JOURNAL_SCHEMA_VERSION,
        "prediction_journal_sha256": journal_sha, "source_report_sha256": source_report_sha,
        "slate_date_ct": str(prediction_journal.get("slate_date_ct") or ""),
        "prediction_generated_at_utc": str(prediction_journal.get("generated_at_utc") or ""),
        "settled_at_utc": parse_timestamp(settled_at_utc).astimezone(timezone.utc).isoformat(),
        "prediction_count": len(outcomes), "resolved_count": resolved, "unresolved_count": unresolved,
        "win_count": sum(row["settlement_result"] == "WIN" for row in outcomes),
        "loss_count": sum(row["settlement_result"] == "LOSS" for row in outcomes),
        "push_count": sum(row["settlement_result"] == "PUSH" for row in outcomes),
        "settlement_complete": unresolved == 0, "outcomes": outcomes,
    }
