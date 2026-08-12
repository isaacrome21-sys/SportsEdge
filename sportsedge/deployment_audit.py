"""Fail-closed audit guard for SportsEdge deployment eligibility transitions."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping


class DeploymentAuditError(ValueError):
    pass


REQUIRED_TRANSITION_FIELDS = {
    "event_id", "event_type", "recorded_at_utc", "market",
    "previous_eligibility", "previous_stage", "new_eligibility", "new_stage",
    "reason_code", "commit_sha", "workflow_run_ids", "artifact_ids",
    "artifact_sha256", "validation_sample_count", "subgroup_counts",
    "historical_gate", "live_parity_gate", "runtime_gate",
    "truth_gate_test_result", "deployment_effect",
}


def load_events(path: str | Path = "audit/validation_events.jsonl") -> list[dict[str, Any]]:
    events=[]
    p=Path(path)
    if not p.exists():
        raise DeploymentAuditError("VALIDATION_EVENTS_MISSING")
    for i,line in enumerate(p.read_text(encoding="utf-8").splitlines(),1):
        if not line.strip(): continue
        try: row=json.loads(line)
        except Exception as exc: raise DeploymentAuditError(f"VALIDATION_EVENT_JSON_INVALID line={i}") from exc
        if not isinstance(row,dict): raise DeploymentAuditError(f"VALIDATION_EVENT_NOT_OBJECT line={i}")
        events.append(row)
    return events


def _transitions(events: list[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    out={}
    for e in events:
        if e.get("event_type") != "DEPLOYMENT_ELIGIBILITY_TRANSITION": continue
        market=str(e.get("market") or "")
        if not market: raise DeploymentAuditError("DEPLOYMENT_TRANSITION_MARKET_MISSING")
        missing=REQUIRED_TRANSITION_FIELDS-set(e)
        if missing: raise DeploymentAuditError(f"DEPLOYMENT_TRANSITION_FIELDS_MISSING market={market} fields={sorted(missing)}")
        if e.get("previous_eligibility") is not False or e.get("new_eligibility") is not True or e.get("new_stage")!="DEPLOYED":
            raise DeploymentAuditError(f"DEPLOYMENT_TRANSITION_STATE_INVALID market={market}")
        if not isinstance(e.get("workflow_run_ids"),list) or not e["workflow_run_ids"]:
            raise DeploymentAuditError(f"DEPLOYMENT_TRANSITION_RUN_IDS_MISSING market={market}")
        if not isinstance(e.get("artifact_ids"),list) or not e["artifact_ids"]:
            raise DeploymentAuditError(f"DEPLOYMENT_TRANSITION_ARTIFACT_IDS_MISSING market={market}")
        hashes=e.get("artifact_sha256")
        if not isinstance(hashes,(dict,list)) or not hashes:
            raise DeploymentAuditError(f"DEPLOYMENT_TRANSITION_HASHES_MISSING market={market}")
        for gate in ("historical_gate","live_parity_gate","runtime_gate","truth_gate_test_result"):
            if e.get(gate) not in (True,"PASS"):
                raise DeploymentAuditError(f"DEPLOYMENT_TRANSITION_GATE_NOT_PASS market={market} gate={gate}")
        if e.get("deployment_effect") != "ELIGIBILITY_FALSE_TO_TRUE":
            raise DeploymentAuditError(f"DEPLOYMENT_TRANSITION_EFFECT_INVALID market={market}")
        out[market]=e
    return out


def validate_deployment_audit(*, registry_path: str|Path="config/deployments.json", events_path: str|Path="audit/validation_events.jsonl", baseline_registry: Mapping[str,Any]|None=None) -> None:
    registry=json.loads(Path(registry_path).read_text(encoding="utf-8"))
    markets=registry.get("markets")
    if not isinstance(markets,dict): raise DeploymentAuditError("DEPLOYMENT_REGISTRY_INVALID")
    transitions=_transitions(load_events(events_path))
    for market,meta in markets.items():
        eligible=meta.get("eligible")
        if eligible is True:
            ev=transitions.get(market)
            if ev is None: raise DeploymentAuditError(f"ELIGIBLE_WITHOUT_TRANSITION market={market}")
            if meta.get("stage")!="DEPLOYED": raise DeploymentAuditError(f"ELIGIBLE_STAGE_NOT_DEPLOYED market={market}")
        if market in transitions and eligible is not True:
            raise DeploymentAuditError(f"TRANSITION_WITHOUT_ELIGIBLE_REGISTRY market={market}")
    if baseline_registry is not None:
        base=(baseline_registry.get("markets") or {})
        for market,meta in markets.items():
            before=(base.get(market) or {}).get("eligible")
            if before is False and meta.get("eligible") is True and market not in transitions:
                raise DeploymentAuditError(f"UNAUTHORIZED_FALSE_TO_TRUE market={market}")


def main() -> int:
    validate_deployment_audit()
    print("DEPLOYMENT_AUDIT_PASS")
    return 0

if __name__=="__main__": raise SystemExit(main())
