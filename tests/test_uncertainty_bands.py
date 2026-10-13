"""Tests for uncertainty bands + sample-size flags (sportsedge.uncertainty).

Band math is hand-verified against independently computed Wilson score
interval values (see module docstring). Row extraction, flag thresholds,
and fail-closed paths are unit-tested on synthetic rows; the card hook is
integration-tested through run_full with recorded fixtures only -- no
network is touched.
"""
import unittest
from datetime import datetime, timezone
from urllib.parse import urlparse, parse_qs

from sportsedge import uncertainty as U
from artifacts.run_it_full import run_full


# ---------------------------------------------------------------------------
# Band math (hand-verified reference values, z = 1.96)
# ---------------------------------------------------------------------------
class WilsonMathTest(unittest.TestCase):
    def test_known_value_half_hundred(self):
        # Hand-computed: denom=1.038416, center=0.5, half=0.096170.
        lo, hi = U.wilson_interval(0.5, 100)
        self.assertAlmostEqual(lo, 0.4038, places=4)
        self.assertAlmostEqual(hi, 0.5962, places=4)

    def test_known_value_one_ten(self):
        # Hand-computed: center=0.86121, half=0.13879 -> (0.7225, 1.0).
        lo, hi = U.wilson_interval(1.0, 10)
        self.assertAlmostEqual(lo, 0.7225, places=4)
        self.assertEqual(hi, 1.0)

    def test_known_value_zero_ten(self):
        # Symmetry with p=1: (0.0, 1 - 0.72246) = (0.0, 0.2775).
        lo, hi = U.wilson_interval(0.0, 10)
        self.assertEqual(lo, 0.0)
        self.assertAlmostEqual(hi, 0.2775, places=4)

    def test_clamps_to_unit_interval(self):
        lo, hi = U.wilson_interval(0.99, 2)
        self.assertGreaterEqual(lo, 0.0)
        self.assertLessEqual(hi, 1.0)
        self.assertGreater(hi, lo)

    def test_band_narrows_with_sample(self):
        w10 = U.wilson_interval(0.55, 10)
        w100 = U.wilson_interval(0.55, 100)
        w1000 = U.wilson_interval(0.55, 1000)
        self.assertGreater(w10[1] - w10[0], w100[1] - w100[0])
        self.assertGreater(w100[1] - w100[0], w1000[1] - w1000[0])

    def test_band_contains_p(self):
        for p, n in [(0.5, 100), (0.7, 5), (0.2, 3), (1.0, 7)]:
            lo, hi = U.wilson_interval(p, n)
            self.assertLessEqual(lo, p)
            self.assertGreaterEqual(hi, p)

    def test_invalid_inputs_fail_closed(self):
        for bad in [(-0.1, 10), (1.5, 10), (0.5, 0), (0.5, -3),
                    (0.5, 2.5), ("x", 10), (0.5, "x"), (True, 10)]:
            with self.assertRaises(ValueError, msg=str(bad)):
                U.wilson_interval(*bad)


# ---------------------------------------------------------------------------
# Sample extraction + flags
# ---------------------------------------------------------------------------
def game_row(p=0.55, home_n=8, away_n=12, notes=None):
    row = {"sport": "NFL", "market": "TOTAL", "estimate_p": p,
           "status": "BELOW_THRESHOLD"}
    if notes is None:
        notes = [f"HOME_HISTORY_COUNT:{home_n}", f"AWAY_HISTORY_COUNT:{away_n}"]
    row["context_notes"] = notes
    return row


class SampleExtractionTest(unittest.TestCase):
    def test_game_uses_min_side(self):
        n, unit, reason = U.effective_sample(game_row(home_n=8, away_n=3), "GAME")
        self.assertEqual((n, unit, reason), (3, "prior_games_min_side", None))

    def test_game_missing_counts_unknown(self):
        row = game_row()
        row["context_notes"] = ["NO_FETCH_MANUAL_MODE_NO_PUBLIC_CONTEXT"]
        block = U.annotate_row(row)
        self.assertEqual(block["sample_flag"], U.UNKNOWN_SAMPLE)
        self.assertIsNone(block["band_lo"])
        self.assertIn("NO_BAND_INVENTED", block["band_reason"])
        self.assertIn("UNKNOWN_SAMPLE", block["sample_caution"])
        # The visible caution is hoisted to the row by attach_uncertainty.
        U.attach_uncertainty([row])
        self.assertIn("UNKNOWN_SAMPLE", row["sample_caution"])

    def test_pitcher_prior_starts(self):
        row = {"sport": "MLB", "market": "PITCHER_K",
               "model_probability": 0.6, "prior_start_count": 7,
               "status": "WATCH_BELOW_EV_FLOOR"}
        block = U.annotate_row(row)
        self.assertEqual(block["market_type"], "MLB_PITCHER_PROP")
        self.assertEqual(block["n_eff"], 7)
        self.assertEqual(block["sample_unit"], "prior_starts")
        self.assertEqual(block["sample_flag"], U.LOW_SAMPLE)  # threshold 10
        self.assertIsNotNone(block["band_lo"])
        self.assertLess(block["band_lo"], 0.6)
        self.assertGreater(block["band_hi"], 0.6)
        self.assertIn("LOW_SAMPLE", block["sample_caution"])
        U.attach_uncertainty([row])
        self.assertIn("LOW_SAMPLE", row["sample_caution"])

    def test_pitcher_adequate_at_ten(self):
        row = {"sport": "MLB", "market": "PITCHER_OUTS",
               "model_probability": 0.6, "prior_start_count": 10,
               "status": "WATCH_BELOW_EV_FLOOR"}
        block = U.annotate_row(row)
        self.assertEqual(block["sample_flag"], U.ADEQUATE_SAMPLE)
        self.assertIsNone(block["sample_caution"])
        self.assertNotIn("sample_caution", row)

    def test_batter_prior_games(self):
        row = {"sport": "MLB", "market": "BATTER_HITS",
               "model_probability": 0.5, "prior_game_count": 14,
               "status": "WATCH_LINEUP_NOT_CONFIRMED"}
        block = U.annotate_row(row)
        self.assertEqual(block["market_type"], "MLB_BATTER_PROP")
        self.assertEqual(block["n_eff"], 14)
        self.assertEqual(block["sample_flag"], U.ADEQUATE_SAMPLE)

    def test_nfl_five_games_is_low(self):
        row = {"sport": "NFL", "market": "PLAYER_PASSING_YARDS",
               "model_probability": 0.52, "prior_game_count": 5,
               "status": "WATCH_PLAYER_PARTICIPATION_UNVERIFIED"}
        block = U.annotate_row(row)
        self.assertEqual(block["market_type"], "NFL_PLAYER_PROP")
        self.assertEqual(block["sample_flag"], U.LOW_SAMPLE)  # threshold 10

    def test_cfb_ten_games_adequate(self):
        row = {"sport": "CFB", "market": "PLAYER_RUSHING_YARDS",
               "model_probability": 0.52, "prior_game_count": 11,
               "status": "WATCH_PLAYER_PARTICIPATION_UNVERIFIED"}
        self.assertEqual(U.annotate_row(row)["sample_flag"], U.ADEQUATE_SAMPLE)

    def test_unknown_market_type_no_band(self):
        row = {"sport": "NFL", "market": "FIRST_TD",
               "model_probability": 0.2, "status": "NO_MODEL_OR_MARKET"}
        block = U.annotate_row(row)
        self.assertEqual(block["market_type"], "UNKNOWN_MARKET_TYPE")
        self.assertEqual(block["sample_flag"], U.UNKNOWN_SAMPLE)
        self.assertIsNone(block["band_lo"])
        self.assertIn("NO_DECLARED_THRESHOLD", block["band_reason"])

    def test_unpriced_row_gets_nothing(self):
        row = {"sport": "NFL", "market": "ML", "status": "BLOCKED_STARTED"}
        self.assertIsNone(U.annotate_row(row))
        counts = U.attach_uncertainty([row])
        self.assertEqual(counts["NO_PROBABILITY"], 1)
        self.assertNotIn("uncertainty", row)

    def test_invalid_probability_no_band_but_flag_from_sample(self):
        row = {"sport": "MLB", "market": "PITCHER_K",
               "model_probability": 1.5, "prior_start_count": 12,
               "status": "NO_MODEL_OR_MARKET"}
        block = U.annotate_row(row)
        # probability_of rejects 1.5 -> no block at all (no probability)
        self.assertIsNone(block)

    def test_zero_sample_low_flag_no_band(self):
        row = {"sport": "MLB", "market": "BATTER_HITS",
               "model_probability": 0.5, "prior_game_count": 0,
               "status": "NO_MODEL_OR_MARKET"}
        block = U.annotate_row(row)
        self.assertEqual(block["sample_flag"], U.LOW_SAMPLE)
        self.assertIsNone(block["band_lo"])
        self.assertEqual(block["band_reason"], "N_EFF_ZERO_NO_BAND")

    def test_flag_threshold_boundaries(self):
        self.assertEqual(U.flag_sample("GAME", 4), U.LOW_SAMPLE)
        self.assertEqual(U.flag_sample("GAME", 5), U.ADEQUATE_SAMPLE)
        self.assertEqual(U.flag_sample("MLB_PITCHER_PROP", 9), U.LOW_SAMPLE)
        self.assertEqual(U.flag_sample("MLB_PITCHER_PROP", 10), U.ADEQUATE_SAMPLE)
        self.assertEqual(U.flag_sample("GAME", None), U.UNKNOWN_SAMPLE)
        self.assertEqual(U.flag_sample("UNKNOWN_TYPE", 50), U.UNKNOWN_SAMPLE)

    def test_band_never_narrower_than_data(self):
        # Game band must use the MINIMUM side count, not the sum or max.
        thin = game_row(p=0.6, home_n=20, away_n=4)
        block = U.annotate_row(thin)
        self.assertEqual(block["n_eff"], 4)
        lo4, hi4 = U.wilson_interval(0.6, 4)
        self.assertAlmostEqual(block["band_lo"], round(lo4, 6))
        self.assertAlmostEqual(block["band_hi"], round(hi4, 6))
        lo20, hi20 = U.wilson_interval(0.6, 20)
        self.assertGreater(block["band_width"], round(hi20 - lo20, 6))

    def test_methodology_block_documents_everything(self):
        m = U.methodology_block()
        self.assertEqual(m["schema"], "SPORTSEDGE_UNCERTAINTY_METHOD_V1")
        self.assertIn("GAME", m["adequacy_thresholds_declared_unfitted"])
        self.assertIn("MLB_PITCHER_PROP", m["adequacy_thresholds_declared_unfitted"])
        self.assertTrue(m["research_only"])
        self.assertTrue(any("NOT captured" in s or "NOT_CAPTURED" in s or
                            "NOT captured" in s for s in
                            [m["what_the_band_is_not"]]))


# ---------------------------------------------------------------------------
# Card integration: run_full with recorded fixtures, no network
# ---------------------------------------------------------------------------
KICKOFF = "2026-10-12T00:00:00Z"
AS_OF = datetime(2026, 10, 11, 21, 13, tzinfo=timezone.utc)


def mlb_schedule():
    return {"dates": [{"date": "2026-10-11", "games": [{
        "gamePk": 831111, "gameDate": KICKOFF,
        "teams": {
            "home": {"team": {"name": "Milwaukee Brewers", "id": 158},
                     "probablePitcher": {"id": 800222,
                                         "fullName": "Jacob Misiorowski"}},
            "away": {"team": {"name": "Los Angeles Dodgers", "id": 119},
                     "probablePitcher": {"id": 800111,
                                         "fullName": "Tarik Skubal"}},
        }}]}]}


def mlb_logs(starts=7):
    splits = []
    for i in range(starts):
        splits.append({
            "date": f"2026-09-{i + 1:02d}", "game": {"gamePk": 900100 + i},
            "stat": {"gamesStarted": 1, "strikeOuts": 5 + i % 4,
                     "inningsPitched": "5.2", "earnedRuns": i % 3,
                     "hits": 3 + i % 4, "baseOnBalls": i % 3}})
    return {"stats": [{"type": {"displayName": "gameLog"},
                       "group": {"displayName": "pitching"},
                       "splits": splits}]}


def mlb_getter(url, *, starts=7):
    host = urlparse(url).hostname
    assert host == "statsapi.mlb.com", url
    if urlparse(url).path.endswith("/schedule"):
        return mlb_schedule()
    if "/people/" in url and "/stats" in url:
        return mlb_logs(starts=starts)
    raise AssertionError(url)


def prop(**extra):
    row = {"sport": "MLB", "away": "Los Angeles Dodgers",
           "home": "Milwaukee Brewers", "kickoff": KICKOFF,
           "market": "PITCHER_K", "side": "OVER", "line": 7.5,
           "odds": -111, "book": "draftkings",
           "player_name": "Jacob Misiorowski",
           "quote_captured_at": "2026-10-11T21:12:10Z"}
    row.update(extra)
    return row


class CardIntegrationTest(unittest.TestCase):
    def test_priced_prop_rows_carry_uncertainty_and_actionability(self):
        card = run_full(
            {"sport": "MLB",
             "lines": [prop(), prop(side="UNDER", odds=-114)]},
            now=AS_OF, getter=mlb_getter, auto_context=True)
        rows = card["evaluated_rows"]
        self.assertEqual(len(rows), 2)
        for r in rows:
            # 7 prior starts -> LOW_SAMPLE against the declared 10 gate.
            self.assertIn("uncertainty", r)
            self.assertEqual(r["uncertainty"]["sample_flag"], "LOW_SAMPLE")
            self.assertEqual(r["uncertainty"]["n_eff"], 7)
            self.assertIsNotNone(r["uncertainty"]["band_lo"])
            self.assertLess(r["uncertainty"]["band_lo"],
                            r["model_probability"])
            self.assertIn("sample_caution", r)
            self.assertIn(r["actionability"], {"ACTIONABLE", "WATCH"})
            self.assertIn("actionability_detail", r)
        # Card-level documentation + summary counts.
        self.assertIn("uncertainty_methodology", card)
        counts = card["summary"]["sample_flag_counts"]
        self.assertEqual(counts["LOW_SAMPLE"], 2)
        act = card["summary"]["actionability"]
        self.assertEqual(act["total_rows"], 2)
        self.assertEqual(sum(act["counts"].values()), 2)
        self.assertAlmostEqual(sum(act["percentages"].values()), 100.0)
        self.assertTrue(act["research_only"])

    def test_blocked_rows_counted_not_banded(self):
        card = run_full(
            {"sport": "MLB",
             "lines": [prop(player_name="Wrong Person"),
                       prop(side="UNDER", odds=-114,
                            player_name="Wrong Person")]},
            now=AS_OF, getter=mlb_getter, auto_context=True)
        rows = card["evaluated_rows"]
        self.assertTrue(all(r["status"] == "NO_MODEL_OR_MARKET" for r in rows))
        self.assertTrue(all("uncertainty" not in r for r in rows))
        self.assertTrue(all(r["actionability"] == "BLOCKED" for r in rows))
        act = card["summary"]["actionability"]
        self.assertEqual(act["counts"]["BLOCKED"], 2)
        self.assertEqual(act["percentages"]["BLOCKED"], 100.0)
        codes = [t["reason_code"] for t in act["top_blocked_reasons"]]
        self.assertIn("NO_MODEL_OR_MARKET", codes)

    def test_render_card_shows_actionability_and_sample_tags(self):
        from scripts.free_models_phone_issue import render_card
        card = run_full(
            {"sport": "MLB",
             "lines": [prop(), prop(side="UNDER", odds=-114)]},
            now=AS_OF, getter=mlb_getter, auto_context=True)
        text = render_card(card)
        self.assertIn("**Actionability:**", text)
        self.assertIn("of 2 rows", text)
        # 7 prior starts -> LOW_SAMPLE tag on the rendered prop rows.
        self.assertIn("[LOW_SAMPLE]", text)

    def test_manual_mode_game_row_unknown_sample_fail_closed(self):
        # Manual --no-fetch mode prices from priors only: no verified
        # history counts exist, so the row must be UNKNOWN_SAMPLE with no
        # invented band.
        card = run_full(
            {"lines": [{
                "sport": "NFL", "away": "Baltimore Ravens",
                "home": "Atlanta Falcons", "market": "ML", "side": "AWAY",
                "odds": -110, "opposite_odds": 100,
                "commence_time": "2026-10-13T17:00:00Z"}]},
            now=AS_OF, getter=lambda url: None, auto_context=False)
        rows = card["evaluated_rows"]
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertIn("estimate_p", r)
        self.assertEqual(r["uncertainty"]["sample_flag"], "UNKNOWN_SAMPLE")
        self.assertIsNone(r["uncertainty"]["band_lo"])
        self.assertIsNone(r["uncertainty"]["band_hi"])
        self.assertIn("sample_caution", r)
        self.assertEqual(card["summary"]["sample_flag_counts"]["UNKNOWN_SAMPLE"], 1)


if __name__ == "__main__":
    unittest.main()
