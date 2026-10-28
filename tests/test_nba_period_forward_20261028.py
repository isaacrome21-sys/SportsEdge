"""Tests for sportsedge/nba_period_forward.py — the NBA period-lines
forward wiring build (prereg draft PR #2843 §4.1/§6; feed admission
PR #2880). Offline: fixtures are the merged admission packet's pinned
samples plus synthetic records. The build is NOT FROZEN: counted entry
points must refuse by name and every output must stamp NON_COUNTED.
"""
import json
from pathlib import Path

import pytest

from sportsedge import nba_period_forward as fwd
from sportsedge.sports.nba.period_history import NBAPeriodObservation

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = (ROOT / "research/nba_quarter_score_feed_admission_20261028"
            / "sample_manifest.json")
SAMPLES = {e["espn_event_id"]: e
           for e in json.loads(MANIFEST.read_text(encoding="utf-8"))["samples"]}


def _record(**over):
    rec = {"game_id": "401909877",
           "tipoff": "2026-10-27T23:30:00+00:00",
           "observed_at": "2026-10-28T12:04:50+00:00",
           "home_quarters": [26, 30, 30, 31],
           "away_quarters": [31, 30, 21, 35],
           "source": "ESPN_SUMMARY_API",
           "source_version": "espn-summary-v1:20261028"}
    rec.update(over)
    return rec


# -- §4.1 form gate ------------------------------------------------------

def test_manifest_samples_all_pass_the_form_gate():
    obs = fwd.observations_from_admission_manifest(MANIFEST)
    assert len(obs) == 5
    assert all(isinstance(o, NBAPeriodObservation) for o in obs)
    by_id = {o.game_id: o for o in obs}
    # The overtime game: OT points (8/7) never enter the tuples.
    ot = by_id["401909877"]
    assert ot.home_quarters == (26, 30, 30, 31)
    assert ot.away_quarters == (31, 30, 21, 35)
    assert sum(ot.home_quarters) == 117  # final 125 includes the 8 OT points


def test_form_gate_refuses_wrong_source_by_name():
    with pytest.raises(fwd.NBAPeriodForwardError) as e:
        fwd.observation_from_record(_record(source="NBA_CDN"))
    assert e.value.reason == fwd.REFUSAL_SOURCE_NOT_ADMITTED
    with pytest.raises(fwd.NBAPeriodForwardError) as e:
        fwd.observation_from_record(_record(source_version="espn-summary-v2:20990101"))
    assert e.value.reason == fwd.REFUSAL_SOURCE_NOT_ADMITTED


@pytest.mark.parametrize("bad", [
    [26, 30, 30],                 # three quarters
    [26, 30, 30, 31, 8],          # overtime folded into the tuple
    [26, 30, 30, 31.0],           # float, even integral
    [26, 30, 30, True],           # bool
    [26, 30, 30, "31"],           # numeric string
    [26, 30, 30, -1],             # negative
])
def test_form_gate_refuses_nonconforming_quarters(bad):
    with pytest.raises(fwd.NBAPeriodForwardError) as e:
        fwd.observation_from_record(_record(home_quarters=bad))
    assert e.value.reason == fwd.REFUSAL_FORM_INVALID


def test_form_gate_refuses_naive_timestamps_and_bad_ids():
    with pytest.raises(fwd.NBAPeriodForwardError):
        fwd.observation_from_record(_record(tipoff="2026-10-27T23:30:00"))
    with pytest.raises(fwd.NBAPeriodForwardError):
        fwd.observation_from_record(_record(game_id=401909877))
    with pytest.raises(fwd.NBAPeriodForwardError):
        # observed before tipoff — a pregame "observation" is impossible
        fwd.observation_from_record(_record(observed_at="2026-10-27T20:00:00+00:00"))


def test_manifest_entry_cross_checks_are_rerun():
    entry = json.loads(json.dumps(SAMPLES["400579520"]))
    entry["home_half_scores"] = [56, 37]           # Q1+Q2 is 55, not 56
    with pytest.raises(fwd.NBAPeriodForwardError) as e:
        fwd.observation_from_manifest_entry(entry)
    assert e.value.reason == fwd.REFUSAL_HALF_SUM_MISMATCH

    entry = json.loads(json.dumps(SAMPLES["400579520"]))
    entry["home_final"] = 93                        # linescores sum to 92
    with pytest.raises(fwd.NBAPeriodForwardError) as e:
        fwd.observation_from_manifest_entry(entry)
    assert e.value.reason == fwd.REFUSAL_SCORE_MISMATCH


# -- game rows / priors ----------------------------------------------------

def test_game_row_from_entry_uses_full_finals_and_et_date():
    row = fwd.game_row_from_entry(SAMPLES["401909877"])   # BKN @ BOS, OT
    assert row["home"] == "BOS" and row["away"] == "BKN"
    assert row["home_pts"] == 125.0 and row["away_pts"] == 124.0  # incl. OT
    assert row["home_quarters"] == (26, 30, 30, 31)               # regulation only
    assert row["date"] == "2026-10-27" and row["season"] == 2026
    # 02:30Z tip is the prior ET evening's slate date.
    row2 = fwd.game_row_from_entry(SAMPLES["400579521"])  # DEN @ GS
    assert row2["date"] == "2015-04-15" and row2["home"] == "GSW"  # ESPN GS -> GSW


def test_history_filter_is_strictly_before():
    entries = list(SAMPLES.values())
    rows = fwd.history_from_entries(entries, before_date="2015-04-16")
    assert {r["game_id"] for r in rows} == {"400579520", "400579521"}
    rows = fwd.history_from_entries(entries, before_date="2015-04-15")
    assert rows == []     # same-slate games never enter priors


# -- NOT_FROZEN rails -------------------------------------------------------

def test_counted_entry_points_refuse_not_frozen():
    with pytest.raises(fwd.NBAPeriodForwardError) as e:
        fwd.price_period_game([], "BOS", "BKN", season=2026,
                              target_date="2026-10-28", counted=True)
    assert e.value.reason == "NBA_PERIOD_FORWARD_NOT_FROZEN"
    with pytest.raises(fwd.NBAPeriodForwardError) as e:
        fwd.price_counted_slate([])
    assert e.value.reason == "NBA_PERIOD_FORWARD_NOT_FROZEN"
    with pytest.raises(fwd.NBAPeriodForwardError) as e:
        fwd.run_forward_test()
    assert e.value.reason == "NBA_PERIOD_FORWARD_NOT_FROZEN"


# -- NON_COUNTED pricing + grading on synthetic history ---------------------

def _synthetic_history():
    """Four fictional teams, a 2014 fit span and a full 2026 season of
    admitted-form entries, built programmatically."""
    from datetime import date, timedelta
    teams = ["BOS", "BKN", "MIA", "NYK"]
    entries = []

    def entry(gid, d, season, home, away, hq, aq, hot=(), aot=()):
        hl, al = list(hq) + list(hot), list(aq) + list(aot)
        entries.append({
            "espn_event_id": gid, "engine_season": season,
            "home_team": home, "away_team": away,
            "home_linescores": hl, "away_linescores": al,
            "home_quarters_regulation": list(hq),
            "away_quarters_regulation": list(aq),
            "home_ot_periods": list(hot), "away_ot_periods": list(aot),
            "home_half_scores": [hq[0] + hq[1], hq[2] + hq[3]],
            "away_half_scores": [aq[0] + aq[1], aq[2] + aq[3]],
            "home_final": sum(hl), "away_final": sum(al),
            "observation": {
                "game_id": gid, "tipoff": f"{d.isoformat()}T00:30:00+00:00",
                "observed_at": f"{d.isoformat()}T12:00:00+00:00",
                "home_quarters": list(hq), "away_quarters": list(aq),
                "source": "ESPN_SUMMARY_API",
                "source_version": "espn-summary-v1:20261028"}})

    pairs = [("BOS", "BKN"), ("MIA", "NYK"), ("BOS", "MIA"), ("BKN", "NYK"),
             ("BOS", "NYK"), ("BKN", "MIA"), ("BKN", "BOS"), ("NYK", "MIA"),
             ("MIA", "BOS"), ("NYK", "BKN"), ("NYK", "BOS"), ("MIA", "BKN")]
    for i in range(8):     # frozen fit span (season 2014)
        h, a = pairs[i]
        entry(f"9000000{i:02d}", date(2014, 10, 28) + timedelta(days=3 * i), 2014,
              h, a, (25, 27, 26, 28), (24, 26, 25, 27))
    for i in range(120):   # 2026 season priors: 60 team-games each side of 200+
        h, a = pairs[i % len(pairs)]
        q = 20 + (i % 7)
        entry(f"9000010{i:03d}", date(2026, 10, 20) + timedelta(days=i // 4), 2026,
              h, a, (q, q + 1, q + 2, q + 1), (q - 1, q, q + 1, q))
    return entries


TARGET_ENTRY_DATE = "2026-12-25"


def _target_entry():
    entries = _synthetic_history()
    extra = []
    from datetime import date
    hl = {"espn_event_id": "900009999", "engine_season": 2026,
          "home_team": "BOS", "away_team": "BKN",
          "home_linescores": [30, 28, 26, 29], "away_linescores": [27, 25, 28, 24],
          "home_quarters_regulation": [30, 28, 26, 29],
          "away_quarters_regulation": [27, 25, 28, 24],
          "home_ot_periods": [], "away_ot_periods": [],
          "home_half_scores": [58, 55], "away_half_scores": [52, 52],
          "home_final": 113, "away_final": 104,
          "observation": {
              "game_id": "900009999", "tipoff": "2026-12-25T17:30:00+00:00",
              "observed_at": "2026-12-26T12:00:00+00:00",
              "home_quarters": [30, 28, 26, 29],
              "away_quarters": [27, 25, 28, 24],
              "source": "ESPN_SUMMARY_API",
              "source_version": "espn-summary-v1:20261028"}}
    return hl


def test_price_and_grade_non_counted_end_to_end():
    entries = _synthetic_history()
    history = fwd.history_from_entries(entries, before_date=TARGET_ENTRY_DATE)
    priced = fwd.price_period_game(history, "BOS", "BKN", season=2026,
                                   target_date=TARGET_ENTRY_DATE)
    assert priced["status"] == "PRICED"
    assert priced["periods"]["status"] == "PRICED"
    assert priced["counted"] is False
    assert priced["state"] == "NON_COUNTED"
    assert priced["freeze_state"] == "DRAFT_NOT_IN_FORCE"
    assert priced["play_eligible"] is False
    assert priced["forward_clock_credit"] is False

    graded = fwd.grade_period_game(priced, _target_entry())
    assert graded["status"] == "GRADED"
    assert graded["counted"] is False
    assert graded["actuals"]["game_quarters"] == [57, 53, 54, 53]
    assert graded["actuals"]["game_halves"] == [110, 107]
    for sub in fwd.SUBFAMILIES:
        assert graded["mae"][sub] is not None and graded["mae"][sub] >= 0


def test_grade_refuses_identity_mismatch():
    entries = _synthetic_history()
    history = fwd.history_from_entries(entries, before_date=TARGET_ENTRY_DATE)
    priced = fwd.price_period_game(history, "BOS", "BKN", season=2026,
                                   target_date=TARGET_ENTRY_DATE)
    wrong = _target_entry()
    wrong["away_team"] = "MIA"
    wrong["observation"] = dict(wrong["observation"])
    with pytest.raises(fwd.NBAPeriodForwardError) as e:
        fwd.grade_period_game(priced, wrong)
    assert e.value.reason == fwd.REFUSAL_GRADE_IDENTITY_MISMATCH


def test_grade_settles_closing_quotes_non_counted():
    entries = _synthetic_history()
    history = fwd.history_from_entries(entries, before_date=TARGET_ENTRY_DATE)
    priced = fwd.price_period_game(history, "BOS", "BKN", season=2026,
                                   target_date=TARGET_ENTRY_DATE)
    model_q1 = priced["periods"]["game_quarter_totals"][0]
    quotes = [{"subfamily": "GAME_QUARTER_TOTAL", "window": "Q1",
               "team": None, "status": "PRICED", "line": model_q1 - 2.5},
              {"subfamily": "GAME_QUARTER_TOTAL", "window": "Q2",
               "team": None, "status": "NOT_OFFERED", "line": None}]
    graded = fwd.grade_period_game(priced, _target_entry(),
                                   closing_quotes=quotes)
    assert len(graded["settlements"]) == 1     # NOT_OFFERED never settles
    s = graded["settlements"][0]
    assert s["counted"] is False and s["actual"] == 57
    assert s["result"] in ("WIN", "LOSS", "PUSH")
