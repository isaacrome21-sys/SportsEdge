#!/usr/bin/env python3
"""Dry-run verification of the owner receipt infrastructure.

DEVELOPMENT ONLY — this is not a capture tool and activates
nothing. It runs the three dry-run scenarios of
``sportsedge/backtest/receipt_dry_run.py`` (ARCHIVED-in-sandbox,
REFUSED, killed-mid-append -> INDETERMINATE) against a sandbox
archive the caller names explicitly. There is deliberately **no
default archive directory**: the production archive
(``archive/strict-forward-capture``) can never be selected — the
sandbox guard refuses it (and anything inside the repository's
``archive/`` tree, and any directory not clearly named with
``dry-run``) before a single byte is written.

Owner authorization (Isaac, Oct 12 2026): receipt-infrastructure
development and dry-run verification may proceed under the Lane A
HOLD; activation, retrospective backfill, holdout access, and
production promotion remain separately gated, and the freeze SHA
is chosen only at the moment an activation is approved — never
preselected here.

Usage:

    python scripts/dry_run_receipt_infra.py \
        --sandbox-root /tmp/sportsedge-dry-run

Prints a JSON report; exit 0 only when every scenario passes and
the production archive's tree digest is unchanged.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sportsedge.backtest import receipt_dry_run as dr


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sandbox-root", required=True, type=Path,
                        help="directory the dry-run archives are "
                             "created under; each archive directory "
                             "is named with 'dry-run' and guarded "
                             "against the production archive path")
    args = parser.parse_args(argv)
    try:
        report = dr.run_all_dry_runs(args.sandbox_root)
    except dr.DryRunError as exc:
        print(json.dumps({"status": "DRY_RUN_REFUSED",
                          "reason": str(exc)}, indent=2,
                         sort_keys=True))
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
