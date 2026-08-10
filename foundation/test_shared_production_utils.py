#!/usr/bin/env python3
import hashlib
import math
from datetime import datetime, timezone, timedelta

from sportsedge_identity_rng import candidate_seed_sequence, candidate_rng
from sportsedge_candidate_binding import check_binding
from sportsedge_price_ttl import check_double_ttl
from sportsedge_truth_gate import truth_gate

# Identity RNG: exact SHA-256 identity, deterministic, full-width, divergent identities.
h1 = hashlib.sha256(b"candidate-1").hexdigest()
h2 = hashlib.sha256(b"candidate-2").hexdigest()
s1 = candidate_seed_sequence(h1)
s2 = candidate_seed_sequence(h2)
assert len(s1.entropy) == 8 and len(s1.entropy) * 32 > 64
assert list(s1.entropy) != list(s2.entropy)
assert candidate_rng(h1).random(16).tolist() == candidate_rng(h1).random(16).tolist()
assert candidate_rng(h1).random(16).tolist() != candidate_rng(h2).random(16).tolist()
for bad_hash in ("g" * 64, "a" * 32, "a" * 63, "a" * 65, ""):
    try:
        candidate_rng(bad_hash)
    except ValueError:
        pass
    else:
        raise AssertionError(f"invalid build_hash accepted: {bad_hash!r}")

# Strict candidate binding, including bool/int coercion and malformed attestation.
model = {"game_id":"G1","market":"hits","entity_id":"P1","line":0.5,"side":"over"}
quote = {"game_id":"G1","market":"hits","entity_id":"P1","line":0.5,"side":"over"}
dep = {"market":"hits","eligible":True}
assert check_binding(model, quote, dep).ok
for field, bad_value in [("game_id","G2"),("market","runs"),("entity_id","P2"),("line",1.5),("side","under")]:
    q = dict(quote); q[field] = bad_value
    assert not check_binding(model, q, dep).ok
q = dict(quote); q["line"] = True
assert not check_binding(model, q, dep).ok
assert not check_binding(model, quote, None).ok
assert not check_binding(model, quote, {"market":"hits","eligible":1}).ok
assert not check_binding(model, quote, {"market":"hits","eligible":"true"}).ok
assert not check_binding(model, quote, {"market":"runs","eligible":True}).ok

# Double TTL, including fresh-at-ingress/stale-at-finalization and invalid numeric TTL.
t0 = datetime(2026, 8, 10, 20, 0, tzinfo=timezone.utc)
price = {"sportsbook":"DK","source_surface":"TEST","game_id":"G1","market":"hits","entity_id":"P1","line":0.5,"side":"over","odds":-110,"retrieved_at":t0.isoformat(),"ttl_seconds":300}
assert check_double_ttl(price, t0 + timedelta(seconds=10), t0 + timedelta(seconds=299)).ok
assert not check_double_ttl(price, t0 + timedelta(seconds=10), t0 + timedelta(seconds=301)).ok
assert not check_double_ttl(price, t0 + timedelta(seconds=10), t0 + timedelta(seconds=5)).ok
for ttl in (0, -1, float("inf"), float("nan"), True, None):
    bad = dict(price); bad["ttl_seconds"] = ttl
    assert not check_double_ttl(bad, t0, t0).ok
bad = dict(price); bad["retrieved_at"] = "not-a-time"
assert not check_double_ttl(bad, t0, t0).ok
assert not check_double_ttl(price, t0.replace(tzinfo=None), t0).ok

# Truth Gate: exact outcomes and fail-closed numeric validation.
def tg(p=.60, odds=-110, **kw):
    args = dict(binding_ok=True, binding_reason="bound", deployment_eligible=True,
                freshness_ok=True, freshness_reason="fresh")
    args.update(kw)
    return truth_gate(p, odds, **args)
assert tg().bet_status == "OFFICIAL_BET"
assert tg(.40).bet_status == "PASS"
assert tg(binding_ok=False).bet_status == "BLOCKED"
assert tg(deployment_eligible=False).bet_status == "BLOCKED"
assert tg(freshness_ok=False).bet_status == "BLOCKED"
for odds in (0, 99, -99, float("inf"), float("nan"), 1_000_001):
    assert tg(odds=odds).bet_status == "BLOCKED"
for p in (1.2, -0.1, float("inf"), float("nan"), True):
    assert tg(p).bet_status == "BLOCKED"
for kf in (0, -0.1, 1.1, float("inf"), float("nan"), True):
    assert tg(kelly_fraction=kf).bet_status == "BLOCKED"

print("shared production utilities regression PASS")
