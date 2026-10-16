"""Owner-audit negative regression tests for the per-game composite
(issue #2359, audit posted Oct 15, 2026).

One negative test per audit finding, each proving the failure mode is
refused fail-closed on this branch:

1. Duplicate selection risk: two captures of the SAME selection carrying
   DIFFERENT read IDs must not survive deduplication -- dedupe keys on
   selection identity, never on a read ID.
2. Incomplete market sets: a selection-set member missing its ``set_id``
   must be refused as incomplete, never silently bound by game grouping.
3. Research-only enforcement: a per-game (child) evaluator emitting a
   row with status "PLAY" triggers the permission guard; a composite
   research card can never surface PLAY (no validated families exist).
4. Capture authenticity: a declared operative instant that no recorded
   capture timestamp supports (a self-declared final re-read) is
   refused; the operative instant must be the game's own recorded final
   verification read.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from sportsedge.per_game_composite import (
    CompositeRefusal, operative_instant_for, run_composite,
    validate_selection_sets)

NOW = datetime(2026, 10, 15, 23, 40, 0, tzinfo=timezone.utc)

MLB_AWAY, MLB_HOME = "Milwaukee Brewers", "Los Angeles Dodgers"
MLB_KICKOFF = "2026-10-16T00:00:00Z"
KEY = ("MLB", MLB_AWAY, MLB_HOME, "2026-10-16T00:00:00+00:00")


def _row(market, side, odds, captured, **extra):
    row = {"sport": "MLB", "away": MLB_AWAY, "home": MLB_HOME,
           "kickoff": MLB_KICKOFF, "book": "draftkings",
           "quote_captured_at": captured, "market": market, "side": side,
           "odds": odds}
    row.update(extra)
    return row


def _stub_card(rows, *, as_of="2026-10-15T23:33:41+00:00"):
    """Minimal per-game card in run_full's shape for merge unit tests."""
    evaluated = []
    for i, row in enumerate(rows):
        evaluated.append({"input_index": i,
                          "status": "RESEARCH_POSITIVE_EV_UNVALIDATED",
                          **row})
    return {
        "schema": "SPORTSEDGE_FREE_RESEARCH_CARD_V1",
        "as_of_utc": as_of, "wall_utc": as_of,
        "authority": {}, "quote_freshness_policy": {"max_age_seconds": 180},
        "min_ev": 0.02, "primary_lane": "LANE_A_INDEPENDENT",
        "play_gate": {}, "canonical_coverage": {}, "runner": "STUB",
        "research_projection_note": "stub",
        "edges": list(evaluated), "lane_b_edges": [], "lane_b_watchlist": [],
        "independent_candidates": [], "independent_watchlist": [],
        "evaluated_rows": evaluated,
        "prop_candidates": [], "prop_watchlist": [], "prop_unpriced": [],
        "diagnostics": [], "source_receipts": [],
        "selection_intake": [{"sport": r["sport"]} for r in evaluated],
        "summary": {"rows": len(evaluated), "edges": len(evaluated),
                    "lane_b_edges": 0, "lane_b_watchlist": 0,
                    "status_counts": {
                        "RESEARCH_POSITIVE_EV_UNVALIDATED": len(evaluated)}},
        "factor_coverage": {"schema": "FC", "by_input_index": [],
                            "status_counts": {}, "advanced_metrics": {}},
        "prepricing_factor_audit": {"schema": "PF",
                                    "market_odds_as_features": False,
                                    "by_input_index": []},
        "prop_model_status": {"unsupported_player_markets_blocked": 0},
        "input_snapshot": {"n_rows": len(evaluated), "rows_sha1": "x",
                           "as_of_utc": as_of, "wall_utc": as_of,
                           "historical_repriced": False},
    }


def _game_row(market, selection, line=None, **extra):
    row = {"sport": "MLB", "game": f"{MLB_AWAY} @ {MLB_HOME}",
           "kickoff_utc": "2026-10-16T00:00:00+00:00", "market": market,
           "selection": selection, "line": line}
    row.update(extra)
    return row


# ------------------------------------------------------- finding 1 -----

def test_finding1_same_selection_two_read_ids_refuses_real_runner():
    """Two captures of one selection, different read IDs (and different
    stamps/odds): dedupe keys on the selection, so the merge refuses."""
    payload = {"lines": [
        _row("MONEYLINE", "AWAY", 135, "2026-10-15T23:33:04Z",
             capture_id="capture-1", source_read_id="read-aaa"),
        _row("MONEYLINE", "AWAY", 132, "2026-10-15T23:33:41Z",
             capture_id="capture-2", source_read_id="read-bbb"),
    ]}
    with pytest.raises(CompositeRefusal, match="COMPOSITE_DUPLICATE_SELECTION"):
        run_composite(payload, now=NOW, auto_context=False)


def test_finding1_same_selection_two_read_ids_refuses_merge_level():
    """Same guarantee at the merge itself, independent of how the child
    runner treats intake provenance fields."""
    first = _game_row("ML", "Milwaukee Brewers ML", source_read_id="read-aaa",
                      capture_id="capture-1")
    second = _game_row("ML", "Milwaukee Brewers ML", source_read_id="read-bbb",
                       capture_id="capture-2")
    card = _stub_card([first, second])
    payload = {"lines": [
        _row("MONEYLINE", "AWAY", 135, "2026-10-15T23:33:04Z",
             capture_id="capture-1", source_read_id="read-aaa"),
        _row("MONEYLINE", "AWAY", 132, "2026-10-15T23:33:41Z",
             capture_id="capture-2", source_read_id="read-bbb"),
    ]}
    with pytest.raises(CompositeRefusal, match="COMPOSITE_DUPLICATE_SELECTION"):
        run_composite(payload, now=NOW, run_full_fn=lambda *a, **k: card)


# ------------------------------------------- identity robustness --------

def _nfl_tt(side, odds, line, team_side, captured, **extra):
    row = {"sport": "NFL", "away": "Seattle Seahawks",
           "home": "Denver Broncos", "kickoff": "2026-10-16T00:15:00Z",
           "book": "draftkings", "quote_captured_at": captured,
           "market": "TEAM_TOTALS", "side": side, "odds": odds,
           "line": line, "team_side": team_side}
    row.update(extra)
    return row


def test_thin_derivative_team_totals_distinct_selections_merge():
    """Regression (found on the real Oct 15 night intake): NFL derivative
    team-total evaluated rows are thin -- bare "OVER"/"UNDER" with no
    line, team or game fields -- so an evaluated-only identity collapses
    Seattle OVER 20.5 and Denver OVER 19.5 into one "duplicate".  The
    identity binds the paired intake row; distinct selections merge."""
    payload = {"lines": [
        _nfl_tt("OVER", -130, 20.5, "AWAY", "2026-10-15T23:36:21Z"),
        _nfl_tt("UNDER", 100, 20.5, "AWAY", "2026-10-15T23:36:21Z"),
        _nfl_tt("OVER", -115, 19.5, "HOME", "2026-10-15T23:36:21Z"),
        _nfl_tt("UNDER", -110, 19.5, "HOME", "2026-10-15T23:36:21Z"),
    ]}
    card = run_composite(payload, now=NOW, auto_context=False)
    tt = [r for r in card["evaluated_rows"] if r["market"] == "TEAM_TOTAL"]
    assert len(tt) == 4


def test_thin_derivative_team_total_duplicate_capture_refuses():
    """The same thin-row selection captured twice (different read IDs)
    still refuses: the intake-bound identity sees one selection."""
    payload = {"lines": [
        _nfl_tt("OVER", -130, 20.5, "AWAY", "2026-10-15T23:36:14Z",
                capture_id="capture-1"),
        _nfl_tt("OVER", -128, 20.5, "AWAY", "2026-10-15T23:36:21Z",
                capture_id="capture-2"),
        _nfl_tt("UNDER", 100, 20.5, "AWAY", "2026-10-15T23:36:21Z"),
    ]}
    with pytest.raises(CompositeRefusal, match="COMPOSITE_DUPLICATE_SELECTION"):
        run_composite(payload, now=NOW, auto_context=False)


# ------------------------------------------------------- finding 2 -----

def test_finding2_set_member_missing_set_id_refused_incomplete():
    """A set member that declares set_size (it belongs to a set of 2)
    but whose set_id is missing: refused as incomplete, never bound."""
    payload = {"lines": [
        _row("TOTALS", "OVER", -110, "2026-10-15T23:33:41Z", line=8.5,
             set_id="game-total", set_size=2),
        _row("TOTALS", "UNDER", -110, "2026-10-15T23:33:41Z", line=8.5,
             set_size=2),  # set_id missing
    ]}
    with pytest.raises(CompositeRefusal,
                       match="COMPOSITE_SELECTION_SET_INCOMPLETE"):
        run_composite(payload, now=NOW, auto_context=False)


def test_finding2_declared_set_short_of_its_size_refused_incomplete():
    keyed = [(KEY, {"set_id": "ml", "set_size": 3}),
             (KEY, {"set_id": "ml", "set_size": 3})]
    with pytest.raises(CompositeRefusal,
                       match="COMPOSITE_SELECTION_SET_INCOMPLETE"):
        validate_selection_sets(keyed)


def test_finding2_set_split_across_games_refused():
    other = ("MLB", "Chicago Cubs", "St. Louis Cardinals",
             "2026-10-16T00:05:00+00:00")
    keyed = [(KEY, {"set_id": "s", "set_size": 2}),
             (other, {"set_id": "s", "set_size": 2})]
    with pytest.raises(CompositeRefusal,
                       match="COMPOSITE_SELECTION_SET_SPLIT_ACROSS_GAMES"):
        validate_selection_sets(keyed)


def test_finding2_complete_set_and_unmarked_rows_pass():
    keyed = [(KEY, {"set_id": "s", "set_size": 2}),
             (KEY, {"set_id": "s", "set_size": 2}),
             (KEY, {"market": "MONEYLINE"})]  # ordinary row, no markers
    validate_selection_sets(keyed)  # must not raise


# ------------------------------------------------------- finding 3 -----

def test_finding3_child_play_status_in_evaluated_rows_refused():
    card = _stub_card([_game_row("ML", "Milwaukee Brewers ML")])
    card["evaluated_rows"][0]["status"] = "PLAY"
    card["edges"][0]["status"] = "PLAY"
    payload = {"lines": [_row("MONEYLINE", "AWAY", 135, "2026-10-15T23:33:41Z")]}
    with pytest.raises(CompositeRefusal, match="COMPOSITE_PLAY_STATUS_FORBIDDEN"):
        run_composite(payload, now=NOW, run_full_fn=lambda *a, **k: card)


def test_finding3_child_play_status_on_watch_surface_only_refused():
    """PLAY smuggled onto a non-evaluated surface still trips the guard."""
    card = _stub_card([_game_row("ML", "Milwaukee Brewers ML")])
    sneaky = dict(card["evaluated_rows"][0])
    sneaky["status"] = "PLAY"
    card["independent_candidates"] = [sneaky]
    payload = {"lines": [_row("MONEYLINE", "AWAY", 135, "2026-10-15T23:33:41Z")]}
    with pytest.raises(CompositeRefusal, match="COMPOSITE_PLAY_STATUS_FORBIDDEN"):
        run_composite(payload, now=NOW, run_full_fn=lambda *a, **k: card)


def test_finding3_real_cards_never_surface_play():
    payload = {"lines": [
        _row("MONEYLINE", "AWAY", 135, "2026-10-15T23:33:41Z"),
        _row("MONEYLINE", "HOME", -155, "2026-10-15T23:33:41Z"),
    ]}
    card = run_composite(payload, now=NOW, auto_context=False)
    for surface in ("evaluated_rows", "edges", "independent_candidates",
                    "independent_watchlist", "lane_b_edges", "lane_b_watchlist"):
        assert all(r.get("status") != "PLAY" for r in card[surface]), surface
    assert card["position_accounting"]["accounting"] == \
        "CORRELATED_STACK_AS_SINGLE_POSITION"


# ------------------------------------------------------- finding 4 -----

def test_finding4_declared_re_read_without_capture_evidence_refused():
    """The caller claims a final re-read at 23:35:41Z, but the game's
    recorded captures end at 23:33:41Z: the claim is unsupported by
    capture timestamps and the composite refuses."""
    payload = {"lines": [
        _row("MONEYLINE", "AWAY", 135, "2026-10-15T23:33:04Z"),
        _row("TOTALS", "OVER", -110, "2026-10-15T23:33:41Z", line=8.5),
    ]}
    key = "MLB|Milwaukee Brewers|Los Angeles Dodgers|2026-10-16T00:00:00+00:00"
    with pytest.raises(
            CompositeRefusal,
            match="COMPOSITE_OPERATIVE_INSTANT_NOT_CAPTURE_EVIDENCED"):
        run_composite(payload, now=NOW, auto_context=False,
                      operative_instants={key: "2026-10-15T23:35:41Z"})


def test_finding4_declared_instant_with_no_captures_at_all_refused():
    instant = datetime(2026, 10, 15, 23, 35, 41, tzinfo=timezone.utc)
    with pytest.raises(
            CompositeRefusal,
            match="COMPOSITE_OPERATIVE_INSTANT_NOT_CAPTURE_EVIDENCED"):
        operative_instant_for([], override=instant, game_label="G")


def test_finding4_declared_instant_equal_to_recorded_final_read_accepted():
    """Positive control: a declaration that IS the recorded final
    verification read (the max capture stamp) is capture-evidenced."""
    payload = {"lines": [
        _row("MONEYLINE", "AWAY", 135, "2026-10-15T23:33:04Z"),
        _row("TOTALS", "OVER", -110, "2026-10-15T23:33:41Z", line=8.5),
    ]}
    key = "MLB|Milwaukee Brewers|Los Angeles Dodgers|2026-10-16T00:00:00+00:00"
    card = run_composite(payload, now=NOW, auto_context=False,
                         operative_instants={key: "2026-10-15T23:33:41Z"})
    assert card["composite"]["games"][0]["operative_instant_utc"] == \
        "2026-10-15T23:33:41+00:00"
