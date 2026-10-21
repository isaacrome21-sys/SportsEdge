"""Offline Check D sections 5.2–5.4; supplements merged D 5.1, never admits.

5.2: >=95% of all declared closes in [actual start - 6h, actual start).
5.3: a single declared timezone offset difference across ten tightest
identity-matched Check A pairs. Reports explicit offset evidence only; never
guesses a zone for naive timestamps or shifts quotes to force agreement.
5.4: impossible-quote scan on the entire supplied provider quote cohort.
Source completeness, true timestamp semantics and anchors remain external
authentication requirements; numerical consistency alone cannot prove them.
"""
from datetime import datetime, timedelta
from decimal import Decimal

from .oddspapi_numeric_admission_ad import (
    NumericAdmissionRefusal, _assess_d, _id, _sha, _stamp, _validate_quote)

VERSION = "ODDSPAPI_CHECK_D_SECTIONS_DRYRUN_V1"


class CheckDRefusal(ValueError):
    pass


def _keys(obj, fields):
    if not isinstance(obj, dict) or set(obj) != set(fields.split()):
        raise CheckDRefusal("D_SECTIONS_SCHEMA_INVALID")


def _anchor(raw, event):
    _keys(raw, "canonical_event_id actual_first_play_utc official_source_sha256")
    if raw["canonical_event_id"] != event:
        raise CheckDRefusal("D_ACTUAL_START_EVENT_MISMATCH")
    _sha(raw["official_source_sha256"], "D_ACTUAL_START")
    return _stamp(raw["actual_first_play_utc"], "D_ACTUAL_START")


def _section_52(closes):
    rows, seen = [], set()
    if not isinstance(closes, list):
        raise CheckDRefusal("D_CLOSE_LIST_REQUIRED")
    for close in closes:
        # Reuse exact #2446 close schema and D5.1 structural checks.
        result = _assess_d(close)
        key = (close["canonical_event_id"], close["market_id"], close["bookmaker"],
               _stamp(close["provider_created_at_utc"], "D_CLOSE"))
        if key in seen:
            raise CheckDRefusal("D_DUPLICATE_CLOSE_UNIT")
        seen.add(key)
        in_window = False
        reason = result["reason"]
        if result["status"] == "PASS_NUMERIC_ONLY":
            first = _anchor(close["actual_first_play"], close["canonical_event_id"])
            in_window = first - timedelta(hours=6) <= key[-1] < first
            if not in_window:
                reason = "D_CLOSE_MORE_THAN_SIX_HOURS_BEFORE_START"
        rows.append({"candidate_sha256": close["candidate_sha256"],
                     "in_window": in_window, "reason": reason})
    count = sum(r["in_window"] for r in rows)
    rate = Decimal(count) / len(rows) if rows else None
    return {"status": "NO_DATA" if rate is None else "CALCULATED",
            "required_rate": "0.95", "denominator": len(rows), "in_window": count,
            "observed_rate": str(rate) if rate is not None else None,
            "numeric_bar_met_UNVERIFIED": rate is not None and rate >= Decimal("0.95"),
            "rows": rows}


def _section_53(samples):
    if not isinstance(samples, list):
        raise CheckDRefusal("D_A_SAMPLE_LIST_REQUIRED")
    pairs, unmatched, seen_ids, seen_pairs = [], [], set(), set()
    for sample in samples:
        _keys(sample, "sample_id dk oddspapi")
        sid = _id(sample["sample_id"], "D_A_SAMPLE")
        if sid in seen_ids:
            raise CheckDRefusal("D_DUPLICATE_A_SAMPLE_ID")
        seen_ids.add(sid)
        if sample["dk"] is None or sample["oddspapi"] is None:
            unmatched.append(sid)
            continue
        dk = _validate_quote(sample["dk"], papi=False)
        papi = _validate_quote(sample["oddspapi"], papi=True)
        identity = tuple(dk[k] for k in ("event", "market", "side", "bookmaker", "line"))
        if identity != tuple(papi[k] for k in ("event", "market", "side", "bookmaker", "line")):
            unmatched.append(sid)
            continue
        key = identity + (dk["time"], papi["time"])
        if key in seen_pairs:
            raise CheckDRefusal("D_DUPLICATE_A_PAIR")
        seen_pairs.add(key)
        gap = abs((dk["time"] - papi["time"]).total_seconds())
        if gap > 1800:
            unmatched.append(sid)
            continue
        def offset(q):
            return datetime.fromisoformat(q["captured_at_utc"].replace("Z", "+00:00")).utcoffset().total_seconds()
        delta = offset(sample["oddspapi"]) - offset(sample["dk"])
        pairs.append({"sample_id": sid, "gap_seconds": gap,
                      "declared_offset_difference_seconds": delta})
    # Stable tie rule fixed in code, never selected after inspecting results.
    tightest = sorted(pairs, key=lambda x: (x["gap_seconds"], x["sample_id"]))[:10]
    offsets = {p["declared_offset_difference_seconds"] for p in tightest}
    enough = len(tightest) == 10
    return {"status": "CALCULATED" if enough else "INSUFFICIENT_PAIRS",
            "required_pairs": 10, "matched_pairs_available": len(pairs),
            "tightest_pairs": tightest, "unmatched_sample_ids": unmatched,
            "single_declared_offset_difference_seconds": next(iter(offsets)) if enough and len(offsets) == 1 else None,
            "numeric_bar_met_UNVERIFIED": enough and len(offsets) == 1,
            "true_provider_timezone_independently_authenticated": False,
            "semantics": "DECLARED_ISO_OFFSET_CONSISTENCY_ONLY_NO_INFERRED_SHIFT"}


def _section_54(scan):
    if not isinstance(scan, list):
        raise CheckDRefusal("D_QUOTE_SCAN_LIST_REQUIRED")
    results, seen, quotes_seen = [], set(), {}
    for item in scan:
        _keys(item, "scan_id quote retrieved_at_utc actual_first_play claimed_pregame")
        sid = _id(item["scan_id"], "D_SCAN")
        if sid in seen:
            raise CheckDRefusal("D_DUPLICATE_SCAN_ID")
        seen.add(sid)
        if type(item["claimed_pregame"]) is not bool:
            raise CheckDRefusal("D_PREGAME_BOOLEAN_REQUIRED")
        reasons = []
        try:
            q = _validate_quote(item["quote"], papi=True)
            quote_key = tuple(q[k] for k in ("event", "market", "side", "bookmaker", "line", "time"))
            raw_price = Decimal(str(item["quote"]["decimal_price"]))
            if quote_key in quotes_seen and quotes_seen[quote_key] != raw_price:
                reasons.append("D_CONFLICTING_PRICE_SAME_QUOTE_IDENTITY_TIME")
            quotes_seen[quote_key] = raw_price
            retrieved = _stamp(item["retrieved_at_utc"], "D_RETRIEVED")
            if q["time"] > retrieved:
                reasons.append("D_QUOTE_AFTER_RETRIEVAL")
            if item["claimed_pregame"]:
                first = _anchor(item["actual_first_play"], q["event"])
                if q["time"] >= first:
                    reasons.append("D_POST_START_QUOTE_CLAIMED_PREGAME")
        except (NumericAdmissionRefusal, CheckDRefusal) as exc:
            # Malformed quotes count as failed observations, never disappear.
            reasons.append(str(exc))
        results.append({"scan_id": sid, "pass_numeric_only": not reasons,
                        "reasons": reasons})
    return {"status": "CALCULATED" if results else "NO_DATA",
            "scanned": len(results), "failed": sum(not r["pass_numeric_only"] for r in results),
            "numeric_bar_met_UNVERIFIED": bool(results) and all(r["pass_numeric_only"] for r in results),
            "rows": results,
            "scope": "QUOTE_SCHEMA_FINITE_PRICE_LINE_TIME_BOOK_SIDE_AND_PREGAME_CHRONOLOGY"}


def evaluate_check_d_sections(payload):
    _keys(payload, "version cohort_manifest_sha256 close_candidates dk_samples quote_scan")
    if payload["version"] != VERSION:
        raise CheckDRefusal("D_SECTIONS_VERSION_INVALID")
    digest = _sha(payload["cohort_manifest_sha256"], "D_COHORT")
    sections = {"5.2": _section_52(payload["close_candidates"]),
                "5.3": _section_53(payload["dk_samples"]),
                "5.4": _section_54(payload["quote_scan"])}
    return {"version": VERSION, "status": "NOT_ADMITTED_D_SECTIONS_DRYRUN",
            "sections": sections, "cohort_manifest_sha256_shape_only": digest,
            "numeric_sections_met_UNVERIFIED": all(s["numeric_bar_met_UNVERIFIED"] for s in sections.values()),
            "requires_separate_D_5_1": True, "source_and_cohort_authenticated": False,
            "admission": "NOT_ADMITTED", "eligible": False, "play_authority": False}
