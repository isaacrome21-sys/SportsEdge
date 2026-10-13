"""Moneyline settlement types (2026-10-12 owner settlement ruling).

DraftKings' published rules distinguish TWO_WAY moneylines (no Draw
selection; ties settle as PUSH) from THREE_WAY moneylines (a separate
DRAW selection; ties settle as DRAW, never a push). These tests prove:

* the typed model in sportsedge.moneyline_settlement settles both
  types explicitly and fails closed (SETTLEMENT_TYPE_UNDECLARED) when
  no type is declared;
* DraftKings' F5 moneyline is declared TWO_WAY from its published
  rules, so a tied F5 game now settles PUSH through the full catalog
  settlement path instead of raising
  F5_MONEYLINE_TIE_POLICY_NOT_NORMALIZED -- while an undeclared book
  keeps the historical fail-closed refusal;
* the full-game DraftKings moneyline is likewise declared TWO_WAY;
* two-way F5 EV keeps win / push / loss as separate masses and a push
  returns the stake (EV contribution exactly zero).
"""
from __future__ import annotations

import pytest

from sportsedge.mlb_acceptance_matrix import build_acceptance_matrix
from sportsedge.mlb_additional_pit_joiner import (
    MLBPITJoinError, _f5_moneyline_outcome, _policy_ambiguity,
)
from sportsedge.mlb_catalog_prediction_settlement import (
    build_catalog_prediction_settlement_record,
    build_catalog_settlement_report,
)
from sportsedge.mlb_edge_score import ev_per_dollar
from sportsedge.mlb_pit_archive_router import (
    F5_TIE_POLICY_AMBIGUITY, _harden_f5_moneyline_ties,
)
from sportsedge.mlb_pit_joiner import observation_key
from sportsedge.moneyline_settlement import (
    MoneylineSettlementError, MoneylineSettlementType,
    declared_moneyline_settlement_type, moneyline_winning_outcome,
    require_moneyline_settlement_type, settle_moneyline,
    SETTLEMENT_TYPE_UNDECLARED,
)
from sportsedge.prediction_journal import build_prediction_journal_record

TWO_WAY = MoneylineSettlementType.TWO_WAY
THREE_WAY = MoneylineSettlementType.THREE_WAY

SHA = "a" * 64
GAME_ID = "822696"


# ------------------------------------------------------------ typed API

def test_two_way_tie_pushes_and_teams_settle():
    assert settle_moneyline(
        TWO_WAY, side="HOME", selected_runs=2, other_runs=2) == "PUSH"
    assert settle_moneyline(
        TWO_WAY, side="HOME", selected_runs=3, other_runs=2) == "WIN"
    assert settle_moneyline(
        TWO_WAY, side="AWAY", selected_runs=1, other_runs=2) == "LOSS"


def test_three_way_tie_is_draw_never_push():
    # Team selections lose to the draw; the draw selection wins.
    assert settle_moneyline(
        THREE_WAY, side="HOME", selected_runs=2, other_runs=2) == "LOSS"
    assert settle_moneyline(
        THREE_WAY, side="DRAW", selected_runs=2, other_runs=2) == "WIN"
    assert settle_moneyline(
        THREE_WAY, side="DRAW", selected_runs=2, other_runs=3) == "LOSS"
    assert moneyline_winning_outcome(
        THREE_WAY, home_runs=2, away_runs=2) == "DRAW"
    assert moneyline_winning_outcome(
        TWO_WAY, home_runs=2, away_runs=2) == "PUSH"


def test_two_way_has_no_draw_selection():
    with pytest.raises(MoneylineSettlementError):
        settle_moneyline(
            TWO_WAY, side="DRAW", selected_runs=2, other_runs=2)


def test_undeclared_type_fails_closed():
    with pytest.raises(MoneylineSettlementError) as excinfo:
        settle_moneyline(
            None, side="HOME", selected_runs=2, other_runs=2)
    assert SETTLEMENT_TYPE_UNDECLARED in str(excinfo.value)
    with pytest.raises(MoneylineSettlementError) as excinfo:
        moneyline_winning_outcome(None, home_runs=1, away_runs=1)
    assert SETTLEMENT_TYPE_UNDECLARED in str(excinfo.value)
    with pytest.raises(MoneylineSettlementError) as excinfo:
        require_moneyline_settlement_type("F5_MONEYLINE", "UnknownBook")
    assert SETTLEMENT_TYPE_UNDECLARED in str(excinfo.value)


def test_draftkings_declarations_are_two_way_with_citations():
    for market in ("F5_MONEYLINE", "MONEYLINE"):
        assert declared_moneyline_settlement_type(
            market, "DraftKings") is TWO_WAY
        assert declared_moneyline_settlement_type(
            market, "draftkings") is TWO_WAY
    from sportsedge.moneyline_settlement import (
        moneyline_settlement_declaration)
    declaration = moneyline_settlement_declaration(
        "F5_MONEYLINE", "DraftKings")
    assert declaration["settlement_type"] is TWO_WAY
    assert any("baseball-betting-guide" in url
               for url in declaration["sources"])
    assert any("market-rules" in url for url in declaration["sources"])
    # Nothing else is declared: no inherited types for other books.
    assert declared_moneyline_settlement_type(
        "F5_MONEYLINE", "FanDuel") is None
    assert declared_moneyline_settlement_type(
        "MONEYLINE", "FanDuel") is None


# ------------------------------------------------------- joiner behavior

_TIED_F5 = {"f5": {"away_runs": 2, "home_runs": 2}}


def test_joiner_tie_without_declared_type_still_refuses():
    with pytest.raises(MLBPITJoinError) as excinfo:
        _f5_moneyline_outcome(_TIED_F5, "HOME")
    assert "F5_MONEYLINE_TIE_POLICY_NOT_NORMALIZED" in str(excinfo.value)
    assert _policy_ambiguity(_TIED_F5, "F5_MONEYLINE") == [
        "F5_MONEYLINE_TIE_POLICY_NOT_NORMALIZED"]
    assert _policy_ambiguity(
        _TIED_F5, "F5_MONEYLINE", sportsbook="UnknownBook") == [
        "F5_MONEYLINE_TIE_POLICY_NOT_NORMALIZED"]


def test_joiner_tie_with_two_way_type_settles_push():
    assert _f5_moneyline_outcome(
        _TIED_F5, "HOME", settlement_type=TWO_WAY) == "PUSH"
    assert _f5_moneyline_outcome(
        _TIED_F5, "AWAY", settlement_type=TWO_WAY) == "PUSH"
    assert _policy_ambiguity(
        _TIED_F5, "F5_MONEYLINE", sportsbook="DraftKings") == []


# ------------------------------------------------------ router hardening

def _router_inputs(sportsbook):
    quote = {
        "market": "F5_MONEYLINE", "game_id": "999",
        "entity_id": "20", "line": 0.0, "side": "HOME",
        "book_key": "draftkings", "sportsbook": sportsbook,
        "quote_retrieved_at": "2026-08-24T00:00:00+00:00",
    }
    key = observation_key(
        game_id="999", market="F5_MONEYLINE", entity_id="20", line=0.0,
        side="HOME", book_key="draftkings",
        quote_ts="2026-08-24T00:00:00+00:00")
    facts = [{"game_id": "999",
              "facts": {"f5": {"away_runs": 2, "home_runs": 2}}}]
    settlements = [{"observation_key": key, "ambiguity_reasons": []}]
    return {"quotes": [quote]}, facts, settlements


def test_router_hardening_skips_declared_draftkings_only():
    payload, facts, settlements = _router_inputs("DraftKings")
    out = _harden_f5_moneyline_ties(
        archive_payload=payload, official_fact_reports=facts,
        settlement_rows=settlements)
    assert out[0]["ambiguity_reasons"] == []

    payload, facts, settlements = _router_inputs("UnknownBook")
    out = _harden_f5_moneyline_ties(
        archive_payload=payload, official_fact_reports=facts,
        settlement_rows=settlements)
    assert out[0]["ambiguity_reasons"] == [F5_TIE_POLICY_AMBIGUITY]


# ------------------------------------------------- full catalog path

def _rules(sportsbook="DraftKings"):
    required = set()
    for row in build_acceptance_matrix()["markets"]:
        required.update(row["requirements"]["settlement_semantics"])
    return {
        rule: {
            "status": "VALIDATED", "sportsbook": sportsbook,
            "source_sha256": SHA,
            "captured_at_utc": "2026-08-25T11:30:00+00:00",
            "source_locator": f"fixture://{sportsbook}/{rule}",
        } for rule in sorted(required)}


def _tied_facts():
    ids = {"away_team_id": "10", "home_team_id": "20"}
    return {
        "game_pk": GAME_ID, "status": "Final",
        "source": "MLB_STATSAPI_BOX_SCORE_AND_LIVE_FEED",
        "game": {**ids, "away_runs": 3, "home_runs": 3,
                 "run_diff_home": 0, "total_runs": 6},
        "f5": {**ids, "away_runs": 2, "home_runs": 2,
               "run_diff_home": 0, "total_runs": 4},
        "first_inning": {"away_runs": 0, "home_runs": 0,
                         "nrfi": True, "yrfi": False},
        "batters": [{"player_id": "10", "plate_appearances": 4, "hits": 2,
                     "singles": 1, "doubles": 0, "triples": 0,
                     "home_runs": 1, "total_bases": 5, "rbi": 2,
                     "runs": 1, "walks": 1, "strikeouts": 1,
                     "stolen_bases": 0, "extra_base_hits": 1,
                     "hits_runs_rbis": 5, "hits_runs_stolen_bases": 3,
                     "runs_rbis": 3, "hits_stolen_bases": 2,
                     "hits_walks_stolen_bases": 3}],
        "pitchers": [
            {"player_id": "20", "walks": 2, "walks_allowed": 2,
             "strikeouts": 7, "hits_allowed": 4, "earned_runs": 1,
             "outs": 18, "hits_walks_er": 7},
            {"player_id": "21", "walks": 4, "walks_allowed": 4,
             "strikeouts": 5, "hits_allowed": 6, "earned_runs": 3,
             "outs": 15, "hits_walks_er": 13},
        ],
        "first_home_run": {"occurred": True, "batter_id": "10"},
        "winning_pitcher": {"pitcher_id": "20"},
    }


def _prediction(market, entity, side, line, *, sportsbook="DraftKings"):
    row = {"source_index": 0, "game_id": GAME_ID, "market": market,
           "entity_id": entity, "line": line, "side": side,
           "american_odds": -110, "model_p": 0.55, "bet_status": "PASS",
           "reason": "TEST", "sportsbook": sportsbook,
           "book_key": sportsbook.lower().replace(" ", ""),
           "model_input_hash": SHA, "distribution_sha256": "b" * 64,
           "readout_sha256": "c" * 64,
           "readout_version": "mlb_v7_game_readout_v1"}
    return row


def _settle(prediction, *, sportsbook="DraftKings"):
    journal = build_prediction_journal_record({
        "mode": "AUTOMATIC", "slate_date_ct": "2026-08-25",
        "generated_at_utc": "2026-08-25T10:00:00+00:00",
        "run_status": "PASS", "card_status": "PASS",
        "results": [prediction]})
    assert journal is not None
    report = build_catalog_settlement_report(
        _tied_facts(), source="MLB_STATSAPI_BOX_SCORE_AND_LIVE_FEED",
        evidence_class="LIVE_OFFICIAL_FACT_PROBE",
        generated_at_utc="2026-08-25T12:00:00+00:00",
        book_rule_evidence=_rules(sportsbook))
    return build_catalog_prediction_settlement_record(
        journal, settlement_reports_by_game={GAME_ID: report},
        settled_at_utc="2026-08-25T12:10:00+00:00")


def test_tied_f5_moneyline_settles_push_through_full_path():
    record = _settle(_prediction("F5_MONEYLINE", GAME_ID, "HOME", None))
    row = record["outcomes"][0]
    assert row["settlement_result"] == "PUSH"
    assert record["push_count"] == 1
    assert record["settlement_complete"] is True


def test_tied_full_game_moneyline_settles_push_for_draftkings():
    record = _settle(_prediction("MONEYLINE", GAME_ID, "HOME", None))
    assert record["outcomes"][0]["settlement_result"] == "PUSH"


def test_tied_moneylines_stay_unresolved_for_undeclared_books():
    record = _settle(
        _prediction("MONEYLINE", GAME_ID, "HOME", None,
                    sportsbook="FanDuel"),
        sportsbook="FanDuel")
    row = record["outcomes"][0]
    assert row["settlement_result"] == "UNRESOLVED"
    assert "MONEYLINE_FINAL_TIE_REQUIRES_BOOK_RULE" in \
        row["settlement_reason"]

    record = _settle(
        _prediction("F5_MONEYLINE", GAME_ID, "HOME", None,
                    sportsbook="FanDuel"),
        sportsbook="FanDuel")
    row = record["outcomes"][0]
    assert row["settlement_result"] == "UNRESOLVED"
    assert row["settlement_reason"] == \
        "F5_MONEYLINE_TIE_POLICY_NOT_NORMALIZED"


# ------------------------------------------------------------ EV masses

def test_two_way_ev_keeps_push_mass_separate_and_returns_stake():
    from sportsedge.f5_distribution import (
        F5Distribution, read_f5_probability)
    distribution = F5Distribution(
        away_history_games=200, home_history_games=200,
        joint_score_pmf={"2,2": 0.30, "3,2": 0.35, "2,3": 0.35},
        distribution_sha256="d" * 64)
    readout = read_f5_probability(
        distribution, market="F5_MONEYLINE", side="HOME")
    win_p = readout.probability
    push_p = readout.push_probability
    loss_p = 1.0 - win_p - push_p
    assert push_p > 0.05  # the tie mass survives as its own mass
    assert win_p > 0 and loss_p > 0
    # EV consumes the three masses separately: win pays the price,
    # loss forfeits the stake, push contributes exactly zero.
    expected = win_p * (100.0 / 120.0) - loss_p
    assert ev_per_dollar(win_p, -120, push_p=push_p) == \
        pytest.approx(expected)
    # A certain tie returns the stake: EV is zero, not -1.
    assert ev_per_dollar(0.0, -120, push_p=1.0) == 0.0
    assert ev_per_dollar(0.0, -120, push_p=0.0) == -1.0
