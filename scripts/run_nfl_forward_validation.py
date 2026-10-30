#!/usr/bin/env python3
"""Governed entry point for NFL_FORWARD_VALIDATION_DESIGN_V1.

ACTIVATION IS NOT AUTHORIZED. Owner ruling (Isaac, Oct 13 2026):
implementation and synthetic testing ONLY for the NFL forward-validation
harness. No real-data evaluation, no holdout access or consumption, no
activation, no scheduling.

This entry point therefore has exactly two behaviors:

* ``--dry-run-proof`` runs the design section 3.3 two-slate dry-run proof
  against fabricated synthetic records only and writes the proof report
  (stamped ``DRY_RUN_NOT_EVIDENCE``) to ``--output-dir``. This is the
  pipeline proof the design requires *before an activation request may
  even be made*; it is not evidence about any model.
* Every other invocation — in particular any attempt to run an evidence
  (activated) campaign — refuses by construction, before any argument is
  acted on, and writes nothing. Activation requires the owner approval
  artifact of design section 4.1 at
  ``config/research/nfl_forward_validation_activation_v1.json`` naming
  scope, legs, and freeze SHA. No such artifact exists; creating one is
  an owner action outside this implementation, and even if one appeared
  this build still refuses
  (``FORWARD_VALIDATION_ACTIVATION_NOT_IMPLEMENTED_IN_THIS_BUILD``).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sportsedge.research.nfl_forward_validation_v1 import (
    ForwardValidationNotActivated,
    assert_forward_validation_activated,
    run_two_slate_dry_run_proof,
)


def run_activation(*, repo_root: Path) -> dict:
    # Authorization is checked first and unconditionally; every other
    # argument is inert. Mirrors the G2 attempt-2 governed runner.
    assert_forward_validation_activated(repo_root)
    raise ForwardValidationNotActivated(
        "FORWARD_VALIDATION_NOT_ACTIVATED")  # unreachable


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="NFL forward validation (DESIGN_V1) — "
                    "activation NOT authorized; dry-run proof only.")
    parser.add_argument("--dry-run-proof", action="store_true",
                        help="run the synthetic two-slate dry-run proof")
    parser.add_argument("--output-dir", type=Path, default=None,
                        help="where the dry-run proof report is written")
    parser.add_argument("--games-per-slate", type=int, default=4)
    args = parser.parse_args(argv)
    if args.dry_run_proof:
        if args.output_dir is None:
            print("DRY_RUN_PROOF_OUTPUT_DIR_REQUIRED", file=sys.stderr)
            return 2
        report = run_two_slate_dry_run_proof(
            games_per_slate=args.games_per_slate)
        args.output_dir.mkdir(parents=True, exist_ok=True)
        out = args.output_dir / "nfl_forward_validation_dry_run_proof.json"
        out.write_text(json.dumps(report, indent=2, sort_keys=True,
                                  default=str))
        print(f"DRY_RUN_PROOF_WROTE {out}")
        print(f"verdict: {report['verdict']} "
              f"stamp: {report['stamp']} "
              f"counts: {report['reconciliation_counts']}")
        return 0
    try:
        run_activation(repo_root=Path.cwd())
    except ForwardValidationNotActivated as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0  # unreachable while activation is unauthorized


if __name__ == "__main__":
    raise SystemExit(main())
