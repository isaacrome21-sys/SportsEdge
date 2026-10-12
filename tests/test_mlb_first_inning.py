"""Tests for the Phase 1 MLB first-inning build.

Covers: pure-math model properties, fail-closed gates, verified linescore
parsing/pooling, starter split extraction, and phone routing (supported
markets priced, HR/pitches blocked with explicit reasons).
"""
from datetime import datetime, timezone

import pytest

from sportsedge.mlb_first_inning_data import (
    FirstInningDataError,
    build_team_histories,
    collect_completed_games,
    parse_completed_linescore_game,
    prior_pools,
    starter_first_inning_allowed_from_pbp,
)
from sportsedge.mlb_first_inning_model import (
    BLOCKED_MARKETS,
    FIRST_INNING_MODEL_VERSION,
    MODEL_MARKETS,
    FirstInningModelError,
    blended_rate,
    jeffreys_mean,
    poisson_over,
    price_game_first_inning_runs,
    price_team_first_inning,
    price_team_hits,
)
from sportsedge.mlb_phone_first_inning_pricing import (
    FIRST_INNING_PHONE_MARKETS,
    blocked,
    phone_first_inning_rows,
)


def _pools(value, n=12):
    return [value] * n


# ---------------------------------------------------------------- model math

def test_nrfi_yrfi_are_exact_complements():
    out = price_game_first_inning_runs(
        away_for=_pools(0), home_against=_pools(0),
        home_for=_pools(1), away_against=_pools(1))
    assert abs(out["p_over"] + out["p_under"] - 1.0) < 1e-12


def test_probabilities_strictly_interior_even_with_extreme_history():
    out = price_game_first_inning_runs(
        away_for=_pools(0), home_against=_pools(0),
        home_for=_pools(0), away_against=_pools(0))
    assert 0.0 < out["p_under"] < 1.0
    assert 0.0 < out["p_over"] < 1.0
    out2 = price_game_first_inning_runs(
        away_for=_pools(4), home_against=_pools(4),
        home_for=_pools(4), away_against=_pools(4))
    assert 0.0 < out2["p_over"] < 1.0


def test_higher_scoring_history_raises_over_probability():
    low = price_game_first_inning_runs(
        away_for=_pools(0), home_against=_pools(0),
        home_for=_pools(0), away_against=_pools(0))["p_over"]
    high = price_game_first_inning_runs(
        away_for=_pools(2), home_against=_pools(2),
        home_for=_pools(2), away_against=_pools(2))["p_over"]
    assert high > low


def test_jeffreys_smoothing_uses_no_league_data():
    # Same pools -> same rate regardless of any external context.
    assert jeffreys_mean([0] * 10) == pytest.approx(0.5 / 10)
    assert jeffreys_mean([1] * 10) == pytest.approx(10.5 / 10)
    assert blended_rate([0] * 10, [2] * 10) == pytest.approx(
        0.5 * (0.5 / 10 + 20.5 / 10))


def test_poisson_over_matches_closed_form_at_half_lines():
    from math import exp
    assert poisson_over(0.5, 1.0) == pytest.approx(1.0 - exp(-1.0))
    assert poisson_over(6.5, 8.0) == pytest.approx(
        1.0 - sum(exp(-8.0) * 8.0 ** i / __import__("math").factorial(i)
                  for i in range(7)))


def test_team_hits_line_6_5_prices_and_complements():
    out = price_team_hits(team_for=_pools(8, 15), team_against=_pools(9, 15),
                          line=6.5)
    assert 0.0 < out["p_over"] < 1.0
    assert abs(out["p_over"] + out["p_under"] - 1.0) < 1e-12


def test_model_version_pinned():
    assert FIRST_INNING_MODEL_VERSION.startswith("mlb_first_inning_team_rates")


# --------------------------------------------------------------- fail closed

def test_insufficient_history_fails_closed():
    with pytest.raises(FirstInningModelError) as exc:
        price_game_first_inning_runs(
            away_for=_pools(0, 9), home_against=_pools(0),
            home_for=_pools(0), away_against=_pools(0))
    assert "FIRST_INNING_HISTORY_INSUFFICIENT" in str(exc.value)


def test_invalid_pool_values_rejected():
    with pytest.raises(FirstInningModelError):
        price_team_hits(team_for=[8] * 14 + [-1], team_against=_pools(8, 15),
                        line=6.5)
    with pytest.raises(FirstInningModelError):
        price_team_hits(team_for=[8] * 14 + [True], team_against=_pools(8, 15),
                        line=6.5)


def test_wrong_lines_rejected():
    with pytest.raises(FirstInningModelError):
        price_game_first_inning_runs(
            away_for=_pools(0), home_against=_pools(0),
            home_for=_pools(0), away_against=_pools(0), line=1.5)
    with pytest.raises(FirstInningModelError):
        price_team_first_inning("FIRST_INNING_TEAM_RUNS",
                                team_for=_pools(0), team_against=_pools(0),
                                line=2.5)


def test_blocked_markets_carry_explicit_reasons():
    assert BLOCKED_MARKETS["FIRST_INNING_HR"] == \
        "FIRST_INNING_HR_NOT_IN_VERIFIED_LINESCORE"
    assert BLOCKED_MARKETS["FIRST_INNING_PITCHES"] == \
        "FIRST_INNING_PITCHES_NO_VERIFIED_PER_INNING_HISTORY"
    assert "FIRST_INNING_HR" in FIRST_INNING_PHONE_MARKETS
    assert "FIRST_INNING_PITCHES" in FIRST_INNING_PHONE_MARKETS
    for m in ("FIRST_INNING_RUNS", "FIRST_INNING_HITS",
              "FIRST_INNING_TEAM_RUNS", "TEAM_HITS"):
        assert m in MODEL_MARKETS


# ------------------------------------------------------- verified data layer

def _game(game_pk, date, away_id, home_id, a1r, h1r, a1h, h1h, ah, hh,
          game_type="R", detailed="Final"):
    return {
        "gamePk": game_pk, "gameDate": date, "gameType": game_type,
        "status": {"detailedState": detailed},
        "teams": {
            "away": {"team": {"id": away_id, "name": "Away Team"}},
            "home": {"team": {"id": home_id, "name": "Home Team"}},
        },
        "linescore": {
            "innings": [{"num": 1,
                         "away": {"runs": a1r, "hits": a1h},
                         "home": {"runs": h1r, "hits": h1h}}],
            "teams": {"away": {"hits": ah}, "home": {"hits": hh}},
        },
    }


def test_linescore_parse_extracts_first_inning_and_hits():
    parsed = parse_completed_linescore_game(
        _game(1, "2025-06-01T19:00:00Z", 10, 20, 1, 0, 2, 1, 9, 5))
    assert parsed["inn1_away_runs"] == 1
    assert parsed["inn1_home_runs"] == 0
    assert parsed["inn1_away_hits"] == 2
    assert parsed["inn1_home_hits"] == 1
    assert parsed["game_away_hits"] == 9
    assert parsed["game_home_hits"] == 5


def test_non_final_and_missing_linescore_are_skipped_not_imputed():
    assert parse_completed_linescore_game(
        _game(1, "2025-06-01T19:00:00Z", 10, 20, 1, 0, 2, 1, 9, 5,
              detailed="In Progress")) is None
    broken = _game(2, "2025-06-01T19:00:00Z", 10, 20, 1, 0, 2, 1, 9, 5)
    del broken["linescore"]["innings"]
    assert parse_completed_linescore_game(broken) is None


def test_collect_counts_skips_and_filters_postseason():
    dates = [{"games": [
        _game(1, "2025-06-01T19:00:00Z", 10, 20, 1, 0, 2, 1, 9, 5),
        _game(2, "2025-10-05T19:00:00Z", 10, 20, 0, 0, 1, 1, 7, 7,
              game_type="P"),
        {"gamePk": 3},  # corrupt identity -> skip
    ]}]
    games, skipped = collect_completed_games(dates)
    assert len(games) == 1 and games[0]["game_pk"] == "1"
    assert skipped == 2


def test_prior_pools_are_strictly_prior_and_venue_split():
    dates = [{"games": [
        _game(10 + d, f"2025-06-{d + 1:02d}T19:00:00Z", 10, 99, 1, 0, 2, 1,
              9, 5) for d in range(12)
    ] + [
        _game(50, "2025-06-20T19:00:00Z", 99, 10, 0, 2, 1, 3, 5, 9),
    ]}]
    games, _ = collect_completed_games(dates)
    histories = build_team_histories(games)
    pools = prior_pools(histories, 10, was_home=False,
                        before_iso="2025-06-20T00:00:00Z")
    assert pools["game_count"] == 12
    assert pools["inn1_for"] == [1] * 12       # away team top-1 runs
    assert pools["inn1_against"] == [0] * 12
    home_pools = prior_pools(histories, 10, was_home=True,
                             before_iso="2025-06-21T00:00:00Z")
    assert home_pools["game_count"] == 1
    assert home_pools["inn1_for"] == [2]       # home team bottom-1 runs


def test_unknown_team_history_fails_closed():
    with pytest.raises(FirstInningDataError):
        prior_pools({}, 12345, was_home=False, before_iso="2025-06-20T00:00:00Z")


# ------------------------------------------------------- starter split (IN_BUILD)

def _pbp_plays(pitcher_id, half, scores):
    plays = []
    for i, (hs, aws) in enumerate(scores):
        plays.append({
            "about": {"inning": 1, "halfInning": half},
            "matchup": {"pitcher": {"id": pitcher_id}},
            "result": {"homeScore": hs, "awayScore": aws},
        })
    return plays


def test_starter_first_inning_allowed_counts_runs():
    pbp = {"allPlays": (
        _pbp_plays(99, "top", [(0, 0), (0, 1)]) +      # not our pitcher
        _pbp_plays(7, "bottom", [(0, 0), (1, 0), (1, 0), (3, 0)])
    )}
    out = starter_first_inning_allowed_from_pbp(7, game_pks=[111],
                                       getter=lambda url: pbp)
    assert out["n_starts"] == 1
    assert out["runs_allowed"] == [3]
    assert out["status"] == "IN_BUILD_NOT_APPLIED_TO_PRICING"


def test_starter_split_unverified_when_pitcher_never_throws_first():
    pbp = {"allPlays": _pbp_plays(99, "bottom", [(0, 0), (1, 0)])}
    with pytest.raises(FirstInningDataError) as exc:
        starter_first_inning_allowed_from_pbp(7, game_pks=[111],
                                     getter=lambda url: pbp)
    assert "STARTER_FIRST_INNING_SPLIT_UNVERIFIED" in str(exc.value)


# ------------------------------------------------------------------ routing

def _schedule_getter(games_by_date, fixture_game):
    def get(url):
        if "/people/" in url and "gameLog" in url:
            # Probable pitcher gameLogs: id 1 -> Dodgers (119) away starts,
            # id 2 -> Brewers (158) home starts; gamePks reference the fake
            # history (in the 75-day lookback) so linescore lookup succeeds.
            # Only season=2026 carries splits (2025 returns empty).
            from urllib.parse import urlparse, parse_qs
            qs = parse_qs(urlparse(url).query)
            if qs.get("season", [""])[0] != "2026":
                return {"stats": []}
            pid = url.split("/people/")[1].split("/")[0]
            if pid == "1":
                pks, team = [3, 5, 7, 9, 11], 119
            elif pid == "2":
                pks, team = [4, 6, 8, 10, 12], 158
            else:
                return {"stats": []}
            base = datetime(2026, 7, 28, tzinfo=timezone.utc).date()
            splits = []
            for pk in pks:
                day = base + __import__("datetime").timedelta(days=(pk - 1) // 2)
                splits.append({"date": day.isoformat(), "gameType": "R",
                               "game": {"gamePk": pk}, "team": {"id": team},
                               "stat": {"gamesStarted": 1}})
            return {"stats": [{"splits": splits}]}
        from urllib.parse import urlparse, parse_qs
        qs = parse_qs(urlparse(url).query)
        start, end = qs["startDate"][0], qs["endDate"][0]
        dates = []
        day = start
        while day <= end:
            day_games = list(games_by_date.get(day, []))
            if day == "2026-10-11":
                day_games = day_games + [fixture_game]
            if day_games:
                dates.append({"date": day, "games": day_games})
            day = (datetime.strptime(day, "%Y-%m-%d").date()
                   + __import__("datetime").timedelta(days=1)).isoformat()
        return {"dates": dates}
    return get


def _fixture_game():
    return {
        "gamePk": 999, "gameDate": "2026-10-12T00:00:00Z",
        "status": {"detailedState": "Scheduled"},
        "teams": {
            "away": {"team": {"id": 119, "name": "Los Angeles Dodgers"},
                     "probablePitcher": {"id": 1, "fullName": "Away Ace"}},
            "home": {"team": {"id": 158, "name": "Milwaukee Brewers"},
                     "probablePitcher": {"id": 2, "fullName": "Home Ace"}},
        },
    }


def _history_games():
    games_by_date = {}
    pk = 1
    day = datetime(2026, 7, 28, tzinfo=timezone.utc).date()
    end = datetime(2026, 10, 10, tzinfo=timezone.utc).date()
    while day <= end:
        iso = day.isoformat()
        games_by_date[iso] = [
            _game(pk, iso + "T19:00:00Z", 119, 900, 0, 1, 1, 2, 8, 9),
            _game(pk + 1, iso + "T23:00:00Z", 901, 158, 1, 0, 2, 1, 9, 8),
        ]
        pk += 2
        day += __import__("datetime").timedelta(days=1)
    return games_by_date


def _row(**kw):
    base = {"sport": "MLB", "away": "Los Angeles Dodgers",
            "home": "Milwaukee Brewers",
            "kickoff": "2026-10-11T19:00:00-05:00",
            "book": "draftkings",
            "quote_captured_at": "2026-10-11T20:00:00Z",
            "market": "FIRST_INNING_RUNS", "line": 0.5,
            "side": "OVER", "odds": 105}
    base.update(kw)
    return base


def test_blocked_rows_carry_explicit_reasons_without_network():
    rows = [_row(market="FIRST_INNING_HR", team="AWAY"),
            _row(market="FIRST_INNING_PITCHES", team="HOME")]
    out, receipts = phone_first_inning_rows(rows, now=datetime(
        2026, 10, 11, 20, 0, tzinfo=timezone.utc), getter=lambda url: None)
    assert out[0]["status"] == "NO_MODEL_OR_MARKET"
    assert out[0]["reason"] == "FIRST_INNING_HR_NOT_IN_VERIFIED_LINESCORE"
    assert out[1]["reason"] == "FIRST_INNING_PITCHES_NO_VERIFIED_PER_INNING_HISTORY"
    assert receipts == []


def test_supported_market_prices_end_to_end_with_fake_history():
    from sportsedge.mlb_phone_first_inning_pricing import FIRST_INNING_BINARY_VERSION
    getter = _schedule_getter(_history_games(), _fixture_game())
    now = datetime(2026, 10, 11, 20, 0, tzinfo=timezone.utc)
    rows = [_row(side="OVER", odds=105),
            _row(side="UNDER", odds=-140)]
    out, receipts = phone_first_inning_rows(rows, now=now, getter=getter)
    assert len(out) == 2
    for row in out:
        assert row["status"] in (
            "RESEARCH_CANDIDATE_NOT_VALIDATED", "WATCH_BELOW_EV_FLOOR",
            "WATCH_QUOTE_NOT_CURRENT", "WATCH_PRICE_CAP")
        assert 0.0 < row["model_probability"] < 1.0
        assert row["engine_version"] == FIRST_INNING_BINARY_VERSION
        assert row["source"] == "FREE_MLB_STATSAPI_LINESCORE"
        # Validated starter component applied; park disclosed as not wired.
        assert row["starter_adjustment"]["status"] == "VALIDATED_APPLIED"
        assert row["park_adjustment"]["status"] == "NOT_WIRED"
        assert row["model_p_half"]["p_away_scores"] is not None
    assert receipts and receipts[0]["prior_games_away"] >= 10


def test_binary_model_probability_matches_hand_computation():
    # Fake history: away scores in 0/30 prior away 1st innings; home starter
    # allowed a run in 5/5 prior starts (all within the lookback window).
    from sportsedge.mlb_first_inning_model import jeffreys_binary_rate
    getter = _schedule_getter(_history_games(), _fixture_game())
    now = datetime(2026, 10, 11, 20, 0, tzinfo=timezone.utc)
    out, _ = phone_first_inning_rows(
        [_row(side="OVER", odds=105), _row(side="UNDER", odds=-140)],
        now=now, getter=getter)
    p_away = 0.5 * (jeffreys_binary_rate([0] * 30)
                    + jeffreys_binary_rate([1] * 5))
    assert out[0]["model_p_half"]["p_away_scores"] == pytest.approx(p_away)
    assert out[0]["model_p_half"]["p_home_scores"] == pytest.approx(p_away)


def test_in_build_team_markets_blocked_with_explicit_reasons():
    # TEAM_HITS / FIRST_INNING_TEAM_RUNS / FIRST_INNING_HITS have verified
    # data paths but their models did not pass the harness bar: no
    # probabilities are emitted, ever.
    getter = _schedule_getter(_history_games(), _fixture_game())
    now = datetime(2026, 10, 11, 20, 0, tzinfo=timezone.utc)
    rows = [_row(market="TEAM_HITS", line=6.5, team="AWAY", side="OVER",
                 odds=105, label="Dodgers team hits"),
            _row(market="FIRST_INNING_TEAM_RUNS", line=0.5, team="HOME",
                 side="UNDER", odds=-140, label="Brewers first-inning run"),
            _row(market="FIRST_INNING_HITS", line=0.5, team="AWAY",
                 side="OVER", odds=105, label="Dodgers first-inning hits")]
    out, _ = phone_first_inning_rows(rows, now=now, getter=getter)
    assert all(r["status"] == "NO_MODEL_OR_MARKET" for r in out)
    assert all(r["reason"].startswith("IN_BUILD_HARNESS") for r in out)
    assert "model_probability" not in out[0]


def test_blocked_helper_shape_matches_runner_conventions():
    row = blocked({"market": "FIRST_INNING_HR", "side": "OVER"}, "X")
    assert row["status"] == "NO_MODEL_OR_MARKET"
    assert row["research_only"] is True
    assert row["model_p_authority"] is False


# ------------------------------------------------- starter model (gameLog path)

class _FakeSource:
    def __init__(self, payloads):
        self.payloads = payloads

    def _fetch(self, url):
        for key, payload in self.payloads.items():
            if key in url:
                return payload
        return None


def _gamelog_payload():
    def split(date, pk, team, started):
        return {"date": date, "gameType": "R",
                "game": {"gamePk": pk}, "team": {"id": team},
                "stat": {"gamesStarted": started}}
    return {"stats": [{"splits": [
        split("2025-05-01", 101, 10, 1),
        split("2025-05-07", 102, 10, 1),
        split("2025-05-13", 103, 10, 1),
        split("2025-05-19", 104, 10, 0),  # relief appearance, not a start
        split("2025-05-25", 105, 10, 1),
        split("2025-05-31", 106, 10, 1),
        split("2025-06-06", 107, 10, 1),
    ]}]}


def _games_by_pk():
    # starter's team = 10 (away in all these games) -> allowed = inn1_home_runs
    return {
        "101": {"away_id": 10, "home_id": 20, "inn1_home_runs": 0, "inn1_away_runs": 1},
        "102": {"away_id": 10, "home_id": 21, "inn1_home_runs": 2, "inn1_away_runs": 0},
        "103": {"away_id": 10, "home_id": 22, "inn1_home_runs": 1, "inn1_away_runs": 0},
        "105": {"away_id": 10, "home_id": 23, "inn1_home_runs": 0, "inn1_away_runs": 2},
        "106": {"away_id": 10, "home_id": 24, "inn1_home_runs": 3, "inn1_away_runs": 1},
        "107": {"away_id": 10, "home_id": 25, "inn1_home_runs": 0, "inn1_away_runs": 0},
    }


def test_pitcher_prior_starts_filters_to_starts_only():
    from sportsedge.mlb_first_inning_data import pitcher_prior_starts
    src = _FakeSource({"gameLog": _gamelog_payload()})
    starts = pitcher_prior_starts(777, seasons=(2025,), source=src)
    assert [s["game_pk"] for s in starts] == ["101", "102", "103", "105", "106", "107"]
    assert all(s["team_id"] == 10 for s in starts)


def test_starter_allowed_uses_correct_half():
    from sportsedge.mlb_first_inning_data import starter_first_inning_allowed
    src = _FakeSource({"gameLog": _gamelog_payload()})
    allowed = starter_first_inning_allowed(
        777, before_date="2025-06-10", games_by_pk=_games_by_pk(), source=src,
        seasons=(2025,))
    assert allowed == [0, 2, 1, 0, 3, 0]


def test_starter_allowed_fails_closed_below_min_starts():
    from sportsedge.mlb_first_inning_data import starter_first_inning_allowed
    src = _FakeSource({"gameLog": _gamelog_payload()})
    with pytest.raises(FirstInningDataError) as exc:
        starter_first_inning_allowed(
            777, before_date="2025-05-20", games_by_pk=_games_by_pk(),
            source=src, seasons=(2025,), min_starts=5)
    assert "STARTER_FIRST_INNING_HISTORY_INSUFFICIENT" in str(exc.value)


def test_starter_model_prices_and_complements():
    from sportsedge.mlb_first_inning_model import (
        price_game_first_inning_runs_with_starter)
    out = price_game_first_inning_runs_with_starter(
        away_for=[0] * 12, home_starter_allowed=[0, 1, 0, 0, 2, 0],
        home_for=[1] * 12, away_starter_allowed=[1, 0, 1, 0, 0, 1])
    assert 0.0 < out["p_over"] < 1.0
    assert abs(out["p_over"] + out["p_under"] - 1.0) < 1e-12
    # Better starter (fewer allowed) -> higher NRFI probability.
    good = price_game_first_inning_runs_with_starter(
        away_for=[1] * 12, home_starter_allowed=[0] * 6,
        home_for=[1] * 12, away_starter_allowed=[0] * 6)["p_under"]
    bad = price_game_first_inning_runs_with_starter(
        away_for=[1] * 12, home_starter_allowed=[3] * 6,
        home_for=[1] * 12, away_starter_allowed=[3] * 6)["p_under"]
    assert good > bad


def test_starter_model_fails_closed_without_starter_history():
    from sportsedge.mlb_first_inning_model import (
        price_game_first_inning_runs_with_starter)
    with pytest.raises(FirstInningModelError) as exc:
        price_game_first_inning_runs_with_starter(
            away_for=[0] * 12, home_starter_allowed=[0] * 4,
            home_for=[0] * 12, away_starter_allowed=[0] * 6)
    assert "STARTER_FIRST_INNING_HISTORY_INSUFFICIENT" in str(exc.value)


# ------------------------------------------------------- binary model gates

def test_binary_model_complements_and_interior():
    from sportsedge.mlb_first_inning_model import price_first_inning_binary
    out = price_first_inning_binary(
        away_score_ind=[0] * 30, home_starter_allow_ind=[0] * 5,
        home_score_ind=[1] * 30, away_starter_allow_ind=[1] * 5)
    assert abs(out["p_over"] + out["p_under"] - 1.0) < 1e-12
    assert 0.0 < out["p_over"] < 1.0
    assert out["model_version"].startswith("mlb_first_inning_binary_starter")


def test_binary_model_fails_closed_on_short_pools():
    from sportsedge.mlb_first_inning_model import price_first_inning_binary
    with pytest.raises(FirstInningModelError):
        price_first_inning_binary(
            away_score_ind=[0] * 9, home_starter_allow_ind=[0] * 5,
            home_score_ind=[0] * 30, away_starter_allow_ind=[0] * 5)
    with pytest.raises(FirstInningModelError):
        price_first_inning_binary(
            away_score_ind=[0] * 30, home_starter_allow_ind=[0] * 4,
            home_score_ind=[0] * 30, away_starter_allow_ind=[0] * 5)


def test_binary_model_rejects_non_indicators():
    from sportsedge.mlb_first_inning_model import price_first_inning_binary
    with pytest.raises(FirstInningModelError):
        price_first_inning_binary(
            away_score_ind=[0] * 29 + [2], home_starter_allow_ind=[0] * 5,
            home_score_ind=[0] * 30, away_starter_allow_ind=[0] * 5)


def test_binary_model_no_league_prior():
    # Identical inputs -> identical outputs regardless of external context;
    # the only smoothing is the non-informative Jeffreys Beta(1/2,1/2).
    from sportsedge.mlb_first_inning_model import (
        price_first_inning_binary, jeffreys_binary_rate)
    assert jeffreys_binary_rate([0] * 10) == pytest.approx(0.5 / 11)
    kwargs = dict(away_score_ind=[0] * 10, home_starter_allow_ind=[1] * 5,
                  home_score_ind=[1] * 10, away_starter_allow_ind=[0] * 5)
    assert (price_first_inning_binary(**kwargs)["p_over"]
            == price_first_inning_binary(**kwargs)["p_over"])
