from __future__ import annotations

import pytest

from sportsedge.ballparkpal_context import (
    MODEL_VOTE,
    BallparkPalContextError,
    normalize_ballparkpal_report,
)
from sportsedge.ballparkpal_daily_context import (
    REPORT_SPECS,
    BallparkPalDailyContextError,
    normalize_ballparkpal_daily_report,
)
from sportsedge.mlb_context_autopull import (
    CONTEXT_CLASSES,
    SUPPLEMENTAL_CONTEXT_CLASSES,
    missing_context_classes,
    missing_supplemental_context_classes,
)


def _det_cle_report() -> dict:
    return {
        "game_pk": 824424,
        "observed_at_utc": "2026-09-04T15:35:00Z",
        "teams": {
            "away": {
                "team": "DET",
                "starter": {
                    "name": "Keider Montero",
                    "ip": 5.2,
                    "runs": 2.2,
                    "hits": 4.4,
                    "hr": 0.70,
                    "k": 3.9,
                    "bb": 1.6,
                },
                "bullpen": {
                    "ip": 3.6,
                    "runs": 1.4,
                    "hits": 3.1,
                    "hr": 0.51,
                    "k": 3.8,
                    "bb": 1.4,
                },
                "opener_flag": False,
                "bulk_pitcher_flag": False,
                "short_leash_flag": False,
            },
            "home": {
                "team": "CLE",
                "starter": {
                    "name": "Logan Allen",
                    "ip": 3.5,
                    "runs": 1.7,
                    "hits": 3.2,
                    "hr": 0.60,
                    "k": 3.0,
                    "bb": 1.5,
                },
                "bullpen": {
                    "ip": 5.8,
                    "runs": 2.1,
                    "hits": 4.4,
                    "hr": 0.90,
                    "k": 6.8,
                    "bb": 2.6,
                },
                "opener_flag": False,
                "bulk_pitcher_flag": False,
                "short_leash_flag": True,
            },
        },
    }


def test_ballparkpal_normalizes_as_context_only_and_derives_bullpen_share():
    row = normalize_ballparkpal_report(_det_cle_report(), expected_game_pk=824424)

    assert MODEL_VOTE is False
    assert row["model_p_eligible"] is False
    assert row["truth_gate_eligible"] is False
    assert row["source_role"] == "CONTEXT_ONLY"
    assert row["projected_game_runs"] == pytest.approx(7.4)
    assert row["away"]["projected_total_runs_allowed"] == pytest.approx(3.6)
    assert row["home"]["projected_total_runs_allowed"] == pytest.approx(3.8)
    assert row["home"]["bullpen_share"] == pytest.approx(5.8 / (3.5 + 5.8))
    assert row["home"]["bullpen_heavy_flag"] is True
    assert row["home"]["short_leash_flag"] is True


def test_ballparkpal_game_identity_mismatch_fails_closed():
    with pytest.raises(BallparkPalContextError, match="game identity mismatch"):
        normalize_ballparkpal_report(_det_cle_report(), expected_game_pk=999999)


def test_ballparkpal_daily_report_families_are_context_only():
    for report_type, spec in REPORT_SPECS.items():
        row = normalize_ballparkpal_daily_report(
            report_type,
            {
                "game_pk": 824424,
                "observed_at_utc": "2026-09-04T15:45:00Z",
                "source_url": "https://example.invalid/ballparkpal",
                "payload": {"sample": report_type},
            },
            expected_game_pk=824424,
        )
        assert row["context_class"] == spec["context_class"]
        assert row["source_role"] == "CONTEXT_ONLY"
        assert row["model_p_eligible"] is False
        assert row["truth_gate_eligible"] is False
        assert "model_p_vote" in row["prohibited_uses"]
        assert "market_price_substitution" in row["prohibited_uses"]


def test_most_likely_is_not_allowed_to_masquerade_as_market_price():
    row = normalize_ballparkpal_daily_report(
        "most_likely",
        {
            "game_pk": 824424,
            "payload": {"to_hit_hr": [{"player": "C. Jensen", "sim_american": 306}]},
        },
    )
    assert row["source"] == "BALLPARKPAL_MOST_LIKELY_REPORT"
    assert "no_vig_input" in row["prohibited_uses"]
    assert "market_price_substitution" in row["prohibited_uses"]


def test_ballparkpal_daily_game_identity_mismatch_fails_closed():
    with pytest.raises(BallparkPalDailyContextError, match="game identity mismatch"):
        normalize_ballparkpal_daily_report(
            "stadium_weather",
            {"game_pk": 824424, "payload": {"runs": 0.0}},
            expected_game_pk=999999,
        )


def test_missing_ballparkpal_does_not_block_required_context_completeness():
    bundle = {
        "observations": {
            **{key: {"status": "AVAILABLE"} for key in CONTEXT_CLASSES},
            **{key: {"status": "MISSING_PROVIDER"} for key in SUPPLEMENTAL_CONTEXT_CLASSES},
        }
    }

    assert missing_context_classes(bundle) == ()
    assert missing_supplemental_context_classes(bundle) == SUPPLEMENTAL_CONTEXT_CLASSES
