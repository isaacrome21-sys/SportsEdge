#!/usr/bin/env python3
from datetime import datetime,timedelta,timezone
from orchestrator_v0_2 import OrchestrationError,PriceRecord,run_candidate
UTC=timezone.utc; T0=datetime(2026,8,10,18,18,25,tzinfo=UTC)
def price():
    return PriceRecord("dk","DRAFTKINGS","PUBLIC","g","total_bases","player over 1.5",1.5,+120,T0,300,"UNATTESTED")
MI={"build_hash":"abc123"}
def engine(mi): return {"model_p":0.60,"model_input_hash":"abc123","source_kind":"SPORTSEDGE_MODEL","engine_code_version":"x"}
def native_mc_engine(mi): return {"model_p":0.60,"model_input_hash":"abc123","source_kind":"SPORTSEDGE_MC","engine_code_version":"tb","mc_status":"PASS","mc_paths":25_000}
def external_mc(mi,paths): return {"status":"PASS","paths":paths}
def raises(fn,text):
    try: fn()
    except OrchestrationError as e:
        assert text in str(e),(text,str(e)); return
    raise AssertionError(text)
r=run_candidate(price=price(),model_input=MI,deployment_status={"status":"PASS"},run_started_at=T0+timedelta(seconds=1),decision_time=T0+timedelta(seconds=2),engine_fn=native_mc_engine,mc_paths=25_000,require_mc=True)
assert r.mc_paths==25_000 and r.model_input_hash=="abc123" and r.model_source_kind=="SPORTSEDGE_MC"
r2=run_candidate(price=price(),model_input=MI,deployment_status={"status":"PASS"},run_started_at=T0+timedelta(seconds=1),decision_time=T0+timedelta(seconds=2),engine_fn=engine,mc_fn=external_mc,mc_paths=25_000,require_mc=True)
assert r2.mc_paths==25_000
raises(lambda:run_candidate(price=price(),model_input=MI,deployment_status={"status":"PASS"},run_started_at=T0+timedelta(seconds=1),decision_time=T0+timedelta(seconds=2),engine_fn=lambda mi:{"model_p":.6,"model_input_hash":"WRONG","source_kind":"SPORTSEDGE_MODEL"}),"MODEL_INPUT_HASH_MISMATCH")
raises(lambda:run_candidate(price=price(),model_input=MI,deployment_status={"status":"PASS"},run_started_at=T0+timedelta(seconds=1),decision_time=T0+timedelta(seconds=2),engine_fn=engine,require_mc=True),"MC_ATTESTATION_MISSING")
raises(lambda:run_candidate(price=price(),model_input=MI,deployment_status={"status":"PASS"},run_started_at=T0+timedelta(seconds=1),decision_time=T0+timedelta(seconds=2),engine_fn=native_mc_engine,mc_fn=external_mc,require_mc=True),"AMBIGUOUS_MC_ATTESTATION")
raises(lambda:run_candidate(price=price(),model_input=MI,deployment_status={"status":"PASS"},run_started_at=T0+timedelta(seconds=1),decision_time=T0+timedelta(seconds=301),engine_fn=native_mc_engine,require_mc=True),"STALE_PRICE:FINALIZATION")
print("orchestrator v0.2 regression PASS")
