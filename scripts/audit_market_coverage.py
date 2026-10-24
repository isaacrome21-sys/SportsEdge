#!/usr/bin/env python3
"""Fail-closed audit of declared SportsEdge market surfaces."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _json(path: str):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def football_engine_capability(surface: dict) -> tuple[dict[str, dict], list[str]]:
    """Disclose per-sport declared code paths separately from market validation.

    IMPLEMENTED is a source declaration, *never* certified Model_P, market
    admission, executable pricing, or a sportsbook quote. Invalid/omitted
    states are exposed instead of quietly counted as available.
    """
    sports = surface.get("sports")
    if not isinstance(sports, list) or not sports or len(sports) != len(set(sports)) or any(
            not isinstance(s, str) or not s.strip() for s in sports):
        raise ValueError("FOOTBALL_SPORTS_INVALID")
    rows = surface.get("markets")
    if not isinstance(rows, list):
        raise ValueError("FOOTBALL_MARKETS_INVALID")
    counts = {sport: {"implemented_markets": [], "no_engine_markets": [],
                      "declared_market_count": len(rows),
                      "engine_implemented_is_market_validated": False}
              for sport in sports}
    invalid = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            invalid.append(f"row:{index}")
            continue
        identity = f"{row.get('family')}:{row.get('market')}"
        states = row.get("engine_state_by_sport")
        for sport in sports:
            state = states.get(sport) if isinstance(states, dict) else None
            if state == "IMPLEMENTED":
                counts[sport]["implemented_markets"].append(identity)
            elif state == "NO_ENGINE":
                counts[sport]["no_engine_markets"].append(identity)
            else:
                invalid.append(f"{sport}:{identity}:{state}")
    for summary in counts.values():
        summary["implemented_count"] = len(summary["implemented_markets"])
        summary["no_engine_count"] = len(summary["no_engine_markets"])
        summary["all_engines_present"] = (
            summary["implemented_count"] == summary["declared_market_count"]
        )
    return counts, sorted(invalid)


def main() -> int:
    failures: list[str] = []
    report: dict[str, object] = {}

    mlb = _json("config/mlb_market_catalog.json")
    mlb_markets = []
    for key, value in mlb.items():
        if key == "schema_version":
            continue
        if isinstance(value, list) and all(isinstance(x, str) for x in value):
            mlb_markets.extend(value)
    if len(mlb_markets) != len(set(mlb_markets)):
        failures.append("MLB_MARKET_CATALOG_DUPLICATE")
    deployments = _json("config/deployments.json").get("markets", {})
    missing_deployments = sorted(set(mlb_markets) - set(deployments))
    undeclared_deployments = sorted(set(deployments) - set(mlb_markets))
    if missing_deployments:
        failures.append("MLB_MARKETS_MISSING_DEPLOYMENT_ROWS")
    if undeclared_deployments:
        failures.append("MLB_DEPLOYMENT_ROWS_NOT_IN_CATALOG")
    report["MLB"] = {
        "declared_market_count": len(set(mlb_markets)),
        "deployment_market_count": len(deployments),
        "missing_deployments": missing_deployments,
        "undeclared_deployments": undeclared_deployments,
        "eligible_market_count": sum(bool(row.get("eligible")) for row in deployments.values()),
        "ineligible_market_count": sum(not bool(row.get("eligible")) for row in deployments.values()),
        "declared_is_not_admitted": True,
    }

    football = _json("config/football_market_surface.json")
    football_rows = football.get("markets", [])
    keys = [(str(row.get("family")), str(row.get("market"))) for row in football_rows]
    if len(keys) != len(set(keys)):
        failures.append("FOOTBALL_MARKET_SURFACE_DUPLICATE")
    invalid_engines = []
    for row in football_rows:
        engines = row.get("engines")
        if not isinstance(engines, list) or not engines or any(x not in {"A", "B", "C"} for x in engines):
            invalid_engines.append(row.get("market"))
    if invalid_engines:
        failures.append("FOOTBALL_MARKET_ENGINE_CONTRACT_INVALID")
    try:
        capability_by_sport, invalid_states = football_engine_capability(football)
    except ValueError:
        capability_by_sport, invalid_states = {}, ["FOOTBALL_SURFACE_SHAPE_INVALID"]
    if invalid_states:
        failures.append("FOOTBALL_MARKET_ENGINE_STATE_INVALID")
    report["FOOTBALL"] = {
        "sports": football.get("sports", []),
        "declared_market_count": len(keys),
        "families": sorted({family for family, _ in keys}),
        "invalid_engine_rows": invalid_engines,
        "invalid_engine_state_rows": invalid_states,
        "by_sport_engine_capability": capability_by_sport,
        "declared_engine_implementation_is_not_validation": True,
    }

    for sport, path in (("PGA", "config/pga_market_surface.json"), ("UFC", "config/ufc_market_surface.json")):
        payload = _json(path)
        supported = [str(row.get("market")) for row in payload.get("supported_markets", [])]
        unsupported = [str(x) for x in payload.get("unsupported_without_new_engine", [])]
        if len(supported) != len(set(supported)):
            failures.append(f"{sport}_SUPPORTED_MARKET_DUPLICATE")
        overlap = sorted(set(supported).intersection(unsupported))
        if overlap:
            failures.append(f"{sport}_SUPPORTED_UNSUPPORTED_OVERLAP")
        report[sport] = {
            "supported_market_count": len(supported),
            "supported_markets": supported,
            "explicitly_unsupported_count": len(unsupported),
            "overlap": overlap,
        }

    # PGA validation must be market-shape aware.  Outright/FRL are exhaustive
    # N-way markets; top-K and make-cut are binary per player but non-exhaustive
    # across players; H2H is paired two-way with push semantics.  A missing or
    # mismatched methodology row is a CI failure so evidence cannot silently use
    # a two-sided benchmark for an incompatible market surface.
    pga_supported = set(report["PGA"]["supported_markets"])
    pga_benchmark = _json("config/pga_benchmark_methodology.json")
    benchmark_rows = pga_benchmark.get("markets", {})
    benchmark_markets = set(benchmark_rows)
    if pga_benchmark.get("schema_version") != "PGA_BENCHMARK_V1":
        failures.append("PGA_BENCHMARK_SCHEMA_INVALID")
    if benchmark_markets != pga_supported:
        failures.append("PGA_BENCHMARK_SURFACE_MISMATCH")
    allowed = {
        "OUTRIGHT": ("EXHAUSTIVE_N_WAY_MUTUALLY_EXCLUSIVE", "MULTIPLICATIVE_NWAY_V1"),
        "FIRST_ROUND_LEADER": ("EXHAUSTIVE_N_WAY_MUTUALLY_EXCLUSIVE", "MULTIPLICATIVE_NWAY_V1"),
        "TOP_K": ("PER_SELECTION_BINARY_NONEXHAUSTIVE_ACROSS_PLAYERS", "MULTIPLICATIVE_2WAY_V1"),
        "MAKE_CUT": ("PER_SELECTION_BINARY_NONEXHAUSTIVE_ACROSS_PLAYERS", "MULTIPLICATIVE_2WAY_V1"),
        "H2H": ("TWO_WAY_MATCHUP_WITH_PUSH_POSSIBLE", "MULTIPLICATIVE_2WAY_V1"),
    }
    invalid_benchmark_rows = []
    for market, expected in allowed.items():
        row = benchmark_rows.get(market, {})
        actual = (row.get("shape"), row.get("devig_method"))
        if actual != expected:
            invalid_benchmark_rows.append(market)
    if invalid_benchmark_rows:
        failures.append("PGA_BENCHMARK_MARKET_SHAPE_INVALID")
    if benchmark_rows.get("OUTRIGHT", {}).get("require_complete_field") is not True:
        failures.append("PGA_OUTRIGHT_COMPLETE_FIELD_NOT_REQUIRED")
    if benchmark_rows.get("FIRST_ROUND_LEADER", {}).get("require_complete_field") is not True:
        failures.append("PGA_FRL_COMPLETE_FIELD_NOT_REQUIRED")
    for market in ("TOP_K", "MAKE_CUT"):
        row = benchmark_rows.get(market, {})
        if row.get("require_paired_yes_no") is not True or row.get("cross_player_normalization") != "FORBIDDEN":
            failures.append(f"PGA_{market}_BINARY_BENCHMARK_INVALID")
    report["PGA"]["benchmark_schema_version"] = pga_benchmark.get("schema_version")
    report["PGA"]["benchmark_markets"] = sorted(benchmark_markets)
    report["PGA"]["invalid_benchmark_rows"] = invalid_benchmark_rows

    report["LIVE"] = {
        "registry_present": (ROOT / "sportsedge/live_markets.py").is_file(),
        "status": "SHADOW_UNVALIDATED",
    }
    if not report["LIVE"]["registry_present"]:
        failures.append("LIVE_MARKET_REGISTRY_MISSING")

    # PASS is limited to structural contracts. It must not be read as a
    # 100%-ready or market-beating prediction system.
    gaps = {"MLB_ineligible": report["MLB"]["ineligible_market_count"],
            "football_no_engine_by_sport": {
                sport: states["no_engine_count"]
                for sport, states in capability_by_sport.items()}}
    readiness = ("GAPS_PRESENT" if gaps["MLB_ineligible"] or
                 any(gaps["football_no_engine_by_sport"].values()) else
                 "NOT_VERIFIED_BY_STRUCTURAL_AUDIT")
    payload = {"status": "PASS" if not failures else "FAIL",
               "status_scope": "STRUCTURAL_REGISTRY_CONSISTENCY_ONLY",
               "readiness_status": readiness, "readiness_gaps": gaps,
               "does_not_grant_model_p_or_play": True,
               "failures": failures, "surfaces": report}
    out = ROOT / "artifacts/run_it/market_coverage.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
