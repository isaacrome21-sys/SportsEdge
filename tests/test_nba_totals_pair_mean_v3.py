"""Strict chronological and research-only behavior of NBA totals V3."""
from datetime import datetime, timedelta, timezone
import math
import unittest

from scripts.research_nba_totals_pair_mean_v3_screen import score_archive
from sportsedge.research.nba_scoring_level_v2 import predict_total as v2_predict
from sportsedge.research.nba_totals_pair_mean_v3 import predict_total as v3_predict


def _history(count=40):
    base = datetime(2026, 7, 1, 23, tzinfo=timezone.utc)
    rows = []
    for n in range(count):
        tip = base + timedelta(days=n)
        rows.append({"game_id": f"g-{n}", "source_ref": f"box-{n}",
                     "tipoff": tip.isoformat(),
                     "observed_at": (tip + timedelta(hours=5)).isoformat(),
                     "home": "A" if n % 2 == 0 else "B",
                     "away": "B" if n % 2 == 0 else "A",
                     "home_pts": 109 + n % 13, "away_pts": 100 + n % 11})
    return rows


def _asof(rows):
    return (datetime.fromisoformat(rows[-1]["observed_at"])
            + timedelta(hours=6)).isoformat()


def _test_pair_mean_exact_construction_and_no_card_authority():
    rows = _history()
    parent = v2_predict(rows, home="A", away="B", as_of=_asof(rows))
    v3 = v3_predict(rows, home="A", away="B", as_of=_asof(rows))
    league = parent["league_points_per_team"]
    assert parent["status"] == v3["status"] == "RESEARCH_PROJECTION"
    assert math.isclose(v3["predicted_total"],
                        2*league + (parent["predicted_total"] - 2*league)/2)
    assert v3["parent_v2_total"] == parent["predicted_total"]
    assert v3["play_authority"] is False and v3["research_only"] is True
    assert v3["market_test"] == "NOT_ADMITTED_HISTORICAL_REFERENCE"
    assert v3["activation_status"] == "INELIGIBLE_FAILED_EXPLORATORY_SCREEN"


def _test_future_results_excluded_without_backfill():
    rows = _history()
    asof = _asof(rows)
    before = v3_predict(rows, home="A", away="B", as_of=asof)
    future_tip = datetime.fromisoformat(asof) + timedelta(days=1)
    rows.append({"game_id": "future", "source_ref": "future-box",
                 "tipoff": future_tip.isoformat(),
                 "observed_at": (future_tip + timedelta(hours=5)).isoformat(),
                 "home": "A", "away": "B", "home_pts": 190, "away_pts": 190})
    after = v3_predict(rows, home="A", away="B", as_of=asof)
    assert before["predicted_total"] == after["predicted_total"]
    assert after["future_excluded"] == 1


def _test_input_refusals_inherited(invalid):
    rows = _history()
    if invalid == "no_source":
        rows[-1].pop("source_ref")
    elif invalid == "fake_observed":
        rows[-1]["observed_at"] = rows[-1]["tipoff"]
    else:
        rows[-1]["game_id"] = rows[0]["game_id"]
    try:
        v3_predict(rows, home="A", away="B", as_of="2026-09-01T13:00:00Z")
    except ValueError as exc:
        assert "NBA_TOTALS_" in str(exc)
    else:
        raise AssertionError("V3 accepted invalid PIT history")


def _test_insufficient_history_retains_refusal():
    rows = _history(4)
    result = v3_predict(rows, home="A", away="B", as_of=_asof(rows))
    assert result["status"] == "REFUSED"
    assert result["reason"] == "NBA_TOTALS_INSUFFICIENT_PIT_HISTORY"
    assert result["play_authority"] is False


def _archive(market=221.5):
    rows = []
    for n in range(40):
        day = datetime(2014, 11, 1, tzinfo=timezone.utc) + timedelta(days=n)
        rows.append({"home_team": "Alpha", "away_team": "Beta",
                     "home_final": 105+n%7, "away_final": 110+n%5,
                     "season": 2014, "date": int(day.strftime("%Y%m%d")),
                     "close_over_under": 220.5})
    rows.append({"home_team": "Alpha", "away_team": "Beta",
                 "home_final": 104, "away_final": 117, "season": 2015,
                 "date": 20150110, "close_over_under": market})
    return rows


def _test_reference_not_used_to_predict():
    a = score_archive(_archive(221.5), begin=2015, end=2015,
                      require_parent_reference_parity=False)
    b = score_archive(_archive(251.5), begin=2015, end=2015,
                      require_parent_reference_parity=False)
    assert a["paired_games"] == b["paired_games"] == 1
    assert a["v3_rmse_paired"] == b["v3_rmse_paired"]
    assert a["v2_rmse_paired"] == b["v2_rmse_paired"]
    assert a["indicative_reference_rmse_paired"] != b["indicative_reference_rmse_paired"]
    assert a["eligible_for_card"] is False and a["promotion_authority"] is False


def _test_same_day_outcome_not_leaked_into_forecast():
    rows = _archive()
    rows.append({"home_team": "Gamma", "away_team": "Delta",
                 "home_final": 200, "away_final": 200, "season": 2015,
                 "date": 20150110, "close_over_under": None})
    before = score_archive(_archive(), begin=2015, end=2015,
                           require_parent_reference_parity=False)
    after = score_archive(rows, begin=2015, end=2015,
                          require_parent_reference_parity=False)
    assert before["v3_rmse_paired"] == after["v3_rmse_paired"]
    assert before["v2_rmse_paired"] == after["v2_rmse_paired"]


class TestNbaTotalsPairMeanV3(unittest.TestCase):
    def test_pair_mean_construction(self):
        _test_pair_mean_exact_construction_and_no_card_authority()

    def test_future_exclusion(self):
        _test_future_results_excluded_without_backfill()

    def test_input_refusals(self):
        for invalid in ("no_source", "fake_observed", "duplicate"):
            with self.subTest(invalid=invalid):
                _test_input_refusals_inherited(invalid)

    def test_history_refusal(self):
        _test_insufficient_history_retains_refusal()

    def test_market_independence(self):
        _test_reference_not_used_to_predict()

    def test_same_day_result_exclusion(self):
        _test_same_day_outcome_not_leaked_into_forecast()


if __name__ == "__main__":
    unittest.main()
