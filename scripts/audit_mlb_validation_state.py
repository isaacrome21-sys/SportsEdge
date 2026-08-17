#!/usr/bin/env python3
"""Derive MLB market validation state from durable evidence without promoting by assertion."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

REQUIRED_GATES = (
    "historical_point_in_time",
    "untouched_holdout",
    "calibration",
    "settlement_semantics",
    "forward_evidence",
    "production_parity",
)


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def status(value: str, **extra: Any) -> dict[str, Any]:
    return {"status": value, **extra}


def failed_gate_names(report: dict[str, Any]) -> list[str]:
    out=[]
    for name, meta in (report.get("gates") or {}).items():
        if isinstance(meta, dict) and meta.get("pass") is False:
            out.append(str(name))
    return sorted(out)


def settlement_state(root: Path) -> dict[str, dict[str, Any]]:
    p=root/"SETTLEMENT"/"latest"/"report.json"
    if not p.is_file(): return {}
    r=load(p)
    invariants=r.get("invariants") or {}
    valid=(
        r.get("state")=="SETTLEMENT_SEMANTICS_PASS"
        and r.get("sportsbook_data_used") is False
        and r.get("source")=="MLB_STATSAPI_BOX_SCORE_AND_LIVE_FEED"
        and bool(r.get("facts_sha256"))
        and bool(invariants)
        and all(v is True for v in invariants.values())
    )
    if not valid: return {}
    out={}
    for market in r.get("proven_markets") or []:
        out[str(market)]={"settlement_semantics":status("PASS",evidence=str(p),game_pk=r.get("game_pk"),facts_sha256=r.get("facts_sha256"))}
    for market in r.get("excluded_markets") or []:
        out[str(market)]={"settlement_semantics":status("PENDING",evidence=str(p),reason="SPECIAL_SETTLEMENT_SEMANTICS_NOT_YET_PROVEN")}
    return out


def bb_state(root: Path) -> dict[str, Any] | None:
    p=root/"PITCHER_BB"/"latest"/"bb_v6_forward_shadow_report.json"
    s=root/"PITCHER_BB"/"latest"/"bb_v6_settlements.json"
    if not p.is_file(): return None
    r=load(p)
    settlements=load(s) if s.is_file() else []
    settlement_ok=(
        r.get("sportsbook_data_used") is False
        and ((r.get("gates") or {}).get("integrity") or {}).get("pass") is True
        and bool(settlements)
        and all(x.get("source")=="MLB_STATSAPI_BOX_SCORE" for x in settlements if isinstance(x,dict))
    )
    eligible=bool(((r.get("market") or {}).get("PITCHER_BB") or {}).get("eligible"))
    return {
        "settlement_semantics": status("PASS" if settlement_ok else "FAIL", evidence=str(p)),
        "forward_evidence": status("PASS" if eligible else "FAIL", evidence=str(p), failed_gates=failed_gate_names(r), state=r.get("state"), settled=r.get("settled_unique_pitchers")),
    }


def nrfi_state(root: Path) -> dict[str, Any] | None:
    p=root/"NRFI_YRFI"/"latest"/"nrfi_v6_forward_shadow_report.json"
    s=root/"NRFI_YRFI"/"latest"/"nrfi_v6_settlements.json"
    if not p.is_file(): return None
    r=load(p)
    settlements=load(s) if s.is_file() else []
    settlement_ok=(
        r.get("sportsbook_data_used") is False
        and ((r.get("gates") or {}).get("integrity") or {}).get("pass") is True
        and bool(settlements)
        and all(x.get("source")=="MLB_STATSAPI_LIVE_FEED_LINESCORE_V2" for x in settlements if isinstance(x,dict))
    )
    result={}
    for market in ("NRFI","YRFI"):
        eligible=bool(((r.get("markets") or {}).get(market) or {}).get("eligible"))
        result[market]={
            "settlement_semantics": status("PASS" if settlement_ok else "FAIL", evidence=str(p)),
            "forward_evidence": status("PASS" if eligible else "FAIL", evidence=str(p), failed_gates=failed_gate_names(r), state=r.get("state"), settled=r.get("settled_unique_games")),
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
