"""Canonical RUN IT wiring tests (2026-10-12).

Proves, offline only:
(a) each newly wired pricer/stage is reachable from the canonical entry
    point (artifacts.run_it_full.run_full) or its canonical stage module
    and produces a priced-or-named-blocker outcome on fixtures;
(b) every market in the Phase 1 coverage matrix (89 markets) resolves
    through sportsedge.canonical_coverage to PRICED_PATH or BLOCKED with
    a named taxonomy blocker -- the test asserts the RESOLUTION, not
    pricing, for markets without verified inputs.
"""
import csv
import gzip
from datetime import datetime, timezone
from pathlib import Path

import pytest

from sportsedge.canonical_coverage import (
    BLOCKER_TAXONOMY, MARKET_RESOLUTIONS, blocked_row_for,
    coverage_summary, resolve_market)
from sportsedge.nfl_phone_anytime_td_pricing import phone_anytime_td_rows
from sportsedge.nfl_phone_derivative_pricing import phone_nfl_derivative_rows

# The Phase 1 coverage matrix market list (89), embedded verbatim so the
# repo test does not depend on files outside the repository. Drift between
# this list and the canonical coverage table fails the first test.
MATRIX_MARKETS = [
    ("MLB", "BATTER_BB"), ("MLB", "BATTER_K"), ("MLB", "DOUBLES"),
    ("MLB", "EITHER_PITCHER_BB"), ("MLB", "EITHER_PITCHER_ER"),
    ("MLB", "EITHER_PITCHER_HITS_ALLOWED"), ("MLB", "EXTRA_BASE_HITS"),
    ("MLB", "F5_MONEYLINE"), ("MLB", "F5_RUN_LINE"),
    ("MLB", "F5_TEAM_TOTALS"), ("MLB", "F5_TOTALS"),
    ("MLB", "FIRST_HOME_RUN"), ("MLB", "HITS"), ("MLB", "HITS_RUNS_RBIS"),
    ("MLB", "HITS_RUNS_STOLEN_BASES"), ("MLB", "HITS_STOLEN_BASES"),
    ("MLB", "HITS_WALKS_STOLEN_BASES"), ("MLB", "HOME_RUNS"),
    ("MLB", "MONEYLINE"), ("MLB", "NRFI"), ("MLB", "PITCHER_BB"),
    ("MLB", "PITCHER_ER"), ("MLB", "PITCHER_HITS_ALLOWED"),
    ("MLB", "PITCHER_HITS_WALKS_ER"), ("MLB", "PITCHER_K"),
    ("MLB", "PITCHER_OUTS"), ("MLB", "PITCHER_RECORD_WIN"), ("MLB", "RBI"),
    ("MLB", "RUNS"), ("MLB", "RUNS_RBIS"), ("MLB", "RUN_LINE"),
    ("MLB", "SINGLES"), ("MLB", "STOLEN_BASES"), ("MLB", "TEAM_TOTALS"),
    ("MLB", "TOTALS"), ("MLB", "TOTAL_BASES"), ("MLB", "TRIPLES"),
    ("MLB", "YRFI"),
    ("NFL", "alternate_spread"), ("NFL", "alternate_total"),
    ("NFL", "anytime_td"), ("NFL", "attempts"),
    ("NFL", "both_teams_to_score_n"), ("NFL", "completions"),
    ("NFL", "defensive_special_teams_td"), ("NFL", "fg_made"),
    ("NFL", "first_half_moneyline"), ("NFL", "first_half_spread"),
    ("NFL", "first_half_total"), ("NFL", "first_score"),
    ("NFL", "first_td"), ("NFL", "interceptions"),
    ("NFL", "kicking_points"), ("NFL", "largest_lead"),
    ("NFL", "longest_completion"), ("NFL", "longest_fg_made"),
    ("NFL", "longest_reception"), ("NFL", "longest_rush"),
    ("NFL", "moneyline"), ("NFL", "pass_plus_rush_yards"),
    ("NFL", "passing_tds"), ("NFL", "passing_yards"),
    ("NFL", "player_interceptions"), ("NFL", "player_sacks"),
    ("NFL", "quarter_moneyline"), ("NFL", "quarter_spread"),
    ("NFL", "quarter_total"), ("NFL", "race_to_n_points"),
    ("NFL", "receiving_yards"), ("NFL", "receptions"),
    ("NFL", "rush_attempts"), ("NFL", "rush_plus_rec_yards"),
    ("NFL", "rush_yards"), ("NFL", "rushing_yards"), ("NFL", "safety"),
    ("NFL", "second_half_moneyline"), ("NFL", "second_half_spread"),
    ("NFL", "second_half_total"), ("NFL", "spread"),
    ("NFL", "tackles_assists"), ("NFL", "targets"), ("NFL", "team_sacks"),
    ("NFL", "team_total"), ("NFL", "team_turnovers"), ("NFL", "total"),
    ("NFL", "total_touchdowns"), ("NFL", "two_plus_td"),
    ("NFL", "winning_margin_band"), ("NFL", "xp_made"),
]

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)


# ------------------------------------------------------------ coverage

def test_coverage_table_matches_phase1_matrix_exactly():
    assert len(MATRIX_MARKETS) == 89
    assert set(MATRIX_MARKETS) == set(MARKET_RESOLUTIONS)


def test_every_matrix_market_resolves_priced_path_or_named_blocker():
    for sport, market in MATRIX_MARKETS:
        res = resolve_market(sport, market)
        assert res is not None, (sport, market)
        if res["state"] == "PRICED_PATH":
            assert res["engine"], (sport, market)
            assert res["blocker"] is None
        else:
            assert res["state"] == "BLOCKED"
            assert res["blocker"] in BLOCKER_TAXONOMY, (sport, market)
            assert res["detail"], (sport, market)


def test_coverage_summary_counts():
    summary = coverage_summary()
    assert summary["markets_total"] == 89
    assert summary["priced_path_count"] == 39
    assert summary["blocked_count"] == 50
    assert summary["blocked_counts_by_cause"] == {
        "NO_DATA": 1, "NO_ENGINE": 45, "NO_QUOTE": 4}
    assert summary["coverage_is_not_validation"] is True


def test_blocked_row_for_names_the_taxonomy_blocker():
    row = blocked_row_for("MLB", "F5_MONEYLINE",
                          {"market": "F5_MONEYLINE", "side": "HOME"})
    assert row["status"] == "NO_MODEL_OR_MARKET"
    assert row["blocker"] == "NO_QUOTE"
    assert row["reason"].startswith("NO_QUOTE: ")
    row = blocked_row_for("NFL", "FG_MADE", {"market": "FG_MADE"})
    assert row["blocker"] == "NO_ENGINE"
    # Priced-path markets are owned by their engines, not this fallback.
    assert blocked_row_for("NFL", "ANYTIME_TD", {"market": "ANYTIME_TD"}) is None
    assert blocked_row_for("NBA", "PLAYER_POINTS", {"market": "X"}) is None


def test_dispatch_sets_match_stage_modules():
    # run_it_full classifies via the dependency-light coverage constants;
    # the stage modules own the same sets. Drift fails here.
    from sportsedge.canonical_coverage import (
        NFL_ANYTIME_TD_MARKETS, NFL_DERIVATIVE_MARKETS, NFL_FIRST_TD_MARKETS)
    from sportsedge.nfl_phone_anytime_td_pricing import (
        FIRST_TD_MARKETS, TD_MARKETS)
    from sportsedge.nfl_phone_derivative_pricing import DERIVATIVE_MARKETS
    assert NFL_DERIVATIVE_MARKETS == frozenset(DERIVATIVE_MARKETS)
    assert NFL_ANYTIME_TD_MARKETS == frozenset(TD_MARKETS)
    assert NFL_FIRST_TD_MARKETS == frozenset(FIRST_TD_MARKETS)


def test_superseded_route_notices_present():
    root = Path(__file__).resolve().parents[1]
    for rel in ("scripts/run_auto_dk_cards.py",
                "scripts/run_auto_mlb_resilient.py",
                "scripts/run_auto_mlb.py",
                "scripts/run_auto_nfl_resilient.py",
                "scripts/run_manual_mlb_snapshot.py",
                "scripts/run_nfl_lines_card.py",
                "scripts/run_nfl_unified_lines_card.py",
                "scripts/run_cfb_sdv_card_v2.py"):
        text = (root / rel).read_text(encoding="utf-8")
        assert "SUPERSEDED ROUTE" in text, rel
        assert "artifacts/run_it_full.py" in text, rel


# ------------------------------------------------------- derivative stage

def _sim_rows():
    """Synthetic joint score distribution (stage-level fixture only)."""
    rows = []
    home_scores = [27, 24, 31, 20, 17, 28, 23, 30, 21, 26]
    away_scores = [20, 17, 24, 13, 20, 21, 16, 27, 14, 23]
    for home, away in zip(home_scores, away_scores):
        rows.append({
            "home_score": home, "away_score": away,
            "first_half_home_score": home // 2,
            "first_half_away_score": away // 2,
        })
    return rows


def test_derivative_stage_prices_from_supplied_distribution():
    dist = _sim_rows()
    rows = [
        {"market": "TEAM_TOTALS", "away": "BUF", "home": "LAR",
         "side": "HOME", "line": 24.5},
        {"market": "TEAM_TOTALS", "away": "BUF", "home": "LAR",
         "side": "AWAY", "line": 20.5},
        {"market": "FIRST_HALF_TOTAL", "away": "BUF", "home": "LAR",
         "side": "OVER", "line": 23.5},
    ]
    out, _ = phone_nfl_derivative_rows(
        rows, distributions={("BUF", "LAR"): dist})
    assert len(out) == 3
    for result in out:
        assert result["status"] == "PRICED_RESEARCH"
        assert result["quote_judged"] is False
    home_over = sum(1 for r in dist if r["home_score"] > 24.5) / len(dist)
    assert out[0]["model_probabilities"]["over"] == pytest.approx(home_over)
    fh_over = sum(1 for r in dist
                  if r["first_half_home_score"]
                  + r["first_half_away_score"] > 23.5) / len(dist)
    assert out[2]["model_probabilities"]["over"] == pytest.approx(fh_over)


def test_derivative_stage_fails_closed_without_distribution():
    rows = [
        {"market": "TEAM_TOTALS", "away": "BUF", "home": "LAR",
         "side": "HOME", "line": 24.5},
        {"market": "FIRST_HALF_TOTAL", "away": "BUF", "home": "LAR",
         "side": "OVER", "line": 23.5},
        {"market": "SECOND_HALF_TOTAL", "away": "BUF", "home": "LAR",
         "side": "OVER", "line": 24.5},
        {"market": "QUARTER_TOTAL", "away": "BUF", "home": "LAR",
         "side": "OVER", "line": 13.5},
        {"market": "ALTERNATE_TOTAL", "away": "BUF", "home": "LAR",
         "side": "OVER", "line": 51.5},
    ]
    out, _ = phone_nfl_derivative_rows(rows)
    assert [r["status"] for r in out] == ["NO_MODEL_OR_MARKET"] * 5
    assert all(r["blocker"] == "NO_ENGINE" for r in out)
    assert out[0]["reason"] == "NFL_TEAM_TOTAL_SCORE_DISTRIBUTION_EMPTY"
    assert out[1]["reason"] == "SIMULATION_ROWS_EMPTY"
    assert out[2]["reason"] in (
        "SIMULATION_ROWS_EMPTY", "SECOND_HALF_OT_RULE_REQUIRED")
    assert out[3]["reason"] == "QUARTER_UNSPECIFIED"
    assert out[4]["reason"] == "SIMULATION_ROWS_EMPTY"


def test_derivative_stage_emits_results_in_input_order():
    # The runner pairs stage results with intake rows positionally.
    # Team totals are grouped per fixture inside the stage, but the
    # emitted order must stay the input order -- a mixed input (period
    # row first) exposed this when the Oct 13, 2026 owner ruling began
    # routing team totals and first-half rows here together.
    rows = [
        {"market": "FIRST_HALF_TOTAL", "away": "BUF", "home": "LAR",
         "side": "OVER", "line": 23.5},
        {"market": "TEAM_TOTALS", "away": "BUF", "home": "LAR",
         "side": "HOME", "line": 24.5},
    ]
    out, _ = phone_nfl_derivative_rows(rows)
    assert out[0]["reason"] == "SIMULATION_ROWS_EMPTY"
    assert out[1]["reason"] == "NFL_TEAM_TOTAL_SCORE_DISTRIBUTION_EMPTY"


def test_derivative_stage_first_half_team_total_blocks_period_reason():
    # First-half team totals are period markets: no pricer of their own,
    # so the period-distribution guard is the named reason (owner
    # ruling, Oct 13, 2026 -- distinct from the full-game team-total
    # ground, NFL_TEAM_TOTAL_SCORE_DISTRIBUTION_EMPTY).
    out, _ = phone_nfl_derivative_rows([
        {"market": "FIRST_HALF_TEAM_TOTAL", "away": "BUF", "home": "LAR",
         "side": "OVER", "line": 10.5}])
    assert out[0]["status"] == "NO_MODEL_OR_MARKET"
    assert out[0]["blocker"] == "NO_ENGINE"
    assert out[0]["reason"] == "SIMULATION_ROWS_EMPTY"


def test_derivative_rows_blocked_through_run_full():
    from artifacts.run_it_full import run_full
    rows = [
        {"sport": "NFL", "market": "TEAM_TOTALS", "away": "Buffalo Bills",
         "home": "Los Angeles Rams", "side": "HOME", "line": 24.5,
         "odds": -110, "kickoff": "2026-10-25T17:00:00Z"},
        {"sport": "NFL", "market": "FIRST_HALF_TOTAL",
         "away": "Buffalo Bills", "home": "Los Angeles Rams",
         "side": "OVER", "line": 23.5, "odds": -110,
         "kickoff": "2026-10-25T17:00:00Z"},
    ]
    card = run_full({"lines": rows}, now=NOW, auto_context=False)
    evaluated = card["evaluated_rows"]
    assert evaluated[0]["blocker"] == "NO_ENGINE"
    assert evaluated[0]["reason"] == "NFL_TEAM_TOTAL_SCORE_DISTRIBUTION_EMPTY"
    assert evaluated[1]["blocker"] == "NO_ENGINE"
    assert evaluated[1]["reason"] == "SIMULATION_ROWS_EMPTY"
    assert card["canonical_coverage"]["markets_total"] == 89


# ------------------------------------------------------------ anytime TD

_TD_GAMES = [
    ("2026_01_MIA_BUF", 1, "2026-09-13", "BUF", "MIA"),
    ("2026_02_BUF_NYJ", 2, "2026-09-20", "NYJ", "BUF"),
    ("2026_03_KC_BUF", 3, "2026-09-27", "BUF", "KC"),
    ("2026_04_BUF_NE", 4, "2026-10-04", "NE", "BUF"),
    ("2026_05_DEN_BUF", 5, "2026-10-11", "BUF", "DEN"),
    ("2026_06_SF_BUF", 6, "2026-10-18", "BUF", "SF"),
    ("2026_07_BUF_LAR", 7, "2026-10-25", "LAR", "BUF"),
]
_PLAYERS = [
    ("00-0000001", "Test Runner", "RB"),
    ("00-0000002", "Wide One", "WR"),
    ("00-0000003", "Tight One", "TE"),
    ("00-0000004", "Back Two", "RB"),
]
_RUSH_TDS = [1, 0, 1, 0, 1, 0]
_REC_TDS = [0, 1, 0, 0, 1, 0]


def _write_csv(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        writer.writerows(rows)


def _td_cache(cache_dir):
    cache = Path(cache_dir)
    cache.mkdir(parents=True, exist_ok=True)
    _write_csv(
        cache / "nflverse_games.csv",
        ["game_id", "season", "week", "game_type", "gameday", "gametime",
         "home_team", "away_team", "home_score", "away_score"],
        [(gid, 2026, week, "REG", day, "13:00", home, away,
          24 if week < 7 else "", 17 if week < 7 else "")
         for gid, week, day, home, away in _TD_GAMES])
    stats_header = ["player_id", "player_display_name", "position",
                    "position_group", "season", "week", "season_type",
                    "game_id", "team", "opponent_team", "carries",
                    "rushing_tds", "targets", "receptions", "receiving_tds"]
    stats = []
    for gid, week, _day, home, away in _TD_GAMES[:6]:
        opp = away if home == "BUF" else home
        for pid, name, pos in _PLAYERS:
            if pid == "00-0000001":
                stats.append((pid, name, pos, pos, 2026, week, "REG", gid,
                              "BUF", opp, 12, _RUSH_TDS[week - 1], 4, 3,
                              _REC_TDS[week - 1]))
            elif pid == "00-0000002":
                stats.append((pid, name, pos, pos, 2026, week, "REG", gid,
                              "BUF", opp, 0, 0, 7, 5, _REC_TDS[week - 1]))
            elif pid == "00-0000003":
                stats.append((pid, name, pos, pos, 2026, week, "REG", gid,
                              "BUF", opp, 0, 0, 5, 4, _RUSH_TDS[week - 1]))
            else:
                stats.append((pid, name, pos, pos, 2026, week, "REG", gid,
                              "BUF", opp, 6, 0, 1, 1, 0))
    _write_csv(cache / "nflverse_player_stats_2026.csv", stats_header, stats)
    _write_csv(
        cache / "nflverse_snap_counts_2026.csv",
        ["game_id", "season", "week", "player", "team", "offense_pct"],
        [(gid, 2026, week, name, "BUF",
          {"00-0000001": 0.62, "00-0000002": 0.85,
           "00-0000003": 0.70, "00-0000004": 0.30}[pid])
         for gid, week, _d, _h, _a in _TD_GAMES[:6]
         for pid, name, _p in _PLAYERS])
    pbp_header = ["game_id", "posteam", "yardline_100", "pass_attempt",
                  "rush_attempt", "rusher_player_id", "receiver_player_id",
                  "pass_touchdown", "rush_touchdown", "penalty",
                  "two_point_attempt", "qb_kneel", "qb_spike", "wp",
                  "down", "qtr"]
    pbp = []
    for gid, _week, _day, _home, _away in _TD_GAMES[:6]:
        for i in range(26):  # open-field pass plays
            pbp.append((gid, "BUF", 55, 1, 0, "",
                        "00-0000002" if i % 3 else "00-0000001",
                        0, 0, 0, 0, 0, 0, 0.5, 1 + i % 2, 1 + i % 3))
        for i in range(4):  # red-zone pass plays
            pbp.append((gid, "BUF", 12, 1, 0, "",
                        "00-0000001" if i == 0 else "00-0000002",
                        1 if i == 0 else 0, 0, 0, 0, 0, 0, 0.5, 1, 2))
        for i in range(21):  # open-field rush plays
            pbp.append((gid, "BUF", 60, 0, 1,
                        "00-0000001" if i % 3 else "00-0000004", "",
                        0, 0, 0, 0, 0, 0, 0.5, 1 + i % 2, 1 + i % 3))
        for i in range(4):  # red-zone rush plays, two score
            pbp.append((gid, "BUF", 8, 0, 1, "00-0000001", "",
                        0, 1 if i < 2 else 0, 0, 0, 0, 0, 0.5, 1, 3))
    with gzip.open(cache / "nflverse_pbp_2026.csv.gz", "wt",
                   encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(pbp_header)
        writer.writerows(pbp)
    return cache


def _raising_opener(url, *args, **kwargs):
    raise OSError("offline test: network disabled")


def _td_row(**kw):
    base = {"sport": "NFL", "market": "ANYTIME_TD",
            "player_name": "Test Runner", "team": "Buffalo Bills",
            "opponent": "Los Angeles Rams",
            "kickoff": "2026-10-25T17:00:00Z", "side": "YES", "odds": -150,
            "book": "DraftKings",
            "quote_captured_at": "2026-10-20T11:59:00Z"}
    base.update(kw)
    return base


def test_anytime_td_priced_through_adapter_offline(tmp_path):
    cache = _td_cache(tmp_path / "td")
    rows = [_td_row(side="YES", odds=-150), _td_row(side="NO", odds=130)]
    out, receipts = phone_anytime_td_rows(
        rows, now=NOW, cache_dir=cache, opener=_raising_opener)
    assert len(out) == 2
    for result in out:
        assert result["status"] in (
            "RESEARCH_CANDIDATE_NOT_VALIDATED", "WATCH_BELOW_EV_FLOOR",
            "WATCH_QUOTE_NOT_CURRENT", "WATCH_PRICE_CAP")
        assert result["source"] == "FREE_NFLVERSE_ANYTIME_TD"
        assert 0.0 < result["model_probability"] < 1.0
        assert result["participation_status"] == (
            "SNAP_SHARE_VERIFIED_FROM_NFLVERSE_TRAILING_GAMES")
    yes_p = next(r["model_probability"] for r in out
                 if r["selection"] == "YES")
    no_p = next(r["model_probability"] for r in out
                if r["selection"] == "NO")
    assert yes_p + no_p == pytest.approx(1.0)
    assert receipts and receipts[0]["seasons_loaded"] == [2026]


def test_anytime_td_unknown_player_and_team_fail_closed(tmp_path):
    cache = _td_cache(tmp_path / "td")
    out, _ = phone_anytime_td_rows(
        [_td_row(player_name="Ghost Player")], now=NOW,
        cache_dir=cache, opener=_raising_opener)
    assert out[0]["status"] == "NO_MODEL_OR_MARKET"
    assert "TD_IDENTITY_UNRESOLVED" in out[0]["reason"]
    out, _ = phone_anytime_td_rows(
        [_td_row(team="Buffalo Bisons")], now=NOW,
        cache_dir=cache, opener=_raising_opener)
    assert out[0]["reason"] == "TD_TEAM_IDENTITY_UNVERIFIED"


def test_anytime_td_and_first_td_through_run_full(tmp_path):
    from artifacts.run_it_full import run_full
    cache = _td_cache(tmp_path / "td")
    rows = [
        _td_row(side="YES", odds=-150),
        _td_row(side="NO", odds=130),
        _td_row(market="FIRST_TD", side="YES", odds=900),
    ]
    card = run_full({"lines": rows}, now=NOW, auto_context=False,
                    td_cache_dir=cache)
    evaluated = card["evaluated_rows"]
    td_rows = [r for r in evaluated if r.get("market") == "ANYTIME_TD"]
    assert len(td_rows) == 2
    assert all(r.get("source") == "FREE_NFLVERSE_ANYTIME_TD"
               for r in td_rows)
    assert all(0.0 < r["model_probability"] < 1.0 for r in td_rows)
    first_td = [r for r in evaluated if r.get("market") == "FIRST_TD"]
    assert len(first_td) == 1
    assert first_td[0]["status"] == "NO_MODEL_OR_MARKET"
    assert first_td[0]["reason"] == "NO_VERIFIED_FIRST_SCORING_ATTRIBUTION"
    assert first_td[0]["blocker"] == "NO_DATA"
    assert card["prop_model_status"]["nfl_anytime_td_engine"].startswith(
        "NFLVERSE_")


# --------------------------------------------- NRFI/YRFI + F5 via run_full

def test_nrfi_yrfi_priced_through_run_full():
    from artifacts.run_it_full import run_full
    from tests.test_mlb_first_inning import (
        _fixture_game, _history_games, _schedule_getter)
    getter = _schedule_getter(_history_games(), _fixture_game())
    now = datetime(2026, 10, 11, 20, 0, tzinfo=timezone.utc)
    base = {"sport": "MLB", "away": "Los Angeles Dodgers",
            "home": "Milwaukee Brewers",
            "kickoff": "2026-10-11T19:00:00-05:00", "book": "draftkings",
            "quote_captured_at": "2026-10-11T20:00:00Z"}
    rows = [dict(base, market="NRFI", odds=-140),
            dict(base, market="YRFI", odds=105)]
    card = run_full({"lines": rows}, now=now, getter=getter)
    evaluated = card["evaluated_rows"]
    assert [r["market"] for r in evaluated] == ["NRFI", "YRFI"]
    for result in evaluated:
        assert result["status"] in (
            "RESEARCH_CANDIDATE_NOT_VALIDATED", "WATCH_BELOW_EV_FLOOR",
            "WATCH_QUOTE_NOT_CURRENT", "WATCH_PRICE_CAP")
        assert result["underlying_market"] == "FIRST_INNING_RUNS"
        assert result["priced_via"] == "FIRST_INNING_RUNS_BINARY_AT_0_5"
        assert 0.0 < result["model_probability"] < 1.0
    nrfi_p = evaluated[0]["model_probability"]
    yrfi_p = evaluated[1]["model_probability"]
    assert nrfi_p + yrfi_p == pytest.approx(1.0, abs=1e-6)


def test_f5_blocked_with_named_reason_through_run_full():
    from artifacts.run_it_full import run_full
    rows = [{"sport": "MLB", "market": "F5_MONEYLINE",
             "away": "Los Angeles Dodgers", "home": "Milwaukee Brewers",
             "side": "HOME", "odds": -120,
             "kickoff": "2026-10-12T00:00:00Z",
             "quote_captured_at": "2026-10-11T20:00:00Z"}]
    card = run_full({"lines": rows}, now=NOW, auto_context=False)
    result = card["evaluated_rows"][0]
    assert result["status"] == "NO_MODEL_OR_MARKET"
    assert result["blocker"] == "NO_QUOTE"
    assert "NO_QUOTE" in result["reason"]
    assert "NO_VERIFIED_MODEL_FOR_THIS_MARKET" not in result["reason"]
