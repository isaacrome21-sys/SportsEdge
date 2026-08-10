#!/usr/bin/env python3
from live_era_guard_v0_1 import season_keyed_artifact_status

ART={"models":{"2023|0.5":object(),"2023|1.5":object(),"2024|0.5":object(),"2024|1.5":object()}}

r=season_keyed_artifact_status(market="rbi",artifact=ART,target_season=2024)
assert r["status"]=="PASS_HISTORICAL_SEASON_KEY_PRESENT",r

r=season_keyed_artifact_status(market="rbi",artifact=ART,target_season=2026)
assert r["status"]=="BLOCKED_LIVE_ERA_POLICY",r
assert r["latest_scoring_season"]==2024,r

bad={"market":"rbi","target_season":2026,"artifact_latest_scoring_season":2024,"policy_verified":True}
r=season_keyed_artifact_status(market="rbi",artifact=ART,target_season=2026,live_era_attestation=bad)
assert r["status"]=="BLOCKED_LIVE_ERA_POLICY",r

att={"market":"rbi","target_season":2026,"artifact_latest_scoring_season":2024,"policy_verified":True,"policy":"EXAMPLE_ONLY_TEST_POLICY","validation_hash":"deadbeef"}
r=season_keyed_artifact_status(market="rbi",artifact=ART,target_season=2026,live_era_attestation=att)
assert r["status"]=="PASS_LIVE_ERA_POLICY_ATTESTED",r

print("live era guard tests OK")
