#!/usr/bin/env python3
from datetime import datetime, timedelta, timezone

from orchestrator_v0_1 import OrchestrationError, PriceRecord, run_candidate

UTC = timezone.utc
T0 = datetime(2026, 8, 10, 18, 18, 25, tzinfo=UTC)


def price():
    return PriceRecord(
        source_id="dk_public_20260810T181825Z_bos_ml",
        provider="DRAFTKINGS",
        source_surface="PUBLIC_SPORTSBOOK_PAGE",
        game_id="BOS_TOR_2026-08-10",
        market="moneyline",
        selection="BOS",
        line=None,
        american_odds=-148,
        retrieved_at=T0,
        ttl_seconds=300,
        execution_equivalence="UNATTESTED",
    )


def engine(mi):
    return {"model_p": 0.65, "model_input_hash": "abc123", "source_kind": "SPORTSEDGE_MODEL"}


def mc(mi, paths):
    return {"status": "PASS", "paths": paths}


def raises(fn, contains):
    try:
        fn()
    except OrchestrationError as e:
        assert contains in str(e), (contains, str(e))
        return
    raise AssertionError(f"expected {contains}")


# Happy path: fresh at ingress AND finalization.
r = run_candidate(
    price=price(), model_input={"build_hash": "abc123"}, deployment_status={"status": "PASS"},
    run_started_at=T0 + timedelta(seconds=30), decision_time=T0 + timedelta(seconds=290),
    engine_fn=engine, mc_fn=mc, mc_paths=25_000,
)
assert r.model_status == "PASS"
assert r.bet_status == "PASS"
assert r.mc_paths == 25_000
assert r.price_age_ingress_seconds == 30
assert r.price_age_final_seconds == 290
assert r.run_hash

# Price can be fresh at ingestion yet expire while engine/MC runs: must block.
raises(lambda: run_candidate(
    price=price(), model_input={}, deployment_status={"status": "PASS"},
    run_started_at=T0 + timedelta(seconds=250), decision_time=T0 + timedelta(seconds=301),
    engine_fn=engine, mc_fn=mc,
), "STALE_PRICE:FINALIZATION")

# Already stale at ingestion: must block before engine work.
raises(lambda: run_candidate(
    price=price(), model_input={}, deployment_status={"status": "PASS"},
    run_started_at=T0 + timedelta(seconds=301), decision_time=T0 + timedelta(seconds=302),
    engine_fn=engine, mc_fn=mc,
), "STALE_PRICE:INGRESS")

# Deployment gate remains authoritative.
raises(lambda: run_candidate(
    price=price(), model_input={}, deployment_status={"status": "BLOCKED_DEPLOYMENT_PARITY"},
    run_started_at=T0 + timedelta(seconds=1), decision_time=T0 + timedelta(seconds=2),
    engine_fn=engine, mc_fn=mc,
), "DEPLOYMENT_NOT_AUTHORIZED")

# Sportsbook / consensus probability can never be relabeled Model_P.
def bad_engine(mi):
    return {"model_p": 0.99, "model_input_hash": "x", "source_kind": "SPORTSBOOK_PROBABILITY"}

raises(lambda: run_candidate(
    price=price(), model_input={}, deployment_status={"status": "PASS"},
    run_started_at=T0 + timedelta(seconds=1), decision_time=T0 + timedelta(seconds=2),
    engine_fn=bad_engine, mc_fn=mc,
), "MODEL_P_SOURCE_BANNED")

# MC attestation must prove the requested path count.
def bad_mc(mi, paths):
    return {"status": "PASS", "paths": paths - 1}

raises(lambda: run_candidate(
    price=price(), model_input={}, deployment_status={"status": "PASS"},
    run_started_at=T0 + timedelta(seconds=1), decision_time=T0 + timedelta(seconds=2),
    engine_fn=engine, mc_fn=bad_mc, mc_paths=25_000,
), "MC_ATTESTATION_INVALID")

print("orchestrator v0.1 regression tests PASS")
