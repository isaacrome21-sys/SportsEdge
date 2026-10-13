"""Provider/book evidence is orthogonal to DK offer, input and engine status."""
import copy

import pytest

from sportsedge.provider_book_evidence_audit import (
    ProviderBookAuditError, audit_provider_book_evidence,
)


def dk_report(*, status="OFFERED_ON_THIS_EVENT", shape="TWO_SIDED_OU"):
    offered = {
        "period": "FULL_GAME", "phase": "PREGAME", "offer_shape": shape,
        "settlement": "RULE_UNVERIFIED", "line_variant": "MAIN",
    }
    return {
        "schema": "DK_EVENT_COVERAGE_RECONCILIATION_V1",
        "sport": "MLB", "book": "draftkings", "event_id": "game-123",
        "observed_at_utc": "2026-10-13T12:00:00Z",
        "rows": [{
            "market": "BATTER_HITS", "availability": status,
            "registration_status": "REGISTERED", "engine_state": "NO_ENGINE",
            "offer_variants": [offered] if status == "OFFERED_ON_THIS_EVENT" else [],
        }],
    }


def provider(*, kind="API_CAPABILITY", status="SUPPORTED", name="the_odds_api"):
    value = {
        "provider": name, "book": "draftkings", "sport": "MLB",
        "market": "BATTER_HITS", "period": "FULL_GAME",
        "phase": "PREGAME", "offer_shape": "TWO_SIDED_OU",
        "settlement": "RULE_UNVERIFIED", "line_variant": "MAIN",
        "kind": kind, "status": status,
        "observed_at_utc": "2026-10-13T11:00:00Z",
        "source_url": "https://the-odds-api.com/docs/",
        "receipt_id": name + "-" + kind,
    }
    if kind == "EVENT_FEED_QUOTE":
        value["event_id"] = "game-123"
    return value


def result(records, **kwargs):
    return audit_provider_book_evidence(dk_report(**kwargs), records)


def observation(report):
    return report["rows"][0]["offer_variants"][0]["provider_observations"]


def test_documented_api_support_is_not_book_offer_or_pricing_authority():
    report = result([provider()])
    assert report["rows"][0]["dk_event_availability"] == "OFFERED_ON_THIS_EVENT"
    assert observation(report)[0]["effective_status"] == "SUPPORTED"
    assert observation(report)[0]["scope"] == "GLOBAL_PROVIDER_KEY"
    assert report["rows"][0]["engine_state"] == "NO_ENGINE"
    assert report["pricing_authority"] is False
    assert report["deployment_eligible"] is False
    assert report["model_validated"] is False


def test_api_unsupported_can_coexist_with_confirmed_dk_event_offer():
    report = result([provider(status="UNSUPPORTED")])
    assert report["rows"][0]["dk_event_availability"] == "OFFERED_ON_THIS_EVENT"
    assert observation(report)[0]["effective_status"] == "UNSUPPORTED"
    assert observation(report)[0]["independently_verified"] is False


def test_provider_quote_missing_never_claims_dk_absent():
    report = result([provider(kind="EVENT_FEED_QUOTE", status="QUOTE_MISSING")])
    assert report["rows"][0]["dk_event_availability"] == "OFFERED_ON_THIS_EVENT"
    assert observation(report)[0]["kind"] == "EVENT_FEED_QUOTE"
    assert observation(report)[0]["effective_status"] == "QUOTE_MISSING"


def test_provider_key_support_does_not_overrule_explicit_event_absence():
    report = result([provider()], status="NOT_OFFERED_ON_THIS_EVENT")
    assert report["rows"][0]["dk_event_availability"] == "NOT_OFFERED_ON_THIS_EVENT"
    assert report["rows"][0]["offer_variants"] == []
    assert report["unmatched_provider_observations"][0]["raw_status"] == "SUPPORTED"


def test_uninspected_book_market_stays_unverified_despite_api_support():
    report = result([provider()], status="NOT_VERIFIED_ON_THIS_EVENT")
    assert report["rows"][0]["dk_event_availability"] == "NOT_VERIFIED_ON_THIS_EVENT"
    assert report["unmatched_provider_observations"]


def test_ladder_is_not_conflated_with_two_sided_provider_contract():
    report = result([provider()], shape="LADDER_ONLY")
    assert not observation(report)
    assert len(report["unmatched_provider_observations"]) == 1
    assert report["pricing_authority"] is False


@pytest.mark.parametrize("field,wrong,reason", [
    ("book", "fanduel", "PROVIDER_BOOK_MISMATCH"),
    ("sport", "NFL", "PROVIDER_SPORT_MISMATCH"),
    ("event_id", "game-987", "PROVIDER_EVENT_ID_MISMATCH"),
])
def test_provider_identity_cannot_cross_book_sport_event(field, wrong, reason):
    record = provider(kind="EVENT_FEED_QUOTE", status="QUOTE_OBSERVED")
    record[field] = wrong
    with pytest.raises(ProviderBookAuditError, match=reason):
        result([record])


def test_general_api_capability_cannot_claim_event_identity():
    record = provider()
    record["event_id"] = "game-123"
    with pytest.raises(ProviderBookAuditError, match="GLOBAL_CAPABILITY_MUST_NOT_CLAIM_EVENT"):
        result([record])


@pytest.mark.parametrize("field,value", [
    ("period", "FIRST_HALF"), ("phase", "LIVE"),
    ("settlement", "TIE_PUSH_VERIFIED"), ("line_variant", "ALTERNATE"),
    ("offer_shape", "LADDER_ONLY"),
])
def test_mismatched_contract_dimension_cannot_cross_join(field, value):
    record = provider()
    record[field] = value
    report = result([record])
    assert not observation(report)
    assert len(report["unmatched_provider_observations"]) == 1


def test_two_providers_coexist_without_invented_combined_capability():
    second = provider(name="other_provider", status="UNSUPPORTED")
    report = result([provider(), second])
    statuses = {(o["provider"], o["raw_status"]) for o in observation(report)}
    assert statuses == {("THE_ODDS_API", "SUPPORTED"), ("OTHER_PROVIDER", "UNSUPPORTED")}


def test_later_provider_evidence_not_backdated_to_earlier_dk_board():
    record = provider()
    record["observed_at_utc"] = "2026-10-13T12:01:00+00:00"
    report = result([record])
    matched = observation(report)[0]
    assert matched["raw_status"] == "SUPPORTED"
    assert matched["effective_status"] == "NOT_VERIFIED_AT_DK_CAPTURE"
    assert matched["captured_after_dk_board"] is True


def test_simultaneous_conflicting_provider_assertions_fail_closed():
    first = provider(status="SUPPORTED")
    second = provider(status="UNSUPPORTED")
    second["receipt_id"] = "distinct-receipt"
    with pytest.raises(ProviderBookAuditError, match="PROVIDER_SIMULTANEOUS_CONFLICT"):
        result([first, second])


def test_duplicate_receipt_fails_even_if_sources_disagree():
    first = provider()
    second = provider(name="second_feed")
    second["receipt_id"] = first["receipt_id"]
    with pytest.raises(ProviderBookAuditError, match="PROVIDER_RECEIPT_DUPLICATE"):
        result([first, second])


def test_naive_and_invalid_clock_rejected():
    record = provider()
    record["observed_at_utc"] = "2026-10-13T11:00:00"
    with pytest.raises(ProviderBookAuditError, match="PROVIDER_OBSERVED_AT_TIMEZONE_REQUIRED"):
        result([record])
    bad_board = dk_report()
    bad_board["observed_at_utc"] = "sometime"
    with pytest.raises(ProviderBookAuditError, match="DK_OBSERVED_AT_INVALID"):
        audit_provider_book_evidence(bad_board, [])


def test_source_rejects_insecure_and_credential_embedded_urls():
    record = provider()
    record["source_url"] = "http://the-odds-api.com/"
    with pytest.raises(ProviderBookAuditError, match="EVIDENCE_HTTPS_URL_REQUIRED"):
        result([record])
    record["source_url"] = "https://user:password@the-odds-api.com/"
    with pytest.raises(ProviderBookAuditError, match="EVIDENCE_HTTPS_URL_REQUIRED"):
        result([record])


def test_caller_cannot_smuggle_authority_via_extra_fields():
    record = provider(kind="EVENT_FEED_QUOTE", status="QUOTE_OBSERVED")
    record.update({"deployment_eligible": True, "model_validated": True,
                   "can_derive_two_sided_no_vig": True})
    report = result([record])
    assert report["deployment_eligible"] is False
    assert report["model_validated"] is False
    assert report["pricing_authority"] is False
    assert "deployment_eligible" not in observation(report)[0]


def test_duplicate_dk_variant_and_report_family_rejected():
    board = dk_report()
    board["rows"][0]["offer_variants"].append(
        copy.deepcopy(board["rows"][0]["offer_variants"][0]))
    with pytest.raises(ProviderBookAuditError, match="DK_CONTRACT_VARIANT_DUPLICATE"):
        audit_provider_book_evidence(board, [])
    board = dk_report()
    board["rows"].append(copy.deepcopy(board["rows"][0]))
    with pytest.raises(ProviderBookAuditError, match="DK_FAMILY_DUPLICATE"):
        audit_provider_book_evidence(board, [])


def test_wrong_report_schema_and_invalid_availability_rejected():
    board = dk_report()
    board["schema"] = "UNTRUSTED"
    with pytest.raises(ProviderBookAuditError, match="DK_RECONCILIATION_SCHEMA_REQUIRED"):
        audit_provider_book_evidence(board, [])
    board = dk_report()
    board["rows"][0]["availability"] = "DK_GLOBALLY_NOT_OFFERED"
    with pytest.raises(ProviderBookAuditError, match="DK_AVAILABILITY_INVALID"):
        audit_provider_book_evidence(board, [])


def test_variant_cannot_override_parent_market_identity():
    board = dk_report()
    board["rows"][0]["offer_variants"][0]["market"] = "MONEYLINE"
    report = audit_provider_book_evidence(board, [provider()])
    assert report["rows"][0]["market"] == "BATTER_HITS"
    assert len(report["rows"][0]["offer_variants"][0]["provider_observations"]) == 1


def test_dk_schema_cannot_be_relabelled_as_other_sportsbook():
    board = dk_report()
    board["book"] = "fanduel"
    with pytest.raises(ProviderBookAuditError, match="DK_BOOK_REQUIRED"):
        audit_provider_book_evidence(board, [])
