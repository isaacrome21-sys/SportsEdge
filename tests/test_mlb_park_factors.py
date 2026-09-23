from __future__ import annotations

from datetime import date

from sportsedge.mlb_park_factors import (
    build_park_factors,
    normalize_game_venues,
    prepare_park_history,
)


def _pa(
    *,
    game_pk: int,
    game_date: str,
    event: str,
    stand: str,
    home_score: int | None = None,
    away_score: int | None = None,
) -> dict:
    row = {
        "game_pk": game_pk,
        "game_date": game_date,
        "events": event,
        "stand": stand,
    }
    if home_score is not None:
        row["post_home_score"] = home_score
    if away_score is not None:
        row["post_away_score"] = away_score
    return row


def _history(*, include_scores: bool = True) -> tuple[list[dict], dict[int, int]]:
    rows: list[dict] = []
    venues: dict[int, int] = {}
    # Venue 1 is intentionally HR/run friendly; Venue 2 is intentionally suppressive.
    # Each game has 40 terminal PAs, split evenly L/R.
    for venue_id in (1, 2):
        for game_index in range(8):
            game_pk = venue_id * 1000 + game_index
            venues[game_pk] = venue_id
            game_date = f"2026-09-{10 + game_index:02d}"
            for pa_index in range(40):
                stand = "L" if pa_index % 2 == 0 else "R"
                if venue_id == 1:
                    # LHB HR 4/20; RHB HR 2/20 per game.
                    if stand == "L" and pa_index in {0, 2, 4, 6}:
                        event = "home_run"
                    elif stand == "R" and pa_index in {1, 3}:
                        event = "home_run"
                    elif pa_index % 7 == 0:
                        event = "double"
                    elif pa_index % 3 == 0:
                        event = "single"
                    else:
                        event = "field_out"
                    final_home, final_away = 7, 5
                else:
                    # One LHB HR and no RHB HR per game.
                    if pa_index == 0:
                        event = "home_run"
                    elif pa_index % 11 == 0:
                        event = "double"
                    elif pa_index % 5 == 0:
                        event = "single"
                    else:
                        event = "field_out"
                    final_home, final_away = 2, 1
                is_last = pa_index == 39
                rows.append(_pa(
                    game_pk=game_pk,
                    game_date=game_date,
                    event=event,
                    stand=stand,
                    home_score=final_home if include_scores and is_last else None,
                    away_score=final_away if include_scores and is_last else None,
                ))
    return rows, venues


def _build(rows: list[dict], venues: dict[int, int], venue_id: int, **overrides):
    kwargs = {
        "pitch_rows": rows,
        "game_venues": venues,
        "target_date": date(2026, 9, 22),
        "venue_id": venue_id,
        "lookback_days": 365,
        "min_venue_pa": 100,
        "min_hand_pa": 50,
        "min_venue_games": 4,
        "prior_equivalent_pa": 100,
        "prior_equivalent_hand_pa": 50,
        "prior_equivalent_games": 4,
    }
    kwargs.update(overrides)
    return build_park_factors(**kwargs)


def test_normalize_game_venues_accepts_mapping_and_rows():
    assert normalize_game_venues({"10": {"venue_id": "17"}, 20: 22}) == {10: 17, 20: 22}
    assert normalize_game_venues([
        {"game_pk": 10, "venue_id": 17},
        {"gamePk": 20, "venueId": 22},
    ]) == {10: 17, 20: 22}


def test_prepare_history_is_strictly_prior_and_tracks_target_day_exclusion():
    rows, venues = _history()
    venues[9999] = 1
    rows.append(_pa(
        game_pk=9999,
        game_date="2026-09-22",
        event="home_run",
        stand="L",
        home_score=20,
        away_score=20,
    ))
    selected, games, counts = prepare_park_history(
        rows,
        game_venues=venues,
        target_date=date(2026, 9, 22),
        lookback_days=365,
    )
    assert all(row["game_date"] < "2026-09-22" for row in selected)
    assert 9999 not in games
    assert counts["future_or_target_date_excluded"] == 1


def test_friendly_and_suppressive_venues_separate_after_shrinkage():
    rows, venues = _history()
    friendly = _build(rows, venues, 1)
    suppressive = _build(rows, venues, 2)

    assert friendly["status"] == "AVAILABLE"
    assert suppressive["status"] == "AVAILABLE"
    assert friendly["values"]["park_hr_factor"] > 1.0
    assert suppressive["values"]["park_hr_factor"] < 1.0
    assert friendly["values"]["park_runs_factor"] > 1.0
    assert suppressive["values"]["park_runs_factor"] < 1.0
    assert friendly["values"]["park_hr_factor_lhb"] > friendly["values"]["park_hr_factor_rhb"]
    assert friendly["model_p_eligible"] is False
    assert friendly["promotion_status"] == "RESEARCH_ONLY_UNTIL_TEMPORAL_VALIDATION"


def test_target_day_rows_cannot_change_factor_or_source_hash():
    rows, venues = _history()
    baseline = _build(rows, venues, 1)

    leaked = list(rows)
    leaked_venues = dict(venues)
    leaked_venues[9999] = 1
    for i in range(200):
        leaked.append(_pa(
            game_pk=9999,
            game_date="2026-09-22",
            event="home_run",
            stand="L" if i % 2 == 0 else "R",
            home_score=40 if i == 199 else None,
            away_score=40 if i == 199 else None,
        ))
    guarded = _build(leaked, leaked_venues, 1)

    assert guarded["values"] == baseline["values"]
    assert guarded["source_subset_sha256"] == baseline["source_subset_sha256"]
    assert guarded["exclusions"]["future_or_target_date_excluded"] == 200


def test_sample_gate_fails_closed_instead_of_emitting_small_sample_factor():
    rows, venues = _history()
    result = _build(rows, venues, 1, min_venue_pa=1000, min_hand_pa=500)
    assert result["status"] == "INCOMPLETE"
    assert result["values"]["park_hr_factor"] is None
    assert result["values"]["park_hr_factor_lhb"] is None
    assert result["values"]["park_hr_factor_rhb"] is None
    assert "park_hr_factor" in result["missing_factors"]


def test_runs_factor_fails_closed_when_historical_scores_are_missing():
    rows, venues = _history(include_scores=False)
    result = _build(rows, venues, 1)
    assert result["status"] == "INCOMPLETE"
    assert result["values"]["park_runs_factor"] is None
    assert result["sample"]["venue_scored_games"] == 0
    assert result["sample"]["league_scored_games"] == 0
    # Event-rate factors are still measurable; missing scores do not erase them.
    assert result["values"]["park_hr_factor"] is not None
    assert result["model_p_eligible"] is False
