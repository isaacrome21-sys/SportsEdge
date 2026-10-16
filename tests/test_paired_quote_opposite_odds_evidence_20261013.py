"""Opposite-price evidence standard for the no-vig comparison.

An opposite price asserted as an ``opposite_odds`` field on the SAME intake
row is not a separately timestamped quote: there is no counterpart
observation, no event/period/settlement identity check on a second quote,
and no timestamp pair. It must never earn the EXACT_DK_TWO_SIDED label or
produce a market_no_vig_p — even when the row's own quote_captured_at is
present and valid, because timestamping the assertion does not cure the
missing counterpart. The refusal status names that defect
(OPPOSITE_PRICE_NOT_A_TIMESTAMPED_QUOTE) in both the timestamped and
untimestamped cases rather than QUOTE_TIMESTAMP_MISSING, which would
falsely imply the row's own quote lacked a timestamp.

Kept behaviors: a real partner row still pairs (with the 120s timestamp
enforcement in test_paired_quote_timestamps_20261013.py), a partner row
whose price disagrees with opposite_odds still fails OPPOSITE_ML_CONFLICT,
and a malformed opposite_odds still fails closed (rejected inside
calculate as BLOCKED_INVALID before pairing; the pairing-level
OPPOSITE_ML_INVALID branches are untouched by this change).
"""
from datetime import datetime, timezone
from pathlib import Path
import importlib.util

ROOT = Path(__file__).resolve().parents[1]
engine_spec = importlib.util.spec_from_file_location(
    "free_paired_opp", ROOT / "artifacts" / "free_models.py")
engine = importlib.util.module_from_spec(engine_spec)
engine_spec.loader.exec_module(engine)
NOW = datetime(2026, 10, 11, 13, 0, tzinfo=timezone.utc)
KICKOFF = "2026-10-12T01:15:00Z"
T0 = "2026-10-11T12:59:00Z"

_OMIT = object()


def ml_row(side="AWAY", odds=145, opposite=-175, captured=T0):
    base = {"away": "Buffalo Bills", "home": "Los Angeles Rams",
            "market": "ML", "side": side, "odds": odds,
            "kickoff": KICKOFF}
    if opposite is not _OMIT:
        base["opposite_odds"] = opposite
    if captured is not _OMIT:
        base["quote_captured_at"] = captured
    return base


def card(rows):
    return engine.run({"sport": "NFL", "lines": rows}, now=NOW,
                      auto_context=False)


def projection(c, i=0):
    return c["evaluated_rows"][i]["independent_projection"]


def test_opposite_odds_only_with_own_timestamp_is_refused():
    c = card([ml_row()])
    p = projection(c)
    assert p["paired_market_status"] == "OPPOSITE_PRICE_NOT_A_TIMESTAMPED_QUOTE"
    assert "market_no_vig_p" not in p
    assert "edge_vs_dk_no_vig_pp" not in p
    # The refusal has surface consequences: no independent candidate, the
    # row may surface at most on the watchlist.
    assert c["independent_candidates"] == []
    assert len(c["lane_a_research_diagnostics"]) == 1


def test_opposite_odds_only_without_timestamp_is_refused_with_same_status():
    # The evidentiary defect is identical — no counterpart quote exists —
    # so the refusal names it directly instead of QUOTE_TIMESTAMP_MISSING.
    c = card([ml_row(captured=_OMIT)])
    p = projection(c)
    assert p["paired_market_status"] == "OPPOSITE_PRICE_NOT_A_TIMESTAMPED_QUOTE"
    assert "market_no_vig_p" not in p
    assert c["independent_candidates"] == []


def test_partner_row_with_agreeing_opposite_odds_still_pairs():
    c = card([ml_row(),
              ml_row(side="HOME", odds=-175, opposite=145)])
    for i in (0, 1):
        p = projection(c, i)
        assert p["paired_market_status"] == "EXACT_DK_TWO_SIDED_NO_VIG_RESEARCH"
        assert "market_no_vig_p" in p
    assert abs(projection(c, 0)["market_no_vig_p"]
               + projection(c, 1)["market_no_vig_p"] - 1) < 1e-5


def test_partner_row_with_disagreeing_opposite_odds_still_conflicts():
    c = card([ml_row(),
              ml_row(side="HOME", odds=-180, opposite=145)])
    for i in (0, 1):
        p = projection(c, i)
        assert p["paired_market_status"] == "OPPOSITE_ML_CONFLICT"
        assert "market_no_vig_p" not in p
    assert c["independent_candidates"] == []


def test_malformed_opposite_odds_without_partner_fails_closed():
    # A grossly malformed opposite_odds never reaches the pairing stage:
    # calculate() rejects it while building the anchored side-view, so the
    # row is BLOCKED_INVALID with no projection, no pair, and no no-vig —
    # fail-closed one layer earlier than OPPOSITE_ML_INVALID. (The
    # pairing-level OPPOSITE_ML_INVALID branches in _paired_book_context
    # are untouched by the opposite_odds-evidence change; the git diff for
    # this fix is confined to the no-partner refusal below them.)
    for bad in ("not-a-price", -150.5):
        c = card([ml_row(opposite=bad)])
        row = c["evaluated_rows"][0]
        assert row["status"] == "BLOCKED_INVALID"
        assert "independent_projection" not in row
        assert c["independent_candidates"] == []
