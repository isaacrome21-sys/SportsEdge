"""NBA player-props forward-test evaluator tests (Oct 20, 2026).

Run: python3 -m pytest tests/test_nba_props_forward_evaluator_20261020.py

The evaluator under test is the §12 implementation of the FROZEN
preregistration research/nba_props_forward_20261020/
PREREG_NBA_PROPS_FORWARD_V1.md (sha256 54363908b1e2332a57af9b9263ac2f398438c81b2d366442b80667086657bc79).
Coverage: the four frozen family configs and their hash pin; the §6
CLV definition (hand-checked); the §7 close rule (exactly 60:00
readable, 60:01 stale); all five §8 CLV_MISSING reasons and the
>20% INSUFFICIENT_CLOSE_DATA rule at its exact boundary; the §4
gates (100-row INSUFFICIENT_SAMPLE floor over the 50-row review
floor, exactly-40-games boundary, 4-slates gate); §9 verdicts
(BEATS_MARKET, picked-beats-passed as a binding second condition,
DOES_NOT_BEAT_MARKET); the §2 MARKET_OUT_OF_SCOPE refusal; the §5
engine-provenance screen (n_prior exactly 10 admitted, 9 excluded)
and picked/passed disposition handling; the §10 version discipline
(MODEL_VERSION_MISMATCH) and the framework's fail-closed admission
(POST_START_RECORD, RECORD_MISSING_TIMESTAMP, HISTORICAL excluded).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sportsedge.forward_validation import (  # noqa: E402
    VERDICTS,
    ForwardValidationRefusal,
    load_nba_config,
)
from sportsedge.forward_validation.nba_props import (  # noqa: E402
    PREREG_SHA256,
    evaluate_nba_props,
)

START = "2026-10-21T19:30:00-05:00"  # Wed Oct 21, 2026 — first countable slate
FAMILIES = ("player_points", "player_rebounds", "player_assists", "player_pra")


def stamp(**over):
    s = {"engine_id": "NBA_PROP_EMPIRICAL_V1", "sufficiency_met": True,
         "n_prior": 24, "pool_source": "POSITION_GROUP_EXPANDING_PIT",
         "store_provenance": "SPORTSDATAVERSE_BOX_SCORES",
         "limitation": ("No participation/minutes/availability feed is "
                        "wired: probabilities are over realized outcomes.")}
    s.update(over)
    return s


def nba_row(row_id="r1", event="G1", subject="Player One", *,
            market="player_points", line=24.5, p_over=0.62,
            disposition="PICKED", with_stamp=True, start=START, **over):
    row = {"row_id": row_id, "sport": "NBA", "family": market,
           "market": market, "event_id": event, "event_start": start,
           "subject_id": subject, "line": line,
           "model_version": "NBA_PROP_EMPIRICAL_V1",
           "model_p": {"OVER": p_over, "UNDER": 1.0 - p_over},
           "entry_prices": {"OVER": -110, "UNDER": -110},
           "entry_captured_at": "2026-10-21T12:00:00-05:00",
           "recorded_at": "2026-10-21T12:00:30-05:00",
           "label": "PROSPECTIVE"}
    if disposition is not None:
        row["disposition"] = disposition
    if with_stamp:
        row["engine_stamp"] = stamp()
    row.update(over)
    return row


def nba_close(event="G1", subject="Player One", *, market="player_points",
              line=24.5, over=-130, under=110, at="2026-10-21T19:00:00-05:00"):
    return {"event_id": event, "subject_id": subject, "market": market,
            "line": line, "prices": {"OVER": over, "UNDER": under},
            "captured_at": at}


def nba_outcome(event="G1", subject="Player One", *, market="player_points",
                value=30.0):
    return {"event_id": event, "subject_id": subject, "market": market,
            "value": value}


def points_cfg():
    return load_nba_config("player_points")


def big_family(n_picked=50, n_passed=50, n_events=40, *,
               picked_close=(-130, 110), passed_close=(-110, -110)):
    """A full §4-scale synthetic family: classified, stamped rows across
    n_events games, readable closes, realized outcomes for every row."""
    rows, closes, outcomes = [], [], []
    for i in range(n_picked + n_passed):
        disp = "PICKED" if i < n_picked else "PASSED"
        event, subject = f"G{i % n_events}", f"Player {i}"
        rows.append(nba_row(row_id=f"r{i}", event=event, subject=subject,
                            disposition=disp))
        oc, uc = picked_close if disp == "PICKED" else passed_close
        closes.append(nba_close(event=event, subject=subject, over=oc, under=uc))
        outcomes.append(nba_outcome(event=event, subject=subject,
                                    value=30.0 if i % 2 else 18.0))
    return rows, closes, outcomes


# ---------- the four frozen configs (§2, §4, §12) ----------

def test_all_four_configs_frozen_pinned_and_gated():
    for family in FAMILIES:
        cfg = load_nba_config(family)
        assert cfg.sport == "NBA" and cfg.family == family
        assert cfg.markets == [family]
        assert cfg.engine_id == "NBA_PROP_EMPIRICAL_V1"
        assert cfg.model_version == "NBA_PROP_EMPIRICAL_V1"  # §10 pin
        assert cfg.market_form == "TWO_SIDED"
        assert cfg.sides == ["OVER", "UNDER"] and cfg.over_side == "OVER"
        assert cfg.status.startswith("FROZEN")
        # §4 gates: <100 rows INSUFFICIENT_SAMPLE; 40 games; 4 slates
        assert cfg.min_rows == 100 and cfg.min_events == 40
        assert cfg.min_slates == 4
        # §7/§8: 60-minute close window; >20% missing-close cap
        assert cfg.close_max_age_minutes == 60
        assert cfg.max_clv_missing_share == 0.2
        # §12: hash-pinned to the frozen document
        assert cfg.prereg.endswith("PREREG_NBA_PROPS_FORWARD_V1.md")
        assert cfg.prereg_sha256 == PREREG_SHA256 == (
            "54363908b1e2332a57af9b9263ac2f398438c81b2d366"
            "442b80667086657bc79")
        assert cfg.picked_beats_passed_required is True
        assert len(cfg.sha256) == 64


def test_unknown_family_refused():
    with pytest.raises(ForwardValidationRefusal) as ei:
        load_nba_config("player_threes")
    assert ei.value.reason == "CONFIG_INVALID"


# ---------- §6 CLV, hand-checked ----------

def test_handchecked_clv_on_picked_row():
    # Entry -110/-110 -> no-vig 0.5000; close -130/+110 -> no-vig over
    # 0.542744; CLV = +0.042744 (the framework's Part 2 hand-check value).
    rec = evaluate_nba_props(points_cfg(), [nba_row()], [nba_close()],
                             [nba_outcome()])
    m = rec["markets"]["player_points"]
    scored = m["rows"][0]
    assert scored["selected_side"] == "OVER"
    assert scored["clv"] == pytest.approx(0.04274353876739567, abs=1e-12)
    assert m["clv"]["mean"] == pytest.approx(0.04274353876739567, abs=1e-12)
    assert m["picked_rows"] == 1 and m["passed_rows"] == 0
    assert rec["prereg_sha256"] == PREREG_SHA256
    assert rec["config_status"].startswith("FROZEN")
    assert rec["excluded"]["out_of_scope_rows"] == []
    assert rec["excluded"]["no_engine_provenance_rows"] == []


# ---------- §7 close validity ----------

def test_close_exactly_sixty_minutes_readable_sixty_one_stale():
    edge = evaluate_nba_props(
        points_cfg(), [nba_row()],
        [nba_close(at="2026-10-21T18:30:00-05:00")], [nba_outcome()])
    row = edge["markets"]["player_points"]["rows"][0]
    assert row["close_status"] == "READABLE"  # exactly 60:00 before tip
    assert row["clv"] is not None
    stale = evaluate_nba_props(
        points_cfg(), [nba_row()],
        [nba_close(at="2026-10-21T18:29:59-05:00")], [nba_outcome()])
    row = stale["markets"]["player_points"]["rows"][0]
    assert row["clv_missing_reason"] == "CLOSE_STALE"  # 60:01 before tip
    assert row["clv"] is None


def test_all_five_clv_missing_reasons():
    cfg = points_cfg()

    def reason(closes):
        rec = evaluate_nba_props(cfg, [nba_row()], closes, [nba_outcome()])
        m = rec["markets"]["player_points"]
        assert m["rows"][0]["selected_result"] == "WIN"  # stays in W/L
        assert m["rows"][0]["clv"] is None
        return m["rows"][0]["clv_missing_reason"]

    assert reason([]) == "NO_CLOSE_ROW"
    assert reason([nba_close(line=25.5)]) == "LINE_MOVED"
    one_sided = nba_close()
    one_sided["prices"] = {"OVER": -130}
    assert reason([one_sided]) == "CLOSE_SINGLE_SIDED"
    assert reason([nba_close(at="2026-10-21T19:30:00-05:00")]) == \
        "CLOSE_NOT_PREKICKOFF"
    assert reason([nba_close(at="2026-10-21T18:00:00-05:00")]) == "CLOSE_STALE"


def test_pra_two_sided_combo_close_required():
    # §2: a PRA row without a captured two-sided combo quote is not an
    # entry into CLV — a one-sided combo close yields CLOSE_SINGLE_SIDED.
    cfg = load_nba_config("player_pra")
    row = nba_row(market="player_pra", line=38.5)
    one_sided = nba_close(market="player_pra", line=38.5)
    one_sided["prices"] = {"OVER": -130}
    rec = evaluate_nba_props(cfg, [row], [one_sided],
                             [nba_outcome(market="player_pra", value=44.0)])
    m = rec["markets"]["player_pra"]
    assert m["rows"][0]["clv_missing_reason"] == "CLOSE_SINGLE_SIDED"
    assert m["rows"][0]["clv"] is None
    rec = evaluate_nba_props(cfg, [row], [nba_close(market="player_pra",
                                                   line=38.5)],
                             [nba_outcome(market="player_pra", value=44.0)])
    assert rec["markets"]["player_pra"]["rows"][0]["clv"] is not None


# ---------- §2 scope refusal ----------

def test_out_of_scope_rows_refused_reported_never_absorbed():
    cfg = points_cfg()
    oos_market = nba_row(row_id="oos1", subject="Player Two",
                         market="player_threes")
    oos_sport = nba_row(row_id="oos2", subject="Player Three", sport="WNBA")
    good = nba_row(row_id="ok1", subject="Player Four")
    rec = evaluate_nba_props(
        cfg, [oos_market, oos_sport, good],
        [nba_close(subject="Player Four")],
        [nba_outcome(subject="Player Four")])
    excluded = rec["excluded"]["out_of_scope_rows"]
    assert {e["row_id"] for e in excluded} == {"oos1", "oos2"}
    assert all(e["reason"] == "MARKET_OUT_OF_SCOPE" for e in excluded)
    m = rec["markets"]["player_points"]
    assert m["graded_rows"] == 1  # denominators see only the in-scope row


# ---------- §5 engine provenance ----------

def test_missing_engine_provenance_excluded_and_reported():
    cfg = points_cfg()
    no_stamp = nba_row(row_id="p1", subject="Player A", with_stamp=False)
    insuff = nba_row(row_id="p2", subject="Player B",
                     engine_stamp=stamp(sufficiency_met=False))
    thin = nba_row(row_id="p3", subject="Player C",
                   engine_stamp=stamp(n_prior=9))
    good = nba_row(row_id="ok1", subject="Player D")
    rows = [no_stamp, insuff, thin, good]
    rec = evaluate_nba_props(
        cfg, rows, [nba_close(subject="Player D")],
        [nba_outcome(subject="Player D")])
    reported = {e["row_id"]: e["problems"]
                for e in rec["excluded"]["no_engine_provenance_rows"]}
    assert set(reported) == {"p1", "p2", "p3"}
    assert "ENGINE_ID_MISSING_OR_MISMATCH" in reported["p1"]
    assert "SUFFICIENCY_NOT_MET" in reported["p2"]
    assert "N_PRIOR_MISSING_OR_BELOW_10" in reported["p3"]
    assert rec["markets"]["player_points"]["graded_rows"] == 1


def test_n_prior_exactly_ten_admitted_and_lane_stamp_shape_accepted():
    cfg = points_cfg()
    ten = nba_row(row_id="t10", subject="Player A",
                  engine_stamp=stamp(n_prior=10))
    lane = nba_row(row_id="lane", subject="Player B", with_stamp=False)
    lane["nba_prop_engine"] = {  # the phone lane's own stamp shape
        "engine_id": "NBA_PROP_EMPIRICAL_V1", "sufficiency_met": True,
        "n_prior": 31, "pool_source": "POSITION_GROUP_EXPANDING_PIT",
        "history_basis": "PIT_GAME_LOGS_ONLY",
        "participation_feed": "NOT_WIRED",
        "limitation": "No participation/minutes/availability feed."}
    rec = evaluate_nba_props(
        cfg, [ten, lane],
        [nba_close(subject="Player A"), nba_close(subject="Player B")],
        [nba_outcome(subject="Player A"), nba_outcome(subject="Player B")])
    m = rec["markets"]["player_points"]
    assert m["graded_rows"] == 2
    assert rec["excluded"]["no_engine_provenance_rows"] == []


def test_disposition_from_lane_status_and_unclassified_reported():
    cfg = points_cfg()
    stamped = nba_row(row_id="d1", subject="Player A")
    lane_status = nba_row(row_id="d2", subject="Player B", disposition=None,
                          status="RESEARCH_CANDIDATE_NOT_VALIDATED")
    mystery = nba_row(row_id="d3", subject="Player C", disposition=None)
    rec = evaluate_nba_props(
        cfg, [stamped, lane_status, mystery],
        [nba_close(subject=s) for s in ("Player A", "Player B", "Player C")],
        [nba_outcome(subject=s) for s in ("Player A", "Player B", "Player C")])
    m = rec["markets"]["player_points"]
    assert m["picked_rows"] == 2
    assert m["passed_rows"] == 0
    assert m["unclassified_rows"] == ["d3"]
    assert m["verdict_sample_rows"] == 2  # unclassified enters no denominator


# ---------- fail-closed admission (§10 + framework refusals) ----------

def test_model_version_mismatch_refused():
    bad = nba_row(model_version="NBA_PROP_EMPIRICAL_V2")
    with pytest.raises(ForwardValidationRefusal) as ei:
        evaluate_nba_props(points_cfg(), [bad], [], [])
    assert ei.value.reason == "MODEL_VERSION_MISMATCH"
    assert ei.value.detail["frozen"] == "NBA_PROP_EMPIRICAL_V1"


def test_post_start_record_refused():
    bad = nba_row(recorded_at="2026-10-21T19:45:00-05:00")
    with pytest.raises(ForwardValidationRefusal) as ei:
        evaluate_nba_props(points_cfg(), [bad], [], [])
    assert ei.value.reason == "POST_START_RECORD"


def test_missing_timestamp_refused():
    bad = nba_row()
    del bad["entry_captured_at"]
    with pytest.raises(ForwardValidationRefusal) as ei:
        evaluate_nba_props(points_cfg(), [bad], [], [])
    assert ei.value.reason == "RECORD_MISSING_TIMESTAMP"


def test_historical_record_excluded_not_scored():
    hist = nba_row(row_id="hist1", subject="Player Z",
                   recorded_at="2026-10-21T21:05:00-05:00",
                   label="HISTORICAL")
    good = nba_row(row_id="ok1", subject="Player A")
    rec = evaluate_nba_props(points_cfg(), [hist, good],
                             [nba_close(subject="Player A")],
                             [nba_outcome(subject="Player A")])
    assert rec["excluded"]["historical_rows"] == ["hist1"]
    m = rec["markets"]["player_points"]
    assert m["graded_rows"] == 1
    assert all(r["row_id"] != "hist1" for r in m["rows"])


# ---------- §4 gates ----------

def test_under_100_rows_insufficient_sample_even_past_50_row_floor():
    # 60 rows clears §4's 50-row review floor but not its 100-row
    # INSUFFICIENT_SAMPLE floor: the verdict stays INSUFFICIENT_SAMPLE
    # even with strongly positive picked CLV.
    rows, closes, outcomes = big_family(n_picked=30, n_passed=30)
    rec = evaluate_nba_props(points_cfg(), rows, closes, outcomes,
                             slates_completed=4)
    m = rec["markets"]["player_points"]
    assert m["verdict"] == "INSUFFICIENT_SAMPLE"
    assert m["gates"]["min_rows"] == {"required": 100, "actual": 60,
                                      "pass": False}
    assert m["clv"]["mean"] > 0  # a positive CLV cannot rescue the sample


def test_events_gate_boundary_exactly_forty_games():
    rows, closes, outcomes = big_family(n_events=39)
    rec = evaluate_nba_props(points_cfg(), rows, closes, outcomes,
                             slates_completed=4)
    m = rec["markets"]["player_points"]
    assert m["verdict"] == "INSUFFICIENT_SAMPLE"
    assert m["gates"]["min_events"] == {"required": 40, "actual": 39,
                                        "pass": False}
    rows, closes, outcomes = big_family(n_events=40)
    rec = evaluate_nba_props(points_cfg(), rows, closes, outcomes,
                             slates_completed=4)
    m = rec["markets"]["player_points"]
    assert m["gates"]["min_events"] == {"required": 40, "actual": 40,
                                        "pass": True}
    assert m["verdict"] == "BEATS_MARKET"


def test_slates_gate():
    rows, closes, outcomes = big_family()
    rec = evaluate_nba_props(points_cfg(), rows, closes, outcomes,
                             slates_completed=3)
    m = rec["markets"]["player_points"]
    assert m["verdict"] == "INSUFFICIENT_SAMPLE"
    assert m["gates"]["min_slates"] == {"required": 4, "actual": 3,
                                       "pass": False}


# ---------- §8 boundary: exactly 20% is NOT insufficient ----------

def test_exactly_twenty_percent_missing_close_is_not_insufficient():
    rows, closes, outcomes = big_family()
    closes = closes[10:60] + closes[70:]  # drop 10 picked + 10 passed closes
    assert len(closes) == 80
    rec = evaluate_nba_props(points_cfg(), rows, closes, outcomes,
                             slates_completed=4)
    m = rec["markets"]["player_points"]
    assert m["clv_missing_rows"] == 20
    assert m["clv_missing_share"] == pytest.approx(0.20)
    assert m["verdict"] == "BEATS_MARKET"  # 20% exactly does not trigger §8


def test_twenty_one_percent_missing_close_is_insufficient_close_data():
    rows, closes, outcomes = big_family()
    closes = closes[11:60] + closes[70:]  # drop 11 picked + 10 passed closes
    rec = evaluate_nba_props(points_cfg(), rows, closes, outcomes,
                             slates_completed=4)
    m = rec["markets"]["player_points"]
    assert m["clv_missing_share"] == pytest.approx(0.21)
    assert m["verdict"] == "INSUFFICIENT_CLOSE_DATA"


# ---------- §9 verdicts ----------

def test_beats_market_end_to_end():
    rows, closes, outcomes = big_family()
    rec = evaluate_nba_props(points_cfg(), rows, closes, outcomes,
                             slates_completed=4)
    m = rec["markets"]["player_points"]
    assert m["verdict"] == "BEATS_MARKET"
    assert m["clv"]["ci95_lo"] > 0  # picked CLV, game-clustered CI
    assert m["clv"]["n_events_clustered"] == 40
    assert m["clv_passed"]["mean"] == pytest.approx(0.0, abs=1e-12)
    assert m["picked_beats_passed"] is True
    assert m["picked_rows"] == 50 and m["passed_rows"] == 50
    assert all(g["pass"] for g in m["gates"].values())
    assert m["verdict"] in VERDICTS


def test_picked_must_beat_passed_or_no_beats_verdict():
    # Picked rows beat the market (CLV CI entirely > 0) but the model's
    # own passed rows did even better: §9 — beating only one is not
    # beating the market.
    rows, closes, outcomes = big_family(passed_close=(-150, 130))
    rec = evaluate_nba_props(points_cfg(), rows, closes, outcomes,
                             slates_completed=4)
    m = rec["markets"]["player_points"]
    assert m["clv"]["ci95_lo"] > 0
    assert m["clv_passed"]["mean"] > m["clv"]["mean"]
    assert m["picked_beats_passed"] is False
    assert m["verdict"] == "DOES_NOT_BEAT_MARKET"


def test_flat_picked_clv_does_not_beat_market():
    rows, closes, outcomes = big_family(picked_close=(-110, -110))
    rec = evaluate_nba_props(points_cfg(), rows, closes, outcomes,
                             slates_completed=4)
    m = rec["markets"]["player_points"]
    assert m["clv"]["mean"] == pytest.approx(0.0, abs=1e-12)
    assert m["clv"]["ci95_lo"] <= 0
    assert m["verdict"] == "DOES_NOT_BEAT_MARKET"
