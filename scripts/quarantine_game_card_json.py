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
from sportsedge.game_candidate_quarantine import GAME_SURFACES, game_claim_hold


_IDENTITY_FIELDS = ("game", "selection", "market", "line", "event_id", "sport")
_REASON_PRIORITY = (
    "GAME_PROBABILITY_CLAIM_INVALID",
    "GAME_EV_CLAIM_INVALID",
    "EXTREME_CLAIMED_EV_QUARANTINE",
)


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
    filtered = {}
    quarantined_by_index = {}
    original_holds = {idx: game_claim_hold(row) for idx, row in original_by_index.items()}
    pre_counts = {}
    for name in GAME_SURFACES:
        rows = result.get(name, [])
        if not isinstance(rows, list):
            raise ValueError("GAME_SURFACE_NOT_LIST:" + name)
        pre_counts[name] = len(rows)
        kept = []
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("GAME_SURFACE_ROW_NOT_OBJECT:" + name)
            idx = _index(row, "GAME_SURFACE_ROW")
            original = original_by_index.get(idx)
            if original is None:
                raise ValueError("GAME_SURFACE_REFERENCE_NOT_IN_EVIDENCE")
            for key in ("game", "selection"):
                if key in original and key not in row:
                    raise ValueError("GAME_SURFACE_IDENTITY_MISSING:" + key)
            for key in _IDENTITY_FIELDS:
                if key in original and key in row and original[key] != row[key]:
                    raise ValueError("GAME_SURFACE_IDENTITY_CONFLICT:" + key)
            display_reason, display_max_ev = game_claim_hold(row)
            original_reason, original_max_ev = original_holds[idx]
            reasons = [r for r in (display_reason, original_reason) if r is not None]
            if not reasons:
                kept.append(row)
                continue
            reason = next(r for r in _REASON_PRIORITY if r in reasons)
            finite_maxes = [v for v in (display_max_ev, original_max_ev) if v is not None]
            max_ev = max(finite_maxes) if finite_maxes else None
            existing = quarantined_by_index.get(idx)
            if existing is None:
                quarantined_by_index[idx] = {
                    "input_index": idx,
                    "source_surfaces": [name],
                    "source_status": original.get("status"),
                    "reason": reason,
                    "max_finite_claimed_ev": max_ev,
                    "evidence_bound": True,
                    "research_only": True,
                    "eligible_for_headline": False,
                    "eligible_for_forward_clock": False,
                }
            else:
                existing["source_surfaces"].append(name)
                existing["reason"] = next(r for r in _REASON_PRIORITY if r in (existing["reason"], reason))
                vals = [v for v in (existing["max_finite_claimed_ev"], max_ev) if v is not None]
                existing["max_finite_claimed_ev"] = max(vals) if vals else None
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
