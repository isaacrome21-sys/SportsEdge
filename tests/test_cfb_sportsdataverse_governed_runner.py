from pathlib import Path

def test_governed_runner_imports_frozen_native_evaluator():
 text=Path("scripts/run_cfb_sportsdataverse_bakeoff.py").read_text()
 assert "evaluate_native_candidates" in text
 assert 'CONFIRM="CONSUME_ALL_FOUR_CFB_SDV_ATTEMPTS"' in text
 assert "verify(binding.get" in text
 assert '"attempts_consumed":4' in text
 assert '"model_p_created":False' in text
 assert '"promotion_authority":False' in text
 assert '"official_authority":False' in text

def test_governed_runner_rejects_2026_outcomes_by_construction():
 text=Path("scripts/run_cfb_sportsdataverse_bakeoff.py").read_text()
 assert "CFB_SDV_2026_OUTCOME_FORBIDDEN" in text


def test_governed_workflow_enforces_frozen_null_control_before_selection():
 text=Path(".github/workflows/cfb-sdv-governed-bakeoff.yml").read_text()
 assert "CONSUME_ALL_FOUR_CFB_SDV_ATTEMPTS" in text
 assert "Enforce frozen 200-shuffle null selection control" in text
 assert 'config/cfb_model_selection_policy_v1.json' in text
 assert 'for rep in range(200)' in text
 assert 'NO_CANDIDATE_DEMONSTRATED_SIGNAL_AT_THIS_SAMPLE' in text
 assert '"null_control_enforced"] = True' in text
