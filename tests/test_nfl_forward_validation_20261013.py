"""Synthetic tests for NFL_FORWARD_VALIDATION_DESIGN_V1's harness.

Owner ruling (Isaac, Oct 13 2026): implementation and synthetic tests
ONLY. Every record fabricated here is synthetic; no real data, no
holdout, no activation. The harness refuses evidence campaigns by
construction and these tests assert that refusal.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import sys

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from sportsedge.research import nfl_forward_validation_v1 as fv

UTC = timezone.utc
BASE_KICKOFF = datetime(2026, 9, 13, 17, 0, tzinfo=UTC)
REPS = 2000


# ---------------------------------------------------------------------------
# Fabrication helpers (synthetic only)
# ---------------------------------------------------------------------------

def iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat()


def register(campaign: fv.Campaign, item_id: str, *, kind: str = "CLOSING",
             game_id: str = "G", slate_id: str | None = None,
             week: int = 1, kickoff: datetime = BASE_KICKOFF,
             freeze: str | None = None) -> str:
    return campaign.register_expected({
        "item_id": item_id, "kind": kind, "game_id": game_id,
        "slate_id": slate_id, "week_block": week,
        "window_close_utc": iso(kickoff - timedelta(minutes=2)),
        "freeze_sha256": freeze})


def game_record(*, item_id: str, week: int = 1,
                kickoff: datetime = BASE_KICKOFF,
                kind: str = "CLOSING", home_p: float = 0.55,
                minutes_before: float | None = None,
                spread_line: float = -3.5, total_line: float = 44.5,
                game_id: str = "G") -> dict:
    return fv.make_synthetic_game_record(
        game_id=game_id, week_block=week, kickoff=kickoff,
        capture_kind=kind, item_id=item_id, model_home_p=home_p,
        minutes_before=minutes_before, spread_line=spread_line,
        total_line=total_line)


def build_game_campaign(n_games: int, n_blocks: int, *,
                        model_for, outcome_for,
                        expected_extra: int = 0) -> fv.Campaign:
    """n_games CLOSING captures spread over n_blocks week blocks."""
    campaign = fv.Campaign(mode="DRY_RUN")
    for i in range(n_games):
        week = (i % n_blocks) + 1
        kickoff = BASE_KICKOFF + timedelta(days=7 * (week - 1))
        item_id = f"GAME-{i}:CLOSING"
        register(campaign, item_id, game_id=f"GAME-{i}", week=week,
                 kickoff=kickoff)
        home_score, away_score = outcome_for(i, week)
        rec = game_record(item_id=item_id, week=week, kickoff=kickoff,
                          home_p=model_for(i, week, home_score, away_score),
                          game_id=f"GAME-{i}")
        result = campaign.submit_game_record(rec)
        assert result["accepted"], result
        campaign.submit_settlement(result["record_id"],
                                   home_score=home_score,
                                   away_score=away_score)
    for j in range(expected_extra):
        register(campaign, f"EXTRA-{j}:CLOSING", game_id=f"EXTRA-{j}")
    campaign.reconcile(now=BASE_KICKOFF + timedelta(days=7 * n_blocks))
    return campaign


def prop_pair(*, kickoff: datetime, line: float = 250.5,
              minutes_before: float = 10.0) -> dict:
    return fv.make_synthetic_pair(
        kickoff=kickoff, market="PROP_OU", line=line,
        minutes_before=minutes_before, selections=("OVER", "UNDER"),
        event_id="PROP-EVENT")


def prop_record(*, item_id: str, week: int = 1,
                kickoff: datetime = BASE_KICKOFF,
                family: str = "PASS_YARDS", player: str = "P1",
                engine_p: float = 0.5, line: float = 250.5,
                s1: bool = True, s2: bool = True,
                engine_line: float | None = None,
                recomputed: bool = False) -> dict:
    return {
        "record_kind": "PROP_CAPTURE", "origin": "SYNTHETIC",
        "game_id": "G", "week_block": week, "kickoff_utc": iso(kickoff),
        "player_id": player, "family": family,
        "pair": prop_pair(kickoff=kickoff, line=line),
        "engine_p_over": engine_p,
        "engine_line": line if engine_line is None else engine_line,
        "recomputed_at_captured_line": recomputed,
        "participation": {
            "s1": {"designation": "Full"} if s1 else None,
            "s2": {"designation": "Active"} if s2 else None},
        "expected_item_id": item_id,
    }


def build_prop_campaign(n_rows: int, n_weeks: int, *,
                        engine_p: float = 0.5, stat: float = 260.0,
                        family: str = "PASS_YARDS") -> fv.Campaign:
    campaign = fv.Campaign(mode="DRY_RUN")
    for i in range(n_rows):
        week = (i % n_weeks) + 1
        kickoff = BASE_KICKOFF + timedelta(days=7 * (week - 1))
        item_id = f"PROP-{i}:CLOSING"
        register(campaign, item_id, game_id="G", week=week,
                 kickoff=kickoff)
        rec = prop_record(item_id=item_id, week=week, kickoff=kickoff,
                          family=family, player=f"P{i}",
                          engine_p=engine_p)
        result = campaign.submit_prop_record(rec)
        assert result["accepted"], result
        campaign.submit_prop_settlement(result["record_id"],
                                        stat_value=stat)
    return campaign


# ---------------------------------------------------------------------------
# Paired-quote contract
# ---------------------------------------------------------------------------

def _single_game_campaign() -> tuple[fv.Campaign, str]:
    campaign = fv.Campaign(mode="DRY_RUN")
    register(campaign, "G:CLOSING")
    return campaign, "G:CLOSING"


def test_valid_pair_accepted():
    campaign, item = _single_game_campaign()
    result = campaign.submit_game_record(game_record(item_id=item))
    assert result["accepted"]


def test_cross_book_pair_refused():
    campaign, item = _single_game_campaign()
    rec = game_record(item_id=item)
    rec["pairs"]["MONEYLINE"]["sides"][1]["book"] = "FanDuel"
    result = campaign.submit_game_record(rec)
    assert not result["accepted"]
    assert result["reason"] == "PAIR_BOOK_MISMATCH"


def test_wrong_book_refused():
    campaign, item = _single_game_campaign()
    rec = game_record(item_id=item)
    rec["pairs"]["TOTAL"]["book"] = "FanDuel"
    result = campaign.submit_game_record(rec)
    assert result["reason"].startswith("BOOK_NOT_DRAFTKINGS")


def test_pair_skew_over_120s_refused():
    campaign, item = _single_game_campaign()
    rec = game_record(item_id=item)
    pair = rec["pairs"]["SPREAD"]
    early = BASE_KICKOFF - timedelta(minutes=10)
    pair["sides"][0]["captured_at"] = iso(early - timedelta(seconds=121))
    pair["sides"][1]["captured_at"] = iso(early)
    result = campaign.submit_game_record(rec)
    assert result["reason"] == "PAIR_SKEW_EXCEEDS_120S"


def test_postgame_timestamp_refused():
    campaign, item = _single_game_campaign()
    rec = game_record(item_id=item)
    pair = rec["pairs"]["MONEYLINE"]
    after = BASE_KICKOFF + timedelta(minutes=1)
    pair["sides"][0]["captured_at"] = iso(after - timedelta(seconds=30))
    pair["sides"][1]["captured_at"] = iso(after)
    pair["assembled_at"] = iso(after + timedelta(seconds=5))
    result = campaign.submit_game_record(rec)
    assert result["reason"] == "QUOTE_NOT_PREGAME"


def test_stale_side_refused():
    campaign, item = _single_game_campaign()
    rec = game_record(item_id=item)
    pair = rec["pairs"]["TOTAL"]
    t0 = BASE_KICKOFF - timedelta(minutes=10)
    pair["sides"][0]["captured_at"] = iso(t0)
    pair["sides"][1]["captured_at"] = iso(t0 + timedelta(seconds=60))
    pair["assembled_at"] = iso(t0 + timedelta(seconds=201))
    result = campaign.submit_game_record(rec)
    assert result["reason"] == "QUOTE_STALE_AT_ASSEMBLY"


def test_minus_100_price_refused():
    campaign, item = _single_game_campaign()
    rec = game_record(item_id=item)
    rec["pairs"]["SPREAD"]["sides"][0]["price"] = -100
    result = campaign.submit_game_record(rec)
    assert result["reason"] == "PRICE_MINUS_100_INVALID"


def test_untimestamped_opposite_price_refused():
    campaign, item = _single_game_campaign()
    rec = game_record(item_id=item)
    del rec["pairs"]["MONEYLINE"]["sides"][1]["captured_at"]
    result = campaign.submit_game_record(rec)
    assert result["reason"] == "OPPOSITE_PRICE_NOT_A_TIMESTAMPED_QUOTE"


def test_line_mismatch_refused():
    campaign, item = _single_game_campaign()
    rec = game_record(item_id=item)
    rec["pairs"]["SPREAD"]["sides"][1]["line"] = -4.5
    result = campaign.submit_game_record(rec)
    assert result["reason"] == "PAIR_LINE_MISMATCH"


def test_early_pair_is_pregame_snapshot_not_closing_evidence():
    campaign, item = _single_game_campaign()
    rec = game_record(item_id=item, minutes_before=35.0)
    result = campaign.submit_game_record(rec)
    assert result["accepted"]  # admissible as a pregame snapshot record
    campaign.submit_settlement(result["record_id"], home_score=27,
                               away_score=20)
    readout = fv.game_leg_readout(campaign, "MONEYLINE", reps=REPS)
    assert readout["counts"]["rows"] == 0  # never closing evidence


def test_decision_capture_outside_window_refused():
    campaign = fv.Campaign(mode="DRY_RUN")
    register(campaign, "G:DECISION", kind="DECISION")
    rec = game_record(item_id="G:DECISION", kind="DECISION",
                      minutes_before=30.0)
    result = campaign.submit_game_record(rec)
    assert result["reason"].startswith("DECISION_CAPTURE_OUTSIDE_WINDOW")


def test_postseason_population_refused():
    campaign, item = _single_game_campaign()
    rec = game_record(item_id=item)
    rec["season_phase"] = "POSTSEASON"
    result = campaign.submit_game_record(rec)
    assert result["reason"] == "POPULATION_POSTSEASON_EXCLUDED"


def test_market_anchored_candidate_refused():
    campaign, item = _single_game_campaign()
    rec = game_record(item_id=item)
    rec["model"]["lane"] = "MARKET_ANCHORED"
    result = campaign.submit_game_record(rec)
    assert result["reason"] == "CANDIDATE_MUST_BE_INDEPENDENT_LANE_A"


# ---------------------------------------------------------------------------
# Immutability / duplicates
# ---------------------------------------------------------------------------

def test_duplicate_record_detected_never_duplicated():
    campaign, item = _single_game_campaign()
    rec = game_record(item_id=item)
    first = campaign.submit_game_record(rec)
    second = campaign.submit_game_record(rec)
    assert first["accepted"] and not second["accepted"]
    assert second["reason"] == "DUPLICATE_RECORD"
    assert len(campaign.records) == 1


def test_mutated_resubmission_cannot_replace_original():
    campaign, item = _single_game_campaign()
    first = campaign.submit_game_record(game_record(item_id=item,
                                                    home_p=0.55))
    assert first["accepted"]
    mutated = game_record(item_id=item, home_p=0.91)
    result = campaign.submit_game_record(mutated)
    assert not result["accepted"]
    stored = campaign.records[first["record_id"]]
    assert stored["model"]["moneyline_home_p"] == 0.55


def test_settlement_is_append_once():
    campaign, item = _single_game_campaign()
    result = campaign.submit_game_record(game_record(item_id=item))
    campaign.submit_settlement(result["record_id"], home_score=27,
                               away_score=20)
    with pytest.raises(fv.ForwardValidationError):
        campaign.submit_settlement(result["record_id"], home_score=99,
                                   away_score=0)


# ---------------------------------------------------------------------------
# Watchdog reconciliation / INDETERMINATE semantics
# ---------------------------------------------------------------------------

def test_missed_capture_becomes_indeterminate_and_cannot_be_backfilled():
    campaign = fv.Campaign(mode="DRY_RUN")
    register(campaign, "G:CLOSING", slate_id="SLATE-1")
    counts = campaign.reconcile(now=BASE_KICKOFF + timedelta(hours=1))
    assert counts["INDETERMINATE"] == 1
    assert campaign.slate_state("SLATE-1") == "INDETERMINATE"
    assert any(a["alert"] == "INDETERMINATE_UNRESOLVED"
               for a in campaign.alerts)
    # A later, perfectly valid capture does NOT erase the state.
    result = campaign.submit_game_record(game_record(item_id="G:CLOSING"))
    assert not result["accepted"]
    assert result["reason"] == "LATE_RECORD_AFTER_TERMINAL_STATE:INDETERMINATE"
    assert campaign.items["G:CLOSING"]["state"] == "INDETERMINATE"
    assert campaign.slate_state("SLATE-1") == "INDETERMINATE"


def test_refused_item_is_process_working_not_indeterminate():
    campaign = fv.Campaign(mode="DRY_RUN")
    register(campaign, "G:CLOSING")
    campaign.record_refusal("G:CLOSING", "PRICE_MINUS_100_INVALID")
    counts = campaign.reconcile(now=BASE_KICKOFF + timedelta(hours=1))
    assert counts["REFUSED"] == 1 and counts["INDETERMINATE"] == 0
    result = campaign.submit_game_record(game_record(item_id="G:CLOSING"))
    assert result["reason"] == "ITEM_ALREADY_REFUSED"


def test_gap_record_is_missed_or_blocked_and_terminal():
    campaign = fv.Campaign(mode="DRY_RUN")
    register(campaign, "G:CLOSING")
    campaign.record_gap("G:CLOSING")
    counts = campaign.reconcile(now=BASE_KICKOFF + timedelta(hours=1))
    assert counts["MISSED_OR_BLOCKED"] == 1
    result = campaign.submit_game_record(game_record(item_id="G:CLOSING"))
    assert result["reason"] == "LATE_RECORD_AFTER_TERMINAL_STATE:MISSED_OR_BLOCKED"


def test_satisfied_item_and_not_yet_due_item():
    campaign = fv.Campaign(mode="DRY_RUN")
    register(campaign, "G:CLOSING")
    register(campaign, "H:CLOSING", game_id="H",
             kickoff=BASE_KICKOFF + timedelta(days=7))
    campaign.submit_game_record(game_record(item_id="G:CLOSING"))
    counts = campaign.reconcile(now=BASE_KICKOFF + timedelta(hours=1))
    assert counts["SATISFIED"] == 1 and counts["PENDING"] == 1


def test_freeze_manifest_mismatch_refused_with_alert():
    campaign = fv.Campaign(mode="DRY_RUN")
    register(campaign, "G:CLOSING", freeze="a" * 64)
    rec = game_record(item_id="G:CLOSING")
    rec["freeze_sha256"] = "b" * 64
    result = campaign.submit_game_record(rec)
    assert result["reason"] == "FREEZE_MANIFEST_MISMATCH"
    assert any(a["alert"] == "FREEZE_MANIFEST_MISMATCH"
               for a in campaign.alerts)


# ---------------------------------------------------------------------------
# Game-leg verdict thresholds
# ---------------------------------------------------------------------------

def _win_loss_model(i, week, home, away):
    return 0.9 if home > away else 0.1


def _alternate_outcomes(i, week):
    return (27, 20) if i % 2 == 0 else (20, 27)


def test_game_leg_299_games_is_accrual_only():
    campaign = build_game_campaign(
        299, 20, model_for=lambda i, w, h, a: 0.5,
        outcome_for=_alternate_outcomes)
    readout = fv.game_leg_readout(campaign, "MONEYLINE", reps=REPS)
    assert readout["status"] == "NOT_YET"
    assert readout["verdict"] is None
    assert readout["label"] == "ACCRUAL_ONLY_NOT_A_VERDICT"
    assert readout["activation_state"] == "ACTIVATION_OFF"
    assert readout["counts"]["rows"] == 299


def test_game_leg_300_games_but_19_blocks_is_accrual_only():
    campaign = build_game_campaign(
        300, 19, model_for=lambda i, w, h, a: 0.5,
        outcome_for=_alternate_outcomes)
    readout = fv.game_leg_readout(campaign, "MONEYLINE", reps=REPS)
    assert readout["status"] == "NOT_YET"
    assert readout["counts"]["week_blocks"] == 19


def test_game_leg_decision_records_never_count_toward_verdict():
    campaign = fv.Campaign(mode="DRY_RUN")
    for i in range(300):
        week = (i % 20) + 1
        kickoff = BASE_KICKOFF + timedelta(days=7 * (week - 1))
        item_id = f"D-{i}:DECISION"
        register(campaign, item_id, kind="DECISION", game_id=f"D-{i}",
                 week=week, kickoff=kickoff)
        result = campaign.submit_game_record(game_record(
            item_id=item_id, week=week, kickoff=kickoff, kind="DECISION",
            game_id=f"D-{i}"))
        assert result["accepted"]
        campaign.submit_settlement(result["record_id"], home_score=27,
                                   away_score=20)
    readout = fv.game_leg_readout(campaign, "MONEYLINE", reps=REPS)
    assert readout["counts"]["rows"] == 0
    assert readout["status"] == "NOT_YET"


def test_game_leg_model_equal_market_is_inconclusive_at_target():
    campaign = build_game_campaign(
        300, 20, model_for=lambda i, w, h, a: 0.5,
        outcome_for=_alternate_outcomes)
    readout = fv.game_leg_readout(campaign, "MONEYLINE", reps=REPS)
    assert readout["status"] == "VERDICT_COMPUTED"
    assert readout["verdict"] == "INCONCLUSIVE"
    assert readout["extension_available"] is False  # point estimate is 0
    assert "ML_TIE_MASS_ZERO_KNOWN_DEFECT" in readout["disclosures"]


def test_game_leg_demonstrated_edge_research_only():
    campaign = build_game_campaign(
        300, 20, model_for=_win_loss_model,
        outcome_for=_alternate_outcomes)
    readout = fv.game_leg_readout(campaign, "MONEYLINE", reps=REPS)
    assert readout["verdict"] == "DEMONSTRATED_EDGE_RESEARCH_ONLY"
    assert readout["research_only"] is True
    assert readout["metrics"]["delta_brier"]["ci_high"] < 0
    assert readout["metrics"]["delta_logloss"]["ci_high"] < 0


def test_game_leg_refuted_when_model_worse_than_close():
    campaign = build_game_campaign(
        300, 20, model_for=lambda i, w, h, a: 0.1 if h > a else 0.9,
        outcome_for=_alternate_outcomes)
    readout = fv.game_leg_readout(campaign, "MONEYLINE", reps=REPS)
    assert readout["verdict"] == "REFUTED"


def test_game_leg_inconclusive_favorable_offers_single_extension():
    def favorable_noisy(i, week, home, away):
        # Weeks 1-12: model strong (deltas favorable). Weeks 13-20:
        # model weak on home wins (deltas unfavorable). Grand means
        # favorable; week-cluster CIs straddle zero by construction.
        return 0.75 if week <= 12 else 0.30

    campaign = build_game_campaign(
        300, 20, model_for=favorable_noisy,
        outcome_for=lambda i, w: (27, 20))
    readout = fv.game_leg_readout(campaign, "MONEYLINE")  # default reps
    assert readout["verdict"] == "INCONCLUSIVE"
    assert readout["metrics"]["delta_brier"]["mean"] < 0
    assert readout["metrics"]["delta_logloss"]["mean"] < 0
    assert readout["extension_available"] is True
    assert readout["extension_target_n"] == 600
    # Under the extension, n=300 is accrual again — no interim verdict.
    extended = fv.game_leg_readout(campaign, "MONEYLINE", reps=REPS,
                                   extension_used=True)
    assert extended["status"] == "NOT_YET"


def test_game_leg_coverage_below_75_percent_is_inconclusive_coverage():
    campaign = build_game_campaign(
        300, 20, model_for=_win_loss_model,
        outcome_for=_alternate_outcomes, expected_extra=200)
    readout = fv.game_leg_readout(campaign, "MONEYLINE", reps=REPS)
    assert readout["counts"]["satisfied_ratio"] == pytest.approx(0.6)
    assert readout["verdict"] == "INCONCLUSIVE"
    assert readout["verdict_detail"] == "COVERAGE"


def test_game_leg_push_and_tie_exclusions_are_counted():
    campaign = fv.Campaign(mode="DRY_RUN")
    register(campaign, "PUSH:CLOSING", game_id="PUSH")
    rec = game_record(item_id="PUSH:CLOSING", game_id="PUSH",
                      spread_line=-3.0, total_line=47.0)
    result = campaign.submit_game_record(rec)
    campaign.submit_settlement(result["record_id"], home_score=27,
                               away_score=24)  # margin 3, total 51... use 47
    readout = fv.game_leg_readout(campaign, "SPREAD", reps=REPS)
    assert readout["counts"]["excluded_pushes"] == 1
    campaign2 = fv.Campaign(mode="DRY_RUN")
    register(campaign2, "TIE:CLOSING", game_id="TIE")
    result2 = campaign2.submit_game_record(
        game_record(item_id="TIE:CLOSING", game_id="TIE"))
    campaign2.submit_settlement(result2["record_id"], home_score=20,
                                away_score=20)
    readout2 = fv.game_leg_readout(campaign2, "MONEYLINE", reps=REPS)
    assert readout2["counts"]["excluded_ties"] == 1
    assert readout2["counts"]["rows"] == 0


# ---------------------------------------------------------------------------
# Prop leg
# ---------------------------------------------------------------------------

def test_prop_149_rows_accrual_only():
    campaign = build_prop_campaign(149, 15)
    readout = fv.prop_leg_readout(campaign, "PASS_YARDS", reps=REPS)
    assert readout["status"] == "NOT_YET"
    assert readout["label"] == "ACCRUAL_ONLY_NOT_A_VERDICT"
    assert readout["verdict"] is None


def test_prop_150_rows_provisional_labeled_everywhere():
    campaign = build_prop_campaign(150, 15, engine_p=0.9, stat=260.0)
    readout = fv.prop_leg_readout(campaign, "PASS_YARDS", reps=REPS)
    assert readout["status"] == "PROVISIONAL"
    assert readout["label"] == "PROVISIONAL_UNDERPOWERED"
    assert readout["verdict"] is None
    assert readout["descriptive"]["delta_brier_mean"] < 0
    text = fv.render_readout_text(readout)
    assert "PROVISIONAL_UNDERPOWERED" in text
    assert "ACTIVATION_OFF" in text


def test_prop_299_rows_still_provisional():
    campaign = build_prop_campaign(299, 15)
    readout = fv.prop_leg_readout(campaign, "PASS_YARDS", reps=REPS)
    assert readout["status"] == "PROVISIONAL"
    assert readout["verdict"] is None


def test_prop_300_rows_but_14_weeks_stays_provisional():
    campaign = build_prop_campaign(300, 14)
    readout = fv.prop_leg_readout(campaign, "PASS_YARDS", reps=REPS)
    assert readout["status"] == "PROVISIONAL"
    assert readout["provisional_reason"] == "WEEK_BLOCKS_BELOW_15"


def test_prop_300_rows_15_weeks_verdict_computed():
    campaign = build_prop_campaign(300, 15, engine_p=0.9, stat=260.0)
    readout = fv.prop_leg_readout(campaign, "PASS_YARDS", reps=REPS)
    assert readout["status"] == "VERDICT_COMPUTED"
    assert readout["verdict"] == "DEMONSTRATED_EDGE_RESEARCH_ONLY"


def test_prop_s2_missing_excluded_and_counted():
    campaign = fv.Campaign(mode="DRY_RUN")
    register(campaign, "PX:CLOSING")
    rec = prop_record(item_id="PX:CLOSING", s2=False)
    result = campaign.submit_prop_record(rec)
    assert not result["accepted"]
    assert result["reason"] == "PARTICIPATION_S2_MISSING_EXCLUDED"
    assert campaign.prop_exclusions[0]["reason"] == \
        "PARTICIPATION_S2_MISSING_EXCLUDED"


def test_prop_s1_missing_is_partial_and_excluded_from_verdict_rows():
    campaign = build_prop_campaign(150, 15)
    register(campaign, "PARTIAL:CLOSING")
    rec = prop_record(item_id="PARTIAL:CLOSING", player="PX", s1=False)
    result = campaign.submit_prop_record(rec)
    assert result["accepted"]
    campaign.submit_prop_settlement(result["record_id"], stat_value=260.0)
    readout = fv.prop_leg_readout(campaign, "PASS_YARDS", reps=REPS)
    assert readout["counts"]["partial_participation"] == 1
    assert readout["counts"]["rows"] == 150


def test_prop_engine_prob_must_be_at_captured_line():
    campaign = fv.Campaign(mode="DRY_RUN")
    register(campaign, "PL:CLOSING")
    rec = prop_record(item_id="PL:CLOSING", engine_line=249.5,
                      recomputed=False)
    result = campaign.submit_prop_record(rec)
    assert result["reason"] == "ENGINE_PROB_NOT_AT_CAPTURED_LINE"
    campaign2 = fv.Campaign(mode="DRY_RUN")
    register(campaign2, "PL:CLOSING")
    rec2 = prop_record(item_id="PL:CLOSING", engine_line=249.5,
                       recomputed=True)
    assert campaign2.submit_prop_record(rec2)["accepted"]


def test_prop_out_of_scope_family_refused():
    campaign = fv.Campaign(mode="DRY_RUN")
    register(campaign, "PX:CLOSING")
    rec = prop_record(item_id="PX:CLOSING", family="PLAYER_SACKS")
    result = campaign.submit_prop_record(rec)
    assert result["reason"].startswith("FAMILY_OUT_OF_SCOPE")


def test_prop_dnp_and_push_counted_not_scored():
    campaign = build_prop_campaign(150, 15)
    register(campaign, "DNP:CLOSING")
    rec = prop_record(item_id="DNP:CLOSING", player="PD")
    result = campaign.submit_prop_record(rec)
    campaign.submit_prop_settlement(result["record_id"], stat_value=None,
                                    dnp=True)
    register(campaign, "PUSH:CLOSING")
    push = prop_record(item_id="PUSH:CLOSING", player="PP", line=250.0)
    push_result = campaign.submit_prop_record(push)
    assert push_result["accepted"]
    campaign.submit_prop_settlement(push_result["record_id"],
                                    stat_value=250.0)
    readout = fv.prop_leg_readout(campaign, "PASS_YARDS", reps=REPS)
    assert readout["counts"]["void_dnp"] == 1
    assert readout["counts"]["excluded_pushes"] == 1
    assert readout["counts"]["rows"] == 150


def test_anytime_td_has_no_pair_contract_verdict():
    campaign = fv.Campaign(mode="DRY_RUN")
    register(campaign, "ATD:CLOSING")
    rec = {
        "record_kind": "PROP_CAPTURE", "origin": "SYNTHETIC",
        "game_id": "G", "week_block": 1, "kickoff_utc": iso(BASE_KICKOFF),
        "player_id": "P9", "family": "ANYTIME_TD",
        "quote": {"price": 150,
                  "captured_at": iso(BASE_KICKOFF - timedelta(minutes=10))},
        "participation": {"s1": {"designation": "Full"},
                          "s2": {"designation": "Active"}},
        "expected_item_id": "ATD:CLOSING"}
    result = campaign.submit_prop_record(rec)
    assert result["accepted"]
    readout = fv.prop_leg_readout(campaign, "ANYTIME_TD", reps=REPS)
    assert readout["status"] == \
        "PAIR_CONTRACT_UNDEFINED_FOR_SINGLE_SIDED_MARKET"
    assert readout["verdict"] is None


# ---------------------------------------------------------------------------
# Activation refusal / hard boundaries
# ---------------------------------------------------------------------------

def test_evidence_campaign_refused_by_construction():
    with pytest.raises(fv.ForwardValidationNotActivated) as exc:
        fv.Campaign(mode="EVIDENCE")
    assert "FORWARD_VALIDATION_NOT_ACTIVATED" in str(exc.value)


def test_open_evidence_campaign_refused_without_approval_artifact(tmp_path):
    with pytest.raises(fv.ForwardValidationNotActivated) as exc:
        fv.open_evidence_campaign(tmp_path)
    assert "FORWARD_VALIDATION_NOT_ACTIVATED" in str(exc.value)


def test_even_a_present_artifact_does_not_activate_this_build(tmp_path):
    artifact = tmp_path / "config" / "research" / \
        "nfl_forward_validation_activation_v1.json"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("{}")
    with pytest.raises(fv.ForwardValidationNotActivated) as exc:
        fv.open_evidence_campaign(tmp_path)
    assert "ACTIVATION_NOT_IMPLEMENTED_IN_THIS_BUILD" in str(exc.value)


def test_real_origin_record_refused_in_dry_run():
    campaign, item = _single_game_campaign()
    rec = game_record(item_id=item)
    rec["origin"] = "FORWARD_CAPTURE"
    result = campaign.submit_game_record(rec)
    assert result["reason"].startswith(
        "NON_SYNTHETIC_RECORD_REFUSED_IN_DRY_RUN")


def test_missing_origin_refused():
    campaign, item = _single_game_campaign()
    rec = game_record(item_id=item)
    del rec["origin"]
    result = campaign.submit_game_record(rec)
    assert result["reason"] == "RECORD_ORIGIN_MISSING"


def test_cli_refuses_activation_and_runs_dry_run_proof(tmp_path):
    script = REPO_ROOT / "scripts" / "run_nfl_forward_validation.py"
    refused = subprocess.run([sys.executable, str(script)],
                             capture_output=True, text=True)
    assert refused.returncode == 2
    assert "FORWARD_VALIDATION_NOT_ACTIVATED" in refused.stderr
    out_dir = tmp_path / "proof"
    ok = subprocess.run([sys.executable, str(script), "--dry-run-proof",
                         "--output-dir", str(out_dir)],
                        capture_output=True, text=True)
    assert ok.returncode == 0, ok.stderr
    report = json.loads(
        (out_dir / "nfl_forward_validation_dry_run_proof.json")
        .read_text())
    assert report["verdict"] == "NOT_YET"
    assert report["stamp"] == "DRY_RUN_NOT_EVIDENCE"
    assert report["activation_state"] == "ACTIVATION_OFF"


def test_module_has_no_network_or_scheduler_surface():
    import ast
    tree = ast.parse(Path(fv.__file__).read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    forbidden = {"urllib", "requests", "socket", "http", "subprocess",
                 "sched", "apscheduler", "celery", "ftplib", "smtplib"}
    assert not (imported & forbidden), imported & forbidden


def test_config_manifest_declares_activation_off():
    manifest = json.loads(
        (REPO_ROOT / "config" / "research"
         / "nfl_forward_validation_v1.json").read_text())
    assert manifest["activation_state"] == "ACTIVATION_OFF"
    assert manifest["freeze_sha"] is None
    assert all(v is False for v in manifest["authority"].values())


# ---------------------------------------------------------------------------
# Two-slate dry-run proof
# ---------------------------------------------------------------------------

def test_two_slate_dry_run_proof_end_to_end():
    report = fv.run_two_slate_dry_run_proof(games_per_slate=4)
    assert report["verdict"] == "NOT_YET"
    assert report["label"] == "ACCRUAL_ONLY_NOT_A_VERDICT"
    counts = report["reconciliation_counts"]
    assert counts["SATISFIED"] == 15
    assert counts["REFUSED"] == 2
    assert counts["INDETERMINATE"] == 1
    assert counts["MISSED_OR_BLOCKED"] == 0
    assert report["refusals"], "a dry run with zero refusals is suspicious"
    assert "warning" not in report
    assert any(a["alert"] == "INDETERMINATE_UNRESOLVED"
               for a in report["alerts"])
    for fam, readout in report["readouts"].items():
        assert readout["status"] == "NOT_YET", fam
        assert readout["counts"]["rows"] == 7, fam
    with pytest.raises(fv.ForwardValidationError):
        fv.require_evidence_admissible(report)


def test_every_dry_run_record_is_stamped():
    campaign, item = _single_game_campaign()
    result = campaign.submit_game_record(game_record(item_id=item))
    stored = campaign.records[result["record_id"]]
    assert stored["stamp"] == "DRY_RUN_NOT_EVIDENCE"
