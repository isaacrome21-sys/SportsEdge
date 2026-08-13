from sportsedge.full_model_status import (
    REQUIRED_FULL_MODEL_MARKETS,
    build_required_market_status,
)


def _legacy():
    return {
        "markets": {
            "MONEYLINE": {"eligible": True, "stage": "DEPLOYED", "reason": "legacy"},
            "RUN_LINE": {"eligible": True, "stage": "DEPLOYED", "reason": "legacy"},
            "TOTALS": {"eligible": True, "stage": "DEPLOYED", "reason": "legacy"},
            "NRFI": {"eligible": True, "stage": "DEPLOYED", "reason": "legacy"},
            "YRFI": {"eligible": True, "stage": "DEPLOYED", "reason": "legacy"},
            "HITS": {"eligible": False, "stage": "PRODUCTION_LOGIC_PASS", "reason": "attestation pending"},
            "TOTAL_BASES": {"eligible": False, "stage": "PRODUCTION_LOGIC_PASS", "reason": "attestation pending"},
            "PITCHER_BB": {"eligible": False, "stage": "VALIDATED_MATH", "reason": "residual gap"},
        }
    }


def _strict():
    return {
        "markets": {
            "MONEYLINE": {"eligible": False, "stage": "HOLDOUT_PASS_AWAITING_LIVE_PARITY", "reason": "parity required"},
            "RUN_LINE": {"eligible": False, "stage": "HOLDOUT_PASS_AWAITING_LIVE_PARITY", "reason": "parity required"},
            "TOTALS": {"eligible": False, "stage": "HOLDOUT_PASS_AWAITING_LIVE_PARITY", "reason": "parity required"},
            "NRFI": {"eligible": False, "stage": "HOLDOUT_FAILED", "reason": "z gate failed"},
            "YRFI": {"eligible": False, "stage": "HOLDOUT_FAILED", "reason": "z gate failed"},
        }
    }


def test_all_eight_markets_always_present():
    p = build_required_market_status(legacy_registry=_legacy(), strict_registry=_strict())
    assert p["complete_accounting"] is True
    assert tuple(x["market_family"] for x in p["markets"]) == REQUIRED_FULL_MODEL_MARKETS


def test_strict_registry_overrides_legacy_deployed_state():
    p = build_required_market_status(
        legacy_registry=_legacy(),
        strict_registry=_strict(),
        quote_rows=[{"market": "MONEYLINE"}],
    )
    ml = next(x for x in p["markets"] if x["market_family"] == "MONEYLINE")
    assert ml["state"] == "MODEL_NOT_ELIGIBLE"
    assert ml["validation_stage"] == "HOLDOUT_PASS_AWAITING_LIVE_PARITY"


def test_price_cannot_promote_ineligible_prop_model():
    p = build_required_market_status(
        legacy_registry=_legacy(),
        strict_registry=_strict(),
        quote_rows=[{"market": "HITS"}, {"market": "PITCHER_BB"}],
    )
    states = {x["market_family"]: x["state"] for x in p["markets"]}
    assert states["HITS"] == "MODEL_NOT_ELIGIBLE"
    assert states["PITCHER_BB"] == "MODEL_NOT_ELIGIBLE"


def test_eligible_model_without_quote_is_no_price():
    legacy = _legacy()
    legacy["markets"]["HITS"] = {"eligible": True, "stage": "DEPLOYED", "reason": "attested"}
    p = build_required_market_status(legacy_registry=legacy, strict_registry=_strict())
    hits = next(x for x in p["markets"] if x["market_family"] == "HITS")
    assert hits["state"] == "NO_PRICE"


def test_runtime_block_beats_price_for_eligible_market():
    strict = _strict()
    strict["markets"]["MONEYLINE"] = {"eligible": True, "stage": "DEPLOYED", "reason": "attested"}
    p = build_required_market_status(
        legacy_registry=_legacy(),
        strict_registry=strict,
        quote_rows=[{"market": "MONEYLINE"}],
        runtime_blocks={"MONEYLINE": "PROBABLE_PITCHER_UNRESOLVED"},
    )
    ml = next(x for x in p["markets"] if x["market_family"] == "MONEYLINE")
    assert ml["state"] == "BLOCKED"
    assert ml["reason"] == "PROBABLE_PITCHER_UNRESOLVED"


def test_eligible_priced_market_becomes_candidate_only():
    strict = _strict()
    strict["markets"]["TOTALS"] = {"eligible": True, "stage": "DEPLOYED", "reason": "attested"}
    p = build_required_market_status(
        legacy_registry=_legacy(),
        strict_registry=strict,
        quote_rows=[{"market": "TOTALS"}],
    )
    totals = next(x for x in p["markets"] if x["market_family"] == "TOTALS")
    assert totals["state"] == "PRICED_CANDIDATE"
    assert totals["quote_count"] == 1
