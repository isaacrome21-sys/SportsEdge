#!/usr/bin/env python3
import hashlib
from datetime import datetime, timezone, timedelta

from sportsedge_identity_rng import candidate_seed_sequence, candidate_rng
from sportsedge_candidate_binding import check_binding
from sportsedge_price_ttl import check_double_ttl
from sportsedge_truth_gate import truth_gate

# Identity RNG: deterministic, full-width, different identities diverge.
h1 = hashlib.sha256(b"candidate-1").hexdigest()
h2 = hashlib.sha256(b"candidate-2").hexdigest()
s1 = candidate_seed_sequence(h1)
s2 = candidate_seed_sequence(h2)
assert len(s1.entropy) == 8
assert len(s1.entropy) * 32 > 64
assert list(s1.entropy) != list(s2.entropy)
assert candidate_rng(h1).random(16).tolist() == candidate_rng(h1).random(16).tolist()
assert candidate_rng(h1).random(16).tolist() != candidate_rng(h2).random(16).tolist()

# Strict candidate binding.
model = {"game_id":"G1","market":"hits","entity_id":"P1","line":0.5,"side":"over"}
quote = {"game_id":"G1","market":"hits","entity_id":"P1","line":0.5,"side":"over"}
dep = {"market":"hits","eligible":True}
assert check_binding(model, quote, dep).ok
for field, bad_value in [("game_id","G2"),("market","runs"),("entity_id","P2"),("line",1.5),("side","under")]:
    q = dict(quote); q[field] = bad_value
    assert not check_binding(model, q, dep).ok
assert not check_binding(model, quote, {"market":"runs","eligible":True}).ok
assert not check_binding(model, quote, {"market":"hits","eligible":False}).ok

# Double TTL, including fresh-at-ingress/stale-at-finalization and backwards time.
t0 = datetime(2026, 8, 10, 20, 0, tzinfo=timezone.utc)
price = {"sportsbook":"DK","source_surface":"TEST","game_id":"G1","market":"hits","entity_id":"P1","line":0.5,"side":"over","odds":-110,"retrieved_at":t0.isoformat(),"ttl_seconds":300}
assert check_double_ttl(price, t0 + timedelta(seconds=10), t0 + timedelta(seconds=299)).ok
assert not check_double_ttl(price, t0 + timedelta(seconds=10), t0 + timedelta(seconds=301)).ok
assert not check_double_ttl(price, t0 + timedelta(seconds=10), t0 + timedelta(seconds=5)).ok
bad = dict(price); bad["ttl_seconds"] = 0
assert not check_double_ttl(bad, t0, t0).ok
bad = dict(price); bad["retrieved_at"] = "not-a-time"
assert not check_double_ttl(bad, t0, t0).ok

# Truth Gate: +EV, -EV/pass, stale/binding/deployment block, invalid odds block.
assert truth_gate(.60, -110, binding_ok=True, binding_reason="bound", deployment_eligible=True, freshness_ok=True, freshness_reason="fresh").bet_status == "OFFICIAL_BET"
assert truth_gate(.40, -110, binding_ok=True, binding_reason="bound", deployment_eligible=True, freshness_ok=True, freshness_reason="fresh").bet_status == "PASS"
assert truth_gate(.60, -110, binding_ok=False, binding_reason="bad", deployment_eligible=True, freshness_ok=True, freshness_reason="fresh").bet_status == "BLOCKED"
assert truth_gate(.60, -110, binding_ok=True, binding_reason="bound", deployment_eligible=False, freshness_ok=True, freshness_reason="fresh").bet_status == "BLOCKED"
assert truth_gate(.60, -110, binding_ok=True, binding_reason="bound", deployment_eligible=True, freshness_ok=False, freshness_reason="stale").bet_status == "BLOCKED"
assert truth_gate(.60, 0, binding_ok=True, binding_reason="bound", deployment_eligible=True, freshness_ok=True, freshness_reason="fresh").bet_status == "BLOCKED"
assert truth_gate(1.2, -110, binding_ok=True, binding_reason="bound", deployment_eligible=True, freshness_ok=True, freshness_reason="fresh").bet_status == "BLOCKED"

print("shared production utilities regression PASS")
