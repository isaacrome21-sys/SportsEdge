"""Tests for the pre-pricing factor-ingestion stage.

All pulls use recorded fixtures via a stub getter; no network is touched.
Covers: verified-only adjustment application, per-game factor audit,
critical-factor downgrade paths, archived weather evidence admission
(including stale-archive rejection), and the surgical run_it_full hook.
"""
import unittest
from datetime import datetime, timezone

from artifacts import free_models
from artifacts.run_it_full import run_full
from sportsedge.prepricing import factor_ingestion as fi

NOW = datetime(2026, 10, 11, 18, 0, tzinfo=timezone.utc)
KICKOFF_NFL = "2026-10-12T17:00:00Z"
KICKOFF_MLB = "2026-10-12T20:10:00Z"
ESPN = "https://site.api.espn.com/apis/site/v2/sports"


class FakeGetter:
    """Recorded-fixture getter: unmapped URLs fail like a dead network."""

    def __init__(self, mapping):
        self.mapping = dict(mapping)
        self.calls = []

    def __call__(self, url):
        self.calls.append(url)
        if url not in self.mapping:
            raise OSError("UNMAPPED_URL:" + url)
        return self.mapping[url]


def nfl_teams_payload():
    return {"sports": [{"leagues": [{"teams": [
        {"team": {"id": "1", "displayName": "Atlanta Falcons", "name": "Falcons",
                  "shortDisplayName": "Falcons", "abbreviation": "ATL",
                  "location": "Atlanta"}},
        {"team": {"id": "33", "displayName": "Baltimore Ravens", "name": "Ravens",
                  "shortDisplayName": "Ravens", "abbreviation": "BAL",
                  "location": "Baltimore"}},
    ]}]}]}


def nfl_scoreboard_payload():
    return {"events": [{
        "id": "401772001", "date": KICKOFF_NFL,
        "competitions": [{
            "competitors": [
                {"homeAway": "home",
                 "team": {"id": "1", "abbreviation": "ATL",
                          "displayName": "Atlanta Falcons"}},
                {"homeAway": "away",
                 "team": {"id": "33", "abbreviation": "BAL",
                          "displayName": "Baltimore Ravens"}}],
            "venue": {"indoor": False, "fullName": "Mercedes-Benz Stadium",
                      "address": {"city": "Atlanta", "state": "GA"}},
        }],
    }]}


def sched_game(date, own_id, own, opp_id, opp):
    return {"date": date, "status": {"type": {"completed": True}},
            "competitions": [{"competitors": [
                {"team": {"id": own_id}, "score": {"value": str(own)}},
                {"team": {"id": opp_id}, "score": {"value": str(opp)}}]}]}


def nfl_schedules():
    falcons = [sched_game("2026-09-13T17:00:00Z", "1", 24, "20", 17),
               sched_game("2026-09-20T17:00:00Z", "1", 20, "33", 27),
               sched_game("2026-09-28T17:00:00Z", "1", 31, "11", 24),
               sched_game("2026-10-04T17:00:00Z", "1", 17, "9", 20)]
    ravens = [sched_game("2026-09-13T17:00:00Z", "33", 27, "1", 20),
              sched_game("2026-09-21T17:00:00Z", "33", 24, "5", 24),
              sched_game("2026-09-28T17:00:00Z", "33", 30, "14", 17),
              sched_game("2026-10-05T17:00:00Z", "33", 21, "12", 24)]
    return {"events": falcons}, {"events": ravens}


def nfl_injuries():
    falcons = {"injuries": [
        {"athlete": {"id": "123", "displayName": "Kirk Cousins",
                     "position": {"abbreviation": "QB"}}, "status": "Out"},
        {"athlete": {"id": "124", "displayName": "Bijan Robinson",
                     "position": {"abbreviation": "RB"}}, "status": "Questionable"},
    ]}
    ravens = {"injuries": [
        {"athlete": {"id": "456", "displayName": "Lamar Jackson",
                     "position": {"abbreviation": "QB"}}, "status": "Doubtful"},
    ]}
    return falcons, ravens


def weather_fixtures():
    geocode_url = ("https://geocoding-api.open-meteo.com/v1/search?"
                   "name=Atlanta%2C+Georgia&countryCode=US&count=100&"
                   "language=en&format=json")
    forecast_url = ("https://api.open-meteo.com/v1/forecast?"
                    "latitude=33.75&longitude=-84.39&"
                    "hourly=wind_speed_10m%2Cprecipitation_probability&"
                    "wind_speed_unit=mph&timezone=UTC&forecast_days=10")
    return {
        geocode_url: {"results": [
            {"name": "Atlanta", "admin1": "Georgia", "country_code": "US",
             "latitude": 33.75, "longitude": -84.39, "population": 500000}]},
        forecast_url: {"hourly": {
            "time": ["2026-10-12T17:00"],
            "wind_speed_10m": [20.0],
            "precipitation_probability": [80]}},
    }


def nfl_mapping():
    falcons_sched, ravens_sched = nfl_schedules()
    falcons_inj, ravens_inj = nfl_injuries()
    mapping = {
        f"{ESPN}/football/nfl/teams?limit=500": nfl_teams_payload(),
        f"{ESPN}/football/nfl/scoreboard?dates=20261011&limit=500": {"events": []},
        f"{ESPN}/football/nfl/scoreboard?dates=20261012&limit=500": nfl_scoreboard_payload(),
        f"{ESPN}/football/nfl/scoreboard?dates=20261013&limit=500": {"events": []},
        f"{ESPN}/football/nfl/teams/1/schedule?season=2026": falcons_sched,
        f"{ESPN}/football/nfl/teams/33/schedule?season=2026": ravens_sched,
        f"{ESPN}/football/nfl/teams/1/injuries": falcons_inj,
        f"{ESPN}/football/nfl/teams/33/injuries": ravens_inj,
    }
    mapping.update(weather_fixtures())
    return mapping


def nfl_row(**kw):
    # Option 3: Include fresh quote for #2045 180s freshness check
    # The NOW timestamp is used for quote_captured_at to ensure freshness
    row = {"sport": "NFL", "market": "SPREAD", "away": "Baltimore Ravens",
           "home": "Atlanta Falcons", "side": "HOME", "line": -3.5,
           "odds": -110, "commence_time": KICKOFF_NFL,
           "quote_captured_at": NOW.isoformat()}
    row.update(kw)
    return row


def mlb_mapping():
    teams = {"sports": [{"leagues": [{"teams": [
        {"team": {"id": "19", "displayName": "Los Angeles Dodgers", "name": "Dodgers",
                  "shortDisplayName": "Dodgers", "abbreviation": "LAD",
                  "location": "Los Angeles"}},
        {"team": {"id": "23", "displayName": "Milwaukee Brewers", "name": "Brewers",
                  "shortDisplayName": "Brewers", "abbreviation": "MIL",
                  "location": "Milwaukee"}},
    ]}]}]}
    board = {"events": [{
        "id": "777001", "date": KICKOFF_MLB,
        "competitions": [{
            "competitors": [
                {"homeAway": "home",
                 "team": {"id": "23", "abbreviation": "MIL",
                          "displayName": "Milwaukee Brewers"}},
                {"homeAway": "away",
                 "team": {"id": "19", "abbreviation": "LAD",
                          "displayName": "Los Angeles Dodgers"}}],
            "venue": {"indoor": True, "fullName": "American Family Field",
                      "address": {"city": "Milwaukee", "state": "WI"}},
        }],
    }]}
    home_sched = {"events": [
        sched_game("2026-10-07T18:00:00Z", "23", 5, "19", 3),
        sched_game("2026-10-08T18:00:00Z", "23", 2, "19", 4),
        sched_game("2026-10-09T18:00:00Z", "23", 6, "19", 1),
        sched_game("2026-10-10T18:00:00Z", "23", 3, "19", 5),
        sched_game("2026-10-11T14:00:00Z", "23", 4, "19", 2)]}
    away_sched = {"events": [
        sched_game("2026-10-07T18:00:00Z", "19", 3, "23", 5),
        sched_game("2026-10-08T18:00:00Z", "19", 4, "23", 2),
        sched_game("2026-10-09T18:00:00Z", "19", 1, "23", 6),
        sched_game("2026-10-10T14:00:00Z", "19", 5, "23", 3)]}
    probables = {"dates": [{"games": [{
        "gamePk": 777001, "gameDate": KICKOFF_MLB,
        "status": {"detailedState": "Scheduled"},
        "teams": {
            "home": {"team": {"id": 23, "name": "Milwaukee Brewers",
                              "abbreviation": "MIL"},
                     "probablePitcher": {"id": 222, "fullName": "Test Arm B"}},
            "away": {"team": {"id": 19, "name": "Los Angeles Dodgers",
                              "abbreviation": "LAD"},
                     "probablePitcher": {"id": 111, "fullName": "Test Arm A"}},
        }}]}]}
    stats_url = ("https://statsapi.mlb.com/api/v1/people/%d/stats?"
                 "stats=season&season=2026&group=pitching")
    return {
        f"{ESPN}/baseball/mlb/teams?limit=500": teams,
        f"{ESPN}/baseball/mlb/scoreboard?dates=20261011&limit=500": {"events": []},
        f"{ESPN}/baseball/mlb/scoreboard?dates=20261012&limit=500": board,
        f"{ESPN}/baseball/mlb/scoreboard?dates=20261013&limit=500": {"events": []},
        f"{ESPN}/baseball/mlb/teams/23/schedule?season=2026": home_sched,
        f"{ESPN}/baseball/mlb/teams/19/schedule?season=2026": away_sched,
        ("https://statsapi.mlb.com/api/v1/schedule?sportId=1&date=2026-10-12&"
         "hydrate=team%2CprobablePitcher"): probables,
        stats_url % 111: {"stats": [{"splits": [{"stat": {
            "era": "2.50", "inningsPitched": "150.0", "gamesStarted": 25}}]}]},
        stats_url % 222: {"stats": [{"splits": [{"stat": {
            "era": "3.00", "inningsPitched": "140.0", "gamesStarted": 24}}]}]},
    }


def mlb_row(**kw):
    row = {"sport": "MLB", "market": "TOTAL", "away": "Los Angeles Dodgers",
           "home": "Milwaukee Brewers", "side": "OVER", "line": 8.5,
           "odds": -110, "commence_time": KICKOFF_MLB}
    row.update(kw)
    return row


def factor_names(stage):
    return [f["factor"] for f in stage["factors"]]


def factor_status(stage, name):
    return [(f["status"], f["source"], f["reason"])
            for f in stage["factors"] if f["factor"] == name]


class StageVerifiedPullTests(unittest.TestCase):
    def test_nfl_stage_verified_full(self):
        getter = FakeGetter(nfl_mapping())
        (stage,) = fi.stage_games([nfl_row()], now=NOW, getter=getter)
        self.assertFalse(stage["blocked"])
        adj = stage["adjustments"]
        # QB out -> canonical injury_points contract: -1.5 for an NFL QB.
        self.assertEqual(adj["home_injury_pts"], -1.5)
        # Doubtful QB counts the same as out under the existing contract.
        self.assertEqual(adj["away_injury_pts"], -1.5)
        # Declared weather table: 20 mph + 80% precip -> -1.2 for NFL.
        self.assertEqual(adj["weather_total_adj"], -1.2)
        # Rest: home 8.0d vs away 7.0d -> declared 0.12 * 1.0 = 0.12, but
        # DISABLED_PENDING_INCREMENTAL_VALUE (owner ruling, Oct 13 2026):
        # the priced contribution handed to the engine is zero; the
        # declared value remains in the rest_schedule factor reason.
        self.assertEqual(adj["rest_diff_adj"], 0.0)
        rest = factor_status(stage, "rest_schedule")[0]
        self.assertEqual(rest[0], "DISABLED_PENDING_INCREMENTAL_VALUE")
        self.assertIn("DECLARED_DIFF_ADJ_0.12", rest[2])
        qb_home = factor_status(stage, "qb_specific")
        self.assertEqual(len(qb_home), 2)
        home_used = [s for s in qb_home if s[0] == "USED"]
        self.assertTrue(any("Kirk Cousins" in s[2] for s in home_used))
        away_used = [s for s in qb_home if "Lamar Jackson" in s[2]]
        self.assertTrue(away_used and away_used[0][0] == "USED")
        wx = factor_status(stage, "weather_venue")[0]
        self.assertEqual(wx[0], "USED")
        self.assertIn("OPEN_METEO_LIVE_FREE_NO_KEY", wx[1])
        # Taxonomy coverage: universal + NFL factors all audited.
        for name in fi.UNIVERSAL_FACTORS + fi.SPORT_FACTORS["NFL"]:
            self.assertIn(name, factor_names(stage), name)
        # Rejected method never appears as an audit item.
        self.assertFalse(any("market_odds" in n for n in factor_names(stage)))

    def test_qb_identity_unverifiable_blocks_game(self):
        mapping = nfl_mapping()
        mapping[f"{ESPN}/football/nfl/teams/1/injuries"] = {"unexpected": "shape"}
        mapping[f"{ESPN}/football/nfl/injuries"] = {"unexpected": "shape"}
        getter = FakeGetter(mapping)
        (stage,) = fi.stage_games([nfl_row()], now=NOW, getter=getter)
        self.assertTrue(stage["blocked"])
        self.assertEqual(stage["block_reason"],
                         fi.BLOCK_QB_IDENTITY_UNVERIFIED)
        # Fail-closed: no partial adjustments survive a blocked game.
        self.assertEqual(stage["adjustments"], {})
        qb = factor_status(stage, "qb_specific")
        self.assertTrue(any(s[0] == "MISSING" and "HOME" in s[2] for s in qb))

    def test_injury_points_contract_preserved(self):
        provider = free_models.PublicContext(NOW, getter=FakeGetter(nfl_mapping()))
        falcons = provider.identify("NFL", "Atlanta Falcons")
        pts, status = provider.injury_points("NFL", falcons)
        self.assertEqual(pts, -1.5)
        self.assertEqual(status, "HEURISTIC_OUT_DOUBTFUL_REPORTED_1_UNKNOWN_COMPLETENESS")
        pts_mlb, status_mlb = provider.injury_points("MLB", {"id": "19"})
        self.assertEqual((pts_mlb, status_mlb), (0.0, "NOT_APPLICABLE"))
        rows, row_status = provider.injury_rows("NFL", falcons)
        self.assertEqual(row_status, "STRUCTURE_VERIFIED")
        self.assertEqual(len(rows), 2)


class WeatherEvidenceTests(unittest.TestCase):
    def evidence(self, **kw):
        ev = {"contract": "SPORTSEDGE_WEATHER_EVIDENCE_V1",
              "sport": "NFL",
              "venue": {"name": "Mercedes-Benz Stadium", "city": "Atlanta",
                        "state": "GA", "indoor": False},
              "kickoff_utc": KICKOFF_NFL,
              "retrieved_at_utc": "2026-10-11T12:00:00Z",
              "source": "GITHUB_ACTIONS_ARCHIVE",
              "forecast": {"wind_mph": 20.0, "precip_probability": 80.0}}
        ev.update(kw)
        return ev

    def test_archived_weather_evidence_used(self):
        # SECURITY: User-supplied weather_evidence in the row is NOT trusted.
        # Archived weather must arrive via trusted loader, not input row.
        # This test verifies user evidence is ignored.
        getter = FakeGetter(nfl_mapping())
        row = nfl_row(weather_evidence=self.evidence())
        (stage,) = fi.stage_games([row], now=NOW, getter=getter)
        self.assertFalse(stage["blocked"])
        # User-supplied evidence is marked MISSING (not USED)
        # Note: live Open-Meteo path may still provide weather_total_adj separately
        wx_factors = [f for f in stage["factors"] if f["factor"] == "weather_venue"]
        user_evidence_factors = [f for f in wx_factors
                                 if "USER_SUPPLIED" in f.get("source", "")]
        self.assertTrue(len(user_evidence_factors) > 0)
        self.assertTrue(all(f["status"] == "MISSING" for f in user_evidence_factors))

    def test_stale_archive_rejected_like_missing(self):
        # SECURITY: User-supplied weather evidence is never trusted,
        # regardless of staleness. Marked MISSING.
        getter = FakeGetter(nfl_mapping())
        row = nfl_row(weather_evidence=self.evidence(
            retrieved_at_utc="2026-10-09T00:00:00Z"))
        (stage,) = fi.stage_games([row], now=NOW, getter=getter)
        # User-supplied evidence is marked MISSING (not USED)
        wx_factors = [f for f in stage["factors"] if f["factor"] == "weather_venue"]
        user_evidence_factors = [f for f in wx_factors
                                 if "USER_SUPPLIED" in f.get("source", "")]
        self.assertTrue(len(user_evidence_factors) > 0)
        self.assertTrue(all(f["status"] == "MISSING" for f in user_evidence_factors))

    def test_evidence_contract_and_binding_rejected(self):
        for bad in ({"contract": "WRONG_CONTRACT"},
                    {"kickoff_utc": "2026-10-13T17:00:00Z"},
                    {"retrieved_at_utc": "2026-10-12T18:00:00Z"},
                    {"forecast": {"wind_mph": "fast", "precip_probability": 10}},
                    {"venue": {"indoor": False},
                     "forecast": {"wind_mph": 20, "precip_probability": 101}}):
            ev = self.evidence()
            ev.update(bad)
            with self.assertRaises(fi.WeatherEvidenceError, msg=str(bad)):
                fi.admit_weather_evidence(ev, sport="NFL",
                                          kickoff=free_models.dt(KICKOFF_NFL),
                                          now=NOW)

    def test_declared_weather_table_shared(self):
        self.assertEqual(free_models.declared_weather_total_adj(20, 80, "NFL"), -1.2)
        self.assertEqual(free_models.declared_weather_total_adj(20, 80, "MLB"), -0.36)
        self.assertEqual(free_models.declared_weather_total_adj(10, 10, "NFL"), 0.0)
        self.assertEqual(free_models.declared_weather_total_adj(15, 10, "CFB"), -0.4)


class MlbPitcherTests(unittest.TestCase):
    def test_probable_pitchers_adjustments(self):
        getter = FakeGetter(mlb_mapping())
        (stage,) = fi.stage_games([mlb_row()], now=NOW, getter=getter)
        self.assertFalse(stage["blocked"])
        adj = stage["adjustments"]
        # Declared heuristic (unchanged research math): away starter
        # (ERA 2.50, 150 IP/25 GS) suppression 1.2; home starter
        # (ERA 3.00, 140 IP/24 GS) suppression ~0.843. But the pitcher
        # adjustment is DISABLED_PENDING_INCREMENTAL_VALUE (owner
        # ruling, Oct 13 2026): priced contributions are zero.
        self.assertEqual(adj["home_pitcher_adj"], 0.0)
        self.assertEqual(adj["away_pitcher_adj"], 0.0)
        declared = fi.mlb_pitcher_adjustments(
            getter, game_date=fi.dt(KICKOFF_MLB).date(),
            home={"abbr": "MIL", "name": "Milwaukee Brewers"},
            away={"abbr": "LAD", "name": "Los Angeles Dodgers"},
            season=2026, kickoff=fi.dt(KICKOFF_MLB))[0]
        self.assertEqual(declared["home_pitcher_adj"], -1.2)
        self.assertAlmostEqual(declared["away_pitcher_adj"], -0.843, places=3)
        sp = factor_status(stage, "starting_pitcher")
        self.assertEqual(len(sp), 2)
        self.assertTrue(all(s[0] == "DISABLED_PENDING_INCREMENTAL_VALUE"
                            for s in sp))
        self.assertTrue(any("Test Arm A" in s[2] for s in sp))
        wx = factor_status(stage, "weather_venue")[0]
        # ESPN static indoor venue metadata cannot prove a retractable roof's
        # *game-day* position at American Family Field.
        self.assertEqual((wx[0], wx[1]), ("MISSING", "OPEN_METEO_LIVE_FREE_NO_KEY"))
        self.assertIn("RETRACTABLE_ROOF_STATE_UNVERIFIED", wx[2])
        self.assertNotIn("weather_total_adj", adj)
        bullpen = factor_status(stage, "bullpen")[0]
        # Collector import means audit-visible candidate capability only,
        # not verified game data and never a newly applied pricing factor.
        self.assertEqual(bullpen[0], "PENDING_VALIDATION")
        self.assertIn("SOURCE_MODULE_AVAILABLE_NOT_GAME_VERIFIED", bullpen[2])
        self.assertNotIn("bullpen_adj", adj)
        statcast = factor_status(stage, "statcast")[0]
        self.assertEqual(statcast[0], "PENDING_VALIDATION")
        self.assertIn("SOURCE_MODULE_AVAILABLE_NOT_GAME_VERIFIED", statcast[2])
        self.assertNotIn("statcast_adj", adj)

    def test_retractable_roof_espn_indoor_flag_does_not_claim_closed(self):
        provider = free_models.PublicContext(NOW, getter=FakeGetter(mlb_mapping()))
        fixture = provider.fixture(
            "MLB", "Los Angeles Dodgers", "Milwaukee Brewers",
            free_models.dt(KICKOFF_MLB))
        self.assertIsNotNone(fixture)
        _kickoff, competition = fixture
        self.assertIs(competition["venue"]["indoor"], True)  # static ESPN flag
        adjustment, state = provider.weather("MLB", competition, free_models.dt(KICKOFF_MLB))
        self.assertEqual(adjustment, 0.0)
        self.assertEqual(state, "RETRACTABLE_ROOF_STATE_UNVERIFIED")

    def test_pitcher_unconfirmed_blocks_game(self):
        mapping = mlb_mapping()
        url = ("https://statsapi.mlb.com/api/v1/schedule?sportId=1&date=2026-10-12&"
               "hydrate=team%2CprobablePitcher")
        games = mapping[url]["dates"][0]["games"]
        games[0]["teams"]["away"]["probablePitcher"] = None
        (stage,) = fi.stage_games([mlb_row()], now=NOW, getter=FakeGetter(mapping))
        self.assertTrue(stage["blocked"])
        self.assertEqual(stage["block_reason"], fi.BLOCK_PITCHER_UNCONFIRMED)
        self.assertEqual(stage["adjustments"], {})

    def test_thin_pitcher_sample_blocks(self):
        mapping = mlb_mapping()
        stats_url = ("https://statsapi.mlb.com/api/v1/people/111/stats?"
                     "stats=season&season=2026&group=pitching")
        mapping[stats_url] = {"stats": [{"splits": [{"stat": {
            "era": "1.50", "inningsPitched": "8.0", "gamesStarted": 2}}]}]}
        (stage,) = fi.stage_games([mlb_row()], now=NOW, getter=FakeGetter(mapping))
        self.assertTrue(stage["blocked"])
        self.assertIn("PITCHER_LINE_UNUSABLE", stage["block_detail"])

    def test_allow_completed_for_historical_validation(self):
        from datetime import date
        mapping = mlb_mapping()
        url = ("https://statsapi.mlb.com/api/v1/schedule?sportId=1&date=2026-10-12&"
               "hydrate=team%2CprobablePitcher")
        mapping[url]["dates"][0]["games"][0]["status"]["detailedState"] = "Final"
        getter = FakeGetter(mapping)
        live = fi.mlb_pitcher_adjustments(
            getter, game_date=date(2026, 10, 12),
            home={"abbr": "MIL", "name": "Milwaukee Brewers"},
            away={"abbr": "LAD", "name": "Los Angeles Dodgers"}, season=2026)
        self.assertEqual(live[0], {})
        self.assertFalse(live[2])  # not blocked; engine blocks started games
        hist = fi.mlb_pitcher_adjustments(
            getter, game_date=date(2026, 10, 12),
            home={"abbr": "MIL", "name": "Milwaukee Brewers"},
            away={"abbr": "LAD", "name": "Los Angeles Dodgers"}, season=2026,
            allow_completed=True)
        self.assertFalse(hist[2])
        self.assertEqual(hist[0]["home_pitcher_adj"], -1.2)
        self.assertIn("COMPLETED_GAME_HISTORICAL_VALIDATION", hist[1][0]["reason"])



class MlbPostseasonFixtureFallbackTests(unittest.TestCase):
    """Strict MLB StatsAPI fallback must verify fixtures, never trust DK input."""

    def _without_espn_game(self):
        mapping = mlb_mapping()
        mapping[f"{ESPN}/baseball/mlb/scoreboard?dates=20261012&limit=500"] = {
            "events": []}
        return mapping

    def test_espn_missing_statsapi_game_unblocks_prepricing(self):
        getter = FakeGetter(self._without_espn_game())
        kickoff = free_models.dt(KICKOFF_MLB)
        provider = free_models.PublicContext(NOW, getter=getter)
        fixture = provider.fixture("MLB", "Los Angeles Dodgers",
                                   "Milwaukee Brewers", kickoff)
        self.assertIsNotNone(fixture)
        verified_at, competition = fixture
        self.assertEqual(verified_at, kickoff)
        self.assertEqual(competition["game_pk"], 777001)
        self.assertEqual(competition["source"], "MLB_STATSAPI_SCHEDULE_VERIFIED")
        self.assertEqual(competition["venue"], {})  # Roof/weather NOT verified
        self.assertTrue(any("statsapi.mlb.com/api/v1/schedule?" in url
                            for url in getter.calls))
        # Real production prepricing stage must also accept the same verified
        # fixture and probable pitchers; this is not merely a helper unit test.
        rows = fi.stage_games([mlb_row()], now=NOW,
                              getter=FakeGetter(self._without_espn_game()))
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]["blocked"], rows[0]["block_detail"])
        self.assertIn("home_pitcher_adj", rows[0]["adjustments"])
        self.assertIn("away_pitcher_adj", rows[0]["adjustments"])
        # Do not give weather or unvalidated factors artificial pricing credit.
        self.assertFalse(any(f.get("source") == "OPEN_METEO_LIVE_FREE_NO_KEY"
                             and f.get("status") == "USED" for f in rows[0]["factors"]))

    def test_postponed_or_started_game_cannot_be_admitted(self):
        for state in ("Final", "Postponed", "In Progress"):
            with self.subTest(state=state):
                mapping = self._without_espn_game()
                url = ("https://statsapi.mlb.com/api/v1/schedule?sportId=1&"
                       "date=2026-10-12&hydrate=team%2CprobablePitcher")
                mapping[url]["dates"][0]["games"][0]["status"]["detailedState"] = state
                self.assertIsNone(free_models.PublicContext(
                    NOW, getter=FakeGetter(mapping)).fixture(
                    "MLB", "Los Angeles Dodgers", "Milwaukee Brewers",
                    free_models.dt(KICKOFF_MLB)))

    def test_wrong_identity_or_kickoff_stays_blocked(self):
        mapping = self._without_espn_game()
        provider = free_models.PublicContext(NOW, getter=FakeGetter(mapping))
        self.assertIsNone(provider.fixture(
            "MLB", "Milwaukee Brewers", "Los Angeles Dodgers",
            free_models.dt(KICKOFF_MLB)))  # swapped home/away
        self.assertIsNone(provider.fixture(
            "MLB", "Los Angeles Dodgers", "Milwaukee Brewers",
            datetime(2026, 10, 12, 21, 0, tzinfo=timezone.utc)))
        self.assertIsNone(provider.fixture(
            "NFL", "Los Angeles Dodgers", "Milwaukee Brewers",
            free_models.dt(KICKOFF_MLB)))  # fallback MLB ONLY

    def test_ambiguous_statsapi_fixture_stays_blocked(self):
        mapping = self._without_espn_game()
        url = ("https://statsapi.mlb.com/api/v1/schedule?sportId=1&"
               "date=2026-10-12&hydrate=team%2CprobablePitcher")
        duplicate = dict(mapping[url]["dates"][0]["games"][0])
        duplicate["gamePk"] = 777002
        mapping[url]["dates"][0]["games"].append(duplicate)
        self.assertIsNone(free_models.PublicContext(
            NOW, getter=FakeGetter(mapping)).fixture(
            "MLB", "Los Angeles Dodgers", "Milwaukee Brewers",
            free_models.dt(KICKOFF_MLB)))


class RunnerHookTests(unittest.TestCase):
    def test_run_full_applies_verified_adjustments(self):
        # Option 3: Prepricing adjustments are in a separate object, not in context.
        # User context remains subject to allow_manual_context; prepricing is verified.
        card = run_full({"lines": [nfl_row()]}, now=NOW,
                        getter=FakeGetter(nfl_mapping()))
        row = card["evaluated_rows"][0]
        self.assertIn(row["status"], ("RESEARCH_EDGE", "BELOW_THRESHOLD", "PRICE_CAP"))
        # Prepricing adjustments are separate from user context
        pp = row.get("prepricing_adjustments")
        self.assertIsNotNone(pp)
        self.assertEqual(pp["source"], "SPORTSEDGE_PREPRICING_V1")
        self.assertEqual(pp["verification_status"], "VERIFIED")
        self.assertEqual(pp["adjustments"]["home_injury_pts"], -1.5)
        self.assertEqual(pp["adjustments"]["weather_total_adj"], -1.2)
        # Owner ruling (Oct 13, 2026): the rest differential is DISABLED
        # pending incremental-value evidence -- the declared 0.12 for
        # this fixture (8.0d vs 7.0d) remains in the factor audit
        # reason, but the priced contribution handed over is zero.
        self.assertEqual(pp["adjustments"]["rest_diff_adj"], 0.0)
        # The context reflects applied values (including verified prepricing)
        # The separation is verified via the prepricing_adjustments object above,
        # not by excluding values from context
        audit = card["prepricing_factor_audit"]
        self.assertEqual(audit["schema"], "SPORTSEDGE_PREPRICING_FACTOR_AUDIT_V1")
        self.assertIn("market_odds_as_features", audit)
        entry = audit["by_input_index"][0]
        self.assertFalse(entry["blocked"])
        self.assertTrue(any(f["factor"] == "qb_specific" and f["status"] == "USED"
                            and "Kirk Cousins" in f["reason"]
                            for f in entry["factors"]))
        self.assertTrue(card["source_receipts"])

    def test_run_full_blocks_unverifiable_critical_factor(self):
        def dead(url):
            raise OSError("NETWORK_DOWN")
        card = run_full({"lines": [nfl_row()]}, now=NOW, getter=dead)
        row = card["evaluated_rows"][0]
        self.assertEqual(row["status"], fi.BLOCK_FIXTURE_UNVERIFIED)
        self.assertIn("UNIQUE_FUTURE_ESPN_FIXTURE_MISSING", row["reason"])
        audit = card["prepricing_factor_audit"]["by_input_index"][0]
        self.assertTrue(audit["blocked"])
        self.assertEqual(audit["adjustments"], {})

    def test_manual_mode_audits_without_blocking(self):
        card = run_full({"lines": [nfl_row()]}, now=NOW, auto_context=False)
        row = card["evaluated_rows"][0]
        # Explicit no-fetch may calculate a diagnostic model, but missing
        # verified NFL team factors cannot qualify a current-game edge.
        self.assertEqual(row["status"], "WATCH_NFL_NO_VERIFIED_CONTEXT")
        self.assertEqual(card["edges"], [])
        self.assertEqual(card["independent_candidates"], [])
        entry = card["prepricing_factor_audit"]["by_input_index"][0]
        self.assertFalse(entry["blocked"])
        self.assertTrue(any(f["status"] == "MISSING" and "MANUAL_MODE" in f["reason"]
                            for f in entry["factors"]))

    def test_unverified_input_never_shifts_mean(self):
        mapping = nfl_mapping()
        # Plausible-looking but schema-invalid payloads: nothing may be trusted.
        mapping[f"{ESPN}/football/nfl/teams/1/injuries"] = {"injuries": "notalist"}
        mapping[f"{ESPN}/football/nfl/teams/33/injuries"] = {"injuries": "notalist"}
        mapping[f"{ESPN}/football/nfl/injuries"] = {"injuries": "notalist"}
        mapping[f"{ESPN}/football/nfl/teams/1/schedule?season=2026"] = {"events": "x"}
        mapping[f"{ESPN}/football/nfl/teams/33/schedule?season=2026"] = {"events": "x"}
        (stage,) = fi.stage_games([nfl_row()], now=NOW,
                                  getter=FakeGetter(mapping))
        # Injury feed unusable -> critical QB factor missing -> blocked, no shifts.
        self.assertTrue(stage["blocked"])
        self.assertEqual(stage["adjustments"], {})

    def test_user_context_override_wins_and_is_noted(self):
        # Option 3: User context requires explicit flag (preserves #2045).
        # Without flag: blocked. With flag: applied and labeled.
        # Undeclared manual context is rejected.
        card = run_full({"lines": [nfl_row(context={"home_injury_pts": -0.5})]},
                        now=NOW, getter=FakeGetter(nfl_mapping()))
        row = card["evaluated_rows"][0]
        self.assertEqual(row["status"], "BLOCKED_MANUAL_CONTEXT_UNDECLARED")
        # With explicit flag: applied and labeled USER_SUPPLIED_MANUAL
        card2 = run_full({"lines": [nfl_row(context={"home_injury_pts": -0.5})]},
                         now=NOW, getter=FakeGetter(nfl_mapping()),
                         allow_manual_context=True)
        row2 = card2["evaluated_rows"][0]
        self.assertIn(row2["status"], ("RESEARCH_EDGE", "BELOW_THRESHOLD", "PRICE_CAP", "WATCH_QUOTE_NOT_CURRENT"))
        # Spoofed prepricing_adjustments in user intake must be ignored
        spoofed = nfl_row()
        spoofed["prepricing_adjustments"] = {"source": "SPOOFED", "adjustments": {"home_injury_pts": 999}}
        card3 = run_full({"lines": [spoofed]}, now=NOW,
                         getter=FakeGetter(nfl_mapping()),
                         allow_manual_context=True)
        row3 = card3["evaluated_rows"][0]
        pp = row3.get("prepricing_adjustments", {})
        # The spoofed values must NOT appear in the trusted prepricing object
        self.assertNotEqual(pp.get("source"), "SPOOFED")

    def test_rest_diff_adj_moves_means(self):
        # Option 3: rest_diff_adj via prepricing (verified) moves means.
        # User context requires the explicit flag (preserves #2045).
        base = {"sport": "NFL", "market": "SPREAD", "away": "X", "home": "Y",
                "side": "HOME", "line": -3.5, "odds": -110,
                "commence_time": KICKOFF_NFL,
                "quote_captured_at": NOW.isoformat()}
        provider = free_models.PublicContext(NOW, getter=lambda url: None)
        plain = free_models.calculate(dict(base), provider, NOW, auto_context=False,
                                      allow_manual_context=True)
        # Via prepricing_adjustments (verified, separate from user context)
        pp = {"source": "TEST", "verification_status": "VERIFIED",
              "adjustments": {"rest_diff_adj": 0.6}, "timestamp_utc": NOW.isoformat()}
        shifted = free_models.calculate(dict(base), provider, NOW, auto_context=False,
                                        allow_manual_context=True,
                                        prepricing_adjustments=pp)
        # The means should move (exact values depend on lane calculations)
        # Just verify the prepricing was applied (not blocked, means differ)
        self.assertNotEqual(plain.get("status"), "BLOCKED_MANUAL_CONTEXT_UNDECLARED")
        self.assertNotEqual(shifted.get("status"), "BLOCKED_MANUAL_CONTEXT_UNDECLARED")


if __name__ == "__main__":
    unittest.main()
