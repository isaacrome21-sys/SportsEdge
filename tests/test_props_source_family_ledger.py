import math

import pytest

from sportsedge.props_market_binding_stage7 import NO_VIG_ONE_SIDED
from sportsedge.props_source_family_ledger import (
    NFL_PROPS_ENGINE,
    ZERO_AUTHORITY,
    append_radar_attempt,
    build_candidate_observation,
    build_radar_candidate,
    grade_source_family_evidence,
    independent_source_class_count,
    narrow_band_classification,
    source_family_confirmation_count,
)


def _card(candidate_id: str, **kwargs):
    base = {
        "source_family_id": "SOURCE_ALPHA",
        "candidate_id": candidate_id,
        "entity_id": "PLAYER",
        "market_id": "RECEPTIONS",
        "side": "OVER",
    }
    base.update(kwargs)
    return build_candidate_observation(**base)


def test_same_source_family_four_cards_count_as_one_independent_class():
    rows = [
        _card("a", line=3.5, projection=4.2),
        _card("b", line=4.5, projection=5.1),
        _card("c", line=5.5, projection=6.0),
        _card("d", line=2.5, projection=3.0),
    ]
    assert independent_source_class_count(rows) == 1
    assert source_family_confirmation_count(rows) == 1


def test_kelce_shape_is_projection_lean_but_negative_price_ev():
    row = build_candidate_observation(
        source_family_id="SOURCE_ALPHA",
        candidate_id="kelce_like",
        entity_id="PLAYER_K",
        market_id="RECEPTIONS",
        side="OVER",
        line=3.5,
        projection=4.78,
        source_model_probability=0.595,
        offered_odds=-158,
        source_claimed_grade="A+",
        source_claimed_edge_percent=-1.7,
    )
    assert row["projection_directional_delta"] == pytest.approx(1.28)
    assert row["projection_classification"] == "PROJECTION_LEAN"
    assert row["source_model_minus_raw_implied_probability"] < 0
    assert row["source_probability_offer_ev_per_unit"] < 0
    assert row["price_classification"] == "PRICE_EV_NEGATIVE"
    assert row["primary_classification"] == "PROJECTION_LEAN_ONLY"
    assert row["contradiction_flags"] == ["PROJECTION_PRICE_CONTRADICTION"]
    assert row["source_claimed_grade"] == "A+"
    assert row["sportsedge_edge_percent"] is None


def test_rice_shape_one_sided_gap_is_not_no_vig_edge():
    row = build_candidate_observation(
        source_family_id="SOURCE_ALPHA",
        candidate_id="rice_like",
        entity_id="PLAYER_R",
        market_id="ANYTIME_TD",
        side="YES",
        source_model_probability=0.556,
        offered_odds=185,
        source_claimed_edge_percent=20.5,
    )
    assert row["raw_implied_probability"] == pytest.approx(100.0 / 285.0)
    assert row["source_model_minus_raw_implied_probability"] == pytest.approx(
        0.556 - (100.0 / 285.0)
    )
    assert row["market_no_vig_probability"] == NO_VIG_ONE_SIDED
    assert row["pricing_evidence_class"] == "MODEL_VS_OFFERED_PRICE_GAP"
    assert row["primary_classification"] == "MODEL_VS_OFFERED_PRICE_GAP"
    assert row["sportsedge_edge_percent"] is None
    assert row["can_create_sportsedge_ev"] is False


def test_paired_quote_can_be_described_but_still_has_zero_sportsedge_authority():
    row = build_candidate_observation(
        source_family_id="SOURCE_ALPHA",
        candidate_id="paired",
        entity_id="PLAYER_P",
        market_id="RECEPTIONS",
        side="OVER",
        line=4.5,
        projection=4.9,
        source_model_probability=0.54,
        offered_odds=-110,
        paired_other_side_odds=-110,
    )
    assert isinstance(row["market_no_vig_probability"], float)
    assert row["market_no_vig_probability"] == pytest.approx(0.5)
    assert row["source_model_minus_paired_no_vig_probability"] == pytest.approx(0.04)
    assert row["can_create_model_p"] is False
    assert row["can_promote"] is False
    assert row["official_authority"] is False


def test_sutton_shape_collapses_to_single_integer_and_one_source_vote():
    over = build_candidate_observation(
        source_family_id="SOURCE_ALPHA",
        candidate_id="sutton_over",
        entity_id="PLAYER_S",
        market_id="RECEPTIONS",
        side="OVER",
        line=3.5,
        projection=4.0,
    )
    under = build_candidate_observation(
        source_family_id="SOURCE_ALPHA",
        candidate_id="sutton_under",
        entity_id="PLAYER_S",
        market_id="RECEPTIONS",
        side="UNDER",
        line=4.5,
        projection=4.0,
    )
    result = narrow_band_classification([over, under])
    assert result["classification"] == "NARROW_BAND_SAME_CENTER"
    assert result["shared_winning_integer_outcomes"] == [4]
    assert result["independent_source_classes"] == 1
    assert result["confirmation_votes"] == 1


def test_radar_candidate_requires_30s_180s_and_size_for_takeability():
    base = dict(
        source_family_id="SOURCE_ALPHA",
        attempt_id="attempt-1",
        candidate_id="radar-1",
        entity_id="PLAYER_X",
        market_id="PROP_SIDE",
        soft_venue="SOFT_BOOK",
        soft_odds=-167,
        observed_at_ts="2026-09-14T10:00:00-05:00",
        reference_quotes=[
            {"venue": "EXCHANGE_A", "odds": -370, "observed_at_ts": "2026-09-14T10:00:00-05:00"},
            {"venue": "NO_VIG_REF", "odds": -175, "observed_at_ts": "2026-09-14T10:00:00-05:00"},
        ],
        exchange_flow_prints=[483.0, 187.0],
    )
    first = build_radar_candidate(**base)
    assert first["radar_classification"] == "STALE_SOFT_PRICE_CANDIDATE"
    assert first["takeability_status"] == "TAKEABILITY_UNVERIFIED"
    assert first["exchange_flow_total"] == pytest.approx(670.0)
    assert first["exchange_flow_semantics"] == "FACTUAL_PRINTS_ONLY_NO_WHALE_INFERENCE"
    assert first["projection_correctness_inferred_from_radar"] is False

    observed = build_radar_candidate(
        **base,
        persistence_30s_odds=-167,
        persistence_180s_odds=-165,
        usable_size=250.0,
    )
    assert observed["persisted_at_30s"] is True
    assert observed["persisted_at_180s"] is True
    assert observed["takeability_status"] == "TAKEABILITY_OBSERVED"


def test_radar_reprice_worse_fails_persistence():
    row = build_radar_candidate(
        source_family_id="SOURCE_ALPHA",
        attempt_id="attempt-1",
        candidate_id="radar-2",
        entity_id="PLAYER_X",
        market_id="PROP_SIDE",
        soft_venue="SOFT_BOOK",
        soft_odds=-167,
        observed_at_ts="2026-09-14T10:00:00-05:00",
        reference_quotes=[
            {"venue": "REF", "odds": -220, "observed_at_ts": "2026-09-14T10:00:00-05:00"},
        ],
        persistence_30s_odds=-190,
        persistence_180s_odds=-210,
        usable_size=100.0,
    )
    assert row["persisted_at_30s"] is False
    assert row["takeability_status"] == "TAKEABILITY_FAILED_PERSISTENCE"


def test_radar_attempt_ledger_is_append_only_and_chronological():
    first = build_radar_candidate(
        source_family_id="SOURCE_ALPHA",
        attempt_id="attempt-1",
        candidate_id="radar-1",
        entity_id="PLAYER_X",
        market_id="PROP_SIDE",
        soft_venue="BOOK",
        soft_odds=-167,
        observed_at_ts="2026-09-14T10:00:00-05:00",
        reference_quotes=[{"venue": "REF", "odds": -200, "observed_at_ts": "2026-09-14T10:00:00-05:00"}],
    )
    second = build_radar_candidate(
        source_family_id="SOURCE_ALPHA",
        attempt_id="attempt-2",
        candidate_id="radar-1",
        entity_id="PLAYER_X",
        market_id="PROP_SIDE",
        soft_venue="BOOK",
        soft_odds=-170,
        observed_at_ts="2026-09-14T10:05:00-05:00",
        reference_quotes=[{"venue": "REF", "odds": -205, "observed_at_ts": "2026-09-14T10:05:00-05:00"}],
    )
    ledger = append_radar_attempt([], first)
    ledger = append_radar_attempt(ledger, second)
    assert [row["attempt_id"] for row in ledger] == ["attempt-1", "attempt-2"]
    with pytest.raises(ValueError, match="SOURCE_LEDGER_RADAR_ATTEMPT_DUPLICATE"):
        append_radar_attempt(ledger, second)


def test_thin_source_family_sample_is_insufficient():
    assert grade_source_family_evidence(99)["status"] == "INSUFFICIENT_EVIDENCE"
    assert grade_source_family_evidence(100)["status"] == "REVIEWABLE_CONTEXT_ONLY_NO_AUTHORITY"


def test_every_authority_flag_is_literal_false_and_nfl_props_remain_no_engine():
    assert NFL_PROPS_ENGINE == "NO_ENGINE"
    assert ZERO_AUTHORITY
    assert all(value is False for value in ZERO_AUTHORITY.values())
    row = _card("authority", line=3.5, projection=4.0)
    for key in ZERO_AUTHORITY:
        assert row[key] is False
    assert row["nfl_props_engine"] == "NO_ENGINE"


def test_invalid_probability_and_nonaware_radar_time_fail_closed():
    with pytest.raises(ValueError, match="SOURCE_LEDGER_PROBABILITY_INVALID"):
        _card("bad-p", source_model_probability=1.2, offered_odds=120)
    with pytest.raises(ValueError, match="SOURCE_LEDGER_TIMESTAMP_MUST_BE_AWARE"):
        build_radar_candidate(
            source_family_id="SOURCE_ALPHA",
            attempt_id="attempt-1",
            candidate_id="radar",
            entity_id="PLAYER",
            market_id="PROP",
            soft_venue="BOOK",
            soft_odds=-110,
            observed_at_ts="2026-09-14T10:00:00",
            reference_quotes=[{"venue": "REF", "odds": -120, "observed_at_ts": "2026-09-14T10:00:00-05:00"}],
        )
