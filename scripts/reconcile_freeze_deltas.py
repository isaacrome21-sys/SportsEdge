#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from sportsedge.governance.freeze_reconciliation import (  # noqa: E402
    FreezeReconciliationError,
    build_reconciliation_report,
    bundle_snapshot,
    is_ancestor,
    load_json,
    resolve_sha,
)


def _parse_utc_z(value: object, *, field: str, bundle_id: str) -> datetime:
    text = str(value or "")
    if not text.endswith("Z"):
        raise SystemExit(f"REFROZEN_TIMESTAMP_INVALID:{bundle_id}:{field}")
    try:
        return datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError as exc:
        raise SystemExit(
            f"REFROZEN_TIMESTAMP_INVALID:{bundle_id}:{field}"
        ) from exc


def assert_refreeze_machine_verified(
    *, repo: Path, registry: dict[str, object], report: dict[str, object]
) -> None:
    """Fail closed unless every REFROZEN disposition is replay-verifiable.

    A refreeze is admissible only when the registry binds the prior and new
    covered-surface hashes, binds invalidation to the forward-clock restart,
    and the new freeze includes every confirmed drift row for that bundle.
    This grants no model, promotion, staking, Truth Gate, or OFFICIAL authority.
    """

    rows = report.get("rows") or []
    reconciled_through = resolve_sha(repo, str(registry["reconciled_through_sha"]))

    for bundle in registry.get("bundles") or []:
        if not isinstance(bundle, dict):
            continue
        disposition = bundle.get("disposition")
        if not isinstance(disposition, dict) or disposition.get("state") != "REFROZEN":
            continue

        bundle_id = str(bundle.get("bundle_id") or "UNKNOWN_BUNDLE")
        required = (
            "new_bundle_id",
            "new_freeze_sha",
            "forward_clock_restart_at",
            "prior_bundle_hash",
            "new_bundle_hash",
            "prior_semantics_invalid_after",
            "prior_evidence_invalidation_rule",
        )
        missing = [key for key in required if not disposition.get(key)]
        if missing:
            raise SystemExit(
                f"REFROZEN_MACHINE_FIELDS_MISSING:{bundle_id}:{','.join(missing)}"
            )
        if str(disposition["new_bundle_id"]) == bundle_id:
            raise SystemExit(f"REFROZEN_NEW_BUNDLE_ID_NOT_NEW:{bundle_id}")
        if disposition["prior_evidence_invalidation_rule"] != "HASH_AND_TIME":
            raise SystemExit(f"REFROZEN_INVALIDATION_RULE_INVALID:{bundle_id}")

        restart = _parse_utc_z(
            disposition["forward_clock_restart_at"],
            field="forward_clock_restart_at",
            bundle_id=bundle_id,
        )
        invalid_after = _parse_utc_z(
            disposition["prior_semantics_invalid_after"],
            field="prior_semantics_invalid_after",
            bundle_id=bundle_id,
        )
        if restart != invalid_after:
            raise SystemExit(f"REFROZEN_CLOCK_INVALIDATION_MISMATCH:{bundle_id}")

        try:
            old_sha = resolve_sha(repo, str(bundle["freeze_sha"]))
            new_sha = resolve_sha(repo, str(disposition["new_freeze_sha"]))
            if not is_ancestor(repo, old_sha, new_sha):
                raise SystemExit(f"REFROZEN_NOT_DESCENDANT:{bundle_id}")
            if not is_ancestor(repo, new_sha, reconciled_through):
                raise SystemExit(f"REFROZEN_AFTER_RECONCILIATION_BOUNDARY:{bundle_id}")
            prior_snapshot = bundle_snapshot(repo, bundle, old_sha)
            new_snapshot = bundle_snapshot(repo, bundle, new_sha)
        except FreezeReconciliationError as exc:
            raise SystemExit(f"REFROZEN_REPLAY_UNRESOLVED:{bundle_id}:{exc}") from exc

        if prior_snapshot.aggregate_sha256 != disposition["prior_bundle_hash"]:
            raise SystemExit(f"REFROZEN_PRIOR_BUNDLE_HASH_MISMATCH:{bundle_id}")
        if new_snapshot.aggregate_sha256 != disposition["new_bundle_hash"]:
            raise SystemExit(f"REFROZEN_NEW_BUNDLE_HASH_MISMATCH:{bundle_id}")

        bundle_rows = [
            row
            for row in rows
            if isinstance(row, dict) and row.get("bundle_id") == bundle_id
        ]
        if any(row.get("outcome") == "PROVISIONAL_DRIFT_BLOCKED" for row in bundle_rows):
            raise SystemExit(f"REFROZEN_PROVISIONAL_ROWS_REMAIN:{bundle_id}")
        drift_rows = [row for row in bundle_rows if row.get("outcome") == "DRIFT_CONFIRMED"]
        if not drift_rows:
            raise SystemExit(f"REFROZEN_WITHOUT_CONFIRMED_DRIFT:{bundle_id}")
        for row in drift_rows:
            drift_sha = resolve_sha(repo, str(row["merge_sha"]))
            if not is_ancestor(repo, drift_sha, new_sha):
                raise SystemExit(
                    f"REFROZEN_DRIFT_NOT_INCLUDED:{bundle_id}:{row.get('delta_id')}"
                )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Reconcile every registered post-freeze delta against every active freeze bundle."
    )
    parser.add_argument(
        "--policy", default="config/freeze_reconciliation_policy_v1.json"
    )
    parser.add_argument(
        "--registry", default="config/freeze_reconciliation_registry_v1.json"
    )
    parser.add_argument("--repo", default=".")
    parser.add_argument("--current-main-ref", default="main")
    parser.add_argument("--output")
    parser.add_argument("--require-release-ready", action="store_true")
    args = parser.parse_args()

    repo = Path(args.repo).resolve()
    policy = load_json(args.policy)
    registry = load_json(args.registry)
    report = build_reconciliation_report(
        repo=repo,
        policy=policy,
        registry=registry,
        current_main_ref=args.current_main_ref,
    )
    assert_refreeze_machine_verified(repo=repo, registry=registry, report=report)
    rendered = json.dumps(report, sort_keys=True, indent=2) + "\n"
    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    if args.require_release_ready and not report["release_ready"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
