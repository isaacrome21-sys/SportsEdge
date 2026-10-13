"""Offline, no-fetch regression tests for MLB batter game-log loss diagnostics."""
from datetime import datetime, timezone
import json

import pytest

from scripts.audit_mlb_batter_gamelog_losses import audit_gamelog

AS_OF = "2026-10-13T16:00:00Z"
KICKOFF = "2026-10-14T00:00:00Z"
OBSERVED = "2026-10-13T15:59:00Z"


def _row(i, *, date=None, **overrides):
    stat = {
        "plateAppearances": 4,
        "hits": 1,
        "totalBases": 1,
        "rbi": 0,
        "runs": 0,
        "homeRuns": 0,
        "stolenBases": 0,
    }
    stat.update(overrides)
    return {
        "date": date or f"2026-09-{i+1:02d}",
        "game": {"gamePk": 800001 + i},
        "stat": stat,
    }


def _audit(rows, **kwargs):
    return audit_gamelog(
        {"stats": [{"splits": rows}]},
        as_of_utc=kwargs.pop("as_of_utc", AS_OF),
        kickoff_utc=kwargs.pop("kickoff_utc", KICKOFF),
        observed_at_utc=kwargs.pop("observed_at_utc", OBSERVED),
        **kwargs,
    )


def test_clean_history_meets_current_source_minimum_without_model_authority():
    report = _audit([_row(i) for i in range(12)])
    assert report["retained_prior_games"] == 12
    assert report["retained_plate_appearances"] == 48
    assert report["history_minimum_met"] is True
    assert report["diagnostic_only"] is True
    assert report["independent_model_validation"] is False
    assert report["backfilled_evidence"] is False
    assert report["rejected_row_counts"] == {}


def test_missing_total_bases_explains_loss_for_all_current_batter_markets():
    rows = [_row(i) for i in range(12)]
    for row in rows[:9]:
        del row["stat"]["totalBases"]
    report = _audit(rows)
    assert report["retained_prior_games"] == 3
    assert report["rejected_row_counts"]["TOTALBASES_INVALID"] == 9
    assert report["history_minimum_met"] is False


def test_optional_walk_strikeout_double_and_triple_fields_do_not_drop_core_history():
    report = _audit([_row(i) for i in range(10)])
    assert report["history_minimum_met"] is True
    assert report["per_field_retained_game_count"]["baseOnBalls"] == 0
    assert report["per_field_retained_game_count"]["hits"] == 10
    assert report["per_field_retained_game_count"]["strikeOuts"] == 0


def test_missing_optional_stat_is_reported_as_coverage_not_zero():
    rows = [_row(i, baseOnBalls=2) for i in range(10)]
    del rows[0]["stat"]["baseOnBalls"]
    report = _audit(rows)
    assert report["per_field_retained_game_count"]["baseOnBalls"] == 9
    assert report["retained_prior_games"] == 10


def test_zero_pa_not_falsely_counted_as_valid_game():
    rows = [_row(i) for i in range(10)]
    rows[3]["stat"]["plateAppearances"] = 0
    report = _audit(rows)
    assert report["retained_prior_games"] == 9
    assert report["rejected_row_counts"]["ZERO_PLATE_APPEARANCES"] == 1


def test_future_and_same_day_rows_never_become_prior_batter_evidence():
    rows = [_row(i) for i in range(10)] + [
        _row(15, date="2026-10-13"),
        _row(16, date="2026-10-14"),
    ]
    report = _audit(rows)
    assert report["retained_prior_games"] == 10
    assert report["rejected_row_counts"]["NOT_PRIOR_TO_AS_OF_DATE"] == 2


def test_duplicate_game_id_does_not_increase_sample():
    rows = [_row(i) for i in range(10)]
    rows.append(dict(rows[0]))
    report = _audit(rows)
    assert report["retained_prior_games"] == 10
    assert report["rejected_row_counts"]["DUPLICATE_GAME_PK"] == 1


def test_extra_base_hit_inconsistency_fails_closed():
    rows = [_row(i) for i in range(10)]
    rows[0]["stat"]["doubles"] = 2
    rows[0]["stat"]["triples"] = 1
    report = _audit(rows)
    assert report["retained_prior_games"] == 9
    assert report["rejected_row_counts"]["INCONSISTENT_EXTRA_BASE_HIT_COUNTS"] == 1


def test_invalid_core_stat_is_distinct_from_missing_optional_stat():
    rows = [_row(i) for i in range(10)]
    rows[0]["stat"]["hits"] = -1
    report = _audit(rows)
    assert report["retained_prior_games"] == 9
    assert report["rejected_row_counts"]["HITS_INVALID"] == 1


def test_observation_timestamp_cannot_claim_historical_pit_receipt():
    rows = [_row(i) for i in range(10)]
    report = _audit(rows, observed_at_utc="2026-10-13T18:00:00Z")
    assert report["capture_clock_precedes_as_of_and_kickoff"] is False
    assert report["history_minimum_met"] is True
    assert report["diagnostic_only"] is True


def test_missing_stats_object_never_produces_eligible_history():
    with pytest.raises(ValueError, match="MLB_BATTER_GAMELOG_UNAVAILABLE"):
        audit_gamelog({}, as_of_utc=AS_OF, kickoff_utc=KICKOFF,
                      observed_at_utc=OBSERVED)


def test_naive_observed_clock_is_rejected():
    with pytest.raises(ValueError, match="OBSERVED_AT_TIMEZONE_REQUIRED"):
        _audit([_row(i) for i in range(10)],
               observed_at_utc="2026-10-13T15:00:00")
