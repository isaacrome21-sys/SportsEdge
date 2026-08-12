import json,tempfile,unittest
from pathlib import Path
from sportsedge.deployment_audit import validate_deployment_audit,DeploymentAuditError

REQ={"event_id":"e","event_type":"DEPLOYMENT_ELIGIBILITY_TRANSITION","recorded_at_utc":"2026-08-12T00:00:00Z","market":"MONEYLINE","previous_eligibility":False,"previous_stage":"VALIDATED_MATH","new_eligibility":True,"new_stage":"DEPLOYED","reason_code":"ALL_GATES_PASS","commit_sha":"a"*40,"workflow_run_ids":[1],"artifact_ids":[2],"artifact_sha256":{"x":"b"*64},"validation_sample_count":1785,"subgroup_counts":{},"historical_gate":"PASS","live_parity_gate":"PASS","runtime_gate":"PASS","truth_gate_test_result":"PASS","deployment_effect":"ELIGIBILITY_FALSE_TO_TRUE"}

def registry(eligible=False): return {"schema_version":1,"markets":{"MONEYLINE":{"eligible":eligible,"stage":"DEPLOYED" if eligible else "VALIDATED_MATH","reason":"x"}}}

class Tests(unittest.TestCase):
    def run_case(self,reg,events):
        with tempfile.TemporaryDirectory() as td:
            rp=Path(td)/'d.json'; ep=Path(td)/'e.jsonl'; rp.write_text(json.dumps(reg)); ep.write_text(''.join(json.dumps(x)+'\n' for x in events)); validate_deployment_audit(registry_path=rp,events_path=ep)
    def test_current_false_state_needs_no_transition(self): self.run_case(registry(False),[])
    def test_flip_without_event_fails(self):
        with self.assertRaises(DeploymentAuditError): self.run_case(registry(True),[])
    def test_event_without_registry_flip_fails(self):
        with self.assertRaises(DeploymentAuditError): self.run_case(registry(False),[REQ])
    def test_complete_transition_passes(self): self.run_case(registry(True),[REQ])
    def test_missing_artifact_ids_fails(self):
        bad=dict(REQ); bad['artifact_ids']=[]
        with self.assertRaises(DeploymentAuditError): self.run_case(registry(True),[bad])

if __name__=='__main__': unittest.main()
