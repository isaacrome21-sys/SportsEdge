#!/usr/bin/env python3
"""Deterministic JSON -> JSON runner for coherent NFL prop research.

The input must already contain PIT-safe player payloads, market-blind game-state
paths, and research market lines. This wrapper does not fetch sportsbook data,
fit priors, or grant promotion authority.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys
from typing import Any, Mapping

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from sportsedge.nfl_coherent_prop_runner import run_coherent_prop_estimates
from sportsedge.nfl_prop_shared_sim import NflPropSimulationError


class NFLCoherentPropCLIError(ValueError):
    pass


def _canonical(payload: Any) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def run_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise NFLCoherentPropCLIError("NFL_PROP_INPUT_OBJECT_REQUIRED")
    try:
        game_id = str(payload["game_id"])
        teams = payload["teams"]
        states = payload["game_states_by_team"]
        markets = payload["markets"]
    except KeyError as exc:
        raise NFLCoherentPropCLIError(f"NFL_PROP_INPUT_MISSING:{exc.args[0]}") from exc
    seed = int(payload.get("seed", 21))
    rows = run_coherent_prop_estimates(
        game_id=game_id,
        teams=teams,
        game_states_by_team=states,
        markets=markets,
        seed=seed,
    )
    return {
        "schema": "NFL_COHERENT_PROP_RESEARCH_RUN_V1",
        "game_id": game_id,
        "seed": seed,
        "input_sha256": sha256(_canonical(payload)).hexdigest(),
        "rows": rows,
        "status": "RESEARCH_ONLY",
        "authority": "NOT Model_P / NOT Truth Gate / NOT OFFICIAL",
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="PIT-safe JSON input payload")
    parser.add_argument("--output", type=Path, required=True, help="Output JSON path")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        raw = args.input.read_bytes()
        payload = json.loads(raw)
        result = run_payload(payload)
    except (OSError, json.JSONDecodeError, TypeError, ValueError, NflPropSimulationError) as exc:
        print(f"NFL_COHERENT_PROP_RUN_FAILED:{exc}", file=sys.stderr)
        return 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
