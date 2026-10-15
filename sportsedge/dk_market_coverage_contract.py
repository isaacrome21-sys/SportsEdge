"""Research-only DK market coverage contract. No pricing or activation authority."""
from __future__ import annotations

import json
from pathlib import Path

ACTIVE_SPORTS = ("MLB", "NFL", "CFB", "NBA", "CBB")
PARKED_SPORTS = ("NHL", "UFC", "PGA")
REQUIRED_EVIDENCE = (
    "canonical_identity", "intake_adapter", "paired_fresh_quotes",
    "pre_event_provenance", "probability_engine", "chronological_baseline",
    "regression_tests", "exact_head_ci", "prospective_grading",
)


def inspect_census(path: str | Path) -> dict:
    """Inventory menu keys; fail on duplicates and never infer model readiness."""
    census = json.loads(Path(path).read_text(encoding="utf-8"))
    if census.get("schema") != "SPORTSEDGE_DK_INSPECTED_MENU_CENSUS_V1":
        raise ValueError("UNKNOWN_CENSUS_SCHEMA")
    rows = []
    for sport, spec in census.get("sports", {}).items():
        if sport not in ACTIVE_SPORTS:
            raise ValueError("UNSUPPORTED_ACTIVE_SPORT")
        seen = set()
        for item in spec.get("markets", []):
            key = item.get("market_key")
            if not isinstance(key, str) or not key.strip():
                raise ValueError("INVALID_MARKET_KEY")
            if key in seen:
                raise ValueError(f"DUPLICATE_MARKET_KEY:{sport}:{key}")
            seen.add(key)
            rows.append({
                "sport": sport, "market_key": key, "group": item.get("group"),
                "status": "UNVERIFIED", "missing_evidence": list(REQUIRED_EVIDENCE),
                "authority": "MENU_ONLY_NO_PRICING_OR_PLAY",
            })
    return {
        "authority": "RESEARCH_ONLY_NO_CAPTURE_NO_PLAY",
        "rows": rows,
        "missing_sport_census": [s for s in ACTIVE_SPORTS if s not in census.get("sports", {})],
    }


def adjudicate_market(evidence: dict) -> dict:
    """Only complete independently attested evidence can clear the contract."""
    missing = [key for key in REQUIRED_EVIDENCE if evidence.get(key) is not True]
    return {
        "status": "UNVERIFIED" if missing else "EVIDENCE_COMPLETE_REVIEW_REQUIRED",
        "missing_evidence": missing,
        "play_authorized": False,
    }
