"""Tests for sportsedge.backtest.market_baseline. No network.

Fixtures under tests/fixtures/backtest/baseline/:
- archive/...ndjson: synthetic rows in the exact CLOSING_LINE_ARCHIVE_ROW_V2
  schema (clearly labeled TEST_FIXTURE; no real archive data exists yet).
- nflverse_sample.csv / sbr_mlb_sample.json / nba_lines_sample.csv: REAL
  recorded rows extracted once from the evaluated open datasets.
"""
import json
import math
import unittest
from pathlib import Path

from sportsedge.backtest import market_baseline as mb
from sportsedge.backtest import runner, splits

FIX = Path(__file__).parent / "fixtures" / "backtest" / "baseline"


def approx(a, b, tol=1e-9):
    return abs(a - b) <= tol


def novig(home_american, away_american):
    hd = mb.american_to_decimal(home_american)
    ad = mb.american_to_decimal(away_american)
    ih, ia = 1.0 / hd, 1.0 / ad
    return ih / (ih + ia), ia / (ih + ia)


class TestMath(unittest.TestCase):
    def test_american_to_decimal(self):
        self.assertTrue(approx(mb.american_to_decimal(-110), 1.9090909090909092))
        self.assertTrue(approx(mb.american_to_decimal(150), 2.5))
        self.assertTrue(approx(mb.american_to_decimal(100), 2.0))
        for bad in (0, 50, -50, "abc", None, float("nan")):
            with self.assertRaises(mb.BaselineError):
                mb.american_to_decimal(bad)

    def test_no_vig(self):
        nv = mb.no_vig_probs({"home": 1.9090909090909092, "away": 1.9090909090909092})
        self.assertTrue(approx(nv["home"], 0.5))
        self.assertTrue(approx(nv["away"], 0.5))
        with self.assertRaises(mb.BaselineError):
            mb.no_vig_probs({"home": 1.0, "away": 2.0})

    def test_fixture_id(self):
        fix = mb.parse_fixture_id("nfl:2024-09-05:Baltimore Ravens:Kansas City Chiefs")
        self.assertEqual(fix["sport"], "nfl")
        self.assertEqual(fix["date"], "2024-09-05")
        self.assertEqual(fix["archive_key"], "americanfootball_nfl")
        for bad in ("nfl:2024-09-05:KC", "nhl:2024-09-05:A:B",
                    "nfl:2024-13-05:A:B", "nfl:2024-09-05::KC"):
            with self.assertRaises(mb.BaselineError):
                mb.parse_fixture_id(bad)

    def test_canonical_team_aliases(self):
        self.assertEqual(mb.canonical_team("Cleveland Indians"),
                         mb.canonical_team("Cleveland Guardians"))
        self.assertEqual(mb.canonical_team("Athletics Athletics"),
                         mb.canonical_team("Oakland Athletics"))
        self.assertEqual(mb.canonical_team("St. Louis Cardinals"), "stlouiscardinals")


class TestClosingLineArchive(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = mb.ClosingLineArchive(FIX).load()

    def test_stats(self):
        self.assertEqual(self.src.stats["files"], 1)
        # 12 rows read: 1 post-commence + 2 decision-window rows skipped;
        # game2's one-sided market is dropped at quote selection.
        self.assertEqual(self.src.stats["rows_read"], 12)
        self.assertEqual(self.src.stats["rows_skipped"], 3)

    def test_ml_prefers_close_window(self):
        # close window: -148/124 ; t0_prestart: -150/130 -> must use close
        p = self.src.lookup("nfl:2024-09-08:Baltimore Ravens:Kansas City Chiefs",
                            "ML", "HOME")
        exp, _ = novig(-148, 124)
        self.assertTrue(approx(p, exp))
        p2 = self.src.lookup("nfl:2024-09-08:Baltimore Ravens:Kansas City Chiefs",
                             "ML", "AWAY")
        _, exp2 = novig(-148, 124)
        self.assertTrue(approx(p2, exp2))

    def test_spread_exact_line_match(self):
        fid = "nfl:2024-09-08:Baltimore Ravens:Kansas City Chiefs"
        p = self.src.lookup(fid, "SPREAD", "HOME", line=-3.0)
        exp, _ = novig(-118, -102)
        self.assertTrue(approx(p, exp))
        # line mismatch -> MISSING, never invented
        self.assertIsNone(self.src.lookup(fid, "SPREAD", "HOME", line=-3.5))
        self.assertIsNone(self.src.lookup(fid, "SPREAD", "HOME", line=None))

    def test_total(self):
        fid = "nfl:2024-09-08:Baltimore Ravens:Kansas City Chiefs"
        self.assertTrue(approx(self.src.lookup(fid, "TOTAL", "OVER", line=46.0), 0.5))
        self.assertTrue(approx(self.src.lookup(fid, "TOTAL", "UNDER", line=46.0), 0.5))
        self.assertIsNone(self.src.lookup(fid, "TOTAL", "OVER", line=47.0))

    def test_ml_line_must_be_none(self):
        fid = "nfl:2024-09-08:Baltimore Ravens:Kansas City Chiefs"
        self.assertIsNone(self.src.lookup(fid, "ML", "HOME", line=-3.0))

    def test_missing_cases(self):
        # one-sided game archived -> market dropped
        self.assertIsNone(self.src.lookup(
            "nfl:2024-09-08:Arizona Cardinals:Buffalo Bills", "ML", "HOME"))
        # unknown game / bad fixture / unknown market
        self.assertIsNone(self.src.lookup(
            "nfl:2024-09-08:Chicago Bears:Detroit Lions", "ML", "HOME"))
        self.assertIsNone(self.src.lookup("bogus", "ML", "HOME"))
        self.assertIsNone(self.src.lookup(
            "nfl:2024-09-08:Baltimore Ravens:Kansas City Chiefs", "PUCK", "HOME"))
        # CFB sport parses but has no archive rows in fixture
        self.assertIsNone(self.src.lookup(
            "cfb:2024-09-08:Georgia Bulldogs:Alabama Crimson Tide", "ML", "HOME"))

    def test_empty_archive_is_missing(self):
        empty = mb.ClosingLineArchive(FIX / "does-not-exist").load()
        self.assertIsNone(empty.lookup(
            "nfl:2024-09-08:Baltimore Ravens:Kansas City Chiefs", "ML", "HOME"))

    def test_explain(self):
        reason = self.src.explain(
            "nfl:2024-09-08:Chicago Bears:Detroit Lions", "ML", "HOME")
        self.assertIn("closing_line_archive", reason)
        ok = self.src.explain(
            "nfl:2024-09-08:Baltimore Ravens:Kansas City Chiefs", "ML", "HOME")
        self.assertIn("AVAILABLE", ok)


class TestNflverse(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = mb.NflverseBaseline(FIX / "nflverse_sample.csv").load()

    def test_stats(self):
        self.assertEqual(self.src.stats["rows_accepted"], 2)

    def test_super_bowl_lix(self):
        # Recorded: spread_line=-1.5 (AWAY/KC favored), home -115 / away -105,
        # total_line=48.5 (over -115 / under -105), ML home 100 / away -120.
        fid = "nfl:2025-02-09:Kansas City Chiefs:Philadelphia Eagles"
        p = self.src.lookup(fid, "ML", "AWAY")
        _, exp = novig(100, -120)
        self.assertTrue(approx(p, exp))
        # harness line is from the selection's perspective: away close -1.5
        p = self.src.lookup(fid, "SPREAD", "AWAY", line=-1.5)
        _, exp_s = novig(-115, -105)
        self.assertTrue(approx(p, exp_s))
        p = self.src.lookup(fid, "SPREAD", "HOME", line=1.5)
        exp_h, _ = novig(-115, -105)
        self.assertTrue(approx(p, exp_h))
        self.assertIsNone(self.src.lookup(fid, "SPREAD", "HOME", line=-1.5))
        # total_line=48.5
        p = self.src.lookup(fid, "TOTAL", "OVER", line=48.5)
        exp_t, _ = novig(-115, -105)
        self.assertTrue(approx(p, exp_t))

    def test_2024_opener(self):
        # Recorded: spread_line=3 (HOME/KC favored), home -102 / away -118,
        # total 46 (-110/-110), ML home -148 / away 124.
        fid = "nfl:2024-09-05:Baltimore Ravens:Kansas City Chiefs"
        p = self.src.lookup(fid, "SPREAD", "HOME", line=-3.0)
        exp, _ = novig(-102, -118)
        self.assertTrue(approx(p, exp))
        p = self.src.lookup(fid, "SPREAD", "AWAY", line=3.0)
        _, exp_a = novig(-102, -118)
        self.assertTrue(approx(p, exp_a))
        p = self.src.lookup(fid, "ML", "HOME")
        exp, _ = novig(-148, 124)
        self.assertTrue(approx(p, exp))

    def test_wrong_sport_missing(self):
        self.assertIsNone(self.src.lookup(
            "mlb:2024-10-25:New York Yankees:Los Angeles Dodgers", "ML", "HOME"))


class TestSbrMlb(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = mb.SbrMlbBaseline(FIX / "sbr_mlb_sample.json").load()

    def test_world_series_g1(self):
        fid = "mlb:2024-10-25:New York Yankees:Los Angeles Dodgers"
        # DK current: home -125 / away 105
        p = self.src.lookup(fid, "ML", "HOME")
        exp, _ = novig(-125, 105)
        self.assertTrue(approx(p, exp))
        # DK spread: home -1.5 @ 160
        p = self.src.lookup(fid, "SPREAD", "HOME", line=-1.5)
        exp, _ = novig(160, -192)
        self.assertTrue(approx(p, exp))
        self.assertIsNone(self.src.lookup(fid, "SPREAD", "HOME", line=-2.5))
        # DK total 9: over 100 / under -120
        p = self.src.lookup(fid, "TOTAL", "OVER", line=9)
        exp, _ = novig(100, -120)
        self.assertTrue(approx(p, exp))

    def test_2021_opener(self):
        fid = "mlb:2021-04-01:Toronto Blue Jays:New York Yankees"
        p = self.src.lookup(fid, "ML", "AWAY")
        _, exp = novig(-195, 165)
        self.assertTrue(approx(p, exp))

    def test_median_fallback_in_decimal_space(self):
        # No DraftKings in this synthetic book list -> median of decimals.
        quote = self.src._pick_quote([
            {"sportsbook": "fanduel",
             "currentLine": {"homeOdds": -110, "awayOdds": -110}},
            {"sportsbook": "caesars",
             "currentLine": {"homeOdds": -120, "awayOdds": 100}},
        ], "h2h", ("mlb", "2024-10-25", "newyorkyankees", "losangelesdodgers"))
        self.assertTrue(quote["book"].startswith("median_of_2_books"))
        # median of decimals, NOT median of American odds
        decs = sorted([mb.american_to_decimal(-110), mb.american_to_decimal(-120)])
        self.assertTrue(approx(quote["_dec_h"], (decs[0] + decs[1]) / 2.0))


class TestNbaLines(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = mb.NbaLinesBaseline(FIX / "nba_lines_sample.csv").load()

    def test_finals_2025_g1(self):
        # Recorded: ML home 1.20 / away 4.85 (sbr_close). Spreads/totals in
        # this file carry lines only (no closing juice) -> MISSING by design.
        fid = "nba:2025-06-05:Indiana Pacers:Oklahoma City Thunder"
        p = self.src.lookup(fid, "ML", "HOME")
        ih, ia = 1 / 1.2, 1 / 4.85
        self.assertTrue(approx(p, ih / (ih + ia)))
        p = self.src.lookup(fid, "ML", "AWAY")
        self.assertTrue(approx(p, ia / (ih + ia)))
        self.assertIsNone(self.src.lookup(fid, "SPREAD", "HOME", line=-10.0))
        self.assertIsNone(self.src.lookup(fid, "TOTAL", "OVER", line=229.5))

    def test_finals_2024_g1(self):
        fid = "nba:2024-06-06:Dallas Mavericks:Boston Celtics"
        # moneyline absent on this row -> MISSING (fail closed)
        self.assertIsNone(self.src.lookup(fid, "ML", "HOME"))
        self.assertIsNone(self.src.lookup(fid, "SPREAD", "HOME", line=-6.5))
        self.assertIsNone(self.src.lookup(fid, "TOTAL", "UNDER", line=217.5))


class TestComposite(unittest.TestCase):
    def test_precedence_archive_over_nflverse(self):
        archive = mb.ClosingLineArchive(FIX).load()
        nflverse = mb.NflverseBaseline(FIX / "nflverse_sample.csv").load()
        comp = mb.CompositeMarketBaseline([archive, nflverse])
        fid = "nfl:2024-09-08:Baltimore Ravens:Kansas City Chiefs"
        # archive answers (DK test fixture); nflverse has no 2024-09-08 row
        prov = comp.provenance(fid, "ML", "HOME")
        self.assertEqual(prov["source"], "closing_line_archive")
        # game only in nflverse -> falls through
        fid2 = "nfl:2025-02-09:Kansas City Chiefs:Philadelphia Eagles"
        prov2 = comp.provenance(fid2, "ML", "AWAY")
        self.assertEqual(prov2["source"], "nflverse")
        # nowhere -> None with reasons
        prov3 = comp.provenance("nfl:2024-09-08:Chicago Bears:Detroit Lions",
                                "ML", "HOME")
        self.assertIsNone(prov3["source"])
        self.assertEqual(len(prov3["reasons"]), 2)

    def test_as_callable_signature(self):
        comp = mb.CompositeMarketBaseline(
            [mb.NflverseBaseline(FIX / "nflverse_sample.csv").load()])
        fn = comp.as_callable()
        p = fn("nfl:2025-02-09:Kansas City Chiefs:Philadelphia Eagles",
               "TOTAL", "OVER", 48.5)
        self.assertTrue(0.0 < p < 1.0)

    def test_build_default_baseline(self):
        comp = mb.build_default_baseline(
            archive_data_dir=FIX,
            nflverse_csv=FIX / "nflverse_sample.csv",
            mlb_json=FIX / "sbr_mlb_sample.json",
            nba_csv=FIX / "nba_lines_sample.csv")
        self.assertEqual(len(comp.sources), 4)
        empty = mb.build_default_baseline()
        self.assertIsNone(empty.lookup("nfl:2025-02-09:A:B", "ML", "HOME"))
        cov = comp.coverage()
        self.assertEqual([c["source"] for c in cov],
                         ["closing_line_archive", "nflverse", "sbr_mlb", "nba_lines"])


class TestRunnerWiring(unittest.TestCase):
    """The composite plugs into runner.run_backtest's market_baseline slot."""

    def _fixtures(self):
        games = [
            ("nfl:2024-09-05:Baltimore Ravens:Kansas City Chiefs",
             "2024-09-05T23:20:00+00:00", 27, 20),   # KC win
            ("nfl:2025-02-09:Kansas City Chiefs:Philadelphia Eagles",
             "2025-02-09T23:30:00+00:00", 40, 22),   # PHI win
        ]
        fixtures = []
        for fid, kickoff, hs, aws in games:
            as_of = kickoff[:11] + "%02d%s" % (
                int(kickoff[11:13]) - 2, kickoff[13:])
            fixtures.append({
                "fixture_id": fid, "kickoff": kickoff, "as_of": as_of,
                "_hs": hs, "_aws": aws,
            })
        return fixtures

    def test_baseline_leg_populates(self):
        comp = mb.build_default_baseline(
            nflverse_csv=FIX / "nflverse_sample.csv")
        fixtures = self._fixtures()

        def price_fn(model, fixture, as_of, train):
            return [{"market": "ML", "selection": "HOME", "model_p": 0.6}]

        def settle_fn(fixture, market, selection, line):
            hs, aws = fixture["_hs"], fixture["_aws"]
            return 1.0 if hs > aws else 0.0

        sp = [splits.fixed_split(fixtures, "2025-01-01T00:00:00+00:00")]
        result = runner.run_backtest(
            fixtures=fixtures, splits=sp, models=["m"],
            price_fn=price_fn, settle_fn=settle_fn,
            market_baseline=comp.as_callable())
        self.assertEqual(result["baseline"]["status"], "AVAILABLE")
        # Only the test fixture (SB LIX) is priced; the opener is train.
        self.assertEqual(len(result["baseline"]["records"]), 1)
        comp_res = runner.compare_models(result)
        self.assertEqual(comp_res["baseline"]["status"], "AVAILABLE")
        self.assertGreater(comp_res["baseline"]["summary"]["n"], 0)

    def test_baseline_missing_without_source(self):
        fixtures = self._fixtures()

        def price_fn(model, fixture, as_of, train):
            return [{"market": "ML", "selection": "HOME", "model_p": 0.6}]

        def settle_fn(fixture, market, selection, line):
            return 1.0

        sp = [splits.fixed_split(fixtures, "2025-01-01T00:00:00+00:00")]
        result = runner.run_backtest(
            fixtures=fixtures, splits=sp, models=["m"],
            price_fn=price_fn, settle_fn=settle_fn,
            market_baseline=None)
        self.assertEqual(result["baseline"]["status"], "MISSING")


if __name__ == "__main__":
    unittest.main()


ATT = FIX / "adversarial"


class TestAdversarialRedTeam(unittest.TestCase):
    """Isaac's standing directive: try to break it. Each attack below must
    fail closed with an explicit BASELINE_* code — a corrupted baseline
    silently feeding the harness is worse than MISSING."""

    # -- attack 1: misaligned timestamps --------------------------------
    def test_archive_row_date_must_match_partition_file(self):
        src = mb.ClosingLineArchive(ATT).load()
        reasons = src.stats["skip_reasons"]
        self.assertIn("BASELINE_ARCHIVE_DATE_MISMATCH", reasons)
        # the bad-date game is MISSING, not joined to the wrong date
        self.assertIsNone(src.lookup(
            "nfl:2024-09-10:Buffalo Bills:Arizona Cardinals", "ML", "HOME"))

    def test_nflverse_season_gameday_mismatch(self):
        src = mb.NflverseBaseline(ATT / "nflverse_attack.csv").load()
        self.assertIn("BASELINE_NFLVERSE_SEASON_MISMATCH",
                      src.stats["skip_reasons"])
        # the 2020-stamped row never loads
        self.assertIsNone(src.lookup(
            "nfl:2024-09-08:Green Bay Packers:Chicago Bears", "ML", "HOME"))

    def test_mlb_date_key_must_match_start(self):
        src = mb.SbrMlbBaseline(ATT / "sbr_mlb_attack.json").load()
        self.assertIn("BASELINE_MLB_DATE_MISMATCH", src.stats["skip_reasons"])
        self.assertIsNone(src.lookup(
            "mlb:2024-06-03:Boston Red Sox:New York Yankees", "ML", "HOME"))

    def test_nba_season_label_mismatch(self):
        src = mb.NbaLinesBaseline(ATT / "nba_lines_attack.csv").load()
        self.assertIn("BASELINE_NBA_SEASON_MISMATCH", src.stats["skip_reasons"])
        self.assertIsNone(src.lookup(
            "nba:2024-10-22:New York Knicks:Boston Celtics", "ML", "HOME"))

    # -- attack 2: book mislabeling --------------------------------------
    def test_archive_rejects_non_draftkings_book(self):
        src = mb.ClosingLineArchive(ATT).load()
        self.assertIn("BASELINE_BOOK_UNEXPECTED", src.stats["skip_reasons"])

    def test_mlb_violent_cross_book_dispersion_quarantines(self):
        src = mb.SbrMlbBaseline(ATT / "sbr_mlb_attack.json").load()
        self.assertIn("BASELINE_BOOK_DISPERSION_EXCEEDED",
                      src.stats["skip_reasons"])
        fid = "mlb:2024-06-02:Texas Rangers:Miami Marlins"
        self.assertIsNone(src.lookup(fid, "ML", "HOME"))
        self.assertIn("BASELINE_GAME_QUARANTINED", src.explain(fid, "ML", "HOME"))
        # the clean game in the same file still works
        p = src.lookup("mlb:2024-06-01:Chicago Cubs:Cincinnati Reds",
                       "ML", "HOME")
        self.assertIsNotNone(p)

    # -- attack 3: missing games ------------------------------------------
    def test_missing_game_is_missing_not_zero(self):
        src = mb.NflverseBaseline(ATT / "nflverse_attack.csv").load()
        self.assertIsNone(src.lookup(
            "nfl:2024-09-08:Kansas City Chiefs:Buffalo Bills", "ML", "HOME"))
        self.assertIn("BASELINE_GAME_NOT_ARCHIVED",
                      src.explain("nfl:2024-09-08:Kansas City Chiefs:Buffalo Bills",
                                  "ML", "HOME"))

    # -- attack 4: duplicate rows -------------------------------------------
    def test_archive_exact_duplicate_is_harmless(self):
        src = mb.ClosingLineArchive(ATT).load()
        self.assertGreaterEqual(src.stats["duplicate_rows"], 1)
        fid = mb.fixture_id_for_game("nfl", "2024-09-09T00:20:00Z",
                                     "Arizona Cardinals", "Buffalo Bills")
        self.assertIsNotNone(src.lookup(fid, "ML", "HOME"))

    def test_archive_contradictory_duplicate_quarantines(self):
        src = mb.ClosingLineArchive(ATT).load()
        self.assertIn("BASELINE_ARCHIVE_CONTRADICTORY_DUPLICATE",
                      src.stats["skip_reasons"])
        fid = "nfl:2024-09-09:Jacksonville Jaguars:Miami Dolphins"
        self.assertIsNone(src.lookup(fid, "ML", "HOME"))
        self.assertIn("BASELINE_GAME_QUARANTINED", src.explain(fid, "ML", "HOME"))
        self.assertEqual(src.stats["quarantined_games"], 1)

    def test_nflverse_contradictory_duplicate_quarantines(self):
        src = mb.NflverseBaseline(ATT / "nflverse_attack.csv").load()
        self.assertIn("BASELINE_NFLVERSE_CONTRADICTORY_DUPLICATE",
                      src.stats["skip_reasons"])
        fid = "nfl:2024-09-08:New England Patriots:Cincinnati Bengals"
        self.assertIsNone(src.lookup(fid, "ML", "HOME"))
        self.assertIn("BASELINE_GAME_QUARANTINED", src.explain(fid, "ML", "HOME"))

    # -- attack 5: timezone confusion ----------------------------------------
    def test_archive_naive_timestamp_refused(self):
        src = mb.ClosingLineArchive(ATT).load()
        self.assertIn("BASELINE_TIMESTAMP_NAIVE", src.stats["skip_reasons"])

    def test_archive_window_lead_mismatch_refused(self):
        src = mb.ClosingLineArchive(ATT).load()
        self.assertIn("BASELINE_WINDOW_LEAD_MISMATCH",
                      src.stats["skip_reasons"])

    def test_late_game_found_via_local_date(self):
        # commence 2024-09-09T00:20:00Z == 8:20pm ET on 2024-09-08.
        # The fixture id carries the LOCAL date; the archive is UTC-dated.
        fid = mb.fixture_id_for_game("nfl", "2024-09-09T00:20:00Z",
                                     "Arizona Cardinals", "Buffalo Bills")
        self.assertEqual(fid, "nfl:2024-09-08:Arizona Cardinals:Buffalo Bills")
        src = mb.ClosingLineArchive(ATT).load()
        p = src.lookup(fid, "ML", "HOME")
        exp, _ = novig(-300, 240)
        self.assertTrue(approx(p, exp))

    def test_offset_aware_timestamp_converts(self):
        # 1pm ET labeled with its offset must equal 17:00Z.
        ts = mb.parse_ts_utc("2024-09-09T13:00:00-04:00")
        self.assertEqual(ts.strftime("%H:%M"), "17:00")

    # -- attack 6: wrong-season / truncated files ------------------------------
    def test_truncated_season_fails_closed_explicitly(self):
        src = mb.NflverseBaseline(FIX / "nflverse_sample.csv").load()
        with self.assertRaises(mb.BaselineError) as ctx:
            src.assert_min_season_games("2024", 200)
        self.assertIn("BASELINE_SEASON_COVERAGE_SHORT", str(ctx.exception))
        # a genuinely full file passes (skip if absent)
        import os as _os
        _full_path = "/tmp/nfl_games.csv"
        if not _os.path.exists(_full_path):
            self.skipTest("full nfl_games.csv not present")
        full = mb.NflverseBaseline(_full_path).load()
        full.assert_min_season_games("2024", 280)

    def test_season_counts_reported_in_coverage(self):
        src = mb.NflverseBaseline(ATT / "nflverse_attack.csv").load()
        cov = src.coverage()
        self.assertIn("2024", cov["seasons"])
        import json as _json
        _json.dumps(cov)  # coverage must stay JSON-serializable


class TestMarketBlindBoundary(unittest.TestCase):
    """Market data is evaluation-side only, unconditionally.

    These tripwires fail if a pricing dependency or credential ever creeps
    into the evaluation modules. Stored closes may sit ALONGSIDE output as
    research comparison context; no code path may carry them into pricing.
    """

    MODULES = ["sportsedge/backtest/elo.py",
               "sportsedge/backtest/market_baseline.py"]
    # stdlib + intra-package imports only.
    ALLOWED = {
        "math", "csv", "json", "collections", "datetime", "pathlib",
        "zoneinfo", "unittest", "__future__",
    }

    def _code_without_docstrings(self, rel):
        import ast
        repo = Path(__file__).parent.parent
        src = (repo / rel).read_text()
        tree = ast.parse(src)
        doc_lines = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)):
                body = node.body
                if (body and isinstance(body[0], ast.Expr)
                        and isinstance(body[0].value, ast.Constant)
                        and isinstance(body[0].value.value, str)):
                    seg = body[0]
                    doc_lines.update(range(seg.lineno, seg.end_lineno + 1))
        return "\n".join(
            line for i, line in enumerate(src.splitlines(), 1)
            if i not in doc_lines)

    def _imports_of(self, rel):
        import ast
        repo = Path(__file__).parent.parent
        tree = ast.parse((repo / rel).read_text())
        found = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                found.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                mod = (node.module or "").split(".")[0]
                if node.level == 0 and mod:
                    found.add(mod)
                elif node.level and (node.module or "").startswith(
                        ("market_baseline", "elo")):
                    found.add("sportsedge.backtest (intra-package)")
        return found

    def test_evaluation_modules_import_nothing_pricing_related(self):
        for rel in self.MODULES:
            imports = self._imports_of(rel)
            bad = {i for i in imports
                   if i not in self.ALLOWED
                   and i != "sportsedge.backtest (intra-package)"}
            self.assertEqual(bad, set(), "%s imports %r" % (rel, bad))

    def test_no_credential_or_network_references(self):
        # Docstrings may NAME the secret to document the boundary; code
        # must never touch it.
        forbidden = ("apiKey", "SPORTSEDGE_ODDS_API_KEY", "urlopen",
                     "requests.get", "free_models", "run_it_full")
        for rel in self.MODULES:
            src = self._code_without_docstrings(rel)
            for token in forbidden:
                self.assertNotIn(token, src, "%s references %r" % (rel, token))

    def test_no_pricing_module_imports_backtest(self):
        # The import direction is one-way: pricing never pulls in the
        # evaluation package (which holds market data). Validation scripts
        # under scripts/ are tooling, not pricing, and may use the harness.
        repo = Path(__file__).parent.parent
        offenders = []
        for path in repo.rglob("*.py"):
            if "sportsedge/backtest" in str(path).replace("\\", "/"):
                continue
            if "/tests/" in str(path).replace("\\", "/"):
                continue
            if "/scripts/" in str(path).replace("\\", "/"):
                continue
            try:
                src = path.read_text()
            except OSError:
                continue
            if ("from sportsedge.backtest import" in src
                    or "from sportsedge import backtest" in src
                    or "import sportsedge.backtest" in src):
                offenders.append(str(path.relative_to(repo)))
        self.assertEqual(offenders, [])
