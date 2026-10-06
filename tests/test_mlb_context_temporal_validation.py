from sportsedge.mlb_context_temporal_validation import validate_candidate

def _rows(n,base_err,cand_err):
    return [{"game_date":"2026-04-01","actual_total_runs":8,"baseline_total_runs":8+base_err,"candidate_total_runs":8+cand_err} for _ in range(n)]

def test_rejects_small_holdout():
    assert validate_candidate(_rows(199,1,0.5),train_end="2025-12-31",holdout_start="2026-01-01")["status"]=="REJECTED"

def test_validates_only_noninferior_large_holdout():
    out=validate_candidate(_rows(200,1,0.5),train_end="2025-12-31",holdout_start="2026-01-01")
    assert out["status"]=="VALIDATED" and out["candidate_rmse"] < out["baseline_rmse"]

def test_rejects_temporal_overlap():
    try: validate_candidate([],train_end="2026-01-02",holdout_start="2026-01-01")
    except ValueError: pass
    else: raise AssertionError("expected temporal overlap rejection")

