"""Offline tests for team-total / first-half pricing (sportsedge/team_half_pricing.py).

Pins the declared (not fitted) 0.50 first-half scale, the runner routing for
TEAM_TOTAL / TOTAL_1H / SPREAD_1H / ML_1H, and the fail-closed gates:
unverified fixture, unmatched identity, started games, bad lines, unsupported
markets. No network calls; PublicContext is faked where the pricer is tested
directly, and the runner is exercised in no-fetch mode.
Research-only semantics are asserted throughout.

Also covers the 2026-10-11 matchup-adjustment audit: injury_points wiring,
the explicit starting-QB scan (out/doubtful -> 538-adapted calibrated
adjustment, Tier 1 per-QB VALUE gap or Tier 2 calibrated constant;
unverifiable -> QB_PARTICIPATION_UNVERIFIED), and the required MLB
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


def _stub_qb_value(monkeypatch, extra_out=0.918, tier="TIER2_CALIBRATED_CONSTANT",
                   **audit_kw):
    """Stub the nflverse-backed QB VALUE pipeline (no network in tests).

    Default extra_out=+0.918 is the real Tier-2 stacking arithmetic:
    QB_CONSTANT_TOTAL (-0.582) minus injury_points' generic QB component
    (-1.5). Doubtful returns the 50% weight, mirroring production.
    """
    def fake(ratings, starter_name, team_abbr, cache):
        audit = {"tier": tier, "variant": tier,
                 "extra_applied": round(extra_out, 3)}
        audit.update(audit_kw)
        return {"extra_total": extra_out, "variant": tier,
                "source": "TEST_STUB", "audit": audit,
                "provenance": "test"}
    monkeypatch.setattr(th._qb_value, "qb_absence_extra", fake)
    monkeypatch.setattr(th, "_qb_ratings", lambda cache_dir, kickoff: {})
    monkeypatch.setattr(th, "_qb_value_dir", lambda: "/tmp/x")


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


def test_qb_out_applies_calibrated_adjustment(monkeypatch):
    # DELIBERATE CHANGE (2026-10-11, qb-sp-adjustment): the old test asserted
    # the declared -1.5 extra (total -3.0 with injury_points). The calibration
    # study (scripts/study_qb_adjustment.py, nflverse 2015-2020, validated
    # out-of-sample 2021-2024) showed the declared -3.0 is WORSE than no
    # adjustment; the empirical mean backup-start TOTAL effect is -0.582, so
    # the extra stacked on injury_points' generic -1.5 QB term is +0.918.
    # The Lamar Jackson case now prices the verified adjustment, not a guess.
    _stub_qb_value(monkeypatch)
    rows = {"1": [{"status": "Out",
                   "athlete": {"id": "1", "fullName": "Lamar Jackson",
                               "position": {"abbreviation": "QB"}}}]}
    injury = {"1": (-1.5, "HEURISTIC_OUT_DOUBTFUL_REPORTED_1_UNKNOWN_COMPLETENESS")}
    out = _price(monkeypatch, _row(), getter=lambda url: None,
                 injury=injury, injury_rows=rows)
    assert out["status"] == "PRICED_RESEARCH"
    assert out["home_mean"] == 22.75 - 1.5 + 0.918
    assert out["away_mean"] == 21.25
    audit = out["matchup_audit"]
    assert audit["home"]["qb_status"] == "QB_OUT_VERIFIED"
    assert audit["home"]["qb_points"] == 0.918
    assert audit["home"]["qb_value_audit"]["tier"] == "TIER2_CALIBRATED_CONSTANT"
    assert "Lamar Jackson" in audit["home"]["qb_detail"]
    assert "home_qb:QB_OUT_VERIFIED" in audit["coverage"]["verified_applied"]


def test_qb_out_tier1_per_qb_value_gap(monkeypatch):
    # Tier 1: backup verifiable -> the 538-adapted VALUE gap determines the
    # extra (here a -22.0 VALUE gap ~= Huntley-for-Lamar scale), fully
    # recorded in the audit. Direction and magnitude come from the study,
    # not from a declared constant.
    _stub_qb_value(monkeypatch, extra_out=-1.082,
                   tier="TIER1_PER_QB_VALUE", value_gap=-22.0,
                   backup="Tyler Huntley")
    rows = {"1": [{"status": "Out",
                   "athlete": {"id": "1", "fullName": "Lamar Jackson",
                               "position": {"abbreviation": "QB"}}}]}
    injury = {"1": (-1.5, "HEURISTIC_OUT_DOUBTFUL_REPORTED_1_UNKNOWN_COMPLETENESS")}
    out = _price(monkeypatch, _row(), getter=lambda url: None,
                 injury=injury, injury_rows=rows)
    assert out["status"] == "PRICED_RESEARCH"
    assert out["home_mean"] == 22.75 - 1.5 - 1.082
    vaudit = out["matchup_audit"]["home"]["qb_value_audit"]
    assert vaudit["tier"] == "TIER1_PER_QB_VALUE"
    assert vaudit["value_gap"] == -22.0
    assert vaudit["backup"] == "Tyler Huntley"


def test_qb_doubtful_applies_half_weight(monkeypatch):
    # DELIBERATE CHANGE: doubtful is 50% of the calibrated OUT extra
    # (declared play-probability weight; 538's published data has no
    # doubtful cases to fit). Old test asserted the declared -0.75.
    _stub_qb_value(monkeypatch)
    rows = {"1": [{"status": "Doubtful",
                   "athlete": {"id": "9", "fullName": "Joe Burrow",
                               "position": {"abbreviation": "QB"}}}]}
    out = _price(monkeypatch, _row(), getter=lambda url: None, injury_rows=rows)
    assert out["status"] == "PRICED_RESEARCH"
    assert out["home_mean"] == 22.75 + 0.459
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

def _mlb_gamelog(starts, start_date="2026-09-01"):
    """Build a StatsAPI season gameLog payload from per-start lines.

    starts: list of (k, bb, h, r, hr, ip_str). Every split is a start
    (gamesStarted=1) dated before the Oct-2026 kickoff (point-in-time).
    """
    from datetime import date, timedelta
    day = date.fromisoformat(start_date)
    splits = []
    for i, (k, bb, h, r, hr, ip) in enumerate(starts):
        splits.append({
            "date": (day + timedelta(days=5 * i)).isoformat(),
            "season": "2026",
            "opponent": {"id": 999, "name": "Test Opp"},
            "stat": {"gamesStarted": 1, "strikeOuts": k, "baseOnBalls": bb,
                     "hits": h, "runs": r, "homeRuns": hr,
                     "inningsPitched": ip},
        })
    return {"stats": [{"group": {"displayName": "pitching"}, "splits": splits}]}


def _mlb_ace_starts(n, k=8, ip="7.0", bb=1, h=5, r=2, hr=1):
    return [(k, bb, h, r, hr, ip)] * n


def _mlb_getter(schedule_probables, gamelogs, game_status="Scheduled",
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
            return gamelogs[pid]
        raise AssertionError("unexpected URL: " + url)
    return get


def _mlb_row(**kw):
    base = {"sport": "MLB", "market": "TEAM_TOTAL", "side": "OVER", "line": 4.5,
            "away": "Los Angeles Dodgers", "home": "Milwaukee Brewers",
            "kickoff": MLB_KICKOFF, "odds": -110, "team": "HOME"}
    base.update(kw)
    return base


def _mlb_standard_getter():
    # DELIBERATE CHANGE (2026-10-11, qb-sp-adjustment): the old ERA-vs-staff
    # formula is replaced by the 538-adapted rolling game score
    # (sportsedge/mlb_sp_rgs.py; gamma=-0.0699 fit, league mean 51.54).
    # Misiorowski: 20 starts of (7K, 2BB, 4H, 1R, 0HR, 6.0IP):
    #   GS = 47.4+7+27-4-8-3-0 = 66.4; gap = 14.86;
    #   adj = 0.014 - 0.0699*14.86 = -1.025.
    # Skubal: 20 starts of (8K, 1BB, 5H, 2R, 1HR, 7.0IP):
    #   GS = 47.4+8+31.5-2-10-6-4 = 64.9; gap = 13.36;
    #   adj = 0.014 - 0.0699*13.36 = -0.920.
    return _mlb_getter(
        ({"id": 101, "fullName": "Jacob Misiorowski"},
         {"id": 102, "fullName": "Tarik Skubal"}),
        {101: _mlb_gamelog(_mlb_ace_starts(20, k=7, ip="6.0", bb=2, h=4, r=1, hr=0)),
         102: _mlb_gamelog(_mlb_ace_starts(20, k=8, ip="7.0", bb=1, h=5, r=2, hr=1))})


def test_mlb_probable_pitcher_adjustment_shifts_means(monkeypatch):
    out = _price(monkeypatch, _mlb_row(), getter=_mlb_standard_getter())
    assert out["status"] == "PRICED_RESEARCH", out
    # MLB PRIORS: base 4.4, hfa 0.20 -> home 4.5 / away 4.3 before pitching.
    # Home (Brewers) faces Skubal (-0.920); away (Dodgers) faces
    # Misiorowski (-1.025). Each side's total is moved by the OPPOSING
    # starter's rGS adjustment.
    assert out["home_mean"] == round(4.5 - 0.920, 3)
    assert out["away_mean"] == round(4.3 - 1.025, 3)
    audit = out["matchup_audit"]
    assert audit["home"]["probable_pitcher"] == "Tarik Skubal"
    assert audit["away"]["probable_pitcher"] == "Jacob Misiorowski"
    assert audit["home"]["pitcher_rgs"] == 64.9
    assert audit["away"]["rgs_gap_vs_league"] == 14.86
    assert audit["home"]["variant"] == "V2_league_relative_raw"
    assert any(v.startswith("probable_pitcher_home:") for v in
               audit["coverage"]["verified_applied"])


def test_mlb_missing_probable_pitcher_fail_closed(monkeypatch):
    getter = _mlb_getter(
        ({"id": 101, "fullName": "Jacob Misiorowski"}, {}),
        {101: _mlb_gamelog(_mlb_ace_starts(20, k=7, ip="6.0", bb=2, h=4, r=1, hr=0))})
    out = _price(monkeypatch, _mlb_row(), getter=getter)
    assert out["status"] == "NO_MODEL_OR_MARKET"
    assert out["reason"] == "PROBABLE_PITCHER_UNVERIFIED"


def test_mlb_opener_shape_fail_closed(monkeypatch):
    # Fewer than 5 games started: opener/bullpen-game shape is not modeled.
    getter = _mlb_getter(
        ({"id": 101, "fullName": "Jacob Misiorowski"},
         {"id": 102, "fullName": "Tarik Skubal"}),
        {101: _mlb_gamelog(_mlb_ace_starts(20, k=7, ip="6.0", bb=2, h=4, r=1, hr=0)),
         102: _mlb_gamelog(_mlb_ace_starts(2, k=8, ip="7.0", bb=1, h=5, r=2, hr=1))})
    out = _price(monkeypatch, _mlb_row(), getter=getter)
    assert out["status"] == "NO_MODEL_OR_MARKET"
    assert out["reason"] == "PROBABLE_PITCHER_UNVERIFIED"


def test_mlb_bad_starter_is_a_boost_not_a_suppression(monkeypatch):
    # A below-league-average starter raises the opposing total (positive adj).
    # Replacement Arm: 12 starts of (3K, 3BB, 8H, 5R, 2HR, 5.0IP):
    #   GS = 47.4+3+22.5-6-16-15-8 = 27.9; gap = -23.64;
    #   adj = 0.014 - 0.0699*(-23.64) = +1.666.
    getter = _mlb_getter(
        ({"id": 101, "fullName": "Jacob Misiorowski"},
         {"id": 103, "fullName": "Replacement Arm"}),
        {101: _mlb_gamelog(_mlb_ace_starts(20, k=7, ip="6.0", bb=2, h=4, r=1, hr=0)),
         103: _mlb_gamelog(_mlb_ace_starts(12, k=3, ip="5.0", bb=3, h=8, r=5, hr=2))})
    out = _price(monkeypatch, _mlb_row(), getter=getter)
    assert out["status"] == "PRICED_RESEARCH", out
    assert out["home_mean"] == round(4.5 + 1.666, 3)


def test_mlb_first_half_total_uses_adjusted_means(monkeypatch):
    row = _mlb_row(market="TOTAL_1H", team=None, line=4.5)
    row.pop("team", None)
    out = _price(monkeypatch, row, getter=_mlb_standard_getter())
    assert out["status"] == "PRICED_RESEARCH", out
    home_mean = round(4.5 - 0.920, 3)
    away_mean = round(4.3 - 1.025, 3)
    # NOTE: the pricer scales the UNROUNDED means by 0.50; mirror that here.
    # Float tolerance: the production path rounds means only for display.
    exp_p, exp_push = model_probability(
        "MLB", "TOTAL", "OVER", 4.5, (4.5 - 0.920) * 0.50, (4.3 - 1.025) * 0.50)
    assert abs(out["estimate_p"] - exp_p) < 1e-9


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
    # DELIBERATE CHANGE (2026-10-11, qb-sp-adjustment): the old assertion
    # pinned the declared -3.0 total (-1.5 generic + -1.5 declared extra).
    # The calibration study replaced the declared extra with the empirical
    # Tier-2 constant: total effect -0.582, i.e. +0.918 stacked on the -1.5
    # generic term. See MATCHUP_VALIDATION.md and
    # scripts/study_qb_adjustment.py.
    _stub_qb_value(monkeypatch)
    rows = {"2": [{"status": "Out",
                   "athlete": {"id": "8", "fullName": "Lamar Jackson",
                               "position": {"abbreviation": "QB"}}}]}
    injury = {"2": (-1.5, "HEURISTIC_OUT_DOUBTFUL_REPORTED_1_UNKNOWN_COMPLETENESS")}
    out = _price(monkeypatch, _lamar_out_row(), getter=lambda url: None,
                 injury=injury, injury_rows=rows)
    assert out["status"] == "PRICED_RESEARCH"
    assert out["matchup_audit"]["away"]["qb_status"] == "QB_OUT_VERIFIED"
    # -1.5 generic QB injury term + +0.918 calibrated extra = -0.582 total,
    # the empirical mean backup-start effect (Tier 2; backup unverifiable in
    # this fixture).
    assert out["away_mean"] == 21.25 - 1.5 + 0.918
    assert out["home_mean"] == 22.75
    # The estimate is recomputed from the ADJUSTED means: no stale input
    # leaks into the probability.
    exp_p, _ = model_probability("NFL", "ML", "AWAY", None,
                                 22.75 * 0.50, (21.25 - 1.5 + 0.918) * 0.50)
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
        {101: _mlb_gamelog(_mlb_ace_starts(20, k=7, ip="6.0", bb=2, h=4, r=1, hr=0))})
        # Skubal's gameLog missing -> unverifiable
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
        {101: _mlb_gamelog(_mlb_ace_starts(20, k=7, ip="6.0", bb=2, h=4, r=1, hr=0)),
         102: _mlb_gamelog(_mlb_ace_starts(20, k=8, ip="7.0", bb=1, h=5, r=2, hr=1))},
        game_status="In Progress"))
    assert out["status"] == "NO_MODEL_OR_MARKET"
    assert out["reason"] == "PROBABLE_PITCHER_UNVERIFIED"
    assert "stale" in out["detail"]


def test_redteam_opener_low_ip_per_start_refuses(monkeypatch):
    # Five "starts" at 2.4 IP/start is a de-facto opener, not a starter.
    getter = _mlb_getter(
        ({"id": 101, "fullName": "Jacob Misiorowski"},
         {"id": 104, "fullName": "Opener Arm"}),
        {101: _mlb_gamelog(_mlb_ace_starts(20, k=7, ip="6.0", bb=2, h=4, r=1, hr=0)),
         104: _mlb_gamelog([(4, 1, 3, 1, 0, "2.1")] * 5)})
    out = _price(monkeypatch, _mlb_row(), getter=getter)
    assert out["status"] == "NO_MODEL_OR_MARKET"
    assert out["reason"] == "PROBABLE_PITCHER_UNVERIFIED"
    assert "opener" in out["detail"].lower()


def test_redteam_suppression_caps_at_declared_bounds(monkeypatch):
    # DELIBERATE CHANGE: cap is now on the rGS adjustment (+-2.0), not the
    # ERA suppression rate. A super-ace (rGS 86.4, gap 34.86) would suppress
    # -2.42 runs -> capped at -2.0.
    getter = _mlb_getter(
        ({"id": 101, "fullName": "Jacob Misiorowski"},
         {"id": 105, "fullName": "Super Ace"}),
        {101: _mlb_gamelog(_mlb_ace_starts(20, k=7, ip="6.0", bb=2, h=4, r=1, hr=0)),
         105: _mlb_gamelog(_mlb_ace_starts(30, k=11, ip="8.0", bb=1, h=3, r=0, hr=0))})
    out = _price(monkeypatch, _mlb_row(), getter=getter)
    assert out["status"] == "PRICED_RESEARCH", out
    audit = out["matchup_audit"]["home"]  # Brewers face the away ace
    assert audit["rgs_gap_vs_league"] == 34.86
    assert audit["points_applied"] == -2.0
    assert out["home_mean"] == round(4.5 - 2.0, 3)


def test_redteam_gs_boundary_exactly_five_passes(monkeypatch):
    getter = _mlb_getter(
        ({"id": 101, "fullName": "Jacob Misiorowski"},
         {"id": 106, "fullName": "Fifth Starter"}),
        {101: _mlb_gamelog(_mlb_ace_starts(20, k=7, ip="6.0", bb=2, h=4, r=1, hr=0)),
         106: _mlb_gamelog(_mlb_ace_starts(5, k=6, ip="6.0", bb=2, h=5, r=2, hr=1))})
    out = _price(monkeypatch, _mlb_row(), getter=getter)
    assert out["status"] == "PRICED_RESEARCH", out
    assert out["matchup_audit"]["home"]["pitcher_starts"] == 5


def test_redteam_malformed_innings_refuses(monkeypatch):
    for bad_ip in ("198.3", "abc", "-5.0", None):
        getter = _mlb_getter(
            ({"id": 101, "fullName": "Jacob Misiorowski"},
             {"id": 107, "fullName": "Bad Data"}),
            {101: _mlb_gamelog(_mlb_ace_starts(20, k=7, ip="6.0", bb=2, h=4, r=1, hr=0)),
             107: _mlb_gamelog([(6, 2, 5, 2, 1, bad_ip)] * 20)})
        out = _price(monkeypatch, _mlb_row(), getter=getter)
        assert out["status"] == "NO_MODEL_OR_MARKET", bad_ip
        assert out["reason"] == "PROBABLE_PITCHER_UNVERIFIED", bad_ip


def test_redteam_missing_gamelog_fields_blocks(monkeypatch):
    # DELIBERATE CHANGE: the rGS engine reads per-start gameLogs, not season
    # ERA. A split missing a required gameScore input refuses.
    stats = {"stats": [{"group": {"displayName": "pitching"},
                        "splits": [{"date": "2026-09-01", "season": "2026",
                                    "opponent": {"id": 999},
                                    "stat": {"gamesStarted": 1,
                                             "inningsPitched": "6.0"}}]}]}
    getter = _mlb_getter(
        ({"id": 101, "fullName": "Jacob Misiorowski"},
         {"id": 102, "fullName": "Tarik Skubal"}),
        {101: stats,
         102: _mlb_gamelog(_mlb_ace_starts(20, k=8, ip="7.0", bb=1, h=5, r=2, hr=1))})
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
        {101: _mlb_gamelog(_mlb_ace_starts(20, k=7, ip="6.0", bb=2, h=4, r=1, hr=0)),
         102: _mlb_gamelog(_mlb_ace_starts(20, k=8, ip="7.0", bb=1, h=5, r=2, hr=1))},
        extra_games=(dh_game,)))
    assert out["status"] == "NO_MODEL_OR_MARKET"
    assert out["reason"] == "PROBABLE_PITCHER_UNVERIFIED"
    assert "2 matches" in out["detail"]


def test_redteam_tbd_probable_id_refuses(monkeypatch):
    out = _price(monkeypatch, _mlb_row(), getter=_mlb_getter(
        ({"id": 101, "fullName": "Jacob Misiorowski"},
         {"id": 0, "fullName": "TBD"}),
        {101: _mlb_gamelog(_mlb_ace_starts(20, k=7, ip="6.0", bb=2, h=4, r=1, hr=0))}))
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
    # DELIBERATE CHANGE: calibrated +0.918 extra replaces the declared -1.5.
    _stub_qb_value(monkeypatch)
    rows = {"2": [{"status": {"name": "Out"},
                   "athlete": {"id": "8", "fullName": "Lamar Jackson",
                               "position": {"abbreviation": "QB"}}}]}
    out = _price(monkeypatch, _row(), getter=lambda url: None, injury_rows=rows)
    assert out["status"] == "PRICED_RESEARCH"
    assert out["matchup_audit"]["away"]["qb_status"] == "QB_OUT_VERIFIED"
    assert out["away_mean"] == 21.25 + 0.918  # calibrated extra only here


def test_redteam_two_qbs_out_single_declared_penalty(monkeypatch):
    # Documents the declared behavior: the first verified out/doubtful QB
    # triggers the backup penalty once; it does not stack per QB.
    # DELIBERATE CHANGE: calibrated +0.918 extra replaces the declared -1.5.
    _stub_qb_value(monkeypatch)
    rows = {"2": [
        {"status": "Out", "athlete": {"id": "8", "fullName": "QB One",
                                      "position": {"abbreviation": "QB"}}},
        {"status": "Out", "athlete": {"id": "9", "fullName": "QB Two",
                                      "position": {"abbreviation": "QB"}}},
    ]}
    out = _price(monkeypatch, _row(), getter=lambda url: None, injury_rows=rows)
    assert out["status"] == "PRICED_RESEARCH"
    assert out["matchup_audit"]["away"]["qb_points"] == 0.918
    assert out["away_mean"] == 21.25 + 0.918


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
    # DELIBERATE CHANGE: doubtful = 50% of the calibrated +0.918 OUT extra.
    _stub_qb_value(monkeypatch)
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
    assert out["away_mean"] == 21.25 - 1.5 + 0.459
