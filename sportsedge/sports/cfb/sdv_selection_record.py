"""Verify archived selection and exact serving fit without re-running evaluation."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

RECORD = "config/cfb_sdv_completed_selection_v1.json"


def verify_completed_selection(root: Path = Path(".")) -> dict:
    record = json.loads((root / RECORD).read_text())
    if record.get("schema") != "CFB_SDV_COMPLETED_SELECTION_V1" or record.get("canonical_cfbd_freeze_activated") is not False:
        raise ValueError("CFB_SDV_COMPLETED_SELECTION_SCOPE_INVALID")
    if record.get("attempts_consumed") != 4 or record.get("evaluation_performed") is not True:
        raise ValueError("CFB_SDV_COMPLETED_SELECTION_ACCOUNTING_INVALID")
    payloads = {}
    for kind in ("result", "selected_fit"):
        raw = (root / record[kind + "_path"]).read_bytes()
        if hashlib.sha256(raw).hexdigest() != record[kind + "_file_sha256"]:
            raise ValueError("CFB_SDV_COMPLETED_SELECTION_HASH_MISMATCH:" + kind)
        payloads[kind] = json.loads(raw)
    result, fit = payloads["result"], payloads["selected_fit"]
    prereg = json.loads((root / "config/cfb_sportsdataverse_candidate_prereg_v1.json").read_text())
    if prereg["governance"]["attempts_consumed"] != 4 or prereg["governance"]["evaluation_performed"] is not True:
        raise ValueError("CFB_SDV_PREREG_ACCOUNTING_STALE")
    order = prereg["candidate_selection_policy"]["family_order"]
    winner = min(order, key=lambda name: (result["observed"][name]["selection_metric"], order.index(name)))
    if not (winner == result["selected_family"] == record["selected_family"] == fit["family"]):
        raise ValueError("CFB_SDV_COMPLETED_SELECTION_WINNER_MISMATCH")
    latest = max(result["observed"][winner]["folds"], key=lambda fold: fold["season"])
    if not (latest["alpha"] == fit["ridge_alpha"] == record["selected_alpha"]):
        raise ValueError("CFB_SDV_COMPLETED_SELECTION_ALPHA_MISMATCH")
    if fit["bakeoff_run"] != record["workflow_run_id"]:
        raise ValueError("CFB_SDV_COMPLETED_SELECTION_RUN_MISMATCH")
    if result["governance"]["attempts_consumed"] != 4:
        raise ValueError("CFB_SDV_COMPLETED_RESULT_ACCOUNTING_INVALID")
    for payload in (record, fit, result["authority"]):
        if payload.get("promotion_authority") is not False or payload.get("official_authority") is not False:
            raise ValueError("CFB_SDV_COMPLETED_SELECTION_AUTHORITY_INVALID")
    return record
