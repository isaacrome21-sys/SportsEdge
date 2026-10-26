#!/usr/bin/env python3
"""Read-only inventory of model *accuracy evidence*, not a model backtest.

Builds from the canonical MLB/NFL market list plus all forward-evaluator
family configs. A test config, pricing path, good score or historical screen
is NEVER called a validated market. No priced rows, closes, outcomes,
eligibility registry, thresholds, or frozen attempts are changed.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from sportsedge.canonical_coverage import MARKET_RESOLUTIONS, PRICED_PATH

ROOT = Path(__file__).resolve().parents[1]
CONFIGS = Path("sportsedge/forward_validation/configs")
SCHEMA = "SPORTSEDGE_CROSS_SPORT_ACCURACY_READINESS_V1"


class AuditRefusal(ValueError):
    pass


def _read_json(path: Path) -> dict:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise AuditRefusal(f"JSON_UNAVAILABLE_OR_INVALID:{path.name}") from exc
    if not isinstance(doc, dict):
        raise AuditRefusal(f"OBJECT_REQUIRED:{path.name}")
    return doc


def _prereg(path: Path, *, root: Path, expected_sha: str | None) -> None:
    if not path or path.is_absolute() or ".." in path.parts:
        raise AuditRefusal("PREREG_PATH_NOT_RELATIVE")
    target = root / path
    if not target.is_file():
        raise AuditRefusal(f"PREREG_MISSING:{path}")
    if expected_sha is not None:
        if not isinstance(expected_sha, str) or len(expected_sha) != 64:
            raise AuditRefusal(f"PREREG_SHA_INVALID:{path}")
        got = hashlib.sha256(target.read_bytes()).hexdigest()
        if got != expected_sha:
            raise AuditRefusal(f"PREREG_SHA_MISMATCH:{path}")


def _status(row: dict, *, name: str, root: Path) -> str:
    text = row.get("status")
    if not isinstance(text, str):
        raise AuditRefusal(f"CONFIG_STATUS_MISSING:{name}")
    if text.startswith("DRAFT") and "NOT FROZEN" in text:
        prereg = row.get("prereg_draft")
        if not isinstance(prereg, str) or not prereg:
            raise AuditRefusal(f"DRAFT_PREREG_MISSING:{name}")
        _prereg(Path(prereg), root=root, expected_sha=None)
        if row.get("prereg") or row.get("prereg_sha256"):
            raise AuditRefusal(f"DRAFT_CLAIMS_FROZEN_PIN:{name}")
        return "DRAFT_NOT_FROZEN"
    if text.startswith("FINAL-CANDIDATE") and "NOT FROZEN" in text:
        # A pinned candidate: the document hash is registered and verified
        # exactly as for a frozen prereg, but the status itself declares
        # NOT FROZEN — recognition in this inventory confers no freeze,
        # no verdict and no play authority.
        prereg, sha = row.get("prereg"), row.get("prereg_sha256")
        if not isinstance(prereg, str) or not prereg:
            raise AuditRefusal(f"CANDIDATE_PREREG_MISSING:{name}")
        if not isinstance(sha, str) or len(sha) != 64:
            raise AuditRefusal(f"CANDIDATE_PREREG_SHA_MISSING:{name}")
        _prereg(Path(prereg), root=root, expected_sha=sha)
        return "FINAL_CANDIDATE_NOT_FROZEN"
    if text.startswith("FROZEN"):
        prereg, sha = row.get("prereg"), row.get("prereg_sha256")
        if not isinstance(prereg, str) or not prereg:
            raise AuditRefusal(f"FROZEN_PREREG_MISSING:{name}")
        if not isinstance(sha, str) or len(sha) != 64:
            raise AuditRefusal(f"FROZEN_PREREG_SHA_MISSING:{name}")
        _prereg(Path(prereg), root=root, expected_sha=sha)
        return "FROZEN_NO_VERDICT_ATTACHED"
    raise AuditRefusal(f"UNKNOWN_CONFIG_STATUS:{name}")


def accuracy_readiness(*, root: Path = ROOT) -> dict:
    """Audit structural readiness; deliberately accept no fabricated verdicts."""
    config_dir = root / CONFIGS
    files = sorted(config_dir.glob("*.json"))
    if not files:
        raise AuditRefusal("NO_FORWARD_MARKET_CONFIGS")
    config_rows = []
    family_by_market = {}
    original_config_by_market = {}
    for path in files:
        row = _read_json(path)
        state = _status(row, name=path.name, root=root)
        sport = row.get("sport")
        family = row.get("family")
        markets = row.get("markets")
        if (not isinstance(sport, str) or not sport.strip()
                or not isinstance(family, str) or not family.strip()
                or not isinstance(markets, list) or not markets
                or not all(isinstance(m, str) and m.strip() for m in markets)):
            raise AuditRefusal(f"CONFIG_IDENTITY_INVALID:{path.name}")
        for market in markets:
            key = (sport.upper(), market.upper())
            prior = family_by_market.get(key)
            if prior is not None:
                # Coexistence is only the explicitly named, pinned V2
                # amendment of an already-frozen V1 config. Registration
                # cannot silently substitute a different model, floor, or
                # pricing contract for the frozen family.
                prior_name, prior_state = prior
                allowed_differences = {
                    "status", "prereg", "prereg_sha256", "capture_note",
                }
                original = original_config_by_market[key]
                same_contract = all(
                    row.get(field) == original.get(field)
                    for field in set(row) | set(original)
                    if field not in allowed_differences
                )
                is_strict_additive_v2 = (
                    prior_state == "FROZEN_NO_VERDICT_ATTACHED"
                    and state == "FINAL_CANDIDATE_NOT_FROZEN"
                    and path.name == f"{Path(prior_name).stem}_v2.json"
                    and row.get("prereg") != original.get("prereg")
                    and same_contract
                )
                if not is_strict_additive_v2:
                    raise AuditRefusal(
                        f"DUPLICATE_FORWARD_MARKET_CONFIG:{sport}:{market}")
                # Keep V1 canonical. V2 is inventoried but cannot replace
                # the frozen config or confer counting/play permission.
            else:
                family_by_market[key] = (path.name, state)
                original_config_by_market[key] = row
        config_rows.append({
            "file": str(path.relative_to(root)), "sport": sport.upper(),
            "family": family, "markets": markets, "state": state,
            "engine_id": row.get("engine_id"),
            "model_version": row.get("model_version"),
            "capture_scope": row.get("capture_scope"),
            "independent_model_accuracy_verdict": "NOT_EVALUATED_BY_THIS_AUDIT",
            "play_authority_from_config": False,
        })
    # The 89-market canonical map is independent of these 39 test configs.
    # A route to a price is not a route to validated profitability.
    canonical_rows = []
    for (sport, market), resolution in sorted(MARKET_RESOLUTIONS.items()):
        state = resolution["state"]
        key = (sport.upper(), market.upper())
        entry = family_by_market.get(key)
        config = entry[0] if entry is not None else None
        if key == ("MLB", "NRFI") or key == ("MLB", "YRFI"):
            # Two sides of one frozen-boundary first-inning test family.
            entry = family_by_market.get(("MLB", "FIRST_INNING_RUN"))
            config = entry[0] if entry is not None else None
        canonical_rows.append({
            "sport": sport, "market": market, "pricing_path": state,
            "blocker": resolution.get("blocker"),
            "registry_validation_status": resolution.get("validation_status"),
            "forward_test_config": config,
            "readiness": (
                "NO_CANONICAL_PRICING_PATH" if state != PRICED_PATH else
                "NO_FORWARD_TEST_CONFIG" if config is None else
                "RESEARCH_PRICED_NOT_VALIDATED"),
            "validated_accuracy_in_this_audit": False,
            "play_authority_from_readiness": False,
        })

    counts = Counter((x["sport"], x["state"]) for x in config_rows)
    statuses = {sport: {state: n for (s, state), n in sorted(counts.items()) if s == sport}
                for sport in sorted({x["sport"] for x in config_rows})}
    by_sport = Counter(x["sport"] for x in canonical_rows)
    return {
        "schema": SCHEMA,
        "status": "STRUCTURAL_AND_PROVENANCE_AUDIT_ONLY",
        "evaluated_priced_outcomes": 0,
        "paired_quoted_outcomes": 0,
        "validated_families_conferred": 0,
        "play_authority_conferred": False,
        "no_backfill_or_registry_changes": True,
        "scope_limits": [
            "CANONICAL_MLB_NFL_89_MARKETS_PLUS_FORWARD_CONFIGS",
            "NO_NEW_PIT_ENTRY_CLOSE_OUTCOME_DATA_SUPPLIED",
            "NOT_ALL_DECLARED_NBA_CFB_CBB_NHL_UFC_PGA_MARKETS_HAVE_MACHINE_TEST_CONFIGS",
            "CONFIG_FROZEN_IS_NOT_A_BEATS_MARKET_VERDICT",
            "QUALIFICATION_SCORE_0_TO_100_IS_NOT_PREDICTION_ACCURACY",
        ],
        "canonical_market_count": len(canonical_rows),
        "canonical_by_sport": dict(sorted(by_sport.items())),
        "canonical_priced_path_count": sum(x["pricing_path"] == PRICED_PATH for x in canonical_rows),
        "canonical_missing_forward_config_count": sum(x["forward_test_config"] is None for x in canonical_rows),
        "forward_family_config_count": len(config_rows),
        "forward_config_states": statuses,
        "forward_family_configs": config_rows,
        "canonical_markets": canonical_rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = accuracy_readiness()
    body = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(body, encoding="utf-8")
    print(json.dumps({k: report[k] for k in (
        "status", "canonical_market_count", "canonical_priced_path_count",
        "canonical_missing_forward_config_count", "forward_family_config_count",
        "forward_config_states", "validated_families_conferred")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
