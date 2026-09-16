#!/usr/bin/env python3
"""Read-only coverage audit for date-partitioned MLB replay evidence."""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import date
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY = ROOT / "config" / "mlb_v2_replay_coverage_policy.json"


def _day(value):
    return date.fromisoformat(str(value))


def selected_files(root: Path, policy: dict) -> list[Path]:
    start, end = _day(policy["audit_start"]), _day(policy["audit_end"])
    forbidden_start = _day(policy["forbidden_window_start"])
    forbidden_end = _day(policy["forbidden_window_end"])
    if not (end < forbidden_start or start > forbidden_end):
        raise ValueError("AUDIT_SCOPE_OVERLAPS_FORWARD_HOLDOUT")
    selected = []
    if not root.exists():
        return selected
    for folder in sorted(root.iterdir()):
        if not folder.is_dir():
            continue
        try:
            folder_day = _day(folder.name)
        except ValueError:
            continue
        if forbidden_start <= folder_day <= forbidden_end:
            continue
        if start <= folder_day <= end:
            path = folder / "pit_pairs.jsonl"
            if path.is_file():
                selected.append(path)
    return selected


def load_rows(paths):
    rows = []
    for path in paths:
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"ROW_NOT_OBJECT:{path}:{number}")
            rows.append(value)
    return rows


def _book(value):
    raw = str(value or "").strip().lower().replace(" ", "").replace("_", "")
    return {"draftkings":"draftkings", "fanduel":"fanduel", "betmgm":"betmgm", "mgm":"betmgm", "caesars":"caesars", "williamhillus":"caesars"}.get(raw, raw)


def _absence(row, policy):
    explicit = str(row.get("absence_class") or "")
    if explicit == "PINNACLE_NEVER_OFFERED" and row.get("provider_offer_evidence") is not True:
        return "UNATTRIBUTABLE_ABSENCE"
    if explicit == "ARCHIVE_MISSING" and row.get("collection_expected_evidence") is not True:
        return "UNATTRIBUTABLE_ABSENCE"
    if explicit in policy["absence_taxonomy"]:
        return explicit
    if row.get("decision_available") is False or row.get("close_available") is False:
        return policy["default_absence_class"]
    return None


def audit(rows, policy, files):
    measured = set(policy["measured_providers"])
    markets = list(policy["featured_core_markets"])
    minimum = int(policy["minimum_joint_n"])
    counts = defaultdict(lambda: {"rows":0,"decision":0,"close":0,"joint":0,"absence":defaultdict(int)})
    for row in rows:
        book = _book(row.get("bookmaker") or row.get("book"))
        market = str(row.get("market_family") or row.get("market") or row.get("market_id") or "")
        if book not in measured or market not in markets:
            continue
        c = counts[(book, market)]
        c["rows"] += 1
        decision = bool(row.get("decision_available", True))
        close = bool(row.get("close_available", True))
        c["decision"] += int(decision)
        c["close"] += int(close)
        c["joint"] += int(decision and close)
        klass = _absence(row, policy)
        if klass:
            c["absence"][klass] += 1
    market_joint = {}
    provider_market = []
    for market in markets:
        joint = 0
        for book in policy["measured_providers"]:
            c = counts[(book, market)]
            joint += c["joint"]
            provider_market.append({"provider":book,"market":market,"n_rows":c["rows"],"n_decision":c["decision"],"n_close":c["close"],"n_joint":c["joint"],"joint_coverage":c["joint"]/c["rows"] if c["rows"] else 0.0,"absence":dict(c["absence"])})
        market_joint[market] = {"n_joint":joint,"minimum_joint_n":minimum,"structurally_below_minimum_under_fixed_archive_window":joint < minimum}
    return {
        "schema_version":"SPORTSEDGE_MLB_V2_REPLAY_COVERAGE_AUDIT_V1",
        "status":"COMPLETE" if files else "BLOCKED_NO_DATE_PARTITIONED_INPUT",
        "scope":{"start":policy["audit_start"],"end":policy["audit_end"],"read_only":True,"forbidden_forward_holdout":[policy["forbidden_window_start"],policy["forbidden_window_end"]],"files_opened":[str(p) for p in files]},
        "known_preconditions":policy["known_preconditions"],
        "measured_providers":policy["measured_providers"],
        "primary_metric":"JOINT_DECISION_CLOSE_COVERAGE",
        "provider_market_coverage":provider_market,
        "featured_core_market_joint":market_joint,
        "absence_taxonomy":policy["absence_taxonomy"],
        "promotion_authority":False,"may_change_market_eligibility":False,"model_p_authority":False,"truth_gate_authority":False,"official_authority":False,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--require-input", action="store_true")
    args = ap.parse_args()
    policy = json.loads(args.policy.read_text(encoding="utf-8"))
    files = selected_files(args.root, policy)
    result = audit(load_rows(files), policy, files)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True)+"\n", encoding="utf-8")
    print(json.dumps({"status":result["status"],"files":len(files)}, sort_keys=True))
    return 2 if args.require_input and not files else 0


if __name__ == "__main__":
    raise SystemExit(main())
