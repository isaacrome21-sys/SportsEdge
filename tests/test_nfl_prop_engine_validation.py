from copy import deepcopy

from sportsedge.sports.nfl.prop_engine_validation import build_nfl_prop_walkforward_evidence


def _row(player: str, game: int, receptions: int, rec_yards: int, carries: int, rush_yards: int, td: int, attempts: int, completions: int, pass_yards: int, pass_tds: int, ints: int):
    month = 1 + (game - 1) // 4
    day = 1 + ((game - 1) % 4) * 7
    date = f"2026-{month:02d}-{day:02d}"
    return {
        "player_id": player,
        "game_id": f"g{game}",
        "kickoff_ts": f"{date}T18:00:00+00:00",
        "availability_status": "ACTIVE",
        "availability_asof_ts": f"{date}T16:30:00+00:00",
        "role_confirmed": True,
        "role_confirmed_at": f"{date}T17:00:00+00:00",
        "starting_qb_confirmed": True,
        "starting_qb_confirmed_at": f"{date}T17:00:00+00:00",
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
    assert evidence["pit_confirmation_contract"] == "PREKICKOFF_AVAILABILITY_ROLE_AND_STARTING_QB_WHEN_APPLICABLE"
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


def test_missing_role_confirmation_fails_closed_for_all_heldout_rows():
    rows = _history()
    for row in rows:
        row.pop("role_confirmed_at")
    evidence = build_nfl_prop_walkforward_evidence(
        rows, source_manifest_sha256="e" * 64, min_games=6
    )
    assert evidence["evaluation_count"] == 0
    assert any("PROP_PIT_ROLE_CONFIRMED_AT_REQUIRED" in key for key in evidence["skipped"])


def test_missing_starting_qb_confirmation_blocks_passing_only():
    rows = _history()
    for row in rows:
        row.pop("starting_qb_confirmed_at")
    evidence = build_nfl_prop_walkforward_evidence(
        rows, source_manifest_sha256="f" * 64, min_games=6
    )
    assert evidence["markets"]["RECEPTIONS"]["n"] > 0
    for market in ("PASSING_YARDS", "PASS_ATTEMPTS", "COMPLETIONS", "PASSING_TDS", "INTERCEPTIONS"):
        assert evidence["markets"][market]["n"] == 0
    assert any("PROP_PIT_STARTING_QB_CONFIRMED_AT_REQUIRED" in key for key in evidence["skipped"])


def test_post_kickoff_role_confirmation_is_rejected():
    rows = _history()
    for row in rows:
        row["role_confirmed_at"] = row["kickoff_ts"]
    evidence = build_nfl_prop_walkforward_evidence(
        rows, source_manifest_sha256="1" * 64, min_games=6
    )
    assert evidence["evaluation_count"] == 0
    assert any("PROP_PIT_ROLE_CONFIRMED_AT_NOT_PREKICKOFF" in key for key in evidence["skipped"])


def test_authentic_price_evidence_stays_explicitly_missing_but_pit_role_is_enforced():
    evidence = build_nfl_prop_walkforward_evidence(
        _history(), source_manifest_sha256="d" * 64, min_games=6
    )
    missing = set(evidence["missing_promotion_evidence"])
    assert "AUTHENTIC_HISTORICAL_DECISION_PRICES" in missing
    assert "AUTHENTIC_HISTORICAL_CLOSE_PRICES" in missing
    assert "CLV" in missing
    assert "AFTER_VIG_ROI" in missing
    assert "ROLE_AND_STARTER_PIT_CONFIRMATION_EVIDENCE" not in missing
