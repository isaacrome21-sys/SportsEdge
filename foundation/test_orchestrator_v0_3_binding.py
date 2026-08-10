#!/usr/bin/env python3
from datetime import datetime, timedelta, timezone
from orchestrator_v0_3 import OrchestrationError, PriceRecord, run_candidate

UTC = timezone.utc
T0 = datetime(2026, 8, 10, 18, 18, 25, tzinfo=UTC)

MI = {
    "market": "total_bases",
    "entity_id": "player-1",
    "game_id": "game-1",
    "build_hash": "abc123",
}
DEPLOY = {"market": "total_bases", "status": "PASS"}


def price(**kw):
    base = dict(
        source_id="dk-1",
        provider="DRAFTKINGS",
        source_surface="PUBLIC_SPORTSBOOK_PAGE",
        game_id="game-1",
        market="total_bases",
        selection="Player 1 over 1.5 total bases",
        line=1.5,
        american_odds=120,
        retrieved_at=T0,
        ttl_seconds=300,
        execution_equivalence="UNATTESTED_VS_AUTHENTICATED_BETSLIP_FEED",
        entity_id="player-1",
        side="over",
    )
    base.update(kw)
    return PriceRecord(**base)


def engine(mi):
    return {
        "model_p": 0.60,
        "model_input_hash": mi["build_hash"],
        "source_kind": "SPORTSEDGE_MC",
        "engine_code_version": "tb-live-v0.1",
        "mc_status": "PASS",
        "mc_paths": 25_000,
        "line": 1.5,
        "side": "over",
    }


def raises(fn, text):
    try:
        fn()
    except OrchestrationError as e:
        assert text in str(e), (text, str(e))
        return
    raise AssertionError(f"expected {text}")


def run(p=None, mi=None, dep=None, eng=engine, decision_seconds=2):
    return run_candidate(
        price=p or price(),
        model_input=mi or MI,
        deployment_status=dep or DEPLOY,
        run_started_at=T0 + timedelta(seconds=1),
        decision_time=T0 + timedelta(seconds=decision_seconds),
        engine_fn=eng,
        mc_paths=25_000,
        require_mc=True,
    )


# Happy path: all authoritative objects refer to exactly one candidate.
r = run()
assert r.bet_status == "PASS"
assert r.game_id == "game-1" and r.entity_id == "player-1"
assert r.line == 1.5 and r.side == "over"
assert r.american_odds == 120
assert r.price_source_surface == "PUBLIC_SPORTSBOOK_PAGE"
assert r.price_execution_equivalence == "UNATTESTED_VS_AUTHENTICATED_BETSLIP_FEED"
assert r.mc_paths == 25_000

# Wrong-game Model_P cannot price the quote.
mi = dict(MI); mi["game_id"] = "game-2"
raises(lambda: run(mi=mi), "PRICE_MODEL_GAME_MISMATCH")

# Wrong-market Model_P cannot price the quote.
mi = dict(MI); mi["market"] = "hits"
raises(lambda: run(mi=mi), "PRICE_MODEL_MARKET_MISMATCH")

# Deployment authorization must be for the same market.
raises(lambda: run(dep={"market": "hits", "status": "PASS"}), "PRICE_DEPLOYMENT_MARKET_MISMATCH")

# Player-market quote must carry a structured identity, not just a display label.
raises(lambda: run(p=price(entity_id=None)), "PRICE_ENTITY_ID_MISSING")
mi = dict(MI); mi["entity_id"] = "player-2"
raises(lambda: run(mi=mi), "PRICE_MODEL_ENTITY_MISMATCH")

# Engine threshold and side must match the exact quoted market.
def wrong_line(mi):
    out = engine(mi); out["line"] = 2.5; return out
raises(lambda: run(eng=wrong_line), "PRICE_ENGINE_LINE_MISMATCH")

def wrong_side(mi):
    out = engine(mi); out["side"] = "under"; return out
raises(lambda: run(eng=wrong_side), "PRICE_ENGINE_SIDE_MISMATCH")

# The original double-TTL requirement remains enforced.
raises(lambda: run(decision_seconds=301), "STALE_PRICE:FINALIZATION")

# Pipeline time itself cannot run backwards.
raises(
    lambda: run_candidate(
        price=price(), model_input=MI, deployment_status=DEPLOY,
        run_started_at=T0 + timedelta(seconds=5),
        decision_time=T0 + timedelta(seconds=4), engine_fn=engine,
        mc_paths=25_000, require_mc=True,
    ),
    "DECISION_TIME_BEFORE_RUN_START",
)

# Run hash is provenance-sensitive: same probability/edge with different
# price provenance must not produce the same immutable artifact hash.
r2 = run(p=price(source_id="dk-2", source_surface="AUTHENTICATED_FEED", execution_equivalence="ATTESTED"))
assert r2.run_hash != r.run_hash

print("orchestrator v0.3 candidate-binding regression PASS")
