"""Read-only, point-in-time provider-vs-book evidence reconciliation.

Consumes the caller-supplied DK_EVENT_COVERAGE_RECONCILIATION_V1 report,
without fetching any bookmaker or provider. "The Odds API supports this key",
"the provider returned a quote", and "DraftKings offered this contract" are
three distinct assertions. No one of them proves either of the other two.

All evidence is caller-supplied: this is an audit overlay, not a source receipt,
a price calculator, a validation result, or deployment authorization.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from urllib.parse import urlsplit

DK_SCHEMA = "DK_EVENT_COVERAGE_RECONCILIATION_V1"
CONTRACT_FIELDS = ("period", "phase", "offer_shape", "settlement", "line_variant")
KINDS = {
    "API_CAPABILITY": {"SUPPORTED", "UNSUPPORTED", "NOT_VERIFIED"},
    "EVENT_FEED_QUOTE": {"QUOTE_OBSERVED", "QUOTE_MISSING", "NOT_VERIFIED"},
}
DK_AVAILABILITY = {
    "OFFERED_ON_THIS_EVENT", "NOT_OFFERED_ON_THIS_EVENT",
    "NOT_VERIFIED_ON_THIS_EVENT",
}


class ProviderBookAuditError(ValueError):
    pass


def _text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ProviderBookAuditError(label + "_REQUIRED")
    return value.strip()


def _norm(value, label):
    return _text(value, label).upper().replace(" ", "_").replace("-", "_")


def _time(value, label):
    try:
        result = datetime.fromisoformat(_text(value, label).replace("Z", "+00:00"))
    except (ValueError, TypeError) as exc:
        raise ProviderBookAuditError(label + "_INVALID") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise ProviderBookAuditError(label + "_TIMEZONE_REQUIRED")
    return result.astimezone(timezone.utc)


def _url(value):
    value = _text(value, "EVIDENCE_URL")
    parts = urlsplit(value)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
        raise ProviderBookAuditError("EVIDENCE_HTTPS_URL_REQUIRED")
    return value


def _contract(item):
    if not isinstance(item, Mapping):
        raise ProviderBookAuditError("CONTRACT_MUST_BE_OBJECT")
    return (_norm(item.get("market"), "MARKET"),) + tuple(
        _norm(item.get(field), field.upper()) for field in CONTRACT_FIELDS
    )


def audit_provider_book_evidence(dk_report, provider_records):
    """Join evidence only on exact sport/book/event and offered contract variant.

    API_CAPABILITY: general documented provider/key capability, not an offer.
    EVENT_FEED_QUOTE: the provider's event quote observation, not a DK offer.
    No optional market-name-only, period-only, or book-only fuzzy matching.
    """
    if not isinstance(dk_report, Mapping) or dk_report.get("schema") != DK_SCHEMA:
        raise ProviderBookAuditError("DK_RECONCILIATION_SCHEMA_REQUIRED")
    sport = _norm(dk_report.get("sport"), "SPORT")
    book = _text(dk_report.get("book"), "BOOK").lower()
    if book != "draftkings":
        raise ProviderBookAuditError("DK_BOOK_REQUIRED")
    event_id = _text(dk_report.get("event_id"), "EVENT_ID")
    board_at = _time(dk_report.get("observed_at_utc"), "DK_OBSERVED_AT")
    dk_rows = dk_report.get("rows")
    if not isinstance(dk_rows, list):
        raise ProviderBookAuditError("DK_ROWS_REQUIRED")
    if not isinstance(provider_records, Sequence) or isinstance(
        provider_records, (str, bytes)
    ):
        raise ProviderBookAuditError("PROVIDER_RECORDS_MUST_BE_SEQUENCE")

    rows = []
    join_keys = set()
    seen_families = set()
    for row in dk_rows:
        if not isinstance(row, Mapping):
            raise ProviderBookAuditError("DK_ROW_MUST_BE_OBJECT")
        market = _norm(row.get("market"), "MARKET")
        if market in seen_families:
            raise ProviderBookAuditError("DK_FAMILY_DUPLICATE")
        seen_families.add(market)
        availability = _text(row.get("availability"), "DK_AVAILABILITY")
        if availability not in DK_AVAILABILITY:
            raise ProviderBookAuditError("DK_AVAILABILITY_INVALID")
        variants = row.get("offer_variants")
        if not isinstance(variants, list):
            raise ProviderBookAuditError("DK_VARIANTS_REQUIRED")
        if bool(variants) != (availability == "OFFERED_ON_THIS_EVENT"):
            raise ProviderBookAuditError("DK_AVAILABILITY_VARIANT_CONFLICT")
        item = {
            "market": market,
            "dk_event_availability": availability,
            "registration_status": row.get("registration_status"),
            "engine_state": row.get("engine_state"),
            "offer_variants": [],
        }
        for variant in variants:
            if not isinstance(variant, Mapping):
                raise ProviderBookAuditError("DK_VARIANT_MUST_BE_OBJECT")
            key = _contract({**variant, "market": market})
            if key in join_keys:
                raise ProviderBookAuditError("DK_CONTRACT_VARIANT_DUPLICATE")
            join_keys.add(key)
            item["offer_variants"].append({
                **{f: key[i + 1] for i, f in enumerate(CONTRACT_FIELDS)},
                "provider_observations": [],
                # A provider observation is not an independent DK receipt.
                "book_offer_source": "CALLER_SUPPLIED_DK_EVENT_REPORT",
                "no_vig_authority": False,
            })
        rows.append(item)

    normalized = []
    seen_receipts = set()
    seen_identity_time = set()
    for record in provider_records:
        if not isinstance(record, Mapping):
            raise ProviderBookAuditError("PROVIDER_RECORD_NOT_OBJECT")
        provider = _norm(record.get("provider"), "PROVIDER")
        if _text(record.get("book"), "PROVIDER_BOOK").lower() != book:
            raise ProviderBookAuditError("PROVIDER_BOOK_MISMATCH")
        if _norm(record.get("sport"), "PROVIDER_SPORT") != sport:
            raise ProviderBookAuditError("PROVIDER_SPORT_MISMATCH")
        kind = _norm(record.get("kind"), "PROVIDER_KIND")
        if kind not in KINDS:
            raise ProviderBookAuditError("PROVIDER_KIND_INVALID")
        status = _norm(record.get("status"), "PROVIDER_STATUS")
        if status not in KINDS[kind]:
            raise ProviderBookAuditError("PROVIDER_STATUS_INVALID")
        event = record.get("event_id")
        if kind == "EVENT_FEED_QUOTE":
            if _text(event, "PROVIDER_EVENT_ID") != event_id:
                raise ProviderBookAuditError("PROVIDER_EVENT_ID_MISMATCH")
        elif event is not None:
            raise ProviderBookAuditError("GLOBAL_CAPABILITY_MUST_NOT_CLAIM_EVENT")
        observed = _time(record.get("observed_at_utc"), "PROVIDER_OBSERVED_AT")
        receipt = _text(record.get("receipt_id"), "PROVIDER_RECEIPT")
        if receipt in seen_receipts:
            raise ProviderBookAuditError("PROVIDER_RECEIPT_DUPLICATE")
        seen_receipts.add(receipt)
        key = _contract(record)
        identity_time = (provider, kind, key, observed)
        if identity_time in seen_identity_time:
            raise ProviderBookAuditError("PROVIDER_SIMULTANEOUS_CONFLICT")
        seen_identity_time.add(identity_time)
        normalized.append({
            "provider": provider, "kind": kind,
            "raw_status": status,
            "effective_status": (
                status if observed <= board_at else "NOT_VERIFIED_AT_DK_CAPTURE"
            ),
            "captured_after_dk_board": observed > board_at,
            "market": key[0],
            **{f: key[i + 1] for i, f in enumerate(CONTRACT_FIELDS)},
            "source_url": _url(record.get("source_url")),
            "receipt_id": receipt,
            "observed_at_utc": observed.isoformat(),
            "scope": (
                "GLOBAL_PROVIDER_KEY" if kind == "API_CAPABILITY"
                else "EXACT_EVENT_FEED"
            ),
            "independently_verified": False,
        })

    matched = set()
    for row in rows:
        for variant in row["offer_variants"]:
            key = (row["market"],) + tuple(variant[f] for f in CONTRACT_FIELDS)
            for i, record in enumerate(normalized):
                other = (record["market"],) + tuple(
                    record[f] for f in CONTRACT_FIELDS
                )
                if other == key:
                    variant["provider_observations"].append(record)
                    matched.add(i)
            variant["provider_observations"].sort(
                key=lambda x: (x["provider"], x["kind"], x["observed_at_utc"])
            )

    return {
        "schema": "PROVIDER_VS_BOOK_EVIDENCE_AUDIT_V1",
        "sport": sport, "book": book, "event_id": event_id,
        "dk_observed_at_utc": board_at.isoformat(),
        "rows": rows,
        "unmatched_provider_observations": [
            value for i, value in enumerate(normalized) if i not in matched
        ],
        "provider_observation_count": len(normalized),
        "provider_evidence_caller_supplied": True,
        "catalog_globally_verified": False,
        "pricing_authority": False,
        "model_validated": False,
        "deployment_eligible": False,
        "notes": [
            "Provider key support is not proof of DraftKings event offering.",
            "Missing API quote is not proof the sportsbook did not offer a market.",
            "Evidence captured after the DK board cannot be used as-of that board.",
            "Exact variant identity includes period, phase, offer shape, settlement and line variant.",
        ],
    }
