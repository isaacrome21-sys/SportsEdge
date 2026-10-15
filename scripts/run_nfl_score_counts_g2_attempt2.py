#!/usr/bin/env python3
"""Governed development-attempt runner for NFL_SCORE_COUNTS_G2 attempt 2.

EXECUTION IS NOT AUTHORIZED. Owner ruling (Isaac, Oct 13 2026, issue
#2131): the J1 + K3 attempt-2 design is approved for IMPLEMENTATION AND
SYNTHETIC TESTING ONLY. Execution - fitting or evaluating on real
development data - is NO-GO, and attempt 2 remains unspent.

This entry point therefore refuses BY CONSTRUCTION:

* It contains no execution implementation at all: no source download, no
  source parsing, no row building, no evaluation call, no output writing.
  There is no code path from this file to a consumed attempt.
* Any invocation raises ATTEMPT_2_NOT_AUTHORIZED unless a go/no-go ledger
  artifact exists at
  ``config/research/nfl_score_counts_g2_attempt2_go_nogo_v1.json``.
  No such artifact exists, and creating one is itself an owner action
  outside this implementation. Even if one appeared, this build still
  refuses (ATTEMPT_2_EXECUTION_NOT_IMPLEMENTED_IN_THIS_BUILD): the
  execution implementation may only be added by the separately approved
  go/no-go step that derives and freezes the attempt-2 preregistration
  config and dispatches with the frozen confirmation string
  ``CONSUME_SCORE_COUNTS_G2_ATTEMPT_2``.
* The refusal happens before any argument is acted on and writes nothing.

The model form and gates harness live in
``sportsedge/research/nfl_score_counts_g2_v2.py`` and
``sportsedge/research/nfl_score_counts_g2_eval_v2.py`` and are exercised
only by the synthetic test suite (tests/test_nfl_score_counts_g2_attempt2.py),
which fits nothing but seeded synthetic data.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

GO_NO_GO_LEDGER_PATH = Path(
    "config/research/nfl_score_counts_g2_attempt2_go_nogo_v1.json")
CONFIRMATION = "CONSUME_SCORE_COUNTS_G2_ATTEMPT_2"


class Attempt2NotAuthorized(RuntimeError):
    """Raised on every invocation of the attempt-2 execution entry point."""


def assert_attempt2_authorized(repo_root: Path) -> None:
    """Refuse unless a go/no-go ledger artifact exists. It does not."""
    ledger = Path(repo_root) / GO_NO_GO_LEDGER_PATH
    if not ledger.is_file():
        raise Attempt2NotAuthorized(
            "ATTEMPT_2_NOT_AUTHORIZED: no go/no-go ledger artifact at "
            f"{GO_NO_GO_LEDGER_PATH.as_posix()} — owner ruling (issue #2131, "
            "Oct 13 2026) approves implementation and synthetic testing only; "
            "execution is NO-GO and attempt 2 remains unspent.")
    raise Attempt2NotAuthorized(
        "ATTEMPT_2_EXECUTION_NOT_IMPLEMENTED_IN_THIS_BUILD: a go/no-go "
        "ledger artifact is present, but this build contains no execution "
        "implementation; execution code is added only by the separately "
        "approved go/no-go step.")


def run_attempt(*, confirm: str, output_dir: Path,
                repo_root: Path = Path(".")) -> dict:
    # Authorization is checked first and unconditionally: the confirmation
    # string, the output directory, and every other argument are inert.
    assert_attempt2_authorized(repo_root)
    raise Attempt2NotAuthorized("ATTEMPT_2_NOT_AUTHORIZED")  # unreachable


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="NFL_SCORE_COUNTS_G2 attempt 2 — execution NOT authorized.")
    parser.add_argument("--confirm", default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args(argv)
    try:
        run_attempt(confirm=args.confirm or "",
                    output_dir=args.output_dir or Path("."))
    except Attempt2NotAuthorized as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0  # unreachable while execution is unauthorized


if __name__ == "__main__":
    raise SystemExit(main())
