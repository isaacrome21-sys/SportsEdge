"""Regression tests: legacy NFL quarter route corrective (Oct 13, 2026).

Findings (NFL engine audit, Oct 13, 2026): the legacy coverage route in
sportsedge/market_coverage.py priced NFL quarter markets spelled
ML_nQ / SPREAD_nQ at the unfitted QUARTER_FRACTION = 0.25 scale, and its
_base_means added the recent-form factor -- which the owner's Oct 13,
2026 ruling DISABLED (contribution exactly zero) in every canonical
pricing path, and which the period rulings bar from period pricing
altogether (period families may not inherit full-game probabilities or
use an unfitted scale multiplier; NFL period markets fail closed
NO_ENGINE for want of a compliant period distribution).

These tests pin the corrective:
  * every legacy NFL quarter spelling fails closed with the canonical
    derivative stage's outcome (status NO_MODEL_OR_MARKET, reason
    SIMULATION_ROWS_EMPTY, blocker NO_ENGINE) -- parity across spellings
    through the full runner;
  * on every surviving priced coverage path (CFB quarters, margin
    bands), a nonzero recent-form value changes nothing, while the
    declared value stays in context for research with the disabled note;
  * non-NFL gates (CFB/MLB FAILED_VALIDATION) and the legacy spellings'
    recognition (normalization) are unchanged.
All offline (auto_context=False).
"""
from datetime import datetime, timedelta, timezone

import pytest

import sportsedge.market_coverage as mc
from sportsedge.market_coverage import (
    normalize_coverage_market,
    price_coverage_row,
)

NOW = datetime(2026, 10, 11, 18, 0, tzinfo=timezone.utc)
FUTURE = (NOW + timedelta(days=2)).isoformat()

NFL_TEAMS = {"away": "Baltimore Ravens", "home": "Atlanta Falcons"}
CFB_TEAMS = {"away": "Georgia Bulldogs", "home": "Alabama Crimson Tide"}


def row(sport, teams, market, **kw):
    base = {"sport": sport, "commence_time": FUTURE, "odds": -110,
            "market": market}
    base.update(teams)
    base.update(kw)
    return base


def outcome(r):
    return (r.get("status"), r.get("reason"), r.get("blocker"))


CANONICAL_BLOCK = ("NO_MODEL_OR_MARKET", "SIMULATION_ROWS_EMPTY", "NO_ENGINE")

LEGACY_QUARTERS = (
    [f"ML_{q}Q" for q in (1, 2, 3, 4)]
    + [f"SPREAD_{q}Q" for q in (1, 2, 3, 4)]
    + [f"TOTAL_{q}Q" for q in (1, 2, 3, 4)]
    + [f"TEAM_TOTAL_{q}Q" for q in (1, 2, 3, 4)]
)


# --- lane-level block: every legacy NFL quarter spelling ---------------------

@pytest.mark.parametrize("market", LEGACY_QUARTERS)
def test_legacy_nfl_quarter_spellings_block_no_engine(market):
    kw = {}
    if market.startswith(("SPREAD_", "TOTAL_", "TEAM_TOTAL_")):
        kw["line"] = 6.5
    kw["side"] = "HOME_OVER" if market.startswith("TEAM_TOTAL_") else (
        "OVER" if market.startswith("TOTAL_") else "HOME")
    out = price_coverage_row(row("NFL", NFL_TEAMS, market, **kw),
                             now=NOW, auto_context=False)
    assert outcome(out) == CANONICAL_BLOCK
    assert "estimate_p" not in out


@pytest.mark.parametrize("alias", ["FIRST_QUARTER_MONEYLINE",
                                   "SECOND_QUARTER_SPREAD",
                                   "THIRD_QUARTER_TOTAL",
                                   "FOURTH_QUARTER_MONEYLINE"])
def test_legacy_nfl_quarter_long_form_aliases_block_no_engine(alias):
    kw = {"side": "HOME"}
    if "SPREAD" in alias or "TOTAL" in alias:
        kw["line"] = -1.5 if "SPREAD" in alias else 9.5
        kw["side"] = "OVER" if "TOTAL" in alias else "HOME"
    out = price_coverage_row(row("NFL", NFL_TEAMS, alias, **kw),
                             now=NOW, auto_context=False)
    assert outcome(out) == CANONICAL_BLOCK


def test_legacy_spellings_still_recognized():
    # The spellings are NOT deleted: historical records and settlement
    # references name them, and the coverage matrix still recognizes
    # them. Only the NFL pricing path blocks.
    for market in LEGACY_QUARTERS:
        assert normalize_coverage_market(market) == market
    assert normalize_coverage_market("first_quarter_moneyline") == "ML_1Q"


# --- parity through the full runner ------------------------------------------

def test_run_full_legacy_canonical_spelling_parity():
    from artifacts import run_it_full
    pairs = [
        # (legacy row, canonical row)
        (row("NFL", NFL_TEAMS, "ML_1Q", side="HOME"),
         row("NFL", NFL_TEAMS, "QUARTER_MONEYLINE", side="HOME", quarter=1)),
        (row("NFL", NFL_TEAMS, "SPREAD_2Q", side="HOME", line=-0.5),
         row("NFL", NFL_TEAMS, "QUARTER_SPREAD", side="HOME", line=-0.5,
             quarter=2)),
        (row("NFL", NFL_TEAMS, "TOTAL_3Q", side="OVER", line=9.5),
         row("NFL", NFL_TEAMS, "QUARTER_TOTAL", side="OVER", line=9.5,
             quarter=3)),
        (row("NFL", NFL_TEAMS, "TEAM_TOTAL_4Q", side="HOME_OVER", line=6.5),
         None),  # no canonical quarter-team-total name exists
    ]
    lines = []
    for legacy, canonical in pairs:
        lines.append(legacy)
        if canonical is not None:
            lines.append(canonical)
    card = run_it_full.run_full({"lines": lines}, now=NOW, auto_context=False)
    rows = card["evaluated_rows"]
    assert len(rows) == len(lines)
    idx = 0
    for legacy, canonical in pairs:
        legacy_out = rows[idx]
        idx += 1
        assert outcome(legacy_out) == CANONICAL_BLOCK, legacy_out
        if canonical is not None:
            canonical_out = rows[idx]
            idx += 1
            assert outcome(canonical_out) == CANONICAL_BLOCK, canonical_out
            assert outcome(legacy_out) == outcome(canonical_out)


# --- recent form: exactly zero on every surviving priced coverage path -------

@pytest.mark.parametrize("sport,teams,market,kw", [
    ("CFB", CFB_TEAMS, "SPREAD_1Q", {"side": "HOME", "line": -1.5}),
    ("CFB", CFB_TEAMS, "ML_2Q", {"side": "AWAY"}),
    ("NFL", NFL_TEAMS, "MARGIN_BAND", {"side": "HOME_7_12"}),
    ("CFB", CFB_TEAMS, "MARGIN_BAND", {"side": "AWAY_1_6"}),
])
def test_recent_form_contributes_zero_on_surviving_paths(sport, teams,
                                                         market, kw):
    plain = price_coverage_row(row(sport, teams, market, **kw),
                               now=NOW, auto_context=False)
    loaded = price_coverage_row(
        row(sport, teams, market,
            context={"home_form": 3.0, "away_form": -3.0}, **kw),
        now=NOW, auto_context=False)
    assert plain["status"] in {"RESEARCH_EDGE", "BELOW_THRESHOLD", "PRICE_CAP"}
    # Identical means and price: the disabled factor moves nothing.
    assert loaded["estimate_p"] == plain["estimate_p"]
    assert loaded["home_mean"] == plain["home_mean"]
    assert loaded["away_mean"] == plain["away_mean"]
    # The declared value is retained in context for research, labeled.
    assert loaded["context"]["home_form"] == 3.0
    assert loaded["context"]["away_form"] == -3.0
    assert "RECENT_FORM_DISABLED_PENDING_INCREMENTAL_VALUE" in \
        loaded["context_notes"]


def test_base_means_exclude_form_include_injury():
    base = mc._base_means(
        row("NFL", NFL_TEAMS, "MARGIN_BAND", side="HOME_1_6",
            context={"home_form": 2.0, "away_form": -2.0,
                     "home_injury_pts": 1.0, "away_injury_pts": 0.5}),
        now=NOW, auto_context=False)
    prior, _, _, hfa = mc.PRIORS["NFL"]
    # Injury points are part of the retained construction; form is not.
    assert base["home_mean"] == pytest.approx(prior + hfa / 2 + 1.0)
    assert base["away_mean"] == pytest.approx(prior - hfa / 2 + 0.5)
    assert base["context"]["home_form"] == 2.0  # retained for research
    assert "RECENT_FORM_DISABLED_PENDING_INCREMENTAL_VALUE" in \
        base["context_notes"]


def test_base_means_exclude_era_pitcher_adjustment_mlb():
    base = mc._base_means(
        row("MLB", {"away": "Los Angeles Dodgers",
                    "home": "Milwaukee Brewers"}, "ML_3WAY", side="HOME",
            context={"home_pitcher_adj": -1.0, "away_pitcher_adj": 0.8}),
        now=NOW, auto_context=False)
    prior, _, _, hfa = mc.PRIORS["MLB"]
    assert base["home_mean"] == pytest.approx(prior + hfa / 2)
    assert base["away_mean"] == pytest.approx(prior - hfa / 2)
    assert base["context"]["home_pitcher_adj"] == -1.0  # retained
    assert "PITCHER_ADJ_DISABLED_PENDING_INCREMENTAL_VALUE" in \
        base["context_notes"]


# --- non-NFL gates unchanged ---------------------------------------------------

def test_non_nfl_failed_validation_gates_unchanged():
    cfb_total = price_coverage_row(
        row("CFB", CFB_TEAMS, "TOTAL_1Q", side="OVER", line=9.5),
        now=NOW, auto_context=False)
    assert cfb_total["status"] == "NO_MODEL_OR_MARKET"
    assert cfb_total["reason"] == "COVERAGE_MARKET_FAILED_VALIDATION_NOT_WIRED"
    mlb_3way = price_coverage_row(
        row("MLB", {"away": "Los Angeles Dodgers",
                    "home": "Milwaukee Brewers"}, "ML_3WAY", side="HOME"),
        now=NOW, auto_context=False)
    assert mlb_3way["status"] == "NO_MODEL_OR_MARKET"
    assert mlb_3way["reason"] == "COVERAGE_MARKET_FAILED_VALIDATION_NOT_WIRED"
