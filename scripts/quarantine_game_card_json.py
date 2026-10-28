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
from sportsedge.game_candidate_quarantine import GAME_SURFACES, quarantine_game_surfaces


def sanitize_card(card):
    """Return a separately derived research card, preserving evaluated rows."""
    if not isinstance(card, dict):
        raise ValueError("GAME_CARD_NOT_OBJECT")
    if "game_quarantined" in card:
        raise ValueError("GAME_CARD_ALREADY_PARTITIONED")
    originals = card.get("evaluated_rows")
    if not isinstance(originals, list) or any(not isinstance(r, dict) for r in originals):
        raise ValueError("GAME_EVALUATED_ROWS_REQUIRED")
    result = deepcopy(card)
    surfaces = {}
    for key in GAME_SURFACES:
        value = result.get(key, [])
        if not isinstance(value, list):
            raise ValueError("GAME_SURFACE_NOT_LIST:" + key)
        surfaces[key] = value
    filtered, quarantined = quarantine_game_surfaces(surfaces)
    original_indices = {r.get("input_index") for r in originals
                        if type(r.get("input_index")) is int and r["input_index"] >= 0}
    if any(q["input_index"] not in original_indices for q in quarantined):
        raise ValueError("GAME_QUARANTINE_REFERENCE_NOT_IN_EVIDENCE")
    for key in GAME_SURFACES:
        result[key] = filtered[key]
    result["game_quarantined"] = quarantined
    result["game_quarantine_adapter"] = {
        "status": "RESEARCH_ONLY_NOT_PRODUCTION_WIRED",
        "frozen_engine_modified_by_adapter": False,
        "original_evaluated_rows_preserved": True,
        "forward_clock_authority": False,
        "model_verification_authority": False,
    }
    summary = result.get("summary")
    if isinstance(summary, dict):
        result["pre_quarantine_ranked_counts"] = {
            key: len(surfaces[key]) for key in GAME_SURFACES
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
