"""Check E: offline per-cell/per-window coverage, never source admission.

Bars: #2447 comments 6308060982 and 6315337229: >=90% per sampled
window; unsampled cells explicitly NO_DATA. Expected units and cell universe
must be frozen independently before the provider pull, not derived from it.
Unit IDs identify the same fixture/selection granularity on both sides.
"""
from decimal import Decimal
import re

VERSION = "ODDSPAPI_CHECK_E_DRYRUN_V1"


class CheckERefusal(ValueError):
    pass


def _keys(obj, expected):
    if not isinstance(obj, dict) or set(obj) != set(expected.split()):
        raise CheckERefusal("E_SCHEMA_INVALID")


def _id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9:_.-]{1,128}", value):
        raise CheckERefusal("E_ID_INVALID")
    return value


def _ids(value):
    if not isinstance(value, list):
        raise CheckERefusal("E_UNIT_LIST_REQUIRED")
    cleaned = {_id(x) for x in value}
    if len(cleaned) != len(value):
        raise CheckERefusal("E_DUPLICATE_UNIT")
    return cleaned


def evaluate_check_e(payload):
    _keys(payload, "version cohort_manifest_sha256 cells")
    if payload["version"] != VERSION:
        raise CheckERefusal("E_VERSION_INVALID")
    digest = payload["cohort_manifest_sha256"]
    if not isinstance(digest, str) or not re.fullmatch(r"[a-fA-F0-9]{64}", digest):
        raise CheckERefusal("E_COHORT_HASH_REQUIRED")
    if not isinstance(payload["cells"], list) or not payload["cells"]:
        raise CheckERefusal("E_DECLARED_CELL_UNIVERSE_REQUIRED")
    cells, seen = [], set()
    for cell in payload["cells"]:
        _keys(cell, "sport market bookmaker windows")
        key = tuple(_id(cell[k]) for k in ("sport", "market", "bookmaker"))
        if key in seen:
            raise CheckERefusal("E_DUPLICATE_CELL")
        seen.add(key)
        if not isinstance(cell["windows"], list):
            raise CheckERefusal("E_WINDOWS_REQUIRED")
        windows, window_ids = [], set()
        for window in cell["windows"]:
            _keys(window, "window_id expected_unit_ids observed_unit_ids")
            wid = _id(window["window_id"])
            if wid in window_ids:
                raise CheckERefusal("E_DUPLICATE_WINDOW")
            window_ids.add(wid)
            expected = _ids(window["expected_unit_ids"])
            observed = _ids(window["observed_unit_ids"])
            if observed - expected:
                raise CheckERefusal("E_OBSERVED_UNIT_OUTSIDE_FROZEN_COHORT")
            rate = Decimal(len(observed)) / len(expected) if expected else None
            status = ("NO_DATA" if rate is None else "PASS_NUMERIC_ONLY"
                      if rate >= Decimal("0.90") else "FAIL")
            windows.append({"window_id": wid, "status": status,
                            "expected": len(expected), "observed": len(observed),
                            "missing_unit_ids": sorted(expected - observed),
                            "coverage": str(rate) if rate is not None else None})
        status = ("FAIL" if any(w["status"] == "FAIL" for w in windows)
                  else "NO_DATA" if not windows or any(
                      w["status"] == "NO_DATA" for w in windows)
                  else "PASS_NUMERIC_ONLY")
        cells.append({"sport": key[0], "market": key[1], "bookmaker": key[2],
                      "status": status, "windows": windows,
                      "numeric_e_bar_met_UNVERIFIED": status == "PASS_NUMERIC_ONLY"})
    return {"version": VERSION, "status": "NOT_ADMITTED_E_DRYRUN",
            "required_coverage_per_sampled_window": "0.90", "cells": cells,
            "cohort_manifest_sha256_shape_only": digest.lower(),
            "cohort_and_source_authenticated": False,
            "admission": "NOT_ADMITTED", "eligible": False, "play_authority": False}
