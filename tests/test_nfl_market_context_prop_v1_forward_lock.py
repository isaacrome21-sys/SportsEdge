import json
from pathlib import Path
import subprocess

LOCK = Path("config/research/nfl_market_context_prop_v1_2026_forward_lock.json")
SURFACE = Path("config/football_prop_engine_surface.json")


def load_lock():
    return json.loads(LOCK.read_text(encoding="utf-8"))


def test_candidate_surface_is_exact_byte_bound():
    cfg = load_lock()
    assert cfg["status"] == "FROZEN_BEFORE_2026_WEEK5_FORWARD_EVIDENCE"
    for item in cfg["candidate_identity"]["code_surface"]:
        got = subprocess.check_output(["git", "hash-object", item["path"]], text=True).strip()
        assert got == item["git_blob_sha1"]


def test_forward_window_is_week5_plus_no_backfill():
    cfg = load_lock()
    w = cfg["forward_window"]
    assert w["season"] == 2026
    assert w["first_eligible_week"] == 5
    assert w["last_eligible_week"] == 18
    assert w["first_eligible_kickoff_utc"] == "2026-10-09T00:15:00Z"
    assert w["prelock_rows_admissible"] is False
    assert w["weeks_1_through_4_admissible"] is False
    assert w["backfill_allowed"] is False


def test_game_market_context_cannot_create_game_edge():
    cfg = load_lock()
    env = cfg["model_contract"]["game_environment"]
    assert env["source"] == "SPORTSBOOK_MARKET_CENTER_CONTEXT_ONLY"
    assert env["game_market_prices_create_edge"] is False
    assert env["game_market_model_authority"] is False
    assert cfg["authority"]["game_market_edge"] is False


def test_prop_prices_bind_after_projection_not_inside_projection():
    cfg = load_lock()
    d = cfg["decision_snapshot"]
    m = cfg["model_contract"]
    assert d["prop_quote_may_bind_threshold_and_ev_after_prediction"] is True
    assert d["prop_quote_may_change_player_projection"] is False
    assert m["player_prop_line_as_predictive_feature"] is False
    assert m["player_prop_price_as_predictive_feature"] is False


def test_validation_is_per_market_and_zero_authority():
    cfg = load_lock()
    v = cfg["validation"]
    assert v["per_market_independent"] is True
    assert v["minimum_decision_rows_per_market"] == 100
    assert v["calibration_max"] == 0.06
    assert v["candidate_brier_must_be_lte_devigged_market_brier"] is True
    assert v["candidate_log_loss_must_be_lte_devigged_market_log_loss"] is True
    assert v["missing_sample_behavior"] == "MARKET_STAYS_RESEARCH_NO_MODEL"
    assert not any(value for key, value in cfg["authority"].items() if key != "research_only")


def test_runtime_authority_stays_no_engine():
    surface = json.loads(SURFACE.read_text(encoding="utf-8"))
    nfl = surface["sports"]["NFL"]
    assert nfl["engine_state"] == "NO_ENGINE"
    assert nfl["promotion_state"] == "BLOCKED_NO_VALIDATED_PROBABILITY_ENGINE"
