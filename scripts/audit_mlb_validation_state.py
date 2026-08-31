#!/usr/bin/env python3
"""Derive MLB market validation state from durable evidence without promoting by assertion."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
from typing import Any

REQUIRED_GATES = (
    "historical_point_in_time",
    "untouched_holdout",
    "calibration",
    "settlement_semantics",
    "forward_evidence",
    "production_parity",
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SETTLEMENT_SCHEMA = "mlb_settlement_semantics_v2"
_SETTLEMENT_SOURCE = "MLB_STATSAPI_BOX_SCORE_AND_LIVE_FEED"
_SETTLEMENT_INVARIANTS = frozenset({
    "batter_hits_reconciled",
    "f5_reconciled",
    "facts_present",
    "final_status",
    "first_inning_reconciled",
    "home_run_order_reconciled",
    "winning_pitcher_decision_present",
})
_BB_SCHEMA = "bb_v6_forward_shadow_evaluation_v1"
_BB_SETTLEMENT_SOURCE = "MLB_STATSAPI_BOX_SCORE"
_NRFI_SCHEMA = "nrfi_v6_forward_shadow_evaluation_v1"
_NRFI_SETTLEMENT_SOURCE = "MLB_STATSAPI_LIVE_FEED_LINESCORE_V2"


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def status(value: str, **extra: Any) -> dict[str, Any]:
    return {"status": value, **extra}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def valid_sha256(value: Any) -> bool:
    return isinstance(value, str) and _SHA256_RE.fullmatch(value) is not None


def failed_gate_names(report: dict[str, Any]) -> list[str]:
    gates = report.get("gates")
    if not isinstance(gates, dict) or not gates:
        return ["EVIDENCE_GATES_MISSING"]
    return sorted(
        str(name)
        for name, meta in gates.items()
        if not isinstance(meta, dict) or meta.get("pass") is not True
    )


def settlement_rows_valid(value: Any, *, source: str) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and all(isinstance(row, dict) and row.get("source") == source for row in value)
    )


def settlement_state(root: Path) -> dict[str, dict[str, Any]]:
    p=root/"SETTLEMENT"/"latest"/"report.json"
    if not p.is_file(): return {}
    r=load(p)
    if not isinstance(r, dict): return {}
    invariants=r.get("invariants") or {}
    proven=r.get("proven_markets")
    excluded=r.get("excluded_markets")
    valid=(
        r.get("schema_version")==_SETTLEMENT_SCHEMA
        and r.get("state")=="SETTLEMENT_SEMANTICS_PASS"
        and r.get("sportsbook_data_used") is False
        and r.get("source")==_SETTLEMENT_SOURCE
        and valid_sha256(r.get("facts_sha256"))
        and isinstance(invariants, dict)
        and _SETTLEMENT_INVARIANTS.issubset(invariants)
        and all(v is True for v in invariants.values())
        and isinstance(proven, list) and bool(proven)
        and all(isinstance(m, str) and m for m in proven)
        and len(proven)==len(set(proven))
        and isinstance(excluded, list)
        and all(isinstance(m, str) and m for m in excluded)
        and not set(proven).intersection(excluded)
        and str(r.get("game_pk") or "").strip()!=""
        and str(r.get("generated_at_utc") or "").strip()!=""
    )
    if not valid: return {}
    evidence={
        "evidence":str(p),
        "evidence_sha256":sha256_file(p),
        "game_pk":r.get("game_pk"),
        "facts_sha256":r.get("facts_sha256"),
        "schema_version":r.get("schema_version"),
        "source":r.get("source"),
        "generated_at_utc":r.get("generated_at_utc"),
    }
    out={}
    for market in proven:
        out[market]={"settlement_semantics":status("PASS",**evidence)}
    for market in excluded:
        out[market]={"settlement_semantics":status("PENDING",**evidence,reason="SPECIAL_SETTLEMENT_SEMANTICS_NOT_YET_PROVEN")}
    return out


def bb_state(root: Path) -> dict[str, Any] | None:
    p=root/"PITCHER_BB"/"latest"/"bb_v6_forward_shadow_report.json"
    s=root/"PITCHER_BB"/"latest"/"bb_v6_settlements.json"
    if not p.is_file(): return None
    r=load(p)
    if not isinstance(r, dict): return None
    settlements=load(s) if s.is_file() else []
    report_contract_ok=(
        r.get("schema_version")==_BB_SCHEMA
        and r.get("sportsbook_data_used") is False
    )
    settlement_ok=(
        report_contract_ok
        and ((r.get("gates") or {}).get("integrity") or {}).get("pass") is True
        and settlement_rows_valid(settlements,source=_BB_SETTLEMENT_SOURCE)
    )
    failed=failed_gate_names(r)
    eligible=((r.get("market") or {}).get("PITCHER_BB") or {}).get("eligible") is True
    forward_ok=report_contract_ok and eligible and r.get("state")=="MODEL_ELIGIBLE" and not failed
    evidence={"evidence":str(p),"evidence_sha256":sha256_file(p)}
    if s.is_file(): evidence["settlement_sha256"]=sha256_file(s)
    return {
        "settlement_semantics": status("PASS" if settlement_ok else "FAIL", **evidence),
        "forward_evidence": status("PASS" if forward_ok else "FAIL", **evidence, failed_gates=failed, state=r.get("state"), settled=r.get("settled_unique_pitchers")),
    }


def nrfi_state(root: Path) -> dict[str, Any] | None:
    p=root/"NRFI_YRFI"/"latest"/"nrfi_v6_forward_shadow_report.json"
    s=root/"NRFI_YRFI"/"latest"/"nrfi_v6_settlements.json"
    if not p.is_file(): return None
    r=load(p)
    if not isinstance(r, dict): return None
    settlements=load(s) if s.is_file() else []
    report_contract_ok=(
        r.get("schema_version")==_NRFI_SCHEMA
        and r.get("sportsbook_data_used") is False
    )
    settlement_ok=(
        report_contract_ok
        and ((r.get("gates") or {}).get("integrity") or {}).get("pass") is True
        and settlement_rows_valid(settlements,source=_NRFI_SETTLEMENT_SOURCE)
    )
    failed=failed_gate_names(r)
    evidence={"evidence":str(p),"evidence_sha256":sha256_file(p)}
    if s.is_file(): evidence["settlement_sha256"]=sha256_file(s)
    result={}
    for market in ("NRFI","YRFI"):
        eligible=((r.get("markets") or {}).get(market) or {}).get("eligible") is True
        forward_ok=report_contract_ok and eligible and r.get("state")=="MODEL_ELIGIBLE" and not failed
        result[market]={
            "settlement_semantics": status("PASS" if settlement_ok else "FAIL", **evidence),
            "forward_evidence": status("PASS" if forward_ok else "FAIL", **evidence, failed_gates=failed, state=r.get("state"), settled=r.get("settled_unique_games")),
        }
    return result


def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--registry", default="config/mlb_validation_evidence.json")
    ap.add_argument("--data-root", default=".data-branch/runtime/model-validation")
    ap.add_argument("--output", default="artifacts/mlb-validation/derived_status.json")
    args=ap.parse_args()

    reg=load(Path(args.registry)); markets=reg.get("markets") or {}
    if tuple(reg.get("required_gates") or ()) != REQUIRED_GATES:
        raise SystemExit("VALIDATION_GATE_CONTRACT_MISMATCH")
    root=Path(args.data_root)
    derived={m:{g:status("PENDING") for g in REQUIRED_GATES} for m in sorted(markets)}

    generic_settlement=settlement_state(root)
    for m,evidence in generic_settlement.items():
        if m in derived: derived[m].update(evidence)

    bb=bb_state(root)
    if bb and "PITCHER_BB" in derived:
        derived["PITCHER_BB"].update(bb)
    n=nrfi_state(root)
    if n:
        for m, evidence in n.items():
            if m in derived: derived[m].update(evidence)

    summary={
        "markets":len(derived),
        "gate_passes":sum(v["status"]=="PASS" for row in derived.values() for v in row.values()),
        "gate_failures":sum(v["status"]=="FAIL" for row in derived.values() for v in row.values()),
        "gate_pending":sum(v["status"]=="PENDING" for row in derived.values() for v in row.values()),
        "fully_validated_markets":sum(all(row[g]["status"]=="PASS" for g in REQUIRED_GATES) for row in derived.values()),
    }
    payload={"schema_version":1,"required_gates":list(REQUIRED_GATES),"markets":derived,"summary":summary}
    out=Path(args.output); out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(payload,indent=2,sort_keys=True)+"\n")
    print(json.dumps(summary,indent=2,sort_keys=True))
    return 0

if __name__=="__main__": raise SystemExit(main())
