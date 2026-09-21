import json
from pathlib import Path
import shutil

import pytest

from sportsedge.sports.nfl.prop_research_lane import (
    AUTHORITY_FOOTER,
    PROP_CARD_SCHEMA,
    PROP_LEDGER_NAMESPACE,
    PropResearchLaneError,
    build_prop_ledger_record,
    build_prop_research_card,
    exposure_group_id,
    load_frozen_context_profile,
    prepare_role_snapshot,
    prop_ledger_relative_path,
    simulate_prepared_props,
    write_prop_ledger,
)
from sportsedge.sports.nfl.prop_role_challenger import PropQuoteEvaluation

ROOT = Path(__file__).resolve().parents[1]


def _prior(**extra):
    return {
        "game_id": "game-2",
        "known_at": "2026-09-21T15:00:00Z",
        "pass_attempts": 34.0,
        "rush_attempts": 3.0,
        "targets": 8.0,
        **extra,
    }


def _history(game_id="game-1", known_at="2026-09-20T20:00:00Z", **extra):
    return {
        "game_id": game_id,
        "known_at": known_at,
        "pass_attempts": 31,
        "rush_attempts": 4,
        "targets": 7,
        **extra,
    }


def _evaluation(entity, market, ev, edge=0.04):
    return PropQuoteEvaluation(
        entity_id=entity,
        market=market,
        side="OVER",
        line=50.5,
        book="DraftKings",
        price_american=-110,
        estimate_p=0.58,
        estimate_p_nonpush=0.58,
        push_p=0.0,
        market_no_vig_p=0.50,
        edge_probability_points=edge,
        ev_per_dollar=ev,
    )


def test_context_config_is_versioned_and_hash_bound():
    profile = load_frozen_context_profile(ROOT)
    assert profile.version == "NFL_PROP_CONTEXT_V1"
    assert profile.profile_id == "NEUTRAL"
    assert len(profile.config_sha256) == 64
    assert profile.multipliers == {
        "pass_volume_multiplier": 1.0,
        "rush_volume_multiplier": 1.0,
        "target_multiplier": 1.0,
    }


def test_context_byte_change_fails_without_manifest_update(tmp_path):
    (tmp_path / "config/research").mkdir(parents=True)
    for name in ("nfl_prop_role_context_v1.json", "nfl_prop_role_context_manifest.json"):
        shutil.copy(ROOT / "config/research" / name, tmp_path / "config/research" / name)
    config_path = tmp_path / "config/research/nfl_prop_role_context_v1.json"
    config = json.loads(config_path.read_text())
    config["profiles"]["NEUTRAL"]["target_multiplier"] = 1.01
    config_path.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n")
    with pytest.raises(PropResearchLaneError, match="CONTEXT_CONFIG_SHA256_MISMATCH"):
        load_frozen_context_profile(tmp_path)


def test_pit_role_requires_asof_before_kickoff_and_known_at():
    with pytest.raises(PropResearchLaneError, match="ROLE_ASOF_MUST_PRECEDE_KICKOFF"):
        prepare_role_snapshot(
            root=ROOT,
            game_id="game-2",
            entity_id="qb1",
            kickoff_at="2026-09-21T18:00:00Z",
            as_of="2026-09-21T18:00:00Z",
            history=[_history()],
            projected_role=_prior(),
        )
    bad = _history()
    del bad["known_at"]
    with pytest.raises(PropResearchLaneError, match="PIT_KNOWN_AT_REQUIRED"):
        prepare_role_snapshot(
            root=ROOT,
            game_id="game-2",
            entity_id="qb1",
            kickoff_at="2026-09-21T18:00:00Z",
            as_of="2026-09-21T17:00:00Z",
            history=[bad],
            projected_role=_prior(),
        )


def test_same_game_realized_snaps_are_rejected_even_if_present_in_input():
    with pytest.raises(PropResearchLaneError, match="SAME_GAME_REALIZED_USAGE_FORBIDDEN"):
        prepare_role_snapshot(
            root=ROOT,
            game_id="game-2",
            entity_id="wr1",
            kickoff_at="2026-09-21T18:00:00Z",
            as_of="2026-09-21T17:00:00Z",
            history=[_history(game_id="game-2", actual_snaps=61)],
            projected_role=_prior(pass_attempts=0, rush_attempts=1, targets=7),
        )
    with pytest.raises(PropResearchLaneError, match="SAME_GAME_REALIZED_USAGE_FORBIDDEN"):
        prepare_role_snapshot(
            root=ROOT,
            game_id="game-2",
            entity_id="wr1",
            kickoff_at="2026-09-21T18:00:00Z",
            as_of="2026-09-21T17:00:00Z",
            history=[_history()],
            projected_role=_prior(pass_attempts=0, rush_attempts=1, targets=7, same_game_snap_share=0.86),
        )


def test_future_known_role_or_history_is_rejected():
    with pytest.raises(PropResearchLaneError, match="PIT_INPUT_AFTER_ASOF"):
        prepare_role_snapshot(
            root=ROOT,
            game_id="game-2",
            entity_id="rb1",
            kickoff_at="2026-09-21T18:00:00Z",
            as_of="2026-09-21T17:00:00Z",
            history=[_history(known_at="2026-09-21T17:00:01Z")],
            projected_role=_prior(pass_attempts=0, rush_attempts=15, targets=4),
        )


def test_valid_pit_role_binds_context_hash_and_simulates():
    prepared = prepare_role_snapshot(
        root=ROOT,
        game_id="game-2",
        entity_id="rb1",
        kickoff_at="2026-09-21T18:00:00Z",
        as_of="2026-09-21T17:00:00Z",
        history=[_history(pass_attempts=0, rush_attempts=12, targets=3)],
        projected_role=_prior(pass_attempts=0, rush_attempts=15, targets=4),
    )
    assert prepared.context_version == "NFL_PROP_CONTEXT_V1"
    assert len(prepared.context_sha256) == 64
    assert prepared.authority_footer == AUTHORITY_FOOTER
    efficiency = {
        "completion_rate": 0.65,
        "catch_rate": 0.70,
        "pass_td_rate": 0.04,
        "interception_rate": 0.02,
        "yards_per_attempt": 7.0,
        "yards_per_carry": 4.4,
        "yards_per_target": 7.8,
    }
    a = simulate_prepared_props(prepared, efficiency=efficiency, paths=100, seed=7)
    b = simulate_prepared_props(prepared, efficiency=efficiency, paths=100, seed=7)
    assert a.sha256 == b.sha256


def test_component_grouping_counts_correlated_rows_once_per_player_component():
    rows = [
        _evaluation("rb1", "RUSHING_YARDS", 0.09),
        _evaluation("rb1", "RECEIVING_YARDS", 0.08),
        _evaluation("rb1", "RUSH_RECEIVING_YARDS", 0.07),
        _evaluation("rb1", "PASSING_TDS", 0.06),
    ]
    card = build_prop_research_card(game_id="game-2", evaluations=rows)
    assert card.schema == PROP_CARD_SCHEMA
    assert len(card.rows) == 4
    assert card.independent_exposure_count == 2
    yardage_groups = {row.exposure_group_id for row in card.rows if row.component == "YARDAGE"}
    assert yardage_groups == {"game-2:rb1:YARDAGE"}
    assert exposure_group_id("game-2", "rb1", "PASSING_TDS") == "game-2:rb1:TD"


def test_different_players_are_distinct_exposure_groups():
    card = build_prop_research_card(
        game_id="game-2",
        evaluations=[
            _evaluation("rb1", "RUSHING_YARDS", 0.09),
            _evaluation("wr1", "RECEIVING_YARDS", 0.08),
        ],
    )
    assert card.independent_exposure_count == 2


def test_prop_card_and_ledger_are_separate_from_game_market_lane(tmp_path):
    card = build_prop_research_card(
        game_id="game-2",
        evaluations=[_evaluation("wr1", "RECEIVING_YARDS", 0.08)],
    )
    rendered = card.render()
    assert rendered.startswith("NFL PROPS — RESEARCH CARD")
    assert "NOT Model_P / NOT Truth Gate / NOT OFFICIAL" in rendered
    assert card.ledger_namespace == PROP_LEDGER_NAMESPACE
    assert "nfl_run_it" not in card.ledger_namespace

    record = build_prop_ledger_record(card, generated_at="2026-09-21T17:00:00Z")
    assert record["lane"] == "NFL_PROP_RESEARCH_ONLY"
    assert record["independent_exposure_count"] == 1
    assert not any(record["authority"].values())
    rel = prop_ledger_relative_path(record)
    assert rel.startswith(PROP_LEDGER_NAMESPACE + "/")
    assert "game_market" not in rel
    path = write_prop_ledger(tmp_path, record)
    assert path.relative_to(tmp_path).as_posix() == rel
    assert path.exists()
    assert write_prop_ledger(tmp_path, record) == path
