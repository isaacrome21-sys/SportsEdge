#!/usr/bin/env python3
"""Fail-closed audit for every GitHub workflow capable of spending Odds API credits.

Discovery is derived from workflow secret references.  The projection only supplies
metadata needed to prove cost, reserve ownership/guarding, and runtime bindings; it
cannot silently omit a newly added secret-touching workflow.
"""
from __future__ import annotations

import argparse
import importlib
import json
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import yaml

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROJECTION = ROOT / "config/odds_api_request_projection_v3.json"


class PaidConsumerAuditError(RuntimeError):
    pass


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PaidConsumerAuditError(f"JSON_INVALID:{path.relative_to(ROOT)}") from exc
    if not isinstance(value, dict):
        raise PaidConsumerAuditError(f"JSON_NOT_OBJECT:{path.relative_to(ROOT)}")
    return value


def load_workflow(path: Path) -> dict[str, Any]:
    try:
        value = yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    except (OSError, yaml.YAMLError) as exc:
        raise PaidConsumerAuditError(f"WORKFLOW_YAML_INVALID:{path.relative_to(ROOT)}") from exc
    if not isinstance(value, dict):
        raise PaidConsumerAuditError(f"WORKFLOW_NOT_MAPPING:{path.relative_to(ROOT)}")
    return value


def workflow_triggers(workflow: dict[str, Any]) -> set[str]:
    raw = workflow.get("on")
    if isinstance(raw, dict):
        return {str(key) for key in raw}
    if isinstance(raw, list):
        return {str(item) for item in raw}
    if raw is None:
        return set()
    return {str(raw)}


def normalize_values(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    raise PaidConsumerAuditError(f"COST_DIMENSION_INVALID:{value!r}")


def dotted(value: dict[str, Any], path: str) -> Any:
    current: Any = value
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            raise PaidConsumerAuditError(f"POLICY_PATH_MISSING:{path}")
        current = current[part]
    return current


def discovered_paid_workflows(projection: dict[str, Any]) -> dict[str, dict[str, Any]]:
    discovery = projection.get("discovery") or {}
    pattern = str(discovery.get("secret_reference_regex") or "")
    if not pattern:
        raise PaidConsumerAuditError("SECRET_REFERENCE_REGEX_MISSING")
    secret_re = re.compile(pattern)
    found: dict[str, dict[str, Any]] = {}
    for glob in discovery.get("workflow_globs") or []:
        for path in sorted(ROOT.glob(str(glob))):
            text = path.read_text(encoding="utf-8")
            if not secret_re.search(text):
                continue
            rel = path.relative_to(ROOT).as_posix()
            workflow = load_workflow(path)
            found[rel] = {
                "path": path,
                "text": text,
                "workflow": workflow,
                "triggers": workflow_triggers(workflow),
            }
    return found


def require_shared_concurrency(rel: str, workflow: dict[str, Any], projection: dict[str, Any]) -> None:
    expected_group = str(projection["discovery"]["required_concurrency_group"])
    concurrency = workflow.get("concurrency")
    if not isinstance(concurrency, dict):
        raise PaidConsumerAuditError(f"PAID_CONCURRENCY_MISSING:{rel}")
    if str(concurrency.get("group") or "") != expected_group:
        raise PaidConsumerAuditError(f"PAID_CONCURRENCY_GROUP_MISMATCH:{rel}")
    cancel = str(concurrency.get("cancel-in-progress") or "").lower()
    expected_cancel = str(projection["discovery"].get("required_cancel_in_progress", False)).lower()
    if cancel != expected_cancel:
        raise PaidConsumerAuditError(f"PAID_CONCURRENCY_CANCEL_MISMATCH:{rel}")


def request_profile_cost(policy: dict[str, Any], spec: dict[str, Any]) -> tuple[int, list[str], list[str]]:
    markets = normalize_values(dotted(policy, str(spec["markets_path"])))
    regions = normalize_values(dotted(policy, str(spec["regions_path"])))
    if not markets or not regions:
        raise PaidConsumerAuditError("EMPTY_MARKETS_OR_REGIONS")
    return len(markets) * len(regions), markets, regions


def probe_forward_runtime(policy: dict[str, Any]) -> None:
    from sportsedge.sports.nfl.odds_source import build_nfl_odds_url

    cases = {
        "decision": build_nfl_odds_url(),
        "close": build_nfl_odds_url(event_id="audit-event"),
    }
    for profile_name, url in cases.items():
        profile = policy["request_profiles"][profile_name]
        query = parse_qs(urlparse(url).query)
        markets = normalize_values((query.get("markets") or [""])[0])
        regions = normalize_values((query.get("regions") or [""])[0])
        if markets != normalize_values(profile["markets"]):
            raise PaidConsumerAuditError(f"FORWARD_RUNTIME_MARKETS_MISMATCH:{profile_name}")
        if regions != normalize_values(profile["regions"]):
            raise PaidConsumerAuditError(f"FORWARD_RUNTIME_REGIONS_MISMATCH:{profile_name}")


def probe_confirmation_runtime(policy: dict[str, Any]) -> None:
    cfg = load_json(ROOT / "config/nfl_2026_capture.json")
    profile = policy["request_profiles"]["confirmation_fallback"]
    if normalize_values(cfg.get("markets")) != normalize_values(profile["markets"]):
        raise PaidConsumerAuditError("NFL_CONFIRMATION_RUNTIME_MARKETS_MISMATCH")
    if str(cfg.get("sport_key")) != str(policy.get("sport_key")):
        raise PaidConsumerAuditError("NFL_CONFIRMATION_RUNTIME_SPORT_MISMATCH")
    if [str(cfg.get("bookmaker"))] != normalize_values(policy.get("bookmakers")):
        raise PaidConsumerAuditError("NFL_CONFIRMATION_RUNTIME_BOOKMAKER_MISMATCH")
    if normalize_values(profile["regions"]) != ["us"]:
        raise PaidConsumerAuditError("NFL_CONFIRMATION_SINGLE_REGION_POLICY_REQUIRED")


def probe_mlb_failover_runtime(policy: dict[str, Any]) -> None:
    module = importlib.import_module("scripts.archive_raw_game_odds")
    profile = policy["request_profiles"]["game_odds"]
    if normalize_values(getattr(module, "MARKETS")) != normalize_values(profile["markets"]):
        raise PaidConsumerAuditError("MLB_FAILOVER_RUNTIME_MARKETS_MISMATCH")
    if normalize_values(getattr(module, "REGIONS")) != normalize_values(profile["regions"]):
        raise PaidConsumerAuditError("MLB_FAILOVER_RUNTIME_REGIONS_MISMATCH")
    if str(getattr(module, "SPORT_KEY")) != str(policy.get("sport_key")):
        raise PaidConsumerAuditError("MLB_FAILOVER_RUNTIME_SPORT_MISMATCH")


def runtime_probe(name: str, policy: dict[str, Any]) -> None:
    if name == "archive_policy":
        guard = policy.get("provider_budget_guard") or {}
        if guard.get("enabled") is not True:
            raise PaidConsumerAuditError("ARCHIVE_PROVIDER_BUDGET_GUARD_DISABLED")
        return
    if name == "nfl_forward_url_builder":
        probe_forward_runtime(policy)
        return
    if name == "nfl_confirmation_capture_config":
        probe_confirmation_runtime(policy)
        return
    if name == "mlb_failover_constants":
        probe_mlb_failover_runtime(policy)
        return
    raise PaidConsumerAuditError(f"RUNTIME_PROBE_UNKNOWN:{name}")


def audit(projection_path: Path = DEFAULT_PROJECTION) -> dict[str, Any]:
    projection = load_json(projection_path)
    consumers = projection.get("consumers")
    if not isinstance(consumers, dict) or not consumers:
        raise PaidConsumerAuditError("DECLARED_CONSUMERS_MISSING")

    discovered = discovered_paid_workflows(projection)
    discovered_set = set(discovered)
    declared_set = set(consumers)
    missing = sorted(discovered_set - declared_set)
    stale = sorted(declared_set - discovered_set)
    if missing:
        raise PaidConsumerAuditError("UNDECLARED_PAID_WORKFLOW:" + ",".join(missing))
    if stale:
        raise PaidConsumerAuditError("STALE_DECLARED_PAID_WORKFLOW:" + ",".join(stale))

    reserve = int(projection.get("confirmation_reserve_credits"))
    budget = load_json(ROOT / str(projection["provider_budget_path"]))
    budget_reserve = int(budget["lower_priority_paid_work"]["minimum_confirmation_reserve_credits"])
    if reserve != budget_reserve:
        raise PaidConsumerAuditError("CONFIRMATION_RESERVE_PROJECTION_MISMATCH")

    owner = str(projection.get("reserve_owner_workflow") or "")
    rows: list[dict[str, Any]] = []
    for rel in sorted(discovered):
        actual = discovered[rel]
        spec = consumers[rel]
        actual_triggers = actual["triggers"]
        declared_triggers = {str(item) for item in spec.get("triggers") or []}
        if actual_triggers != declared_triggers:
            raise PaidConsumerAuditError(
                f"TRIGGER_SET_MISMATCH:{rel}:actual={sorted(actual_triggers)}:declared={sorted(declared_triggers)}"
            )
        require_shared_concurrency(rel, actual["workflow"], projection)

        policy_path = ROOT / str(spec.get("policy_file") or "")
        policy = load_json(policy_path)
        runtime_probe(str(spec.get("runtime_probe") or ""), policy)

        profile_rows = []
        for profile_name, profile_spec in sorted((spec.get("request_profiles") or {}).items()):
            cost, markets, regions = request_profile_cost(policy, profile_spec)
            declared_cost = int(profile_spec.get("declared_credits_per_call"))
            if declared_cost != cost:
                raise PaidConsumerAuditError(
                    f"CREDIT_COST_MISMATCH:{rel}:{profile_name}:declared={declared_cost}:derived={cost}"
                )
            policy_profile = (policy.get("request_profiles") or {}).get(profile_name)
            if isinstance(policy_profile, dict) and "credits_per_call" in policy_profile:
                if int(policy_profile["credits_per_call"]) != cost:
                    raise PaidConsumerAuditError(f"POLICY_CREDIT_COST_MISMATCH:{rel}:{profile_name}")
            if "guard_minimum_path" in profile_spec:
                minimum = int(dotted(policy, str(profile_spec["guard_minimum_path"])))
                if minimum != reserve + cost:
                    raise PaidConsumerAuditError(f"RESERVE_THRESHOLD_MISMATCH:{rel}:{profile_name}")
                guard_text = (ROOT / str(spec["guard_file"])).read_text(encoding="utf-8")
                if f"--minimum-remaining {minimum}" not in guard_text:
                    raise PaidConsumerAuditError(f"RESERVE_THRESHOLD_NOT_ENFORCED:{rel}:{profile_name}")
            profile_rows.append({
                "profile": profile_name,
                "markets": len(markets),
                "regions": len(regions),
                "credits_per_call": cost,
            })

        role = str(spec.get("reserve_role") or "")
        if "schedule" in actual_triggers:
            if rel == owner:
                if role != "reserve_owner":
                    raise PaidConsumerAuditError(f"RESERVE_OWNER_ROLE_INVALID:{rel}")
            else:
                if role != "guarded_lower_priority":
                    raise PaidConsumerAuditError(f"SCHEDULED_PAID_CONSUMER_NOT_GUARDED:{rel}")
                guard_file = ROOT / str(spec.get("guard_file") or "")
                guard_text = guard_file.read_text(encoding="utf-8")
                if "quota_guard" not in guard_text and "odds_api_quota_guard" not in guard_text:
                    raise PaidConsumerAuditError(f"RESERVE_GUARD_PROOF_MISSING:{rel}")
                if str(policy.get("provider_budget_path") or (policy.get("provider_budget_guard") or {}).get("budget_path") or "") != str(projection["provider_budget_path"]):
                    raise PaidConsumerAuditError(f"RESERVE_BUDGET_PATH_MISMATCH:{rel}")
        elif role not in {"manual_only", "guarded_lower_priority", "reserve_owner"}:
            raise PaidConsumerAuditError(f"RESERVE_ROLE_INVALID:{rel}")

        rows.append({
            "workflow": rel,
            "triggers": sorted(actual_triggers),
            "reserve_role": role,
            "request_profiles": profile_rows,
        })

    scheduled_mlb = [row["workflow"] for row in rows if "schedule" in row["triggers"] and "mlb" in row["workflow"].lower()]
    if scheduled_mlb:
        raise PaidConsumerAuditError("MLB_SCHEDULED_PAID_WORKFLOW:" + ",".join(sorted(scheduled_mlb)))

    return {
        "state": "PASS",
        "derived_paid_consumer_count": len(rows),
        "confirmation_reserve_credits": reserve,
        "required_concurrency_group": projection["discovery"]["required_concurrency_group"],
        "consumers": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--projection", type=Path, default=DEFAULT_PROJECTION)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    try:
        report = audit(args.projection)
    except PaidConsumerAuditError as exc:
        print(f"PAID_ODDS_CONSUMER_AUDIT_FAIL:{exc}", file=sys.stderr)
        return 1
    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
