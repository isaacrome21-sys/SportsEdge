from copy import deepcopy

import pytest

from sportsedge.sports.nfl.prop_engines import (
    ENGINE_CONTRACT,
    PropEngineError,
    fit_nfl_prop_engine,
    predict_nfl_prop,
)

SHA = "a" * 64


def _rows(player="p1"):
    out = []
    for i in range(12):
        out.append({
            "player_id": player,
            "game_id": f"g{i:02d}",
            "kickoff_ts": f"2025-{(i // 4) + 9:02d}-{(i % 4) + 1:02d}T18:00:00+00:00",
            "receptions": 3 + i % 5,
            "receiving_yards": 28 + i * 6,
            "targets": 5 + i % 6,
            "rushing_yards": 12 + i * 4,
            "carries": 4 + i % 8,
            "passing_yards": 215 + i * 7,
            "attempts": 29 + i % 8,
            "completions": 18 + i % 7,
            "passing_tds": i % 4,
            "passing_interceptions": i % 2,
            "rushing_tds": 1 if i in {2, 8} else 0,
            "receiving_tds": 1 if i in {1, 4, 10} else 0,
        })
    return out


def test_anytime_td_engine_creates_experimental_model_p_without_price():
    model = fit_nfl_prop_engine(
        _rows(), player_id="p1", market_id="ANYTIME_TD",
        as_of="2026-09-12T12:00:00+00:00", source_manifest_sha256=SHA,
    )
    pred = predict_nfl_prop(
        model, side="YES", availability_status="ACTIVE", role_confirmed=True,
    )
    assert pred.contract == ENGINE_CONTRACT
    assert pred.model_p_status == "EXPERIMENTAL_MODEL_P"
    assert 0 < pred.model_probability < 1
    assert pred.line is None
    assert pred.push_probability == 0
    assert pred.promotion_eligible is False
    assert pred.truth_gate_eligible is False


def test_count_engine_returns_over_under_and_push_mass():
    model = fit_nfl_prop_engine(
        _rows(), player_id="p1", market_id="RECEPTIONS",
        as_of="2026-09-12T12:00:00+00:00", source_manifest_sha256=SHA,
    )
    over = predict_nfl_prop(model, side="OVER", line=5.0, availability_status="EXPECTED_ACTIVE", role_confirmed=True)
    under = predict_nfl_prop(model, side="UNDER", line=5.0, availability_status="EXPECTED_ACTIVE", role_confirmed=True)
    assert 0 <= over.model_probability <= 1
    assert 0 <= under.model_probability <= 1
    assert over.push_probability > 0
    assert over.model_probability + under.model_probability + over.push_probability == pytest.approx(1.0, abs=1e-6)


def test_half_point_count_has_no_push():
    model = fit_nfl_prop_engine(
        _rows(), player_id="p1", market_id="PASS_ATTEMPTS",
        as_of="2026-09-12T12:00:00+00:00", source_manifest_sha256=SHA,
    )
    over = predict_nfl_prop(
        model, side="OVER", line=32.5, availability_status="ACTIVE",
        role_confirmed=True, starting_qb_confirmed=True,
    )
    under = predict_nfl_prop(
        model, side="UNDER", line=32.5, availability_status="ACTIVE",
        role_confirmed=True, starting_qb_confirmed=True,
    )
    assert over.push_probability == 0
    assert over.model_probability + under.model_probability == pytest.approx(1.0, abs=1e-6)


def test_yardage_engine_probability_is_bounded():
    model = fit_nfl_prop_engine(
        _rows(), player_id="p1", market_id="RECEIVING_YARDS",
        as_of="2026-09-12T12:00:00+00:00", source_manifest_sha256=SHA,
    )
    pred = predict_nfl_prop(model, side="OVER", line=62.5, availability_status="ACTIVE", role_confirmed=True)
    assert 0 <= pred.model_probability <= 1
    assert pred.fair_american_odds is None or isinstance(pred.fair_american_odds, int)


def test_fit_is_point_in_time_and_future_rows_do_not_change_model():
    rows = _rows()
    base = fit_nfl_prop_engine(
        rows, player_id="p1", market_id="RECEPTIONS",
        as_of="2026-01-01T00:00:00+00:00", source_manifest_sha256=SHA,
    )
    future = deepcopy(rows)
    future.append({**rows[-1], "game_id": "future", "kickoff_ts": "2026-02-01T18:00:00+00:00", "receptions": 99})
    mutated = fit_nfl_prop_engine(
        future, player_id="p1", market_id="RECEPTIONS",
        as_of="2026-01-01T00:00:00+00:00", source_manifest_sha256=SHA,
    )
    assert base == mutated


def test_market_data_is_rejected_from_fit_even_nested():
    rows = _rows()
    rows[0]["price"] = -115
    with pytest.raises(PropEngineError, match="PROP_MARKET_DATA_PROHIBITED"):
        fit_nfl_prop_engine(rows, player_id="p1", market_id="RECEPTIONS", as_of="2026-09-12T12:00:00+00:00", source_manifest_sha256=SHA)

    rows = _rows()
    rows[0]["meta"] = {"handle": 71}
    with pytest.raises(PropEngineError, match="PROP_MARKET_DATA_PROHIBITED"):
        fit_nfl_prop_engine(rows, player_id="p1", market_id="RECEPTIONS", as_of="2026-09-12T12:00:00+00:00", source_manifest_sha256=SHA)


def test_passing_markets_require_confirmed_starting_qb():
    model = fit_nfl_prop_engine(
        _rows(), player_id="p1", market_id="PASSING_YARDS",
        as_of="2026-09-12T12:00:00+00:00", source_manifest_sha256=SHA,
    )
    with pytest.raises(PropEngineError, match="PROP_STARTING_QB_UNCONFIRMED"):
        predict_nfl_prop(model, side="OVER", line=249.5, availability_status="ACTIVE", role_confirmed=True)


def test_role_and_availability_fail_closed():
    model = fit_nfl_prop_engine(
        _rows(), player_id="p1", market_id="RUSHING_YARDS",
        as_of="2026-09-12T12:00:00+00:00", source_manifest_sha256=SHA,
    )
    with pytest.raises(PropEngineError, match="PROP_ROLE_UNCONFIRMED"):
        predict_nfl_prop(model, side="OVER", line=45.5, availability_status="ACTIVE", role_confirmed=False)
    with pytest.raises(PropEngineError, match="PROP_PLAYER_AVAILABILITY_BLOCKED"):
        predict_nfl_prop(model, side="OVER", line=45.5, availability_status="QUESTIONABLE", role_confirmed=True)
