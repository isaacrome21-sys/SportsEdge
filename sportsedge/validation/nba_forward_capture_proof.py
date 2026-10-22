"""Read-only proof audit for an NBA full-board capture and optional ledger.

This MUST NOT mint forward units, Model_P, validated families or betting
authority. A canonical-JSON digest identifies parsed CONTENT, not raw source-file bytes
or sportsbook origin. Only the CLI, which reads actual bytes, can report a
separate raw file-byte digest. Missing or mismatched evidence fails visibly.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math

from sportsedge.nba_phone_prop_pricing import nba_prop_family_for_market

SCHEMA = "NBA_CAPTURE_LEDGER_STRUCTURAL_AUDIT_V1"
LEDGER_SCHEMA = "SPORTSEDGE_NBA_PROPS_FORWARD_ENTRY_LEDGER_V1"
QUOTE_TTL_SECONDS = 180


class NbaCaptureAuditError(ValueError):
    pass


def _rows(doc):
    rows = doc if isinstance(doc, list) else (
        doc.get("lines", doc.get("rows")) if isinstance(doc, dict) else None
    )
    if not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows):
        raise NbaCaptureAuditError("NBA_RAW_CAPTURE_ROWS_REQUIRED")
    return rows


def _sha(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"),
                              ensure_ascii=True).encode("utf-8")).hexdigest()


def _instant(value, code):
    try:
        d = value if isinstance(value, datetime) else datetime.fromisoformat(
            str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as e:
        raise NbaCaptureAuditError(code) from e
    if d.tzinfo is None or d.utcoffset() is None:
        raise NbaCaptureAuditError(code)
    return d.astimezone(timezone.utc)


def _number(value, code):
    if isinstance(value, bool):
        raise NbaCaptureAuditError(code)
    try:
        n = float(value)
    except (TypeError, ValueError) as e:
        raise NbaCaptureAuditError(code) from e
    if not math.isfinite(n):
        raise NbaCaptureAuditError(code)
    return n


def _capture_ts(r):
    return r.get("quote_captured_at") or r.get("captured_at")


def _event_ts(r):
    for k in ("event_start", "commence_time", "tipoff", "game_start", "start_time"):
        if r.get(k) is not None:
            return r[k]
    return None


def _key(r, family):
    return (str(r.get("capture_id") or ""), str(r.get("event_id") or ""),
            str(r.get("player_name") or r.get("label") or "").strip().casefold(),
            family, _number(r.get("line"), "NBA_CAPTURE_LINE_INVALID"))


def audit_capture(raw_doc, ledger_doc=None):
    """Return structural accounting; never verify caller-provided provenance.

    A full-ledger comparison requires every input quote row to be either
    rejected by its exact original index or covered by one unique paired
    entry. Capture-only audits do not claim a priced forward entry.
    """
    rows = _rows(raw_doc)
    in_scope = []
    groups = defaultdict(list)
    out_of_scope = 0
    books = Counter()
    for index, row in enumerate(rows):
        family = nba_prop_family_for_market(row.get("market"))
        if family is None:
            out_of_scope += 1
            continue
        in_scope.append(index)
        book = str(row.get("book") or "").strip().lower()
        books[book or "<missing>"] += 1
        # Structural pairing can be diagnosed only for identified/line-bound rows.
        if row.get("event_id") and row.get("capture_id") and (
            row.get("player_name") or row.get("label")
        ):
            try:
                groups[_key(row, family)].append((index, row))
            except NbaCaptureAuditError:
                pass
    complete = 0
    single = 0
    duplicate = 0
    for members in groups.values():
        sides = [str(r.get("side") or r.get("selection") or "").upper()
                 for _, r in members]
        if len(members) == 2 and set(sides) == {"OVER", "UNDER"}:
            complete += 1
        elif len(members) == 1:
            single += 1
        else:
            duplicate += 1
    result = {
        "schema": SCHEMA, "status": "CAPTURE_STRUCTURE_ONLY_NO_LEDGER",
        "canonical_raw_json_sha256": _sha(raw_doc),
        "total_raw_rows": len(rows), "in_scope_rows": len(in_scope),
        "out_of_scope_rows": out_of_scope,
        "complete_pair_shape_groups": complete,
        "one_sided_shape_groups": single,
        "ambiguous_or_duplicate_shape_groups": duplicate,
        "in_scope_books": dict(sorted(books.items())),
        "verified_market_admission": False,
        "verified_model_family_count": 0,
        "provider_quote_authentication": "NOT_ESTABLISHED_FROM_INPUT",
        "forward_validation_credit": "NONE",
        "play_authority": False,
    }
    if ledger_doc is None:
        return result
    if not isinstance(ledger_doc, dict) or ledger_doc.get("schema") != LEDGER_SCHEMA:
        raise NbaCaptureAuditError("NBA_LEDGER_SCHEMA_INVALID")
    ledger = ledger_doc.get("ledger")
    rejected = ledger_doc.get("rejected")
    counts = ledger_doc.get("accounting")
    if not isinstance(ledger, list) or not isinstance(rejected, list) or not isinstance(counts, dict):
        raise NbaCaptureAuditError("NBA_LEDGER_ACCOUNTING_MISSING")
    if not isinstance(counts.get("raw_rows"), int) or counts["raw_rows"] != len(rows):
        raise NbaCaptureAuditError("NBA_LEDGER_RAW_COUNT_MISMATCH")
    if counts.get("in_scope_rows") != len(in_scope) or counts.get("out_of_scope_rows") != out_of_scope:
        raise NbaCaptureAuditError("NBA_LEDGER_SCOPE_COUNT_MISMATCH")
    if len(rejected) + 2 * len(ledger) != len(rows):
        raise NbaCaptureAuditError("NBA_LEDGER_RAW_ROW_CONSERVATION_FAILED")
    reject_indices = []
    for item in rejected:
        if not isinstance(item, dict) or type(item.get("input_index")) is not int:
            raise NbaCaptureAuditError("NBA_LEDGER_REJECTED_INDEX_MISSING")
        reject_indices.append(item["input_index"])
    if len(set(reject_indices)) != len(reject_indices) or any(
        index < 0 or index >= len(rows) for index in reject_indices
    ):
        raise NbaCaptureAuditError("NBA_LEDGER_REJECTED_INDEX_INVALID")
    ids = set()
    remaining = set(range(len(rows))) - set(reject_indices)
    if counts.get("ledger_rows") != len(ledger) or counts.get("paired_quote_sets") != len(ledger):
        raise NbaCaptureAuditError("NBA_LEDGER_PAIR_COUNT_MISMATCH")
    if not counts.get("conservation_ok", False):
        raise NbaCaptureAuditError("NBA_LEDGER_SELF_REPORTED_CONSERVATION_FALSE")
    if _sha(ledger) != ledger_doc.get("ledger_sha256"):
        raise NbaCaptureAuditError("NBA_LEDGER_CONTENT_SHA_MISMATCH")
    for rec in ledger:
        if not isinstance(rec, dict):
            raise NbaCaptureAuditError("NBA_LEDGER_RECORD_OBJECT_REQUIRED")
        uid = str(rec.get("row_id") or "")
        if not uid or uid in ids:
            raise NbaCaptureAuditError("NBA_LEDGER_DUPLICATE_OR_MISSING_ROW_ID")
        ids.add(uid)
        if rec.get("research_only") is not True or any(
            rec.get(k) is not False for k in ("eligible", "promotable", "play_authority")
        ):
            raise NbaCaptureAuditError("NBA_LEDGER_FALSE_BETTING_AUTHORITY")
        if rec.get("label") != "PROSPECTIVE" or rec.get("sport") != "NBA":
            raise NbaCaptureAuditError("NBA_LEDGER_RECORDED_SCOPE_INVALID")
        model_p = rec.get("model_p")
        if not isinstance(model_p, dict):
            raise NbaCaptureAuditError("NBA_LEDGER_MODEL_DISTRIBUTION_MISSING")
        p_over = _number(model_p.get("OVER"), "NBA_LEDGER_MODEL_PROBABILITY_INVALID")
        p_under = _number(model_p.get("UNDER"), "NBA_LEDGER_MODEL_PROBABILITY_INVALID")
        if min(p_over, p_under) < 0 or max(p_over, p_under) > 1 or abs(p_over + p_under - 1) > 1e-9:
            raise NbaCaptureAuditError("NBA_LEDGER_MODEL_PROBABILITIES_INVALID")
        stamp = rec.get("engine_stamp")
        if not isinstance(stamp, dict) or rec.get("model_version") != stamp.get("engine_id"):
            raise NbaCaptureAuditError("NBA_LEDGER_MODEL_STAMP_MISMATCH")
        ct = _instant(rec.get("entry_captured_at"), "NBA_LEDGER_CAPTURE_INSTANT_REQUIRED")
        rt = _instant(rec.get("recorded_at"), "NBA_LEDGER_RECORDED_INSTANT_REQUIRED")
        tip = _instant(rec.get("event_start"), "NBA_LEDGER_EVENT_START_REQUIRED")
        if not ct <= rt < tip:
            raise NbaCaptureAuditError("NBA_LEDGER_NONCAUSAL_OR_POSTTIP")
        if (rt - ct).total_seconds() > QUOTE_TTL_SECONDS:
            raise NbaCaptureAuditError("NBA_LEDGER_QUOTE_STALE_AT_RECORDING")
        match = []
        for i in remaining:
            raw = rows[i]
            family = nba_prop_family_for_market(raw.get("market"))
            if family != rec.get("family"):
                continue
            if str(raw.get("capture_id") or "") != str(rec.get("capture_id") or "") or (
                str(raw.get("event_id") or "") != str(rec.get("event_id") or "")
            ):
                continue
            try:
                if _number(raw.get("line"), "NBA_CAPTURE_LINE_INVALID") != _number(rec.get("line"), "NBA_LEDGER_LINE_INVALID"):
                    continue
            except NbaCaptureAuditError:
                continue
            # Match player identity if named on both surfaces to avoid a
            # false join for two same-game players at the identical line.
            rn = str(raw.get("player_name") or raw.get("label") or "").strip().casefold()
            pn = str(rec.get("subject_name") or "").strip().casefold()
            if rn and pn and rn != pn:
                continue
            match.append(i)
        if len(match) != 2:
            raise NbaCaptureAuditError("NBA_LEDGER_PAIR_TO_CAPTURE_JOIN_AMBIGUOUS")
        matched = [rows[i] for i in match]
        sides = {str(x.get("side") or x.get("selection") or "").upper(): x for x in matched}
        if len(sides) != 2 or set(sides) != {"OVER", "UNDER"}:
            raise NbaCaptureAuditError("NBA_LEDGER_PAIR_SIDE_IDENTITY_INVALID")
        prices = rec.get("entry_prices")
        if not isinstance(prices, dict):
            raise NbaCaptureAuditError("NBA_LEDGER_PAIR_PRICES_REQUIRED")
        for side, raw in sides.items():
            if str(raw.get("book") or "").strip().lower() not in {"dk", "draftkings"}:
                raise NbaCaptureAuditError("NBA_LEDGER_PAIR_BOOK_NOT_DK")
            ts = _instant(_capture_ts(raw), "NBA_CAPTURE_TIMESTAMP_REQUIRED")
            st = _instant(_event_ts(raw), "NBA_CAPTURE_EVENT_START_REQUIRED")
            if ts != ct or st != tip:
                raise NbaCaptureAuditError("NBA_LEDGER_CAPTURE_TIMESTAMP_DRIFT")
            price = _number(raw.get("odds", raw.get("price")), "NBA_CAPTURE_ODDS_INVALID")
            if price != _number(prices.get(side), "NBA_LEDGER_ODDS_INVALID"):
                raise NbaCaptureAuditError("NBA_LEDGER_PRICE_DRIFT")
        remaining.difference_update(match)
    if remaining:
        raise NbaCaptureAuditError("NBA_LEDGER_UNACCOUNTED_CAPTURE_INDICES")
    result.update({
        "status": "LEDGER_STRUCTURALLY_RECONCILED_NOT_SOURCE_ATTESTED",
        "ledger_sha256": ledger_doc["ledger_sha256"],
        "ledger_rows_structurally_reconciled": len(ledger),
        "rejected_raw_rows_reconciled": len(rejected),
        "quote_ttl_seconds": QUOTE_TTL_SECONDS,
        "prospective_clock_authentication": "NOT_VERIFIED_BY_THIS_AUDIT",
        "verified_market_admission": False,
        "verified_model_family_count": 0,
        "forward_validation_credit": "NONE_UNTIL_INDEPENDENT_SOURCE_AND_FROZEN_EVALUATION",
        "play_authority": False,
    })
    return result
