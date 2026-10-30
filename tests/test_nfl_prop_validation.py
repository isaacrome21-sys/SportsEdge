from datetime import datetime, timedelta, timezone

import pytest

from sportsedge.sports.nfl.prop_validation import build_prop_walkforward_evidence


def _rows(player_id="p1", n=12):
    start = datetime(2025, 9, 1, 17, tzinfo=timezone.utc)
    rows = []
    for i in range(n):
        rows.append({
            "player_id": player_id,
            "game_id": f"g{i}",
            "kickoff_ts": (start + timedelta(days=7 * i)).isoformat(),
            "receptions": 3 + (i % 5),
            "receiving_yards": 40 + i * 3,
            "targets": 5 + (i % 4),
            "rushing_yards": 12 + i,
            "carries": 2 + (i % 6),
            "passing_yards": 210 + i * 4,
            "attempts": 28 + (i % 7),
            "completions": 18 + (i % 6),
            "passing_tds": i % 3,
            "passing_interceptions": i % 2,
            "rushing_tds": 1 if i in {2, 7, 10} else 0,
            "receiving_tds": 1 if i in {1, 5, 9} else 0,
        })
    return rows


def test_anytime_td_walkforward_is_diagnostic_only():
    evidence = build_prop_walkforward_evidence(
        _rows(),
        player_id="p1",
        market_id="ANYTIME_TD",
        source_manifest_sha256="a" * 64,
        min_games=6,
    )
    assert evidence["heldout_n"] == 6
    assert 0 <= evidence["metrics"]["brier"] <= 1
    assert evidence["promotion_eligible"] is False
    assert evidence["promotion_authority"] is False
    assert evidence["market_price_evidence_present"] is False
    assert "CLV" in evidence["missing_promotion_evidence"]


def test_receiving_yards_walkforward_has_out_of_sample_errors():
    evidence = build_prop_walkforward_evidence(
        _rows(),
        player_id="p1",
        market_id="RECEIVING_YARDS",
        source_manifest_sha256="b" * 64,
        min_games=6,
    )
    assert evidence["heldout_n"] == 6
    assert evidence["metrics"]["mae"] >= 0
    assert evidence["metrics"]["rmse"] >= 0
    assert evidence["truth_gate_eligible"] is False


def test_future_rows_do_not_enter_earlier_fit():
    base = _rows(n=10)
    evidence_a = build_prop_walkforward_evidence(
        base,
        player_id="p1",
        market_id="RECEPTIONS",
        source_manifest_sha256="c" * 64,
        min_games=6,
    )
    mutated = list(base)
    mutated[-1] = dict(mutated[-1])
    mutated[-1]["receptions"] = 99
    evidence_b = build_prop_walkforward_evidence(
        mutated,
        player_id="p1",
        market_id="RECEPTIONS",
        source_manifest_sha256="c" * 64,
        min_games=6,
    )
    assert evidence_a["predictions"][:-1] == evidence_b["predictions"][:-1]


def test_validation_refuses_no_heldout_rows():
    with pytest.raises(ValueError, match="PROP_VALIDATION_NO_HELDOUT_ROWS"):
        build_prop_walkforward_evidence(
            _rows(n=6),
            player_id="p1",
            market_id="RECEPTIONS",
            source_manifest_sha256="d" * 64,
            min_games=6,
        )
