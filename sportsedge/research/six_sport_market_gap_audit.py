"""Fail-closed six-sport declared-market inventory, not an odds or model audit.

Catalog presence is NOT a priced model, quote, bet, or forward validation.
A missing catalog is shown as an explicit incomplete-coverage blocker.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter
import json
from pathlib import Path

SPORTS = ("MLB", "NFL", "CFB", "NBA", "NHL", "CBB")
NBA_GAME = ("MONEYLINE", "SPREAD", "TOTAL", "TEAM_TOTAL")
NBA_RESEARCH_PROPS = ("PLAYER_POINTS", "PLAYER_REBOUNDS", "PLAYER_ASSISTS", "PLAYER_PRA")
NBA_BLOCKED = ("PLAYER_THREES", "PLAYER_STEALS", "PLAYER_BLOCKS", "PLAYER_TURNOVERS",
               "DOUBLE_DOUBLE", "QUARTER", "EXOTICS")


def _json(root: Path, relative: str) -> dict:
    path = root / relative
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"SOURCE_MISSING_OR_INVALID:{relative}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"SOURCE_NOT_OBJECT:{relative}")
    return data


def _nhl_keys(root: Path) -> list[str]:
    relative = "sportsedge/sports/nhl/market_capabilities.py"
    try:
        tree = ast.parse((root / relative).read_text(encoding="utf-8"))
    except (OSError, SyntaxError) as exc:
        raise ValueError(f"NHL_CATALOG_UNREADABLE:{relative}") from exc
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "_CAPABILITIES" for t in node.targets):
            if not isinstance(node.value, ast.Dict):
                break
            keys = [ast.literal_eval(k) for k in node.value.keys]
            if keys and all(isinstance(k, str) and k for k in keys):
                return sorted(set(keys))
    raise ValueError("NHL_CAPABILITY_KEYS_UNAVAILABLE")


def audit_market_gaps(root: Path) -> dict:
    """Report declared market paths; NEVER infer priceability from implementation."""
    root = Path(root)
    rows = []
    def add(sport: str, market: str, state: str, blocker: str, source: str) -> None:
        if not market or not state or not blocker:
            raise ValueError("INCOMPLETE_MARKET_EVIDENCE")
        rows.append({"sport": sport, "market": market, "status": state,
                     "blocker": blocker, "source": source, "priced": False,
                     "production_eligible": False, "forward_graded_n": None})

    surface = _json(root, "config/run_it_surface.json").get("sports", {})
    if not isinstance(surface, dict):
        raise ValueError("RUN_IT_SURFACE_INVALID")
    for sport in SPORTS:
        if sport not in surface:
            add(sport, "__AUTOMATIC_LANE__", "MISSING_LANE",
                "RUN_IT_SURFACE_MISSING_SPORT", "config/run_it_surface.json")
        elif not surface[sport].get("automatic_command"):
            add(sport, "__AUTOMATIC_LANE__", "NO_AUTOMATIC_CAPTURE",
                str(surface[sport].get("blocker") or "AUTOMATIC_CAPTURE_NOT_WIRED"),
                "config/run_it_surface.json")

    football_path = "config/football_market_surface.json"
    football = _json(root, football_path).get("markets")
    if not isinstance(football, list) or not football:
        raise ValueError("FOOTBALL_MARKET_CATALOG_EMPTY")
    prop_state = _json(root, "config/football_prop_engine_surface.json").get("sports", {})
    for entry in football:
        market = str(entry.get("market") or "").upper()
        family = str(entry.get("family") or "")
        for sport in ("NFL", "CFB"):
            engine = entry.get("engine_state_by_sport", {}).get(sport)
            if engine is None:
                add(sport, market, "UNKNOWN", "ENGINE_STATE_NOT_DECLARED", football_path)
            elif family != "game" and prop_state.get(sport, {}).get("engine_state") == "NO_ENGINE":
                add(sport, market, "NO_ENGINE", "FOOTBALL_PROP_AUTHORITY_NO_ENGINE", football_path)
            elif engine != "IMPLEMENTED":
                add(sport, market, "NO_ENGINE", f"DECLARED_{engine}", football_path)
            elif sport == "CFB" and market not in {"MONEYLINE", "SPREAD", "TOTAL"}:
                add(sport, market, "BLOCKED", "CFB_FAMILY_NOT_REGISTERED_FOR_RESEARCH", football_path)
            elif sport == "CFB":
                add(sport, market, "RESEARCH_ONLY", "CFB_FROZEN_MODEL_AND_FORWARD_EVIDENCE_MISSING", football_path)
            else:
                add(sport, market, "UNVERIFIED_ENGINE_PATH", "NFL_FROZEN_MODEL_LIVE_SOURCES_AND_FORWARD_EVIDENCE_REQUIRED", football_path)

    mlb_path = "config/mlb_market_catalog.json"
    mlb = _json(root, mlb_path)
    categories = ("game_markets", "batter_markets", "pitcher_markets", "separate_protocol_markets",
                  "binary_markets_not_coerced", "period_markets_not_coerced")
    for category in categories:
        names = mlb.get(category)
        if not isinstance(names, list):
            raise ValueError(f"MLB_CATALOG_CATEGORY_MISSING:{category}")
        for market in names:
            add("MLB", str(market).upper(), "CATALOG_ONLY_UNVERIFIED",
                "PER_MARKET_MODEL_QUOTE_AND_FORWARD_EVIDENCE_NOT_ESTABLISHED", mlb_path)

    for market in NBA_GAME + NBA_BLOCKED:
        add("NBA", market, "BLOCKED", "NBA_FAMILY_NOT_REGISTERED_FOR_PRICING", "sportsedge/family_market_registry.py")
    for market in NBA_RESEARCH_PROPS:
        add("NBA", market, "RESEARCH_ONLY", "PIT_SUFFICIENCY_AND_MARKET_VALIDATION_REQUIRED", "sportsedge/family_market_registry.py")
    for market in _nhl_keys(root):
        add("NHL", market, "REQUIRES_ENGINE", "NHL_PIT_STATE_AND_VALIDATION_NOT_VERIFIED", "sportsedge/sports/nhl/market_capabilities.py")
    for market in ("MONEYLINE", "SPREAD", "TOTAL", "PLAYER_PROPS", "__UNENUMERATED_MARKETS__"):
        add("CBB", market, "BLOCKED", "CBB_MARKET_REGISTRY_BLOCKED_OR_CATALOG_INCOMPLETE", "sportsedge/family_market_registry.py")

    seen = set()
    for row in rows:
        key = row["sport"], row["market"]
        if key in seen:
            raise ValueError(f"DUPLICATE_MARKET:{key}")
        seen.add(key)
    return {"report_type": "SIX_SPORT_DECLARED_MARKET_GAPS", "production_eligible": False,
            "complete_market_coverage": False, "reason": "CBB_AND_OTHER_UNENUMERATED_MARKETS_NOT_CATALOGUED",
            "sports": list(SPORTS), "market_rows": rows,
            "status_counts": dict(sorted(Counter(r["status"] for r in rows).items()))}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = audit_market_gaps(args.repo_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
