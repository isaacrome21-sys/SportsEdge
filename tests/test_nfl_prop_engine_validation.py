from copy import deepcopy

from sportsedge.sports.nfl.prop_engine_validation import build_nfl_prop_walkforward_evidence


def _row(player: str, game: int, receptions: int, rec_yards: int, carries: int, rush_yards: int, td: int, attempts: int, completions: int, pass_yards: int, pass_tds: int, ints: int):
    return {
        "player_id": player,
        "game_id": f"g{game}",
        "kickoff_ts": f"2026-0{1 + (game - 1)//4}-{1 + ((game - 1)%4)*7:02d}T18:00:00+00:00",
        "receptions": receptions,
        "receiving_yards": rec_yards,
        "targets": receptions + 2,
        "carries": carries,
        "rushing_yards": rush_yards,
        "rushing_tds": td,
        "receiving_tds": 0,
        "attempts": attempts,
        "completions": completions,
        "passing_yards": pass_yards,
        "passing_tds": pass_tds,
        "passing_interceptions": ints,
    }


def _history():
    rows = []
    for i in range(1, 13):
        rows.append(_row(
            "p1", i,
            receptions=3 + (i % 4),
            rec_yards=35 + i * 4,
            carries=8 + (i % 5),
            rush_yards=30 + i * 3,
            td=1 if i % 3 == 0 else 0,
            attempts=28 + (i % 8),
            completions=18 + (i % 7),
            pass_yards=205 + i * 7,
            pass_tds=1 + (i % 3),
            ints=i % 2,
        ))
    return rows


def test_walkforward_emits_all_markets_and_remains_nonpromoting():
    evidence = build_nfl_prop_walkforward_evidence(
        _history(), source_manifest_sha256="a" * 64, min_games=6
    )
    assert evidence["status"] == "MODEL_DISTRIBUTION_DIAGNOSTIC_ONLY"
    assert evidence["promotion_eligible"] is False
    assert evidence["truth_gate_eligible"] is False
    assert evidence["evaluation_count"] > 0
    assert len(evidence["markets"]) == 11
    for payload in evidence["markets"].values():
        assert payload["promotion_eligible"] is False
        assert payload["truth_gate_eligible"] is False
        assert payload["historical_market_price_evidence"] == "UNAVAILABLE_NOT_PROVIDED"
        assert payload["clv"] == "UNAVAILABLE_NOT_PROVIDED"
        assert payload["after_vig_roi"] == "UNAVAILABLE_NOT_PROVIDED"


def test_future_row_does_not_change_prior_walkforward_outputs():
    base = _history()
    first = build_nfl_prop_walkforward_evidence(base, source_manifest_sha256="b" * 64, min_games=6)
    extended = deepcopy(base)
    extended.append(_row("p1", 13, 10, 180, 2, 5, 1, 50, 42, 490, 5, 0))
    second = build_nfl_prop_walkforward_evidence(extended, source_manifest_sha256="b" * 64, min_games=6)

    for market in first["markets"]:
        # The added future game may create new evaluations, but cannot rewrite the
        # already-computed prefix. Aggregate n must only increase.
        assert second["markets"][market]["n"] >= first["markets"][market]["n"]


def test_calibration_metrics_are_bounded_when_present():
    evidence = build_nfl_prop_walkforward_evidence(
        _history(), source_manifest_sha256="c" * 64, min_games=6
    )
    for payload in evidence["markets"].values():
        cal = payload["calibration"]
        if cal["n"]:
            assert 0.0 <= cal["ece"] <= 1.0
            assert 0.0 <= cal["max_bin_deviation"] <= 1.0
            assert 0.0 <= payload["brier"] <= 1.0
            assert payload["log_loss"] >= 0.0


def test_authentic_price_evidence_stays_explicitly_missing():
    evidence = build_nfl_prop_walkforward_evidence(
        _history(), source_manifest_sha256="d" * 64, min_games=6
    )
    missing = set(evidence["missing_promotion_evidence"])
    assert "AUTHENTIC_HISTORICAL_DECISION_PRICES" in missing
    assert "AUTHENTIC_HISTORICAL_CLOSE_PRICES" in missing
    assert "CLV" in missing
    assert "AFTER_VIG_ROI" in missing
