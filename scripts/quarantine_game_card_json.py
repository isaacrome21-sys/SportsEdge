#!/usr/bin/env python3
"""Optional research-only output adapter for frozen game-card JSON.

The frozen artifacts/free_models.py remains byte-identical to its governed pin.
This script is NOT wired into that engine or a production card publisher.
No source quote, Model_P, CLV, forward-clock, or betting authority is conferred.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys

# Allow invocation from any working directory.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sportsedge.game_candidate_quarantine import GAME_SURFACES, EV_KEYS, P_KEYS, game_claim_hold
from sportsedge.quote_freshness import MAX_QUOTE_AGE_SECONDS


# Source-binding is intentionally stricter than a display's convenience fields.
# A detached ranked row must not forge, omit, or change any available
# fixture, settlement, quote, provenance, or eligibility identity. This is
# equality against original evaluated evidence, NOT provider authentication.
_IDENTITY_FIELDS = (
    "game", "selection", "market", "line", "sport",
    "kickoff_utc", "team_totals_team", "event_id", "dk_event_id",
    "period", "phase", "alternate", "settlement_type",
    "odds_american", "book", "sportsbook",
    "quote_captured_at", "captured_at", "source_quote_at",
    "quote_freshness", "pricing_lane", "pricing_provenance",
    "status", "reason", "availability_status", "model_validation",
    "research_only", "model_p_authority", "official_authority",
    "staking_authority", "validated_profitability",
)
_REASON_PRIORITY = (
    "GAME_PROBABILITY_CLAIM_INVALID",
    "GAME_EV_CLAIM_INVALID",
    "EXTREME_CLAIMED_EV_QUARANTINE",
)
_RESEARCH_AUTHORITY = {
    "research_only": True, "official": False, "model_p": False,
    "truth_gate": False, "staking": False, "validated_profitability": False,
}

# These declarations are projected from the frozen engine's research contract.
# The quote-age bound is imported, never caller-configured or relaxed.
_RESEARCH_PLAY_GATE = {
    "rule": "INDEPENDENT_PROBABILITY_REQUIRED_FOR_PLAY",
    "anchored_max_surface": "WATCH",
    "anchored_ev_in_edges_lists": "SUPPRESSED",
    "undetermined_provenance": "FAIL_CLOSED",
    "availability_unverified_max_surface": "RESEARCH_ONLY",
}
_RESEARCH_QUOTE_POLICY = {
    "max_age_seconds": MAX_QUOTE_AGE_SECONDS,
    "stale_quotes_are_watch_only": True,
}
_TOP_LEVEL_AUTHORITY_ALIASES = frozenset({
    "official", "staking", "model_p", "truth_gate", "forward_clock",
    "verified", "play", "no_play", "model_verified",
    "official_authority", "staking_authority", "model_p_authority",
    "validated_profitability", "research_only",
})


# This diagnostic is emitted by the governed engine for FAILED NBA game
# families. Preserve its observed counts, but never trust caller-supplied
# validation, candidate, score, or staking authority inside the object.
_NBA_INTEGRITY_POLICY = {
    "family_validation": "FAILED_VALIDATION",
    "game_families": ["ML", "SPREAD", "TOTAL"],
    "positive_ev_candidate_authority": False,
    "numeric_quality_scores_allowed": False,
    "score_policy": "WITHHELD_FAILED_NBA_GAME_VALIDATION",
    "research_only": True,
    "interpretation": (
        "TOTAL rows share a failed model family: same-direction "
        "quotes are one systematic model-level diagnostic, never "
        "independent market edges. Full rows remain auditable."
    ),
}
_NBA_INTEGRITY_COUNTS = (
    "game_rows", "apparent_positive_gap_total_rows", "under_rows",
    "over_rows", "distinct_games",
)


def _validate_nba_integrity(card):
    if "nba_game_card_integrity" not in card:
        return
    obj = card["nba_game_card_integrity"]
    if not isinstance(obj, dict):
        raise ValueError("GAME_NBA_INTEGRITY_NOT_OBJECT")
    expected_keys = set(_NBA_INTEGRITY_POLICY) | set(_NBA_INTEGRITY_COUNTS) | {
        "same_direction_concentration"
    }
    if set(obj) != expected_keys:
        raise ValueError("GAME_NBA_INTEGRITY_FIELDS_MISMATCH")
    for key, expected in _NBA_INTEGRITY_POLICY.items():
        if type(obj[key]) is not type(expected) or obj[key] != expected:
            raise ValueError("GAME_NBA_INTEGRITY_POLICY_CONFLICT:" + key)
    for key in _NBA_INTEGRITY_COUNTS:
        value = obj[key]
        if type(value) is not int or value < 0:
            raise ValueError("GAME_NBA_INTEGRITY_COUNT_INVALID:" + key)
    total = obj["apparent_positive_gap_total_rows"]
    under = obj["under_rows"]
    over = obj["over_rows"]
    if (under + over != total or total > obj["game_rows"]
            or obj["distinct_games"] > total):
        raise ValueError("GAME_NBA_INTEGRITY_COUNTS_INCONSISTENT")
    concentrated = total >= 3 and (under == 0 or over == 0)
    if (type(obj["same_direction_concentration"]) is not bool
            or obj["same_direction_concentration"] is not concentrated):
        raise ValueError("GAME_NBA_INTEGRITY_CONCENTRATION_CONFLICT")


def _check_research_policy(card, key, expected):
    if key not in card:
        return
    policy = card[key]
    if not isinstance(policy, dict):
        raise ValueError("GAME_CARD_POLICY_NOT_OBJECT:" + key)
    for field, value in policy.items():
        if field not in expected or type(value) is not type(expected[field]) or value != expected[field]:
            raise ValueError("GAME_CARD_POLICY_CONFLICT:" + key + ":" + str(field))


def _validate_card_contract(card):
    """Reject contradictory claims instead of silently laundering them."""
    if card.get("schema") != "SPORTSEDGE_FREE_RESEARCH_CARD_V1":
        raise ValueError("GAME_CARD_SCHEMA_UNSUPPORTED")
    for key in _TOP_LEVEL_AUTHORITY_ALIASES:
        if key in card:
            raise ValueError("GAME_CARD_TOP_LEVEL_AUTHORITY_ALIAS:" + key)
    _check_research_policy(card, "play_gate", _RESEARCH_PLAY_GATE)
    _check_research_policy(card, "quote_freshness_policy", _RESEARCH_QUOTE_POLICY)
    _validate_nba_integrity(card)
    if "authority" in card:
        authority = card["authority"]
        if not isinstance(authority, dict):
            raise ValueError("GAME_CARD_AUTHORITY_NOT_OBJECT")
        for key, value in authority.items():
            # Identity comparison deliberately refuses 0/1 and text booleans.
            if key not in _RESEARCH_AUTHORITY or value is not _RESEARCH_AUTHORITY[key]:
                raise ValueError("GAME_CARD_AUTHORITY_CONFLICT:" + str(key))
    legacy_edges = card.get("lane_b_edges", [])
    if not isinstance(legacy_edges, list) or legacy_edges:
        raise ValueError("GAME_LEGACY_EDGES_MUST_BE_EMPTY")
    summary = card.get("summary")
    if isinstance(summary, dict) and "lane_b_edges" in summary:
        count = summary["lane_b_edges"]
        if type(count) is not int or count != 0:
            raise ValueError("GAME_LEGACY_EDGE_COUNT_MUST_BE_ZERO")



def _numeric_claims(row):
    """Map each displayed numeric-claim path to its untrusted raw value.

    Presence is path-specific: a market-anchored lane cannot impersonate an
    independent projection. Omitted original fields remain permissible for
    compact watchlists; new non-extreme numeric claims are not.
    """
    claims = {}
    def collect(source, prefix):
        if not isinstance(source, dict):
            return
        for key in EV_KEYS + P_KEYS:
            if key in source and source[key] is not None:
                claims[prefix + key] = source[key]
    collect(row, "")
    collect(row.get("independent_projection"), "independent_projection.")
    lanes = row.get("pricing_lanes")
    if isinstance(lanes, dict):
        for lane in ("lane_a_independent", "lane_b_anchored"):
            collect(lanes.get(lane), "pricing_lanes." + lane + ".")
    return claims


def _bind_ordinary_numeric_claims(original, display):
    """Fail closed on any altered, added or type-coerced ordinary EV/P claim.

    An invalid or >=40% claim is handled separately by the global quarantine
    phase, including across earlier surfaces; this binding never turns that
    quarantine into a ranked candidate.
    """
    original_claims = _numeric_claims(original)
    for path, value in _numeric_claims(display).items():
        if path not in original_claims:
            raise ValueError("GAME_SURFACE_NUMERIC_CLAIM_UNATTESTED:" + path)
        attested = original_claims[path]
        if type(value) is not type(attested) or value != attested:
            raise ValueError("GAME_SURFACE_NUMERIC_CLAIM_CONFLICT:" + path)


def _index(row, label):
    idx = row.get("input_index")
    if type(idx) is not int or idx < 0:
        raise ValueError(label + ":GAME_INPUT_INDEX_INVALID")
    return idx


def sanitize_card(card):
    """Return a separately derived research card, preserving evaluated rows."""
    if not isinstance(card, dict):
        raise ValueError("GAME_CARD_NOT_OBJECT")
    if "game_quarantined" in card:
        raise ValueError("GAME_CARD_ALREADY_PARTITIONED")
    _validate_card_contract(card)
    originals = card.get("evaluated_rows")
    if not isinstance(originals, list) or any(not isinstance(r, dict) for r in originals):
        raise ValueError("GAME_EVALUATED_ROWS_REQUIRED")
    original_by_index = {}
    for row in originals:
        idx = _index(row, "GAME_EVALUATED_ROW")
        if idx in original_by_index:
            raise ValueError("GAME_EVALUATED_INPUT_INDEX_DUPLICATE")
        original_by_index[idx] = row

    result = deepcopy(card)
    # Complete missing research declarations without accepting any escalation.
    result["authority"] = dict(_RESEARCH_AUTHORITY)
    result["play_gate"] = dict(_RESEARCH_PLAY_GATE)
    result["quote_freshness_policy"] = dict(_RESEARCH_QUOTE_POLICY)
    result["lane_b_edges"] = []
    # Phase one: validate every displayed row and collect holds globally by
    # original input_index. A bad claim in ONE surface must suppress the same
    # candidate from ALL other ranked surfaces, regardless of list order.
    rows_by_surface = {}
    holds_by_index = {}
    original_holds = {idx: game_claim_hold(row) for idx, row in original_by_index.items()}
    pre_counts = {}
    for name in GAME_SURFACES:
        rows = result.get(name, [])
        if not isinstance(rows, list):
            raise ValueError("GAME_SURFACE_NOT_LIST:" + name)
        pre_counts[name] = len(rows)
        rows_by_surface[name] = rows
        seen = set()
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("GAME_SURFACE_ROW_NOT_OBJECT:" + name)
            idx = _index(row, "GAME_SURFACE_ROW")
            if idx in seen:
                raise ValueError("GAME_SURFACE_DUPLICATE_INPUT_INDEX:" + name)
            seen.add(idx)
            original = original_by_index.get(idx)
            if original is None:
                raise ValueError("GAME_SURFACE_REFERENCE_NOT_IN_EVIDENCE")
            if original.get("status") == "BLOCKED_INVALID":
                raise ValueError("GAME_SURFACE_BLOCKED_EVIDENCE")
            # Identity is mandatory for every ranked reference. Unranked
            # error evidence from the frozen engine may lack these fields
            # and must remain intact for diagnostics, never become a pick.
            for key in ("game", "selection"):
                value = original.get(key)
                if not isinstance(value, str) or not value.strip():
                    raise ValueError("GAME_EVALUATED_IDENTITY_INVALID:" + key)
            for key in _IDENTITY_FIELDS:
                if key in original and key not in row:
                    raise ValueError("GAME_SURFACE_IDENTITY_MISSING:" + key)
                if key in row and key not in original:
                    raise ValueError("GAME_SURFACE_IDENTITY_UNATTESTED:" + key)
                if key in original and (type(original[key]) is not type(row[key])
                                        or original[key] != row[key]):
                    raise ValueError("GAME_SURFACE_IDENTITY_CONFLICT:" + key)
            display_reason, display_max_ev = game_claim_hold(row)
            original_reason, original_max_ev = original_holds[idx]
            # Quarantine extreme/invalid claims globally first. Ordinary
            # displayed EV/P claims must exactly bind to evaluated evidence;
            # a plausible sub-40% forged edge is not a valid research row.
            if display_reason is None and original_reason is None:
                _bind_ordinary_numeric_claims(original, row)
            reasons = [r for r in (display_reason, original_reason) if r is not None]
            if not reasons:
                continue
            reason = next(r for r in _REASON_PRIORITY if r in reasons)
            finite_maxes = [v for v in (display_max_ev, original_max_ev) if v is not None]
            max_ev = max(finite_maxes) if finite_maxes else None
            hold = holds_by_index.get(idx)
            if hold is None:
                holds_by_index[idx] = {"reason": reason, "max_ev": max_ev}
            else:
                hold["reason"] = next(r for r in _REASON_PRIORITY
                                      if r in (hold["reason"], reason))
                vals = [v for v in (hold["max_ev"], max_ev) if v is not None]
                hold["max_ev"] = max(vals) if vals else None

    # Phase two: remove EVERY occurrence of a held index, including earlier
    # clean-looking copies. Keep the original evaluated_rows untouched.
    filtered = {}
    quarantined_by_index = {}
    for name, rows in rows_by_surface.items():
        kept = []
        for row in rows:
            idx = row["input_index"]
            hold = holds_by_index.get(idx)
            if hold is None:
                kept.append(row)
                continue
            existing = quarantined_by_index.get(idx)
            if existing is None:
                existing = {
                    "input_index": idx,
                    "source_surfaces": [],
                    "source_status": original_by_index[idx].get("status"),
                    "reason": hold["reason"],
                    "max_finite_claimed_ev": hold["max_ev"],
                    "evidence_bound": True,
                    "research_only": True,
                    "eligible_for_headline": False,
                    "eligible_for_forward_clock": False,
                }
                quarantined_by_index[idx] = existing
            existing["source_surfaces"].append(name)
        filtered[name] = kept

    for key in GAME_SURFACES:
        result[key] = filtered[key]
    result["game_quarantined"] = list(quarantined_by_index.values())
    result["game_quarantine_adapter"] = {
        "status": "RESEARCH_ONLY_NOT_PRODUCTION_WIRED",
        "frozen_engine_modified_by_adapter": False,
        "original_evaluated_rows_preserved": True,
        "all_ranked_rows_bound_to_original_evidence": True,
        "forward_clock_authority": False,
        "model_verification_authority": False,
    }
    summary = result.get("summary")
    if isinstance(summary, dict):
        result["pre_quarantine_ranked_counts"] = {
            key: pre_counts[key] for key in GAME_SURFACES
        }
        for key in GAME_SURFACES:
            if key in summary:
                summary[key] = len(filtered[key])
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="-", help="Card JSON path, or - for stdin")
    parser.add_argument("--output", default="-", help="Derived card JSON path, or - for stdout")
    args = parser.parse_args(argv)
    raw = sys.stdin.read() if args.input == "-" else Path(args.input).read_text(encoding="utf-8")
    result = sanitize_card(json.loads(raw))
    output = json.dumps(result, allow_nan=False, sort_keys=True, separators=(",", ":")) + "\n"
    if args.output == "-":
        sys.stdout.write(output)
    else:
        Path(args.output).write_text(output, encoding="utf-8")


if __name__ == "__main__":
    main()

