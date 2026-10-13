"""Phase 7 market-coverage tests: pricers, fail-closed paths, and run_it_full routing.

All tests run offline (auto_context=False / synthetic data); no network.
"""
from datetime import datetime, timedelta, timezone

import pytest

from sportsedge.market_coverage import (
    COVERAGE_MARKETS,
    MARGIN_BANDS,
    normalize_coverage_market,
    phone_coverage_rows,
    price_coverage_row,
    quarter_of,
)
from sportsedge.mlb_phone_f5_pricing import normalize_f5_market, phone_f5_rows
from sportsedge.f5_distribution import build_f5_distribution, read_f5_probability

NOW = datetime(2026, 10, 11, 18, 0, tzinfo=timezone.utc)
FUTURE = (NOW + timedelta(days=2)).isoformat()
PAST = (NOW - timedelta(days=2)).isoformat()


def row(**kw):
    base = {"sport": "MLB", "away": "Los Angeles Dodgers",
            "home": "Milwaukee Brewers", "commence_time": FUTURE,
            "odds": -110}
    base.update(kw)
    return base


# --- market id normalization -------------------------------------------------

def test_normalize_coverage_markets():
    assert normalize_coverage_market("ML_3WAY") == "ML_3WAY"
    assert normalize_coverage_market("3way_ml") == "ML_3WAY"
    assert normalize_coverage_market("first_quarter_spread") == "SPREAD_1Q"
    assert normalize_coverage_market("WINNING_MARGIN") == "MARGIN_BAND"
    assert normalize_coverage_market("SPREAD") is None
    assert normalize_coverage_market("F5_TOTALS") is None
    assert normalize_coverage_market(None) is None


def test_quarter_of():
    assert quarter_of("SPREAD_1Q") == 1
    assert quarter_of("TOTAL_4Q") == 4
    assert quarter_of("TEAM_TOTAL_2Q") == 2
    assert quarter_of("ML_3WAY") is None
    assert quarter_of("MARGIN_BAND") is None


def test_normalize_f5_markets():
    assert normalize_f5_market("F5_TOTALS") == "F5_TOTALS"
    assert normalize_f5_market("f5_ml") == "F5_MONEYLINE"
    assert normalize_f5_market("FIRST_5_TOTAL") == "F5_TOTALS"
    assert normalize_f5_market("TOTAL_1Q") is None
    assert normalize_f5_market(None) is None


# --- MLB 3-way ---------------------------------------------------------------

def test_mlb_3way_failed_validation_not_wired():
    # MLB 3-way FAILED harness validation vs the naive baseline (2026-10-11,
    # n=254301): recognized but never priced.
    out = price_coverage_row(row(market="ML_3WAY", side="HOME"),
                             now=NOW, auto_context=False)
    assert out["status"] == "NO_MODEL_OR_MARKET"
    assert out["reason"] == "COVERAGE_MARKET_FAILED_VALIDATION_NOT_WIRED"


def test_mlb_3way_math_sane_via_internals():
    # The Poisson 3-way math itself is sound (unit-tested here); it did not
    # beat the naive baseline out-of-sample, so it is not wired for pricing.
    from sportsedge import market_coverage as mc
    ph, pa, pt = mc._mlb_3way(4.5, 4.3)
    assert ph + pa + pt == pytest.approx(1.0, abs=1e-9)
    assert ph > pa > 0 and pt > 0.05


# --- quarter markets ---------------------------------------------------------

def nfl_row(**kw):
    base = {"sport": "NFL", "away": "Baltimore Ravens",
            "home": "Atlanta Falcons", "commence_time": FUTURE, "odds": -110}
    base.update(kw)
    return base


def test_quarter_total_nfl_blocked_no_engine_owner_ruling_20261013():
    # Owner ruling (Oct 13, 2026): NFL period markets price only from a
    # compliant period distribution; none exists, so an NFL quarter total
    # under the legacy TOTAL_nQ spelling fails closed with the canonical
    # derivative stage's outcome (NO_ENGINE / SIMULATION_ROWS_EMPTY) --
    # the same outcome as the canonical QUARTER_TOTAL spelling. (The
    # family's earlier harness FAILED_VALIDATION gate still governs the
    # non-NFL spellings; see test_quarter_not_for_mlb.)
    out = price_coverage_row(nfl_row(market="TOTAL_1Q", side="OVER", line=9.5),
                             now=NOW, auto_context=False)
    assert out["status"] == "NO_MODEL_OR_MARKET"
    assert out["reason"] == "SIMULATION_ROWS_EMPTY"
    assert out["blocker"] == "NO_ENGINE"


def test_quarter_total_math_sane_via_internals():
    # The math itself is sound (unit-tested here); it simply did not beat
    # the naive baseline out-of-sample, so it is not wired for pricing.
    from sportsedge import market_coverage as mc
    hq, aq, sdt_q, sdm_q = mc._quarter_params("NFL", 22.75, 21.25)
    assert (hq, aq) == (22.75 * 0.25, 21.25 * 0.25)
    win, push = mc._normal_win_push("TOTAL", "OVER", 9.5, hq, aq,
                                    sdt_q, sdm_q)
    assert 0.0 < win < 1.0 and 0.0 <= push < 1.0


def test_quarter_spread_and_ml_nfl_blocked_no_engine_owner_ruling_20261013():
    # Owner ruling (Oct 13, 2026): the legacy *_nQ spellings no longer
    # price NFL quarter markets at the unfitted QUARTER_FRACTION (0.25)
    # scale (and the route previously added the disabled recent-form
    # factor). NFL quarter spread/ML rows fail closed NO_ENGINE /
    # SIMULATION_ROWS_EMPTY, identical to the canonical QUARTER_SPREAD /
    # QUARTER_MONEYLINE spellings. The underlying quarter math remains
    # unit-tested via internals (test_quarter_total_math_sane_via_internals)
    # and through the still-wired CFB quarter path (adversarial suite).
    for row_ in (nfl_row(market="SPREAD_2Q", side="HOME", line=-0.5),
                 nfl_row(market="SPREAD_2Q", side="HOME", line=+0.5),
                 nfl_row(market="ML_3Q", side="AWAY")):
        out = price_coverage_row(row_, now=NOW, auto_context=False)
        assert out["status"] == "NO_MODEL_OR_MARKET"
        assert out["reason"] == "SIMULATION_ROWS_EMPTY"
        assert out["blocker"] == "NO_ENGINE"
        assert "estimate_p" not in out


def test_quarter_team_total_side_styles():
    # NFL quarter team totals take the canonical period block (owner
    # ruling, Oct 13, 2026): NO_ENGINE / SIMULATION_ROWS_EMPTY, the same
    # guard the derivative stage applies to first-half team totals.
    out = price_coverage_row(nfl_row(market="TEAM_TOTAL_1Q", side="HOME_OVER",
                                     line=6.5),
                             now=NOW, auto_context=False)
    assert out["status"] == "NO_MODEL_OR_MARKET"
    assert out["reason"] == "SIMULATION_ROWS_EMPTY"
    assert out["blocker"] == "NO_ENGINE"


def test_quarter_requires_line_and_side():
    # NFL quarter rows block on the period guard before line/side
    # validation (owner ruling, Oct 13, 2026) -- the canonical derivative
    # stage likewise blocks period rows without validating the side.
    out = price_coverage_row(nfl_row(market="TOTAL_1Q", side="OVER"),
                             now=NOW, auto_context=False)
    assert out["status"] == "NO_MODEL_OR_MARKET"
    assert out["reason"] == "SIMULATION_ROWS_EMPTY"
    out2 = price_coverage_row(nfl_row(market="SPREAD_1Q", side="OVER", line=-1.5),
                              now=NOW, auto_context=False)
    assert out2["status"] == "NO_MODEL_OR_MARKET"
    assert out2["reason"] == "SIMULATION_ROWS_EMPTY"
    # Side validation still fires on the wired (CFB) quarter path.
    out3 = price_coverage_row(
        {"sport": "CFB", "away": "Georgia Bulldogs",
         "home": "Alabama Crimson Tide", "commence_time": FUTURE,
         "odds": -110, "market": "SPREAD_1Q", "side": "OVER", "line": -1.5},
        now=NOW, auto_context=False)
    assert out3["status"] == "NO_MODEL_OR_MARKET"
    assert "SIDE_MUST_BE_HOME_AWAY" in out3["reason"]


def test_quarter_not_for_mlb():
    out = price_coverage_row(row(market="TOTAL_1Q", side="OVER", line=2.5),
                             now=NOW, auto_context=False)
    assert out["status"] == "NO_MODEL_OR_MARKET"
    assert out["reason"] == "COVERAGE_MARKET_FAILED_VALIDATION_NOT_WIRED"


# --- margin bands ------------------------------------------------------------

def test_margin_bands_conserve_mass():
    probs = []
    pushes = []
    for band_id, _, _, _ in MARGIN_BANDS:
        out = price_coverage_row(nfl_row(market="MARGIN_BAND", side=band_id),
                                 now=NOW, auto_context=False)
        assert out["status"] in {"RESEARCH_EDGE", "BELOW_THRESHOLD", "PRICE_CAP"}
        probs.append(out["estimate_p"])
        pushes.append(out["push_p"])
    # Bands tile every nonzero margin; add the declared tie mass once.
    assert sum(probs) + pushes[0] == pytest.approx(1.0, abs=0.05)
    # The declared tie approximation is identical across bands.
    assert max(pushes) - min(pushes) < 1e-12


def test_margin_band_invalid_side():
    out = price_coverage_row(nfl_row(market="MARGIN_BAND", side="HOME_2_5"),
                             now=NOW, auto_context=False)
    assert out["status"] == "NO_MODEL_OR_MARKET"
    assert "MARGIN_BAND_SIDE_INVALID" in out["reason"]


# --- fail-closed paths --------------------------------------------------------

def test_started_game_blocked():
    out = price_coverage_row(nfl_row(market="SPREAD_1Q", side="HOME",
                                     line=-1.5, commence_time=PAST),
                             now=NOW, auto_context=False)
    assert out["status"] == "BLOCKED_STARTED"


def test_missing_kickoff_blocked():
    r = nfl_row(market="SPREAD_1Q", side="HOME", line=-1.5)
    del r["commence_time"]
    out = price_coverage_row(r, now=NOW, auto_context=False)
    assert out["status"] == "BLOCKED_KICKOFF_UNVERIFIED"


def test_bad_odds_blocked():
    out = price_coverage_row(nfl_row(market="SPREAD_1Q", side="HOME",
                                     line=-1.5, odds="abc"),
                             now=NOW, auto_context=False)
    assert out["status"] == "NO_MODEL_OR_MARKET"
    assert "ODDS_INVALID" in out["reason"]


def test_phone_coverage_rows_counts_and_receipts():
    rows = [
        nfl_row(market="SPREAD_1Q", side="HOME", line=-1.5),
        nfl_row(market="SPREAD_1Q", side="HOME", line=-1.5),
        nfl_row(market="TOTAL_9Q", side="OVER", line=9.5),  # not a market
        nfl_row(market="SPREAD_1Q", side="HOME", line=-1.5,
                commence_time=PAST),
    ]
    outputs, receipts = phone_coverage_rows(rows, now=NOW, auto_context=False)
    assert len(outputs) == len(rows)
    assert outputs[2]["status"] == "NO_MODEL_OR_MARKET"
    assert outputs[3]["status"] == "BLOCKED_STARTED"
    assert receipts and receipts[-1]["rows"] == 4


# --- F5 pure math (no network) ------------------------------------------------

def _f5_features():
    return {
        "away_f5_runs_for": [0, 1, 2, 0, 3, 1, 0, 2, 1, 0, 4, 1],
        "away_f5_runs_against": [1, 0, 2, 1, 0, 3, 1, 0, 2, 1, 0, 2],
        "home_f5_runs_for": [2, 0, 1, 3, 0, 1, 2, 0, 1, 4, 0, 1],
        "home_f5_runs_against": [0, 2, 1, 0, 2, 1, 0, 3, 1, 0, 2, 1],
        "league_f5_pmf": {"0": 0.3, "1": 0.25, "2": 0.2, "3": 0.12,
                          "4": 0.08, "5": 0.05},
        "league_prior_halves": 500,
        "league_prior_strength": 30,
    }


def test_f5_distribution_readouts_offline():
    dist = build_f5_distribution(_f5_features(), league_prior_strength=30)
    ml = read_f5_probability(dist, market="F5_MONEYLINE", side="HOME")
    tot = read_f5_probability(dist, market="F5_TOTALS", line=4.5, side="OVER")
    tt = read_f5_probability(dist, market="F5_TEAM_TOTALS", line=2.5,
                             side="OVER", team_side="HOME")
    assert 0 < ml.probability < 1
    assert 0 < tot.probability < 1
    assert 0 < tt.probability < 1
    assert ml.distribution_sha256 == dist.distribution_sha256


def test_phone_f5_rows_fail_closed_offline():
    # No getter -> team directory unreachable -> explicit blocked reason.
    rows = [row(market="F5_TOTALS", side="OVER", line=4.5),
            row(market="F5_MONEYLINE", side="HOME")]
    outputs, receipts = phone_f5_rows(rows, now=NOW, auto_context=False)
    assert len(outputs) == 2
    assert all(o["status"] == "NO_MODEL_OR_MARKET" for o in outputs)
    assert outputs[0]["reason"] == "F5_MARKET_FAILED_VALIDATION_NOT_WIRED"


def test_phone_f5_rows_bad_side_offline():
    rows = [row(market="F5_TOTALS", side="HOME", line=4.5)]
    outputs, _ = phone_f5_rows(rows, now=NOW, auto_context=False)
    assert outputs[0]["status"] == "NO_MODEL_OR_MARKET"
    assert outputs[0]["reason"] == "F5_MARKET_FAILED_VALIDATION_NOT_WIRED"


# --- run_it_full routing -----------------------------------------------------

def test_run_it_full_routes_coverage_and_alternates():
    from artifacts import run_it_full
    payload = {"lines": [
        # Alternate run line + alternate total ride the existing SPREAD/TOTAL path.
        # Game-lane rows carry a current quote timestamp: since the PR base,
        # main's game lane fails closed to WATCH_QUOTE_NOT_CURRENT when a row
        # has no verified fresh quote (180s freshness contract), so a priced
        # status is only reachable with quote_captured_at at the card clock.
        dict(sport="MLB", market="SPREAD", side="HOME", line=-2.5,
             away="Los Angeles Dodgers", home="Milwaukee Brewers",
             commence_time=FUTURE, odds=-110,
             quote_captured_at=NOW.isoformat()),
        dict(sport="MLB", market="TOTAL", side="OVER", line=10.5,
             away="Los Angeles Dodgers", home="Milwaukee Brewers",
             commence_time=FUTURE, odds=-110,
             quote_captured_at=NOW.isoformat()),
        # Coverage markets.
        dict(sport="MLB", market="ML_3WAY", side="TIE",
             away="Los Angeles Dodgers", home="Milwaukee Brewers",
             commence_time=FUTURE, odds=+260),
        dict(sport="NFL", market="SPREAD_1Q", side="AWAY", line=0.5,
             away="Baltimore Ravens", home="Atlanta Falcons",
             commence_time=FUTURE, odds=-110),
        dict(sport="NFL", market="TOTAL_1Q", side="OVER", line=9.5,
             away="Baltimore Ravens", home="Atlanta Falcons",
             commence_time=FUTURE, odds=-110),
        dict(sport="NFL", market="MARGIN_BAND", side="HOME_1_6",
             away="Baltimore Ravens", home="Atlanta Falcons",
             commence_time=FUTURE, odds=+280),
        # F5 (offline -> fail-closed with explicit reason, still routed).
        dict(sport="MLB", market="F5_TOTALS", side="UNDER", line=4.5,
             away="Los Angeles Dodgers", home="Milwaukee Brewers",
             commence_time=FUTURE, odds=-115),
        # Player-prop routing untouched.
        dict(sport="MLB", market="PITCHER_K", side="OVER", line=7.5,
             player_name="Some Pitcher",
             away="Los Angeles Dodgers", home="Milwaukee Brewers",
             commence_time=FUTURE, odds=-110),
        # Timing markets stay blocked with explicit reasons.
        dict(sport="MLB", market="FIRST_TO_SCORE", side="HOME",
             away="Los Angeles Dodgers", home="Milwaukee Brewers",
             commence_time=FUTURE, odds=-110),
    ]}
    card = run_it_full.run_full(payload, now=NOW, auto_context=False)
    rows = card["evaluated_rows"]
    assert len(rows) == 9
    by_market = {r.get("market"): r for r in rows}
    assert by_market["SPREAD"]["status"] in {"RESEARCH_EDGE", "BELOW_THRESHOLD",
                                             "PRICE_CAP"}
    assert by_market["TOTAL"]["status"] in {"RESEARCH_EDGE", "BELOW_THRESHOLD",
                                            "PRICE_CAP"}
    # ML_3WAY failed harness validation: routed but never priced.
    assert by_market["ML_3WAY"]["status"] == "NO_MODEL_OR_MARKET"
    assert by_market["ML_3WAY"]["reason"] == \
        "COVERAGE_MARKET_FAILED_VALIDATION_NOT_WIRED"
    # NFL quarter markets (both legacy spellings) fail closed with the
    # canonical period outcome (owner ruling, Oct 13, 2026).
    assert by_market["TOTAL_1Q"]["status"] == "NO_MODEL_OR_MARKET"
    assert by_market["TOTAL_1Q"]["reason"] == "SIMULATION_ROWS_EMPTY"
    assert by_market["TOTAL_1Q"]["blocker"] == "NO_ENGINE"
    assert by_market["SPREAD_1Q"]["market"] == "SPREAD_1Q"
    assert by_market["SPREAD_1Q"]["status"] == "NO_MODEL_OR_MARKET"
    assert by_market["SPREAD_1Q"]["reason"] == "SIMULATION_ROWS_EMPTY"
    assert by_market["SPREAD_1Q"]["blocker"] == "NO_ENGINE"
    assert by_market["MARGIN_BAND"]["market"] == "MARGIN_BAND"
    assert by_market["F5_TOTALS"]["status"] == "NO_MODEL_OR_MARKET"
    assert by_market["F5_TOTALS"]["reason"] == "NO_QUOTE: F5_SOURCE_MISSING — quote names no sportsbook/source"
    assert by_market["PITCHER_K"]["status"] == "NO_MODEL_OR_MARKET"
    assert by_market["FIRST_TO_SCORE"]["status"] == "NO_MODEL_OR_MARKET"
    assert by_market["FIRST_TO_SCORE"]["reason"] == "NO_VERIFIED_MODEL_FOR_THIS_MARKET"
    # Factor audit treats coverage/F5 as game-level markets.
    for idx in (2, 3, 4, 5):
        audit = card["factor_coverage"]["by_input_index"][idx]
        assert audit["factors"]["player_props"]["status"] == "NOT_APPLICABLE"
    assert card["prop_model_status"]["coverage_engine"].startswith(
        "FREE_COVERAGE_EXTENSION")
    assert card["prop_model_status"]["f5_engine"].startswith("MLB_F5_EMPIRICAL")


def test_run_it_full_coverage_aliases():
    from artifacts import run_it_full
    payload = {"lines": [
        dict(sport="MLB", market="3way_ml", side="HOME",
             away="Los Angeles Dodgers", home="Milwaukee Brewers",
             commence_time=FUTURE, odds=-110),
        dict(sport="NFL", market="first_quarter_spread", side="HOME",
             line=-1.5, away="Baltimore Ravens", home="Atlanta Falcons",
             commence_time=FUTURE, odds=-110),
    ]}
    card = run_it_full.run_full(payload, now=NOW, auto_context=False)
    rows = card["evaluated_rows"]
    assert rows[0]["market"] == "ML_3WAY"
    assert rows[0]["reason"] == "COVERAGE_MARKET_FAILED_VALIDATION_NOT_WIRED"
    assert rows[1]["market"] == "SPREAD_1Q"
    # The first_quarter_spread alias resolves to SPREAD_1Q and takes the
    # canonical NFL period block (owner ruling, Oct 13, 2026).
    assert rows[1]["status"] == "NO_MODEL_OR_MARKET"
    assert rows[1]["reason"] == "SIMULATION_ROWS_EMPTY"
    assert rows[1]["blocker"] == "NO_ENGINE"
