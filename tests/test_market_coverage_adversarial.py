"""Adversarial tests for Phase 7 market coverage ("try to break it").

Attack list: pathological boards (duplicates, contradictory sides, extreme
lines/odds, missing/null fields), odds-format edge cases (American sign
handling, decimal-vs-American confusion), degenerate probabilities (p=0/1
must fail closed like the research bridge). All offline.
"""
from datetime import datetime, timedelta, timezone

import pytest

import sportsedge.market_coverage as mc
from sportsedge.market_coverage import price_coverage_row, phone_coverage_rows
from sportsedge.mlb_phone_f5_pricing import phone_f5_rows
from sportsedge.f5_distribution import build_f5_distribution, read_f5_probability

NOW = datetime(2026, 10, 11, 18, 0, tzinfo=timezone.utc)
FUTURE = (NOW + timedelta(days=2)).isoformat()


def nfl(**kw):
    base = {"sport": "NFL", "away": "Baltimore Ravens",
            "home": "Atlanta Falcons", "commence_time": FUTURE, "odds": -110}
    base.update(kw)
    return base


def mlb(**kw):
    base = {"sport": "MLB", "away": "Los Angeles Dodgers",
            "home": "Milwaukee Brewers", "commence_time": FUTURE, "odds": -110}
    base.update(kw)
    return base


def _sane(out):
    p, push = out["estimate_p"], out["push_p"]
    assert 0.0 < p < 1.0, out
    assert 0.0 <= push < 1.0, out
    assert p + push <= 1.0 + 1e-9, out
    for key in ("estimate_p", "push_p", "loss_p", "ev_per_dollar"):
        assert out[key] == out[key], "NaN detected"  # NaN != NaN


# --- extreme lines ------------------------------------------------------------

@pytest.mark.parametrize("line", [-0.5, 0.5])
def test_quarter_spread_lines_sane(line):
    out = price_coverage_row(nfl(market="SPREAD_1Q", side="HOME", line=line),
                             now=NOW, auto_context=False)
    assert out["status"] in {"RESEARCH_EDGE", "BELOW_THRESHOLD", "PRICE_CAP"}
    _sane(out)


@pytest.mark.parametrize("line", [-10000, -100, 100, 10000])
def test_absurd_spread_lines_fail_closed(line):
    # Float underflow would manufacture p=0; the degenerate guard refuses.
    out = price_coverage_row(nfl(market="SPREAD_1Q", side="HOME", line=line),
                             now=NOW, auto_context=False)
    assert out["status"] == "NO_MODEL_OR_MARKET"
    assert out["reason"] == "DEGENERATE_PROBABILITY_REFUSED"


@pytest.mark.parametrize("line", [0.5, 20.0])
def test_large_quarter_spread_lines_sane(line):
    # Large but representable: priced, never NaN, never exactly 0/1 reported.
    out = price_coverage_row(nfl(market="SPREAD_1Q", side="HOME", line=-line),
                             now=NOW, auto_context=False)
    _sane(out)


@pytest.mark.parametrize("line", [40, 1000])
def test_absurd_spread_line_fails_closed(line):
    # line=40 -> raw p~2e-9 rounds to a reported 0.0: refused, never priced
    # as 0. line=1000 underflows to exactly 0.0: refused as well.
    out = price_coverage_row(nfl(market="SPREAD_1Q", side="HOME", line=line),
                             now=NOW, auto_context=False)
    assert out["status"] == "NO_MODEL_OR_MARKET"
    assert out["reason"] == "DEGENERATE_PROBABILITY_REFUSED"


def test_extreme_means_via_context_override():
    out = price_coverage_row(
        nfl(market="MARGIN_BAND", side="HOME_25_PLUS",
            context={"home_rating": 15, "away_rating": -15}),
        now=NOW, auto_context=False)
    _sane(out)
    assert out["estimate_p"] > 0.5  # 31.5-point mean margin: band is likely


def test_extreme_mlb_3way_means():
    # ML_3WAY failed validation: not wired regardless of means.
    out = price_coverage_row(
        mlb(market="ML_3WAY", side="HOME",
            context={"home_rating": 1, "away_rating": -1}),
        now=NOW, auto_context=False)
    assert out["status"] == "NO_MODEL_OR_MARKET"
    assert out["reason"] == "COVERAGE_MARKET_FAILED_VALIDATION_NOT_WIRED"


def test_implausible_mlb_means_blocked():
    # Gating fires before the plausibility check; the market is not wired.
    out = price_coverage_row(
        mlb(market="ML_3WAY", side="HOME",
            context={"home_rating": 10, "away_rating": -10}),
        now=NOW, auto_context=False)
    assert out["status"] == "NO_MODEL_OR_MARKET"
    assert out["reason"] == "COVERAGE_MARKET_FAILED_VALIDATION_NOT_WIRED"


def test_implausible_means_blocked_on_wired_market():
    # The shared _base_means IMPLAUSIBLE_SCORE_MEAN guard still fires for
    # wired markets (tested at the unit level; MLB's only coverage market
    # is currently validation-gated).
    import pytest as _pt
    with _pt.raises(mc.MarketCoverageError) as exc:
        mc._base_means(
            mlb(market="ML_3WAY", side="HOME",
                context={"home_rating": 10, "away_rating": -10}),
            now=NOW, auto_context=False)
    assert "IMPLAUSIBLE_SCORE_MEAN" in str(exc.value)


# --- missing / null fields -----------------------------------------------------

@pytest.mark.parametrize("field", ["odds", "side", "market", "sport"])
def test_null_fields_blocked(field):
    r = nfl(market="SPREAD_1Q", side="HOME", line=-1.5)
    r[field] = None
    out = price_coverage_row(r, now=NOW, auto_context=False)
    assert out["status"] == "NO_MODEL_OR_MARKET", out
    assert out["reason"], out


def test_missing_line_blocked():
    out = price_coverage_row(nfl(market="SPREAD_1Q", side="HOME"),
                             now=NOW, auto_context=False)
    assert out["status"] == "NO_MODEL_OR_MARKET"
    assert "LINE_UNVERIFIED" in out["reason"]


def test_non_string_side_blocked():
    out = price_coverage_row(nfl(market="SPREAD_1Q", side=123, line=-1.5),
                             now=NOW, auto_context=False)
    assert out["status"] == "NO_MODEL_OR_MARKET"


# --- odds format edge cases -----------------------------------------------------

def test_decimal_odds_confusion_blocked():
    # 1.91 is decimal, not American: must be rejected, never mispriced.
    out = price_coverage_row(nfl(market="SPREAD_1Q", side="HOME",
                                 line=-1.5, odds=1.91),
                             now=NOW, auto_context=False)
    assert out["status"] == "NO_MODEL_OR_MARKET"
    assert "ODDS_INVALID" in out["reason"]


def test_zero_odds_blocked():
    out = price_coverage_row(nfl(market="SPREAD_1Q", side="HOME",
                                 line=-1.5, odds=0),
                             now=NOW, auto_context=False)
    assert out["status"] == "NO_MODEL_OR_MARKET"


@pytest.mark.parametrize("odds", [+100, -100, "-110", -110.0])
def test_american_sign_handling(odds):
    out = price_coverage_row(nfl(market="SPREAD_1Q", side="HOME",
                                 line=-1.5, odds=odds),
                             now=NOW, auto_context=False)
    assert out["status"] in {"RESEARCH_EDGE", "BELOW_THRESHOLD", "PRICE_CAP"}


def test_plus_minus_100_identical():
    a = price_coverage_row(nfl(market="SPREAD_1Q", side="HOME",
                               line=-1.5, odds=+100),
                           now=NOW, auto_context=False)
    b = price_coverage_row(nfl(market="SPREAD_1Q", side="HOME",
                               line=-1.5, odds=-100),
                           now=NOW, auto_context=False)
    assert a["estimate_p"] == b["estimate_p"]
    assert a["ev_per_dollar"] == b["ev_per_dollar"]


def test_extreme_odds_no_crash():
    out = price_coverage_row(nfl(market="SPREAD_1Q", side="HOME",
                                 line=-1.5, odds=+10000),
                             now=NOW, auto_context=False)
    _sane(out)
    out2 = price_coverage_row(nfl(market="SPREAD_1Q", side="HOME",
                                  line=-1.5, odds=-100000),
                              now=NOW, auto_context=False)
    assert out2["status"] == "PRICE_CAP"


# --- contradictory / duplicate rows ----------------------------------------------

def test_contradictory_sides_coherent():
    # Quarter totals are validation-gated: both sides fail closed, coherently.
    over = price_coverage_row(nfl(market="TOTAL_1Q", side="OVER", line=9.5),
                              now=NOW, auto_context=False)
    under = price_coverage_row(nfl(market="TOTAL_1Q", side="UNDER", line=9.5),
                               now=NOW, auto_context=False)
    assert over["reason"] == "COVERAGE_MARKET_FAILED_VALIDATION_NOT_WIRED"
    assert under["reason"] == "COVERAGE_MARKET_FAILED_VALIDATION_NOT_WIRED"


def test_contradictory_spread_sides_coherent():
    home = price_coverage_row(nfl(market="SPREAD_1Q", side="HOME", line=-1.5),
                              now=NOW, auto_context=False)
    away = price_coverage_row(nfl(market="SPREAD_1Q", side="AWAY", line=1.5),
                              now=NOW, auto_context=False)
    total = home["estimate_p"] + away["estimate_p"] + home["push_p"]
    assert total == pytest.approx(1.0, abs=1e-9)


def test_duplicate_rows_identical():
    r = nfl(market="SPREAD_1Q", side="HOME", line=-1.5)
    outputs, _ = phone_coverage_rows([r, dict(r)], now=NOW, auto_context=False)
    assert outputs[0]["estimate_p"] == outputs[1]["estimate_p"]
    assert outputs[0]["status"] == outputs[1]["status"]


# --- degenerate probabilities -----------------------------------------------------

def test_degenerate_probability_refused(monkeypatch):
    monkeypatch.setattr(mc, "_normal_win_push",
                        lambda *a, **k: (1.0, 0.0))
    out = price_coverage_row(nfl(market="SPREAD_1Q", side="HOME", line=-1.5),
                             now=NOW, auto_context=False)
    assert out["status"] == "NO_MODEL_OR_MARKET"
    assert out["reason"] == "DEGENERATE_PROBABILITY_REFUSED"


def test_degenerate_zero_refused(monkeypatch):
    monkeypatch.setattr(mc, "_normal_win_push",
                        lambda *a, **k: (0.0, 0.0))
    out = price_coverage_row(nfl(market="SPREAD_1Q", side="HOME", line=-1.5),
                             now=NOW, auto_context=False)
    assert out["status"] == "NO_MODEL_OR_MARKET"
    assert out["reason"] == "DEGENERATE_PROBABILITY_REFUSED"


def test_f5_readout_extreme_lines_sane():
    features = {
        "away_f5_runs_for": [0, 1, 2, 0, 3, 1, 0, 2, 1, 0, 4, 1],
        "away_f5_runs_against": [1, 0, 2, 1, 0, 3, 1, 0, 2, 1, 0, 2],
        "home_f5_runs_for": [2, 0, 1, 3, 0, 1, 2, 0, 1, 4, 0, 1],
        "home_f5_runs_against": [0, 2, 1, 0, 2, 1, 0, 3, 1, 0, 2, 1],
        "league_f5_pmf": {"0": 0.3, "1": 0.25, "2": 0.2, "3": 0.12,
                          "4": 0.08, "5": 0.05},
        "league_prior_halves": 500,
        "league_prior_strength": 30,
    }
    dist = build_f5_distribution(features, league_prior_strength=30)
    for line in (0.5, 4.5, 100.0):
        ro = read_f5_probability(dist, market="F5_TOTALS", line=line,
                                 side="OVER")
        assert 0.0 < ro.probability < 1.0
        assert 0.0 <= ro.push_probability < 1.0


def test_f5_wrong_sport_blocked():
    rows = [nfl(market="F5_TOTALS", side="OVER", line=4.5)]
    outputs, _ = phone_f5_rows(rows, now=NOW, auto_context=False)
    assert outputs[0]["status"] == "NO_MODEL_OR_MARKET"
    assert outputs[0]["reason"] == "F5_MARKET_FAILED_VALIDATION_NOT_WIRED"


def test_team_total_quarter_nonpositive_line_blocked():
    # Gating fires before line validation; the market is not wired.
    for line in (0, -3.5):
        out = price_coverage_row(nfl(market="TEAM_TOTAL_1Q",
                                     side="HOME_OVER", line=line),
                                 now=NOW, auto_context=False)
        assert out["status"] == "NO_MODEL_OR_MARKET"
        assert out["reason"] == "COVERAGE_MARKET_FAILED_VALIDATION_NOT_WIRED"


# --- pathological board through the full runner ------------------------------------

def test_pathological_board_no_crash():
    from artifacts import run_it_full
    payload = {"lines": [
        nfl(market="SPREAD_1Q", side="HOME", line=-1.5),          # dup A
        nfl(market="SPREAD_1Q", side="HOME", line=-1.5),          # dup B
        nfl(market="TOTAL_1Q", side="OVER", line=9.5),            # contradiction
        nfl(market="TOTAL_1Q", side="UNDER", line=9.5),           # contradiction
        nfl(market="SPREAD_2Q", side="HOME", line=10000),         # extreme
        nfl(market="ML_3WAY", side="HOME"),                       # wrong sport
        dict(nfl(market="SPREAD_1Q", side="HOME", line=-1.5,
                 odds=None)),                                     # null odds
        dict(nfl(market="SPREAD_1Q", side=None, line=-1.5)),       # null side
        mlb(market="F5_TOTALS", side="OVER", line=4.5),            # f5 offline
        nfl(market="MARGIN_BAND", side="BOGUS_BAND"),              # bad band
    ]}
    card = run_it_full.run_full(payload, now=NOW, auto_context=False)
    rows = card["evaluated_rows"]
    assert len(rows) == 10
    for r in rows:
        assert r.get("status"), r
        assert r["research_only"] is True
    by = {(r.get("market"), str(r.get("selection"))): r for r in rows}
    assert rows[5]["reason"] == "COVERAGE_MARKET_FAILED_VALIDATION_NOT_WIRED"
    assert rows[6]["reason"] == "ODDS_INVALID"
    assert rows[9]["reason"] == "MARGIN_BAND_SIDE_INVALID"
    # Duplicates price identically.
    assert rows[0]["estimate_p"] == rows[1]["estimate_p"]


def test_game_field_instead_of_away_home():
    out = price_coverage_row(
        {"sport": "NFL", "game": "Baltimore Ravens @ Atlanta Falcons",
         "market": "SPREAD_1Q", "side": "HOME", "line": -1.5,
         "odds": " -110 ", "commence_time": FUTURE},
        now=NOW, auto_context=False)
    assert out["status"] in {"RESEARCH_EDGE", "BELOW_THRESHOLD", "PRICE_CAP"}
    assert out["game"] == "Baltimore Ravens @ Atlanta Falcons"


def test_team_name_side_mixed_case_whitespace():
    out = price_coverage_row(
        nfl(market="ML_2Q", side="  atlanta FALCONS "),
        now=NOW, auto_context=False)
    assert out["status"] in {"RESEARCH_EDGE", "BELOW_THRESHOLD", "PRICE_CAP"}
    assert "Atlanta Falcons" in out["selection"]


def test_lowercase_market_and_tie_side():
    # ML_3WAY is validation-gated; the alias still normalizes before gating.
    out = price_coverage_row(
        mlb(market="ml_3way", side="tie", odds=250),
        now=NOW, auto_context=False)
    assert out["status"] == "NO_MODEL_OR_MARKET"
    assert out["reason"] == "COVERAGE_MARKET_FAILED_VALIDATION_NOT_WIRED"


def test_empty_rows_no_crash():
    outputs, receipts = phone_coverage_rows([], now=NOW, auto_context=False)
    assert outputs == []
    outputs, _ = phone_f5_rows([], now=NOW, auto_context=False)
    assert outputs == []


def _teams_payload():
    return {"teams": [
        {"id": 119, "name": "Los Angeles Dodgers", "abbreviation": "LAD",
         "teamName": "Dodgers", "locationName": "Los Angeles",
         "shortName": "Los Angeles Dodgers", "franchiseName": "Los Angeles"},
        {"id": 158, "name": "Milwaukee Brewers", "abbreviation": "MIL",
         "teamName": "Brewers", "locationName": "Milwaukee",
         "shortName": "Milwaukee Brewers", "franchiseName": "Milwaukee"},
        {"id": 19, "name": "New York Yankees", "abbreviation": "NYY",
         "teamName": "Yankees", "locationName": "New York",
         "shortName": "New York Yankees", "franchiseName": "New York"},
        {"id": 121, "name": "New York Mets", "abbreviation": "NYM",
         "teamName": "Mets", "locationName": "New York",
         "shortName": "New York Mets", "franchiseName": "New York"},
    ]}


def test_statsapi_team_id_exact_and_alias():
    from sportsedge.mlb_phone_f5_pricing import _statsapi_team_id
    payload = _teams_payload()
    assert _statsapi_team_id(payload, "Los Angeles Dodgers") == 119
    assert _statsapi_team_id(payload, "Dodgers") == 119
    assert _statsapi_team_id(payload, "LAD") == 119
    assert _statsapi_team_id(payload, "  milwaukee brewers ") == 158


def test_statsapi_team_id_ambiguous_fails_closed():
    # "New York" alone matches two clubs: must NOT guess.
    from sportsedge.mlb_phone_f5_pricing import _statsapi_team_id
    payload = _teams_payload()
    assert _statsapi_team_id(payload, "New York") is None
    assert _statsapi_team_id(payload, "Springfield Isotopes") is None
    assert _statsapi_team_id(payload, "") is None
    assert _statsapi_team_id({}, "Dodgers") is None


def _fake_game(pk, date, away_id, home_id, away_f5, home_f5):
    innings = [{"num": n,
                "away": {"runs": (away_f5 if n == 1 else 0)},
                "home": {"runs": (home_f5 if n == 1 else 0)}}
               for n in range(1, 10)]
    return {
        "gamePk": pk,
        "officialDate": date,
        "status": {"abstractGameState": "Final"},
        "teams": {
            "away": {"team": {"id": away_id}, "score": away_f5},
            "home": {"team": {"id": home_id}, "score": home_f5},
        },
        "linescore": {"innings": innings},
    }


def _f5_stub_getter():
    from datetime import date as _date, timedelta as _td
    base = _date(2026, 9, 1)
    dodgers = [_fake_game(1000 + i, (base + _td(days=i)).isoformat(),
                          119, 200 + i, (i % 4), ((i + 1) % 3))
               for i in range(12)]
    brewers = [_fake_game(2000 + i, (base + _td(days=i)).isoformat(),
                          300 + i, 158, ((i + 2) % 4), (i % 5))
               for i in range(12)]
    league = [_fake_game(3000 + i, (base + _td(days=i % 30)).isoformat(),
                         400 + i, 500 + i, (i % 6), ((i + 3) % 5))
              for i in range(120)]

    def getter(url):
        if "api/v1/teams?" in url:
            return {"teams": [
                {"id": 119, "name": "Los Angeles Dodgers",
                 "abbreviation": "LAD", "teamName": "Dodgers",
                 "locationName": "Los Angeles", "shortName": "Dodgers",
                 "franchiseName": "Los Angeles"},
                {"id": 158, "name": "Milwaukee Brewers",
                 "abbreviation": "MIL", "teamName": "Brewers",
                 "locationName": "Milwaukee", "shortName": "Brewers",
                 "franchiseName": "Milwaukee"},
            ]}
        if "teamId=119" in url:
            return {"dates": [{"games": dodgers}]}
        if "teamId=158" in url:
            return {"dates": [{"games": brewers}]}
        if "gameType=R" in url:
            return {"dates": [{"games": league}]}
        raise AssertionError("unexpected URL: " + url[:120])

    return getter


def test_phone_f5_rows_end_to_end_with_stub():
    # F5 failed harness validation: the wiring is tested here, but every
    # market fails closed until a verifying model exists.
    rows = [
        mlb(market="F5_TOTALS", side="OVER", line=4.5),
        mlb(market="F5_MONEYLINE", side="HOME"),
        mlb(market="F5_RUN_LINE", side="AWAY", line=0.5),
        mlb(market="F5_TEAM_TOTALS", side="HOME_OVER", line=2.5),
    ]
    outputs, receipts = phone_f5_rows(rows, now=NOW,
                                      getter=_f5_stub_getter())
    assert len(outputs) == 4
    for out in outputs:
        assert out["status"] == "NO_MODEL_OR_MARKET"
        assert out["reason"] == "F5_MARKET_FAILED_VALIDATION_NOT_WIRED"


def test_f5_distribution_math_sane_via_internals():
    # The empirical F5 stack itself is sound (unit-tested here); the wired
    # phone path is gated because it did not beat the naive baseline
    # out-of-sample.
    from sportsedge.f5_distribution import (
        build_f5_distribution as _build, read_f5_probability as _read)
    features = {
        "away_f5_runs_for": [0, 1, 2, 0, 3, 1, 0, 2, 1, 0, 4, 1],
        "away_f5_runs_against": [1, 0, 2, 1, 0, 3, 1, 0, 2, 1, 0, 2],
        "home_f5_runs_for": [2, 0, 1, 3, 0, 1, 2, 0, 1, 4, 0, 1],
        "home_f5_runs_against": [0, 2, 1, 0, 2, 1, 0, 3, 1, 0, 2, 1],
        "league_f5_pmf": {"0": 0.3, "1": 0.25, "2": 0.2, "3": 0.12,
                          "4": 0.08, "5": 0.05},
        "league_prior_halves": 500,
        "league_prior_strength": 30,
    }
    dist = _build(features, league_prior_strength=30)
    ro = _read(dist, market="F5_MONEYLINE", side="HOME")
    assert 0.0 < ro.probability < 1.0


def test_phone_f5_rows_insufficient_history_blocked():
    def getter(url):
        if "api/v1/teams?" in url:
            return {"teams": [
                {"id": 119, "name": "Los Angeles Dodgers",
                 "abbreviation": "LAD", "teamName": "Dodgers",
                 "locationName": "Los Angeles", "shortName": "Dodgers",
                 "franchiseName": "Los Angeles"},
                {"id": 158, "name": "Milwaukee Brewers",
                 "abbreviation": "MIL", "teamName": "Brewers",
                 "locationName": "Milwaukee", "shortName": "Brewers",
                 "franchiseName": "Milwaukee"},
            ]}
        # Only 3 games per team: below the 10-game minimum.
        return {"dates": [{"games": [
            _fake_game(9000 + i, f"2026-09-{10+i}", 119, 158, 1, 2)
            for i in range(3)]}]}

    rows = [mlb(market="F5_TOTALS", side="OVER", line=4.5)]
    outputs, _ = phone_f5_rows(rows, now=NOW, getter=getter)
    assert outputs[0]["status"] == "NO_MODEL_OR_MARKET"
    assert outputs[0]["reason"] == "F5_MARKET_FAILED_VALIDATION_NOT_WIRED"
