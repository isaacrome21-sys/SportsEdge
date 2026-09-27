#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from sportsedge.governance.freeze_reconciliation import (  # noqa: E402
    build_reconciliation_report,
    load_json,
)
from sportsedge.sports.cfb.model_selection_prereg import (  # noqa: E402
    audit_model_selection_prereg,
)

CFB_CANDIDATE_BUNDLE = "CFB_CANDIDATE_PREREG_FREEZE_V1"
CFB_CANDIDATE_REFREEZE_SCHEMA = "CFB_CANDIDATE_PREREG_REFREEZE_V1"
CFB_CANDIDATE_TRIGGER_PR = 833


def _git(repo: Path, *args: str, check: bool = True) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=repo,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if check and proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip()
        raise SystemExit(f"REFROZEN_GIT_CHECK_FAILED:{' '.join(args)}:{detail}")
    return proc.stdout.strip()


def _is_ancestor(repo: Path, older: str, newer: str) -> bool:
    proc = subprocess.run(
        ["git", "merge-base", "--is-ancestor", older, newer],
        cwd=repo,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return proc.returncode == 0


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _parse_timestamp(value: object, error: str) -> datetime:
    text = str(value or "").strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise SystemExit(error) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise SystemExit(error)
    return parsed


def _covered_change(bundle: Mapping[str, Any], path: str) -> bool:
    normalized = path.strip("/")
    for exact in bundle.get("coverage_paths") or []:
        if normalized == str(exact).strip("/"):
            return True
    for prefix in bundle.get("coverage_prefixes") or []:
        value = str(prefix).strip("/")
        if normalized == value or normalized.startswith(value):
            return True
    return False


def _verify_cfb_candidate_prereg_refreeze(
    registry: Mapping[str, Any], bundle: Mapping[str, Any], repo: Path
) -> None:
    disposition = bundle.get("disposition")
    if not isinstance(disposition, Mapping):
        raise SystemExit("CFB_CANDIDATE_REFREEZE_DISPOSITION_REQUIRED")
    if disposition.get("verification_schema") != CFB_CANDIDATE_REFREEZE_SCHEMA:
        raise SystemExit("CFB_CANDIDATE_REFREEZE_VERIFICATION_SCHEMA_INVALID")
    if disposition.get("new_bundle_id") != "CFB_CANDIDATE_PREREG_FREEZE_V3":
        raise SystemExit("CFB_CANDIDATE_REFREEZE_BUNDLE_ID_INVALID")

    prior_freeze = str(bundle.get("freeze_sha") or "")
    if disposition.get("prior_bundle_freeze_sha") != prior_freeze:
        raise SystemExit("CFB_CANDIDATE_REFREEZE_PRIOR_FREEZE_MISMATCH")
    new_freeze = str(disposition.get("new_freeze_sha") or "")
    if len(prior_freeze) != 40 or len(new_freeze) != 40:
        raise SystemExit("CFB_CANDIDATE_REFREEZE_GIT_SHA_INVALID")

    trigger_rows = [
        row
        for row in registry.get("deltas") or []
        if isinstance(row, Mapping) and int(row.get("pr") or 0) == CFB_CANDIDATE_TRIGGER_PR
    ]
    if len(trigger_rows) != 1:
        raise SystemExit("CFB_CANDIDATE_REFREEZE_TRIGGER_DELTA_NOT_UNIQUE")
    trigger_sha = str(trigger_rows[0].get("merge_sha") or "")
    if disposition.get("trigger_delta_sha") != trigger_sha:
        raise SystemExit("CFB_CANDIDATE_REFREEZE_TRIGGER_SHA_MISMATCH")

    _git(repo, "cat-file", "-e", f"{prior_freeze}^{{commit}}")
    _git(repo, "cat-file", "-e", f"{trigger_sha}^{{commit}}")
    _git(repo, "cat-file", "-e", f"{new_freeze}^{{commit}}")
    if not _is_ancestor(repo, prior_freeze, trigger_sha):
        raise SystemExit("CFB_CANDIDATE_REFREEZE_PRIOR_NOT_ANCESTOR_OF_TRIGGER")
    if not _is_ancestor(repo, trigger_sha, new_freeze):
        raise SystemExit("CFB_CANDIDATE_REFREEZE_TRIGGER_NOT_ANCESTOR_OF_NEW_FREEZE")

    restarted = _parse_timestamp(
        disposition.get("forward_clock_restart_at"),
        "CFB_CANDIDATE_REFREEZE_TIMESTAMP_INVALID",
    )
    commit_epoch = int(_git(repo, "show", "-s", "--format=%ct", new_freeze))
    if int(restarted.timestamp()) != commit_epoch:
        raise SystemExit("CFB_CANDIDATE_REFREEZE_TIMESTAMP_NOT_BOUND_TO_FREEZE_COMMIT")

    changed = [line for line in _git(repo, "diff", "--name-only", new_freeze, "--").splitlines() if line]
    covered = sorted(path for path in changed if _covered_change(bundle, path))
    if covered:
        raise SystemExit("CFB_CANDIDATE_REFREEZE_COVERED_BYTES_DRIFT:" + ",".join(covered))

    prereg_path = repo / "config/cfb_model_candidate_prereg_v1.json"
    policy_path = repo / "config/cfb_model_selection_policy_v1.json"
    code_manifest_path = repo / "config/cfb_model_candidate_code_manifest_v1.json"
    specs_path = repo / "config/cfb_model_candidate_specs_v1.json"
    prereg = json.loads(prereg_path.read_text(encoding="utf-8"))
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    code_manifest = json.loads(code_manifest_path.read_text(encoding="utf-8"))
    specs = json.loads(specs_path.read_text(encoding="utf-8"))

    if _sha256_file(code_manifest_path) != prereg.get("code_manifest_sha256"):
        raise SystemExit("CFB_CANDIDATE_REFREEZE_CODE_MANIFEST_SHA256_MISMATCH")
    if _sha256_file(specs_path) != prereg.get("candidate_spec_bundle_sha256"):
        raise SystemExit("CFB_CANDIDATE_REFREEZE_SPEC_BUNDLE_SHA256_MISMATCH")

    identities = code_manifest.get("git_blob_identities") or {}
    if not isinstance(identities, Mapping) or not identities:
        raise SystemExit("CFB_CANDIDATE_REFREEZE_CODE_BLOB_IDENTITIES_MISSING")
    for path, expected in sorted(identities.items()):
        actual = _git(repo, "hash-object", str(path))
        if actual != str(expected):
            raise SystemExit(f"CFB_CANDIDATE_REFREEZE_CODE_BLOB_MISMATCH:{path}")

    report = audit_model_selection_prereg(policy, prereg)
    if report.get("status") != "READY_FOR_FIRST_EVALUATION":
        raise SystemExit(
            "CFB_CANDIDATE_REFREEZE_PREREG_NOT_READY:"
            + ",".join(str(v) for v in report.get("blockers") or [])
        )
    if report.get("attempts_consumed") != 0 or report.get("model_fit_performed") is not False:
        raise SystemExit("CFB_CANDIDATE_REFREEZE_ATTEMPT_OR_FIT_ALREADY_CONSUMED")

    governance = prereg.get("governance") or {}
    if governance.get("attempts_consumed") != 0 or governance.get("evaluation_performed") is not False:
        raise SystemExit("CFB_CANDIDATE_REFREEZE_GOVERNANCE_ATTEMPT_STATE_INVALID")
    for key in ("model_p_created", "promotion_authority", "eligibility_changed", "official_authority"):
        if governance.get(key) is not False:
            raise SystemExit(f"CFB_CANDIDATE_REFREEZE_AUTHORITY_FORBIDDEN:{key}")
    if int(policy.get("candidate_attempt_budget", -1)) != 4 or int(policy.get("attempts_consumed", -1)) != 0:
        raise SystemExit("CFB_CANDIDATE_REFREEZE_POLICY_ATTEMPT_ACCOUNTING_INVALID")
    if set(map(str, policy.get("candidate_families_predeclared") or [])) != set(map(str, prereg.get("candidates") or {})):
        raise SystemExit("CFB_CANDIDATE_REFREEZE_FAMILY_SET_MISMATCH")

    if disposition.get("row_admissibility_semantics") != "PREREGISTRATION_ONLY_NO_EVALUATION_ROWS_V1":
        raise SystemExit("CFB_CANDIDATE_REFREEZE_ROW_ADMISSIBILITY_INVALID")
    if disposition.get("selection_scope_only") is not True:
        raise SystemExit("CFB_CANDIDATE_REFREEZE_SELECTION_SCOPE_REQUIRED")
    authority = disposition.get("authority") or {}
    if not isinstance(authority, Mapping) or any(bool(value) for value in authority.values()):
        raise SystemExit("CFB_CANDIDATE_REFREEZE_AUTHORITY_ESCALATION")


def assert_refreeze_machine_verified(
    registry: dict[str, object], repo: Path = REPO_ROOT
) -> None:
    unverified: list[str] = []
    for bundle in registry.get("bundles") or []:
        if not isinstance(bundle, dict):
            continue
        disposition = bundle.get("disposition")
        if not isinstance(disposition, dict) or disposition.get("state") != "REFROZEN":
            continue
        bundle_id = str(bundle.get("bundle_id") or "UNKNOWN_BUNDLE")
        if bundle_id == CFB_CANDIDATE_BUNDLE:
            _verify_cfb_candidate_prereg_refreeze(registry, bundle, repo)
            continue
        unverified.append(bundle_id)
    if unverified:
        raise SystemExit(
            "REFROZEN_SEMANTICS_NOT_MACHINE_VERIFIED:"
            + ",".join(sorted(unverified))
            + ":ONLY_REVOKED_ALLOWED_UNTIL_PRIOR_BUNDLE_HASH_TIMESTAMP_AND_ROW_ADMISSIBILITY_ARE_VERIFIED"
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
    assert_refreeze_machine_verified(registry, repo=repo)
    report = build_reconciliation_report(
        repo=repo,
        policy=policy,
        registry=registry,
        current_main_ref=args.current_main_ref,
    )
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
