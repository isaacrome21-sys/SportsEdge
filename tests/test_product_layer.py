"""Product-layer tests: card format, paper metrics, red-team degradation cases.

Research-only; no network. Synthetic card dicts mirror the shapes produced by
artifacts/free_models.py (game rows) and research_three_sport_bridge.py (props).
"""
from __future__ import annotations

import pytest

from sportsedge.card_format import (
    extract_plays, format_research_card, model_probability_of,
)
from sportsedge.paper_metrics import (
    PaperMetricsError, beat_close, paper_ledger, summarize, to_markdown,
    validate_record,
)


def game_row(**kw):
    row = {"sport": "NFL", "game": "BAL @ ATL", "selection": "BAL -3",
           "market": "SPREAD", "odds_american": -110, "line": -3,
           "estimate_p": 0.55, "ev_per_dollar": 0.03, "status": "RESEARCH_EDGE",
           "model_validation": "NOT_PROVEN_VS_CLOSE", "context_quality": "HEURISTIC_UNVALIDATED",
           "independent_projection": {"estimate_p": 0.55},
           "market_anchor": {"status": "MARKET_ANCHORED_UNVALIDATED"}}
    row.update(kw)
    return row


def prop_row(**kw):
    row = {"sport": "MLB", "market": "PITCHER_K", "selection": "over",
           "player_name": "T. Skubal", "line": 7.5, "dk_odds": -115,
           "model_probability": 0.58, "ev_per_dollar": 0.024,
           "status": "RESEARCH_CANDIDATE_NOT_VALIDATED",
           "quote_status": "RECENT_CAPTURED_QUOTE",
           "game_id": "123", "model_validation": "NOT_PROVEN_VS_CLOSE"}
    row.update(kw)
    return row


def card_of(*rows):
    return {"as_of_utc": "2026-10-11T00:00:00+00:00",
            "summary": {"rows": len(rows)},
            "evaluated_rows": list(rows),
            "factor_coverage": {"status_counts": {"NOT_WIRED": 4, "HEURISTIC_NOT_VALIDATED": 2}}}


# ---------- card format ----------

def play_lines(card):
    return [l for l in card["rendered_card"].splitlines()
            if l[:2].strip().rstrip(".").isdigit() and "→ model" in l]


def test_plays_ranked_by_ev_probability_before_status():
    card = format_research_card(card_of(
        prop_row(ev_per_dollar=0.01), game_row(ev_per_dollar=0.05),
        game_row(status="BELOW_THRESHOLD", ev_per_dollar=0.001)))
    assert [p["ev_per_dollar"] for p in card["plays"]] == [0.05, 0.01, 0.001]
    for line in play_lines(card):
        assert line.index("→ model") < line.index("→ EV"), line
            # probability digits come before the EV% digits
    assert card["playable_count"] == 2


def test_play_line_shape():
    card = format_research_card(card_of(prop_row()))
    line = play_lines(card)[0]
    assert "T. Skubal" in line and "7.5" in line and "-115" in line
    assert "model 58.0%" in line and "EV +2.40%" in line


def test_zero_edge_card_is_valid_not_padded():
    card = format_research_card(card_of(
        game_row(status="BELOW_THRESHOLD", ev_per_dollar=0.001)))
    assert card["playable_count"] == 0
    assert card["plays"], "priced selections still listed"
    assert "NO EDGES TODAY" in card["rendered_card"]
    assert "valid card" in card["rendered_card"]


def test_degenerate_probabilities_excluded_never_priced():
    bad = [
        game_row(estimate_p=0.0), game_row(estimate_p=1.0),
        game_row(estimate_p=float("nan")),
        game_row(estimate_p="abc", independent_projection={}),
        game_row(estimate_p=None, independent_projection={}),
    ]
    for b in bad:
        b.pop("model_probability", None)
        # degenerate must hold on the preferred independent lane too
        b["independent_projection"] = {"estimate_p": b.get("estimate_p")}
    card = format_research_card(card_of(*bad))
    assert card["plays"] == []
    assert len(card["excluded"]) == len(bad)
    assert all(e["reason"] == "DEGENERATE_OR_MISSING_PROBABILITY" for e in card["excluded"])
    assert model_probability_of(game_row(estimate_p=1.0, independent_projection={})) is None


def test_empty_board_renders():
    card = format_research_card(card_of())
    assert card["plays"] == [] and card["excluded"] == []
    assert "NO EDGES TODAY" in card["rendered_card"]


def test_uncertainty_flags_surfaced_on_card():
    card = format_research_card(card_of(game_row()))
    line = play_lines(card)[0]
    assert "MARKET_ANCHORED_UNVALIDATED" in line
    assert "INDEPENDENT_MARKET_BLIND" in line
    assert "NOT_PROVEN_VS_CLOSE" in line


# ---------- paper metrics ----------

def rec(**kw):
    r = {"month": "2026-10", "selection": "BAL -3", "odds_american": -110,
         "our_p": 0.55, "close_p": 0.57, "close_status": "AVAILABLE",
         "result": "WIN", "units": 1.0}
    r.update(kw)
    return r


def test_beat_close_mixed_missing_degrades_not_invents():
    bc = beat_close([rec(), rec(close_p=0.50), rec(close_status="MISSING", close_p=None)])
    assert bc["status"] == "AVAILABLE"
    assert bc["n"] == 2 and bc["missing_close_n"] == 1
    assert bc["beat"] == 1  # only close_p 0.57 > our_p 0.55
    assert bc["beat_close_pct"] == 50.0
    assert bc["clv_edge_pp"] == pytest.approx(((0.57 - 0.55) + (0.50 - 0.55)) / 2 * 100)


def test_beat_close_all_missing_is_missing_not_zero():
    bc = beat_close([rec(close_status="MISSING", close_p=None), rec(close_status="MISSING")])
    assert bc["status"] == "MISSING"
    assert bc["beat_close_pct"] is None and bc["clv_edge_pp"] is None
    assert bc["n"] == 0


def test_degenerate_records_rejected():
    with pytest.raises(PaperMetricsError):
        validate_record(rec(our_p=1.0))
    with pytest.raises(PaperMetricsError):
        validate_record(rec(our_p=0.0))
    with pytest.raises(PaperMetricsError):
        validate_record(rec(close_p=float("nan")))
    with pytest.raises(PaperMetricsError):
        validate_record(rec(result="MAYBE"))
    with pytest.raises(PaperMetricsError):
        validate_record(rec(units=0))
    rep = summarize([rec(our_p=1.0), rec()])
    assert rep["beat_close"]["rejected_n"] == 1
    assert rep["beat_close"]["n"] == 1


def test_empty_records_is_valid_report():
    rep = summarize([])
    assert rep["records_evaluated"] == 0
    assert rep["research_only"] is True and rep["hypothetical"] is True
    assert rep["beat_close"]["status"] == "MISSING"
    assert rep["monthly_ledger"]["months"] == []
    assert rep["totals"]["units_risked"] == 0
    md = to_markdown(rep)
    assert "zero-play month is valid" in md


def test_ledger_shows_red_months_with_units_denominator():
    records = [
        rec(month="2026-09", result="LOSS"), rec(month="2026-09", result="LOSS"),
        rec(month="2026-10", result="WIN", odds_american=-110),
        rec(month="2026-10", result="PUSH"),
        rec(month="2026-10", result="UNSETTLED"),  # excluded from ledger
    ]
    ledger = paper_ledger(records)["months"]
    sep = next(m for m in ledger if m["month"] == "2026-09")
    oct_ = next(m for m in ledger if m["month"] == "2026-10")
    assert sep["red_month"] is True and sep["profit_units"] == -2.0
    assert sep["units_risked"] == 2.0
    # WIN at -110 risks 1u, profits 100/110, ledger rounds to 2dp
    assert oct_["profit_units"] == pytest.approx(0.91)
    assert oct_["units_risked"] == 2.0  # WIN + PUSH counted; UNSETTLED excluded
    assert oct_["red_month"] is False
    md = to_markdown(summarize(records))
    assert "2026-09" in md and "-2.00u" in md and "u risked" in md
    assert "HYPOTHETICAL" in md and "No bets were placed" in md


def test_positive_odds_payout_math():
    ledger = paper_ledger([rec(month="2026-10", result="WIN", odds_american=150)])["months"]
    assert ledger[0]["profit_units"] == pytest.approx(1.5)


def test_unsettled_counts_in_beat_close_not_ledger():
    records = [rec(result="UNSETTLED"), rec(result="UNSETTLED", close_status="MISSING")]
    rep = summarize(records)
    assert rep["beat_close"]["n"] == 1  # pricing metric needs no settlement
    assert rep["monthly_ledger"]["unsettled_excluded_n"] == 2
    assert rep["monthly_ledger"]["months"] == []
