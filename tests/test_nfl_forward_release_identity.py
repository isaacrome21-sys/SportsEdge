import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from sportsedge.core.validation.nfl_forward_clv_attestation import verify_nfl_forward_clv_bundle
from sportsedge.sports.nfl.m2 import NFL_M2_FEATURE_CONTRACT, PRODUCTION_NFL_M2_MODEL_ID


class NFLForwardReleaseIdentityTests(unittest.TestCase):
    def _bundle(self, root: Path, *, model_sha="1" * 40, collector_sha="2" * 40):
        model = {"schema_version": 1, "sport": "nfl", "model_id": PRODUCTION_NFL_M2_MODEL_ID, "feature_contract": NFL_M2_FEATURE_CONTRACT, "code_git_sha": model_sha, "source_manifest_sha256": "a" * 64, "trained_through_season": 2025, "model": {}}
        model_path = root / "nfl_m2_model.json"
        model_path.write_text(json.dumps(model, sort_keys=True), encoding="utf-8")
        model_hash = hashlib.sha256(model_path.read_bytes()).hexdigest()
        decision = {"decision_ts":"2026-09-10T23:00:00+00:00","game_start_ts":"2026-09-11T00:20:00+00:00","game_id":"g","sport":"nfl","market":"moneyline","side":"AAA","book":"draftkings","line_at_decision":None,"price_at_decision":-110,"model_prob":0.55,"novig_prob":0.5,"ev":0.05,"kelly_frac":0.01,"stake_units":0.01,"gate_result":"SHADOW_QUALIFIED","model_id":PRODUCTION_NFL_M2_MODEL_ID,"feature_contract":NFL_M2_FEATURE_CONTRACT,"code_git_sha":model_sha,"model_artifact_sha256":model_hash}
        close = {"close_ts":"2026-09-11T00:15:00+00:00","game_start_ts":"2026-09-11T00:20:00+00:00","game_id":"g","sport":"nfl","market":"moneyline","side":"AAA","book":"draftkings","closing_line":None,"closing_price":-120,"closing_novig_prob":0.53,"probability_line":None,"model_id":PRODUCTION_NFL_M2_MODEL_ID,"feature_contract":NFL_M2_FEATURE_CONTRACT,"code_git_sha":model_sha}
        d = root / "nfl_forward_decisions.jsonl"; c = root / "nfl_forward_closes.jsonl"
        d.write_text(json.dumps(decision, sort_keys=True)+"\n", encoding="utf-8"); c.write_text(json.dumps(close, sort_keys=True)+"\n", encoding="utf-8")
        evidence = {"schema_version":4,"sport":"nfl","model_id":PRODUCTION_NFL_M2_MODEL_ID,"feature_contract":NFL_M2_FEATURE_CONTRACT,"code_git_sha":model_sha,"model_artifact_sha256":model_hash,"decision_log_sha256":hashlib.sha256(d.read_bytes()).hexdigest(),"close_log_sha256":hashlib.sha256(c.read_bytes()).hexdigest(),"decision_count":1,"close_count":1,"unique_observation_count":1,"first_decision_ts":decision["decision_ts"],"last_close_ts":close["close_ts"],"clv_probability_reference":"DECISION_THRESHOLD","forward_time_contract":"PREGAME_DECISION_TO_PREGAME_CLOSE","close_book_contract":"SAME_BOOK_AS_DECISION","promotion_decision_contract":"SHADOW_QUALIFIED_OR_OFFICIAL","markets":{"moneyline":{"logged_plays":1,"mean_clv":0.03,"beat_close_rate":1.0,"clv_t_stat":0.0}},"rejected_markets":{}}
        e = root / "nfl_clv_evidence.json"; e.write_text(json.dumps(evidence, sort_keys=True), encoding="utf-8")
        files = [d,c,e,model_path]
        manifest = {"schema_version":2,"collector_contract":"NFL_FORWARD_CLV_COLLECTION_V2","collector_git_sha":collector_sha,"model_code_git_sha":model_sha,"model_artifact_sha256":model_hash,"model_id":PRODUCTION_NFL_M2_MODEL_ID,"feature_contract":NFL_M2_FEATURE_CONTRACT,"artifacts":[{"path":p.name,"sha256":hashlib.sha256(p.read_bytes()).hexdigest()} for p in files]}
        (root / "nfl_forward_clv_manifest.json").write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")

    def test_unrelated_main_commit_does_not_reset_pinned_model_release(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp); self._bundle(root)
            att = verify_nfl_forward_clv_bundle(root, workflow_name="football-nfl-forward-clv-collection", workflow_conclusion="success", workflow_event="schedule", workflow_head_branch="main", workflow_head_sha="2"*40, workflow_run_id=123)
            self.assertEqual(att["collector_git_sha"], "2"*40)
            self.assertEqual(att["git_sha"], "1"*40)

    def test_collector_head_still_must_match_scheduled_workflow_head(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp); self._bundle(root, collector_sha="2"*40)
            with self.assertRaisesRegex(ValueError, "NFL_FORWARD_CLV_COLLECTOR_HEAD_SHA_MISMATCH"):
                verify_nfl_forward_clv_bundle(root, workflow_name="football-nfl-forward-clv-collection", workflow_conclusion="success", workflow_event="schedule", workflow_head_branch="main", workflow_head_sha="3"*40, workflow_run_id=123)


if __name__ == "__main__": unittest.main()
