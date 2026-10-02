from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "run_cfb_prop_model_candidate_proxy_tested",
    ROOT / "scripts/run_cfb_prop_model_candidate.py",
)
MOD = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MOD)


def test_proxy_candidate_is_lean_but_explicitly_nonproduction():
    report = {
        "results": [{
            "provider_market": "player_pass_yds",
            "model_p": 0.61,
            "fair_market_p": 0.54,
            "ev_per_dollar": 0.08,
            "bet_status": "OFFICIAL_BET",
            "official_eligible": True,
        }],
        "summary": {"official_bets": 1},
        "governance": {},
    }
    out = MOD._candidateize(report, proxy_usage=True)
    row = out["results"][0]
    assert row["presentation_label"] == "LEAN"
    assert row["decision_tier"] == "MODEL_CANDIDATE"
    assert row["usage_input_class"] == "RESEARCH_PROXY"
    assert row["bet_status"] == "BLOCKED"
    assert row["official_eligible"] is False
    assert row["promotion_authority"] is False
    assert row["reason"] == "CFB_PROP_RESEARCH_PROXY_USAGE_INDEPENDENT_VALIDATION_REQUIRED"
    assert out["summary"]["official_bets"] == 0
    assert out["governance"]["research_proxy_usage"] is True
    assert out["governance"]["production_eligible"] is False


def test_observed_usage_path_keeps_existing_research_label():
    report = {
        "results": [{
            "provider_market": "player_rush_yds",
            "model_p": 0.57,
            "fair_market_p": 0.52,
            "ev_per_dollar": 0.04,
        }],
        "summary": {},
        "governance": {},
    }
    out = MOD._candidateize(report, proxy_usage=False)
    row = out["results"][0]
    assert row["usage_input_class"] == "OBSERVED_USAGE_INPUT"
    assert row["reason"] == "CFB_PROP_RESEARCH_ONLY_INDEPENDENT_VALIDATION_REQUIRED"
    assert out["governance"]["research_proxy_usage"] is False
