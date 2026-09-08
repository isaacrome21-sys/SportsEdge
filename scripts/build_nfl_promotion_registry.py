#!/usr/bin/env python3
"""Build a fail-closed NFL per-market promotion ledger.

This command deliberately does not expose a `--ci-attested` switch. A running
workflow cannot self-attest completion, and a caller-supplied boolean is not
executable evidence. The artifact produced here is therefore PRE-CI; an exact
successful workflow run may later be attached as external evidence without
pretending this step attested itself.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from sportsedge.core.promotion.football_registry import build_nfl_promotion_registry


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--math-evidence", type=Path, required=True)
    parser.add_argument("--historical-evidence", type=Path, required=True)
    parser.add_argument("--market-surface", type=Path, default=Path("config/football_market_surface.json"))
    parser.add_argument("--clv-evidence", type=Path)
    parser.add_argument("--out", type=Path, default=Path("artifacts/football/nfl_promotion_registry.json"))
    args = parser.parse_args()

    math_payload = _read(args.math_evidence)
    math_artifact = math_payload.get("math_artifact", math_payload)
    history = _read(args.historical_evidence)
    surface = _read(args.market_surface)
    if "NFL" not in {str(s).upper() for s in surface.get("sports", [])}:
        raise SystemExit("NFL_MARKET_SURFACE_NOT_DECLARED")
    rows = [row for row in surface.get("markets", []) if isinstance(row, dict) and row.get("market")]
    if not rows:
        raise SystemExit("NFL_MARKET_SURFACE_EMPTY")
    declared_markets = []
    no_engine_markets = []
    for row in rows:
        market = str(row["market"])
        states = row.get("engine_state_by_sport")
        if not isinstance(states, dict) or states.get("NFL") not in {"IMPLEMENTED", "NO_ENGINE"}:
            raise SystemExit(f"NFL_MARKET_ENGINE_STATE_REQUIRED:{market}")
        if states["NFL"] == "IMPLEMENTED":
            declared_markets.append(market)
        else:
            no_engine_markets.append(market)
    if not declared_markets:
        raise SystemExit("NFL_IMPLEMENTED_MARKET_SURFACE_EMPTY")

    clv = _read(args.clv_evidence) if args.clv_evidence is not None else None

    registry = build_nfl_promotion_registry(
        math_artifact,
        history,
        declared_markets=declared_markets,
        ci_attested=False,
        clv_evidence=clv,
    )
    registry["ci_attestation_state"] = "UNATTESTED_IN_RUNNING_WORKFLOW"
    registry["historical_model_id"] = history.get("model_id")
    registry["no_engine_markets"] = sorted(no_engine_markets)
    registry["declared_market_count"] = len(rows)
    registry["implemented_market_count"] = len(declared_markets)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(registry, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(registry, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
