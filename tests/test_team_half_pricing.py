"""Offline tests for team-total / first-half pricing (sportsedge/team_half_pricing.py).

Pins the declared (not fitted) 0.50 first-half scale, the runner routing for
TEAM_TOTAL / TOTAL_1H / SPREAD_1H / ML_1H, and the fail-closed gates:
unverified fixture, unmatched identity, started games, bad lines, unsupported
markets. No network calls; PublicContext is faked where the pricer is tested
directly, and the runner is exercised in no-fetch mode.
Research-only semantics are asserted throughout.

Also covers the 2026-10-11 matchup-adjustment audit: injury_points wiring,
the explicit starting-QB scan (out/doubtful -> declared backup-replacement
penalty; unverifiable -> QB_PARTICIPATION_UNVERIFIED), and the required MLB
probable-pitcher adjustment (verified schedule + season ERA vs staff ERA;
missing/unverifiable -> PROBABLE_PITCHER_UNVERIFIED).
"""
from datetime import datetime, timezone

from artifacts.free_models import model_probability
from artifacts import run_it_full as runner
from sportsedge import team_half_pricing as th

NOW = datetime(2026, 10, 11, 17, 0, tzinfo=timezone.utc)
KICKOFF = "2026-10-18T20:25:00Z"
MLB_KICKOFF = "2026-10-12T00:10:00Z"


class _FakeCtx:
    def __init__(self, now, getter=None, fixture_ok=True, identify_ok=True,
                 injury=None, injury_rows=None):
        self._fixture_ok = fixture_ok
        self._identify_ok = identify_ok
        # injury: (points, status) returned by injury_points, or a dict
        # keyed by team id.
        self._injury = injury
        # injury_rows: list of ESPN injury rows, or dict keyed by team id.
        self._injury_rows = injury_rows

    def fixture(self, sport, away, home, kickoff):
        return {"away": away, "home": home} if self._fixture_ok else None

    def identify(self, sport, name):
        if not self._identify_ok:
            return None
        tid = "1" if "falcons" in name.lower() or "brewers" in name.lower() else "2"
        return {"id": tid, "displayName": name, "abbreviation": name[:3].upper()}

    def schedule(self, sport, team, kickoff):
        return []  # no history -> zero margin proxy

    def injury_points(self, sport, team):
        default = (0.0, "HEURISTIC_OUT_DOUBTFUL_REPORTED_0_UNKNOWN_COMPLETENESS")
        if isinstance(self._injury, dict):
            return self._injury.get(str(team.get("id")), default)
        return self._injury if self._injury is not None else default

    def fetch(self, url):
        if "injuries" in url:
            rows = []
            if isinstance(self._injury_rows, dict):
                for tid, rs in self._injury_rows.items():
                    if ("/teams/%s/injuries" % tid) in url:
                        rows = rs
            elif self._injury_rows is not None:
                rows = self._injury_rows
            return {"injuries": rows}
        return None


def _row(**kw):
    base = {"sport": "NFL", "market": "TOTAL_1H", "side": "OVER", "line": 21.5,
            "away": "Baltimore Ravens", "home": "Atlanta Falcons",
            "kickoff": KICKOFF, "odds": -110}
    base.update(kw)
    return base


def _price(monkeypatch, row, getter=None, **ctxkw):
    monkeypatch.setattr(th, "PublicContext",
                        lambda now, getter=None: _FakeCtx(now, getter, **ctxkw))
    return th.price_team_or_half(row, now=NOW, getter=getter)


def test_half_scale_is_declared_0_50(monkeypatch):
    # NFL PRIORS: base 22.0, hfa 1.5 -> home 22.75 / away 21.25 with no history,
    # no injuries, and a verified no-QB-absence feed.
    out = _price(monkeypatch, _row(), getter=lambda url: None)
    assert out["status"] == "PRICED_RESEARCH"
    assert out["home_mean"] == 22.75
    assert out["away_mean"] == 21.25
    exp_p, exp_push = model_probability(
        "NFL", "TOTAL", "OVER", 21.5, 22.75 * 0.50, 21.25 * 0.50)
    assert out["estimate_p"] == exp_p
    assert out["push_p"] == exp_push
    assert out["research_only"] is True
    assert out["official_authority"] is False
    assert out["model_p_authority"] is False
    assert out["staking_authority"] is False


def test_half_scale_declaration_is_explicit():
    doc = (th.__doc__ or "").lower()
    assert "0.50" in (th.__doc__ or "")
    assert "not a fitted" in doc
    assert "declared" in doc


def test_spread_and_ml_first_half_use_half_scale(monkeypatch):
    for market, mkt in (("SPREAD_1H", "SPREAD"), ("ML_1H", "ML")):
        row = _row(market=market, side="HOME" if market == "ML_1H" else "HOME -3.5",
                   line=None if market == "ML_1H" else 3.5)
        out = _price(monkeypatch, row, getter=lambda url: None)
        assert out["status"] == "PRICED_RESEARCH", (market, out)
        exp_p, exp_push = model_probability(
            "NFL", mkt, out["selection"],
            None if market == "ML_1H" else 3.5, 22.75 * 0.50, 21.25 * 0.50)
        assert out["estimate_p"] == exp_p


def test_team_total_resolves_home_and_away(monkeypatch):
    home = _price(monkeypatch, _row(market="TEAM_TOTAL", team="HOME", line=13.5),
                  getter=lambda url: None)
    away = _price(monkeypatch, _row(market="TEAM_TOTAL", team="AWAY", line=10.5),
                  getter=lambda url: None)
    assert home["status"] == "PRICED_RESEARCH"
    assert away["status"] == "PRICED_RESEARCH"
    assert home["estimate_p"] != away["estimate_p"]  # priced off different means
    bad = _price(monkeypatch, _row(market="TEAM_TOTAL", team="BOGUS", line=13.5),
                 getter=lambda url: None)
    assert bad["status"] == "NO_MODEL_OR_MARKET"
    assert bad["reason"] == "TEAM_TOTAL_TEAM_UNRESOLVED"


def test_missing_identity_fail_closed(monkeypatch):
    out = _price(monkeypatch, _row(sport="XXX"))
    assert out["status"] == "NO_MODEL_OR_MARKET"
    assert out["reason"] == "IDENTITY_OR_SPORT_MISSING"
    out = _price(monkeypatch, _row(away=""))
    assert out["reason"] == "IDENTITY_OR_SPORT_MISSING"


def test_started_game_blocked(monkeypatch):
    out = _price(monkeypatch, _row(kickoff="2026-10-01T20:25:00Z"))
    assert out["status"] == "BLOCKED_STARTED"


def test_fixture_unverified_fail_closed(monkeypatch):
    out = _price(monkeypatch, _row(), fixture_ok=False)
    assert out["status"] == "NO_MODEL_OR_MARKET"
    assert out["reason"] == "FREE_CONTEXT_FIXTURE_NOT_VERIFIED"


def test_identity_unmatched_fail_closed(monkeypatch):
    out = _price(monkeypatch, _row(), identify_ok=False)
    assert out["status"] == "NO_MODEL_OR_MARKET"
    assert out["reason"] == "TEAM_IDENTITY_UNMATCHED"


def test_bad_line_fail_closed(monkeypatch):
    out = _price(monkeypatch, _row(line="abc"), getter=lambda url: None)
    assert out["status"] == "NO_MODEL_OR_MARKET"
    assert out["reason"] == "LINE_UNVERIFIED"


def test_unsupported_market_fail_closed(monkeypatch):
    out = _price(monkeypatch, _row(market="TOTAL_2H"), getter=lambda url: None)
    assert out["status"] == "NO_MODEL_OR_MARKET"
    assert out["reason"] == "UNSUPPORTED_TEAM_HALF_MARKET"


def test_implausible_means_fail_closed(monkeypatch):
    monkeypatch.setattr(th, "PRIORS", {"NFL": (0.1, 13.5, 13.7, 0.0)})
    out = _price(monkeypatch, _row(), getter=lambda url: None)
    assert out["status"] == "NO_MODEL_OR_MARKET"
    assert out["reason"] == "IMPLAUSIBLE_SCORE_MEAN"


def test_runner_routes_team_half_to_pricer_no_fetch():
    # No-fetch mode: the real PublicContext cannot verify a fixture, so the
    # pricer must fail closed with FREE_CONTEXT_FIXTURE_NOT_VERIFIED --
    # proving the rows reached the team-half pricer instead of the router's
    # NO_VERIFIED_MODEL_FOR_THIS_MARKET block.
    rows = [
        _row(market="TEAM_TOTAL", team="HOME", line=13.5),
        _row(market="TOTAL_1H", line=21.5),
        _row(market="SPREAD_1H", side="HOME -3.5", line=3.5),
        _row(market="ML_1H", side="HOME", line=None),
        _row(market="FIRST_HALF_TOTAL", line=21.5),  # alias -> TOTAL_1H
    ]
    card = runner.run_full({"lines": rows}, now=NOW,
                           getter=lambda url: None, auto_context=False)
    by_market = {r["market"]: r for r in card["evaluated_rows"]}
    assert by_market["TOTAL_1H"]["market"] == "TOTAL_1H"
    assert sum(1 for r in card["evaluated_rows"] if r["market"] == "TOTAL_1H") == 2  # alias normalized
    for r in card["evaluated_rows"]:
        assert r["status"] == "NO_MODEL_OR_MARKET", r
        assert r["reason"] == "FREE_CONTEXT_FIXTURE_NOT_VERIFIED", r
    assert card["prop_model_status"]["team_half_engine"] == \
        "FREE_MODELS_MEANS_DECLARED_HALF_SCALE_UNVALIDATED"
    assert card["runner"].endswith("_TEAM_HALF_V1")
    for entry in card["factor_coverage"]["by_input_index"]:
        pp = entry["factors"]["player_props"]
        assert pp["status"] == "NO_MODEL_OR_MARKET", entry
        assert pp["detail"] == "FREE_CONTEXT_FIXTURE_NOT_VERIFIED", entry


# ---------------------------------------------------------------------------
# Matchup-adjustment audit: participation / QB wiring (NFL/CFB/NBA)
# ---------------------------------------------------------------------------

def test_injury_points_wired_into_means(monkeypatch):
    injury = {"1": (-1.5, "HEURISTIC_OUT_DOUBTFUL_REPORTED_1_UNKNOWN_COMPLETENESS"),
              "2": (0.0, "HEURISTIC_OUT_DOUBTFUL_REPORTED_0_UNKNOWN_COMPLETENESS")}
    out = _price(monkeypatch, _row(), getter=lambda url: None, injury=injury)
    assert out["status"] == "PRICED_RESEARCH"
    # Home (Falcons, id 1) carries -1.5 injury points; away untouched.
    assert out["home_mean"] == 22.75 - 1.5
    assert out["away_mean"] == 21.25
    audit = out["matchup_audit"]
    assert audit["home"]["injury_points"] == -1.5
    assert "home_injuries:HEURISTIC_OUT_DOUBTFUL_REPORTED_1_UNKNOWN_COMPLETENESS" \
        in audit["coverage"]["verified_applied"]


def test_qb_out_applies_declared_backup_penalty(monkeypatch):
    # The Lamar Jackson case: verified OUT QB -> generic injury term (-1.5)
    # PLUS the declared backup-replacement penalty (-1.5).
    rows = {"1": [{"status": "Out",
                   "athlete": {"id": "1", "fullName": "Lamar Jackson",
                               "position": {"abbreviation": "QB"}}}]}
    injury = {"1": (-1.5, "HEURISTIC_OUT_DOUBTFUL_REPORTED_1_UNKNOWN_COMPLETENESS")}
    out = _price(monkeypatch, _row(), getter=lambda url: None,
                 injury=injury, injury_rows=rows)
    assert out["status"] == "PRICED_RESEARCH"
    assert out["home_mean"] == 22.75 - 1.5 - 1.5
    assert out["away_mean"] == 21.25
    audit = out["matchup_audit"]
    assert audit["home"]["qb_status"] == "QB_OUT_VERIFIED"
    assert audit["home"]["qb_points"] == -1.5
    assert "Lamar Jackson" in audit["home"]["qb_detail"]
    assert "home_qb:QB_OUT_VERIFIED" in audit["coverage"]["verified_applied"]


def test_qb_doubtful_applies_smaller_declared_penalty(monkeypatch):
    rows = {"1": [{"status": "Doubtful",
                   "athlete": {"id": "9", "fullName": "Joe Burrow",
                               "position": {"abbreviation": "QB"}}}]}
    out = _price(monkeypatch, _row(), getter=lambda url: None, injury_rows=rows)
    assert out["status"] == "PRICED_RESEARCH"
    assert out["home_mean"] == 22.75 - 0.75
    assert out["matchup_audit"]["home"]["qb_status"] == "QB_DOUBTFUL_VERIFIED"


def test_non_qb_out_does_not_trigger_qb_penalty(monkeypatch):
    rows = {"1": [{"status": "Out",
                   "athlete": {"id": "7", "fullName": "Some Receiver",
                               "position": {"abbreviation": "WR"}}}]}
    injury = {"1": (-0.15, "HEURISTIC_OUT_DOUBTFUL_REPORTED_1_UNKNOWN_COMPLETENESS")}
    out = _price(monkeypatch, _row(), getter=lambda url: None,
                 injury=injury, injury_rows=rows)
    assert out["status"] == "PRICED_RESEARCH"
    assert out["home_mean"] == 22.75 - 0.15
    assert out["matchup_audit"]["home"]["qb_status"] == "QB_NO_ABSENCE_VERIFIED"
    assert out["matchup_audit"]["home"]["qb_points"] == 0.0


def test_qb_participation_unverified_fail_closed(monkeypatch):
    injury = {"1": (0.0, "MISSING_OR_UNRECOGNIZED_SOURCE"),
              "2": (0.0, "HEURISTIC_OUT_DOUBTFUL_REPORTED_0_UNKNOWN_COMPLETENESS")}
    out = _price(monkeypatch, _row(), getter=lambda url: None, injury=injury)
    assert out["status"] == "NO_MODEL_OR_MARKET"
    assert out["reason"] == "QB_PARTICIPATION_UNVERIFIED"
    assert out["research_only"] is True


def test_nba_participation_unverified_fail_closed(monkeypatch):
    injury = {"2": (0.0, "MISSING_OR_UNRECOGNIZED_SOURCE")}
    row = _row(sport="NBA", market="TEAM_TOTAL", team="HOME", line=113.5,
               away="Boston Celtics", home="Atlanta Hawks")
    out = _price(monkeypatch, row, getter=lambda url: None, injury=injury)
    assert out["status"] == "NO_MODEL_OR_MARKET"
    assert out["reason"] == "PARTICIPATION_UNVERIFIED"


def test_nba_injury_points_wired_when_verified(monkeypatch):
    injury = {"2": (-0.3, "HEURISTIC_OUT_DOUBTFUL_REPORTED_1_UNKNOWN_COMPLETENESS")}
    row = _row(sport="NBA", market="TEAM_TOTAL", team="HOME", line=113.5,
               away="Boston Celtics", home="Atlanta Hawks")
    out = _price(monkeypatch, row, getter=lambda url: None, injury=injury)
    assert out["status"] == "PRICED_RESEARCH"
    # NBA PRIORS: base 113.0, hfa 2.0 -> home 114.0 / away 112.0; the fake
    # gives both teams id "2", so both carry the -0.3 here.
    assert out["home_mean"] == 114.0 - 0.3
    assert out["away_mean"] == 112.0 - 0.3


# ---------------------------------------------------------------------------
# Matchup-adjustment audit: MLB probable-pitcher adjustment
# ---------------------------------------------------------------------------

def _mlb_people_stats(era, games_started, innings_pitched):
    return {"stats": [{"group": {"displayName": "pitching"},
                       "splits": [{"season": "2026",
                                   "stat": {"era": str(era),
                                            "gamesStarted": games_started,
                                            "inningsPitched": innings_pitched}}]}]}


def _mlb_getter(schedule_probables, people, teams, game_status="Scheduled",
                extra_games=()):
    def get(url):
        if "/schedule?" in url:
            home_p, away_p = schedule_probables
            games = [{
                "status": {"detailedState": game_status},
                "teams": {
                    "home": {"team": {"id": 158, "name": "Milwaukee Brewers"},
                             "probablePitcher": home_p},
                    "away": {"team": {"id": 119, "name": "Los Angeles Dodgers"},
                             "probablePitcher": away_p},
                }}]
            games.extend(extra_games)
            return {"dates": [{"games": games}]}
        if "/people/" in url:
            pid = int(url.split("/people/")[1].split("/")[0])
            return people[pid]
        if "/teams/" in url:
            tid = int(url.split("/teams/")[1].split("/")[0])
            return teams[tid]
        raise AssertionError("unexpected URL: " + url)
    return get


def _mlb_row(**kw):
    base = {"sport": "MLB", "market": "TEAM_TOTAL", "side": "OVER", "line": 4.5,
            "away": "Los Angeles Dodgers", "home": "Milwaukee Brewers",
            "kickoff": MLB_KICKOFF, "odds": -110, "team": "HOME"}
    base.update(kw)
    return base


def _mlb_standard_getter():
    # Misiorowski (1.80 ERA, Brewers staff 3.70) vs Skubal (2.72, Dodgers staff 4.10).
    return _mlb_getter(
        ({"id": 101, "fullName": "Jacob Misiorowski"},
         {"id": 102, "fullName": "Tarik Skubal"}),
        {101: _mlb_people_stats(1.80, 20, "120.0"),
         102: _mlb_people_stats(2.72, 30, "198.0")},
        {158: _mlb_people_stats(3.70, 162, "1450.0"),
         119: _mlb_people_stats(4.10, 162, "1458.1")})


def test_mlb_probable_pitcher_adjustment_shifts_means(monkeypatch):
    out = _price(monkeypatch, _mlb_row(), getter=_mlb_standard_getter())
    assert out["status"] == "PRICED_RESEARCH", out
    # MLB PRIORS: base 4.4, hfa 0.20 -> home 4.5 / away 4.3 before pitching.
    # Home (Brewers) faces Skubal: suppression = min(1.5, 4.10-2.72)=1.38;
    # avg IP/start = 198/30 = 6.6 -> share 0.7333; adj = -1.38*0.7333 = -1.012.
    # Away (Dodgers) faces Misiorowski: suppression = min(1.5, 3.70-1.80)=1.5;
    # avg IP/start = 120/20 = 6.0 -> share 0.6667; adj = -1.5*0.6667 = -1.0.
    assert out["home_mean"] == round(4.5 - 1.38 * (6.6 / 9.0), 3)
    assert out["away_mean"] == round(4.3 - 1.5 * (6.0 / 9.0), 3)
    audit = out["matchup_audit"]
    assert audit["home"]["probable_pitcher"] == "Tarik Skubal"
    assert audit["away"]["probable_pitcher"] == "Jacob Misiorowski"
    assert audit["home"]["pitcher_era"] == 2.72
    assert audit["away"]["staff_era_reference"] == 3.70
    assert any(v.startswith("probable_pitcher_home:") for v in
               audit["coverage"]["verified_applied"])


def test_mlb_missing_probable_pitcher_fail_closed(monkeypatch):
    getter = _mlb_getter(
        ({"id": 101, "fullName": "Jacob Misiorowski"}, {}),
        {101: _mlb_people_stats(1.80, 20, "120.0")},
        {158: _mlb_people_stats(3.70, 162, "1450.0"),
         119: _mlb_people_stats(4.10, 162, "1458.1")})
    out = _price(monkeypatch, _mlb_row(), getter=getter)
    assert out["status"] == "NO_MODEL_OR_MARKET"
    assert out["reason"] == "PROBABLE_PITCHER_UNVERIFIED"


def test_mlb_opener_shape_fail_closed(monkeypatch):
    # Fewer than 5 games started: opener/bullpen-game shape is not modeled.
    getter = _mlb_getter(
        ({"id": 101, "fullName": "Jacob Misiorowski"},
         {"id": 102, "fullName": "Tarik Skubal"}),
        {101: _mlb_people_stats(1.80, 20, "120.0"),
         102: _mlb_people_stats(2.10, 2, "8.0")},
        {158: _mlb_people_stats(3.70, 162, "1450.0"),
         119: _mlb_people_stats(4.10, 162, "1458.1")})
    out = _price(monkeypatch, _mlb_row(), getter=getter)
    assert out["status"] == "NO_MODEL_OR_MARKET"
    assert out["reason"] == "PROBABLE_PITCHER_UNVERIFIED"


def test_mlb_bad_starter_is_a_boost_not_a_suppression(monkeypatch):
    # A below-staff-average starter raises the opposing total (positive adj).
    getter = _mlb_getter(
        ({"id": 101, "fullName": "Jacob Misiorowski"},
         {"id": 103, "fullName": "Replacement Arm"}),
        {101: _mlb_people_stats(1.80, 20, "120.0"),
         103: _mlb_people_stats(6.50, 12, "60.0")},
        {158: _mlb_people_stats(3.70, 162, "1450.0"),
         119: _mlb_people_stats(4.10, 162, "1458.1")})
    out = _price(monkeypatch, _mlb_row(), getter=getter)
    assert out["status"] == "PRICED_RESEARCH", out
    # Brewers face a 6.50 ERA arm on a 4.10 staff: suppression = -1.5 (capped);
    # avg IP/start = 5.0 -> adj = +1.5 * 5/9 = +0.833.
    assert out["home_mean"] == round(4.5 + 1.5 * (5.0 / 9.0), 3)


def test_mlb_first_half_total_uses_adjusted_means(monkeypatch):
    row = _mlb_row(market="TOTAL_1H", team=None, line=4.5)
    row.pop("team", None)
    out = _price(monkeypatch, row, getter=_mlb_standard_getter())
    assert out["status"] == "PRICED_RESEARCH", out
    home_mean = round(4.5 - 1.38 * (6.6 / 9.0), 3)
    away_mean = round(4.3 - 1.5 * (6.0 / 9.0), 3)
    exp_p, exp_push = model_probability(
        "MLB", "TOTAL", "OVER", 4.5, home_mean * 0.50, away_mean * 0.50)
    assert out["estimate_p"] == exp_p


# ---------------------------------------------------------------------------
# PERMANENT REGRESSION TESTS -- Isaac's "verified, not leans" bar, 2026-10-11.
# These encode tonight's two withdrawn cards. They must keep passing: the
# model may apply the verified adjustment or block with the explicit reason
# code, but it must NEVER emit a price/EV on the stale assumption.
# ---------------------------------------------------------------------------

def _lamar_out_row():
    # Tonight's incident: Ravens 1H ML +140 priced as if Lamar Jackson were
    # playing; the market had moved on the backup starting.
    return _row(market="ML_1H", side="AWAY", line=None, odds=140)


def test_regression_lamar_out_feed_unavailable_blocks_no_fake_ev(monkeypatch):
    # Participation feed UNAVAILABLE -> the model must NOT emit a positive-EV
    # price on the stale healthy-roster assumption. It refuses instead.
    injury = {"1": (0.0, "HEURISTIC_OUT_DOUBTFUL_REPORTED_0_UNKNOWN_COMPLETENESS"),
              "2": (0.0, "MISSING_OR_UNRECOGNIZED_SOURCE")}
    out = _price(monkeypatch, _lamar_out_row(), getter=lambda url: None,
                 injury=injury)
    assert out["status"] == "NO_MODEL_OR_MARKET"
    assert out["reason"] == "QB_PARTICIPATION_UNVERIFIED"
    assert "ev_per_dollar" not in out
    assert "home_mean" not in out and "away_mean" not in out
    assert "estimate_p" not in out


def test_regression_lamar_out_feed_available_applies_adjustment(monkeypatch):
    # Feed available and the verified starter is OUT -> the verified
    # adjustment applies; the price is fully determined by verified inputs,
    # never the stale assumption.
    rows = {"2": [{"status": "Out",
                   "athlete": {"id": "8", "fullName": "Lamar Jackson",
                               "position": {"abbreviation": "QB"}}}]}
    injury = {"2": (-1.5, "HEURISTIC_OUT_DOUBTFUL_REPORTED_1_UNKNOWN_COMPLETENESS")}
    out = _price(monkeypatch, _lamar_out_row(), getter=lambda url: None,
                 injury=injury, injury_rows=rows)
    assert out["status"] == "PRICED_RESEARCH"
    assert out["matchup_audit"]["away"]["qb_status"] == "QB_OUT_VERIFIED"
    # -1.5 generic QB injury term + -1.5 declared backup-replacement term.
    assert out["away_mean"] == 21.25 - 3.0
    assert out["home_mean"] == 22.75
    # The estimate is recomputed from the ADJUSTED means: no stale input
    # leaks into the probability.
    exp_p, _ = model_probability("NFL", "ML", "AWAY", None,
                                 22.75 * 0.50, (21.25 - 3.0) * 0.50)
    assert out["estimate_p"] == exp_p
    # And the stale-assumption price is demonstrably different: the withdrawn
    # card's number was materially higher.
    stale_p, _ = model_probability("NFL", "ML", "AWAY", None,
                                   22.75 * 0.50, 21.25 * 0.50)
    assert out["estimate_p"] < stale_p


def test_regression_skubal_feed_unavailable_blocks_no_pitcher_blind_price(monkeypatch):
    # Elite probable pitcher, but the pitcher feed is UNAVAILABLE -> team
    # totals must NOT price on pitcher-blind means.
    def dead_getter(url):
        raise OSError("feed unavailable")
    out = _price(monkeypatch, _mlb_row(), getter=dead_getter)
    assert out["status"] == "NO_MODEL_OR_MARKET"
    assert out["reason"] == "PROBABLE_PITCHER_UNVERIFIED"
    assert "ev_per_dollar" not in out
    assert "home_mean" not in out and "away_mean" not in out
    assert "estimate_p" not in out


def test_regression_skubal_stats_unavailable_blocks(monkeypatch):
    # Schedule lists the ace, but his season stats can't be verified ->
    # still refused; no pitcher-blind price.
    getter = _mlb_getter(
        ({"id": 101, "fullName": "Jacob Misiorowski"},
         {"id": 102, "fullName": "Tarik Skubal"}),
        {101: _mlb_people_stats(1.80, 20, "120.0")},  # Skubal's stats missing
        {158: _mlb_people_stats(3.70, 162, "1450.0"),
         119: _mlb_people_stats(4.10, 162, "1458.1")})
    out = _price(monkeypatch, _mlb_row(), getter=getter)
    assert out["status"] == "NO_MODEL_OR_MARKET"
    assert out["reason"] == "PROBABLE_PITCHER_UNVERIFIED"


# ---------------------------------------------------------------------------
# RED TEAM -- adversarial cases against the adjustment machinery.
# ---------------------------------------------------------------------------

def test_redteam_late_scratch_stale_status_refuses(monkeypatch):
    # The feed says "In Progress" while our kickoff is in the future: the
    # probable listing may be a late scratch or otherwise stale -> refuse.
    out = _price(monkeypatch, _mlb_row(), getter=_mlb_getter(
        ({"id": 101, "fullName": "Jacob Misiorowski"},
         {"id": 102, "fullName": "Tarik Skubal"}),
        {101: _mlb_people_stats(1.80, 20, "120.0"),
         102: _mlb_people_stats(2.72, 30, "198.0")},
        {158: _mlb_people_stats(3.70, 162, "1450.0"),
         119: _mlb_people_stats(4.10, 162, "1458.1")},
        game_status="In Progress"))
    assert out["status"] == "NO_MODEL_OR_MARKET"
    assert out["reason"] == "PROBABLE_PITCHER_UNVERIFIED"
    assert "stale" in out["detail"]


def test_redteam_opener_low_ip_per_start_refuses(monkeypatch):
    # Five "starts" at 2.4 IP/start is a de-facto opener, not a starter.
    getter = _mlb_getter(
        ({"id": 101, "fullName": "Jacob Misiorowski"},
         {"id": 104, "fullName": "Opener Arm"}),
        {101: _mlb_people_stats(1.80, 20, "120.0"),
         104: _mlb_people_stats(3.10, 5, "12.0")},
        {158: _mlb_people_stats(3.70, 162, "1450.0"),
         119: _mlb_people_stats(4.10, 162, "1458.1")})
    out = _price(monkeypatch, _mlb_row(), getter=getter)
    assert out["status"] == "NO_MODEL_OR_MARKET"
    assert out["reason"] == "PROBABLE_PITCHER_UNVERIFIED"
    assert "opener" in out["detail"].lower()


def test_redteam_suppression_caps_at_declared_bounds(monkeypatch):
    # An ace 3.2 runs better than his staff: suppression capped at 1.5/9.
    getter = _mlb_getter(
        ({"id": 101, "fullName": "Jacob Misiorowski"},
         {"id": 105, "fullName": "Super Ace"}),
        {101: _mlb_people_stats(1.80, 20, "120.0"),
         105: _mlb_people_stats(0.90, 30, "198.0")},
        {158: _mlb_people_stats(3.70, 162, "1450.0"),
         119: _mlb_people_stats(4.10, 162, "1458.1")})
    out = _price(monkeypatch, _mlb_row(), getter=getter)
    assert out["status"] == "PRICED_RESEARCH", out
    audit = out["matchup_audit"]["home"]  # Brewers face the away ace
    assert audit["suppression_per_9"] == 1.5
    assert audit["points_applied"] == round(-1.5 * (6.6 / 9.0), 3)
    assert out["home_mean"] == round(4.5 + round(-1.5 * (6.6 / 9.0), 3), 3)


def test_redteam_gs_boundary_exactly_five_passes(monkeypatch):
    getter = _mlb_getter(
        ({"id": 101, "fullName": "Jacob Misiorowski"},
         {"id": 106, "fullName": "Fifth Starter"}),
        {101: _mlb_people_stats(1.80, 20, "120.0"),
         106: _mlb_people_stats(4.00, 5, "28.0")},
        {158: _mlb_people_stats(3.70, 162, "1450.0"),
         119: _mlb_people_stats(4.10, 162, "1458.1")})
    out = _price(monkeypatch, _mlb_row(), getter=getter)
    assert out["status"] == "PRICED_RESEARCH", out
    assert out["matchup_audit"]["home"]["pitcher_games_started"] == 5


def test_redteam_malformed_innings_refuses(monkeypatch):
    for bad_ip in ("198.3", "abc", "-5.0", None):
        getter = _mlb_getter(
            ({"id": 101, "fullName": "Jacob Misiorowski"},
             {"id": 107, "fullName": "Bad Data"}),
            {101: _mlb_people_stats(1.80, 20, "120.0"),
             107: _mlb_people_stats(3.50, 20, bad_ip)},
            {158: _mlb_people_stats(3.70, 162, "1450.0"),
             119: _mlb_people_stats(4.10, 162, "1458.1")})
        out = _price(monkeypatch, _mlb_row(), getter=getter)
        assert out["status"] == "NO_MODEL_OR_MARKET", bad_ip
        assert out["reason"] == "PROBABLE_PITCHER_UNVERIFIED", bad_ip


def test_redteam_missing_era_blocks(monkeypatch):
    stats = {"stats": [{"group": {"displayName": "pitching"},
                        "splits": [{"season": "2026",
                                    "stat": {"gamesStarted": 20,
                                             "inningsPitched": "120.0"}}]}]}
    getter = _mlb_getter(
        ({"id": 101, "fullName": "Jacob Misiorowski"},
         {"id": 102, "fullName": "Tarik Skubal"}),
        {101: stats, 102: _mlb_people_stats(2.72, 30, "198.0")},
        {158: _mlb_people_stats(3.70, 162, "1450.0"),
         119: _mlb_people_stats(4.10, 162, "1458.1")})
    out = _price(monkeypatch, _mlb_row(), getter=getter)
    assert out["status"] == "NO_MODEL_OR_MARKET"
    assert out["reason"] == "PROBABLE_PITCHER_UNVERIFIED"


def test_redteam_doubleheader_refuses(monkeypatch):
    dh_game = {
        "status": {"detailedState": "Scheduled"},
        "teams": {
            "home": {"team": {"id": 158, "name": "Milwaukee Brewers"},
                     "probablePitcher": {"id": 108, "fullName": "Game Two Arm"}},
            "away": {"team": {"id": 119, "name": "Los Angeles Dodgers"},
                     "probablePitcher": {"id": 109, "fullName": "Other Arm"}}}}
    out = _price(monkeypatch, _mlb_row(), getter=_mlb_getter(
        ({"id": 101, "fullName": "Jacob Misiorowski"},
         {"id": 102, "fullName": "Tarik Skubal"}),
        {101: _mlb_people_stats(1.80, 20, "120.0"),
         102: _mlb_people_stats(2.72, 30, "198.0")},
        {158: _mlb_people_stats(3.70, 162, "1450.0"),
         119: _mlb_people_stats(4.10, 162, "1458.1")},
        extra_games=(dh_game,)))
    assert out["status"] == "NO_MODEL_OR_MARKET"
    assert out["reason"] == "PROBABLE_PITCHER_UNVERIFIED"
    assert "2 matches" in out["detail"]


def test_redteam_tbd_probable_id_refuses(monkeypatch):
    out = _price(monkeypatch, _mlb_row(), getter=_mlb_getter(
        ({"id": 101, "fullName": "Jacob Misiorowski"},
         {"id": 0, "fullName": "TBD"}),
        {101: _mlb_people_stats(1.80, 20, "120.0")},
        {158: _mlb_people_stats(3.70, 162, "1450.0"),
         119: _mlb_people_stats(4.10, 162, "1458.1")}))
    assert out["status"] == "NO_MODEL_OR_MARKET"
    assert out["reason"] == "PROBABLE_PITCHER_UNVERIFIED"


def test_redteam_schedule_non_dict_blocks(monkeypatch):
    def bad(url):
        return ["not", "a", "dict"] if "/schedule?" in url else {}
    out = _price(monkeypatch, _mlb_row(), getter=bad)
    assert out["status"] == "NO_MODEL_OR_MARKET"
    assert out["reason"] == "PROBABLE_PITCHER_UNVERIFIED"


def test_redteam_qb_questionable_applies_no_penalty(monkeypatch):
    # Questionable is not out/doubtful: no backup penalty, still priced.
    rows = {"2": [{"status": "Questionable",
                   "athlete": {"id": "8", "fullName": "Lamar Jackson",
                               "position": {"abbreviation": "QB"}}}]}
    out = _price(monkeypatch, _row(), getter=lambda url: None, injury_rows=rows)
    assert out["status"] == "PRICED_RESEARCH"
    assert out["away_mean"] == 21.25
    assert out["matchup_audit"]["away"]["qb_status"] == "QB_NO_ABSENCE_VERIFIED"


def test_redteam_qb_status_dict_shape(monkeypatch):
    # ESPN sometimes nests status as {"name": "Out"}.
    rows = {"2": [{"status": {"name": "Out"},
                   "athlete": {"id": "8", "fullName": "Lamar Jackson",
                               "position": {"abbreviation": "QB"}}}]}
    out = _price(monkeypatch, _row(), getter=lambda url: None, injury_rows=rows)
    assert out["status"] == "PRICED_RESEARCH"
    assert out["matchup_audit"]["away"]["qb_status"] == "QB_OUT_VERIFIED"
    assert out["away_mean"] == 21.25 - 1.5  # declared term only here


def test_redteam_two_qbs_out_single_declared_penalty(monkeypatch):
    # Documents the declared behavior: the first verified out/doubtful QB
    # triggers the backup penalty once; it does not stack per QB.
    rows = {"2": [
        {"status": "Out", "athlete": {"id": "8", "fullName": "QB One",
                                      "position": {"abbreviation": "QB"}}},
        {"status": "Out", "athlete": {"id": "9", "fullName": "QB Two",
                                      "position": {"abbreviation": "QB"}}},
    ]}
    out = _price(monkeypatch, _row(), getter=lambda url: None, injury_rows=rows)
    assert out["status"] == "PRICED_RESEARCH"
    assert out["matchup_audit"]["away"]["qb_points"] == -1.5
    assert out["away_mean"] == 21.25 - 1.5


def test_redteam_ambiguous_grouped_payload_blocks(monkeypatch):
    # League-style grouped payload where two groups claim this team id:
    # rows cannot be attributed -> refuse, matching injury_points' own rule.
    groups = [
        {"id": "2", "injuries": [{"status": "Out",
                                  "athlete": {"id": "8", "fullName": "X",
                                              "position": {
                                                  "abbreviation": "QB"}}}]},
        {"team": {"id": "2"}, "injuries": []},
    ]
    injury = {"2": (0.0, "MISSING_OR_UNRECOGNIZED_SOURCE")}
    out = _price(monkeypatch, _row(), getter=lambda url: None,
                 injury=injury, injury_rows=groups)
    assert out["status"] == "NO_MODEL_OR_MARKET"
    assert out["reason"] == "QB_PARTICIPATION_UNVERIFIED"


def test_redteam_grouped_single_match_qb_detected(monkeypatch):
    # Grouped league payload with exactly one matching group: the QB scan
    # agrees with injury_points' attribution rule.
    groups = [
        {"team": {"id": "1"}, "injuries": []},
        {"team": {"id": "2"}, "injuries": [
            {"status": "Doubtful",
             "athlete": {"id": "8", "fullName": "Lamar Jackson",
                         "position": {"abbreviation": "QB"}}}]},
        {"team": {"id": "7"}, "injuries": []},
    ]
    injury = {"2": (-1.5, "HEURISTIC_OUT_DOUBTFUL_REPORTED_1_UNKNOWN_COMPLETENESS")}
    out = _price(monkeypatch, _row(), getter=lambda url: None,
                 injury=injury, injury_rows=groups)
    assert out["status"] == "PRICED_RESEARCH"
    assert out["matchup_audit"]["away"]["qb_status"] == "QB_DOUBTFUL_VERIFIED"
    assert out["away_mean"] == 21.25 - 1.5 - 0.75
