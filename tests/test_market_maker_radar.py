import json
import unittest
from pathlib import Path

from scripts.analyze_market_maker_radar import (
    analyze,
    american_implied_probability,
    dedupe_archive_rows,
    load_policy,
)

POLICY = load_policy("config/market_maker_radar_v1.json")


def row(
    *,
    capture,
    captured_at,
    book,
    outcome,
    price,
    market="h2h",
    point=None,
    book_last_update=None,
    window="close",
):
    return {
        "schema_version": "CLOSING_LINE_ARCHIVE_ROW_V2",
        "policy_id": "CLOSING_LINE_ARCHIVE_V1",
        "evidence_class": "NOT_EVIDENCE",
        "promotion_authority": False,
        "sport_key": "americanfootball_nfl",
        "event_id": "game-1",
        "commence_time": "2026-09-14T18:00:00Z",
        "capture_id": capture,
        "home_team": "Home",
        "away_team": "Away",
        "book": book,
        "market": market,
        "outcome": outcome,
        "point": point,
        "price_american": price,
        "window": window,
        "captured_at": captured_at,
        "book_last_update": book_last_update,
    }


class PolicyTests(unittest.TestCase):
    def test_radar_is_permanently_zero_authority(self):
        authority = POLICY["authority"]
        for key in (
            "model_p_authority",
            "predictive_model_input",
            "truth_gate_input",
            "promotion_authority",
            "eligibility_authority",
            "staking_authority",
            "official_authority",
        ):
            self.assertFalse(authority[key])
        self.assertEqual(POLICY["evidence_class"], "LAYER_B_HARD_MARKET_DIAGNOSTIC")

    def test_public_splits_are_annotation_only(self):
        splits = json.loads(Path("config/football_public_splits_v1.json").read_text())
        self.assertFalse(splits["sharp_money_signal_authority"])
        self.assertFalse(splits["wager_support_authority"])
        self.assertFalse(splits["predictive_model_input"])
        self.assertTrue(splits["rlm_label_requires_news_attribution"])

    def test_archive_includes_fd_pinnacle_and_dk_but_not_fake_circa(self):
        archive = json.loads(Path("config/closing_line_archive_policy_v1.json").read_text())
        self.assertEqual(set(archive["books"]), {"draftkings", "fanduel", "pinnacle"})
        self.assertEqual(archive["market_radar"]["provider_required_books"], ["circa"])
        self.assertNotIn("circa", archive["books"])


class MathTests(unittest.TestCase):
    def test_american_probability(self):
        self.assertAlmostEqual(american_implied_probability(-110), 110 / 210)
        self.assertAlmostEqual(american_implied_probability(+150), 100 / 250)

    def test_overlapping_window_rows_dedupe_to_one_observation(self):
        base = row(
            capture="c1",
            captured_at="2026-09-14T12:00:00Z",
            book="pinnacle",
            outcome="Home",
            price=-110,
        )
        duplicate = dict(base)
        duplicate["window"] = "t0_prestart"
        deduped = dedupe_archive_rows([base, duplicate])
        self.assertEqual(len(deduped), 1)


class LeadLagTests(unittest.TestCase):
    def test_pinnacle_lead_to_dk_and_fd_is_separate_source_family(self):
        rows = [
            row(capture="c0", captured_at="2026-09-14T12:00:00Z", book="pinnacle", outcome="Home", price=-110),
            row(capture="c0", captured_at="2026-09-14T12:00:00Z", book="draftkings", outcome="Home", price=-110),
            row(capture="c0", captured_at="2026-09-14T12:00:00Z", book="fanduel", outcome="Home", price=-110),
            row(capture="c1", captured_at="2026-09-14T12:05:00Z", book="pinnacle", outcome="Home", price=-120),
            row(capture="c2", captured_at="2026-09-14T12:07:00Z", book="draftkings", outcome="Home", price=-120),
            row(capture="c3", captured_at="2026-09-14T12:09:00Z", book="fanduel", outcome="Home", price=-120),
        ]
        report = analyze(rows, POLICY)
        self.assertEqual(report["state"], "ACTIVE")
        self.assertEqual(report["lead_lag_signal_count"], 2)
        families = {s["source_family_id"] for s in report["lead_lag_signals"]}
        self.assertEqual(
            families,
            {"PINNACLE_TO_DRAFTKINGS_LEAD_LAG_V1", "PINNACLE_TO_FANDUEL_LEAD_LAG_V1"},
        )
        lags = {s["follower_book"]: s["lag_seconds"] for s in report["lead_lag_signals"]}
        self.assertEqual(lags, {"draftkings": 120, "fanduel": 240})
        for summary in report["lead_lag_summary"].values():
            self.assertEqual(summary["validation_status"], "INSUFFICIENT")
            self.assertIsNone(summary["clv"])

    def test_simultaneous_move_is_not_assigned_a_leader(self):
        rows = [
            row(capture="c0", captured_at="2026-09-14T12:00:00Z", book="pinnacle", outcome="Home", price=-110),
            row(capture="c0", captured_at="2026-09-14T12:00:00Z", book="draftkings", outcome="Home", price=-110),
            row(capture="c1", captured_at="2026-09-14T12:05:00Z", book="pinnacle", outcome="Home", price=-120),
            row(capture="c1", captured_at="2026-09-14T12:05:00Z", book="draftkings", outcome="Home", price=-120),
        ]
        report = analyze(rows, POLICY)
        self.assertEqual(report["lead_lag_signal_count"], 0)
        self.assertEqual(report["synchronous_pair_count"], 1)

    def test_same_poll_can_use_distinct_book_source_timestamps(self):
        rows = [
            row(
                capture="c0",
                captured_at="2026-09-14T12:00:00Z",
                book="pinnacle",
                outcome="Home",
                price=-110,
                book_last_update="2026-09-14T11:59:00Z",
            ),
            row(
                capture="c0",
                captured_at="2026-09-14T12:00:00Z",
                book="draftkings",
                outcome="Home",
                price=-110,
                book_last_update="2026-09-14T11:59:00Z",
            ),
            row(
                capture="c1",
                captured_at="2026-09-14T12:10:00Z",
                book="pinnacle",
                outcome="Home",
                price=-120,
                book_last_update="2026-09-14T12:04:00Z",
            ),
            row(
                capture="c1",
                captured_at="2026-09-14T12:10:00Z",
                book="draftkings",
                outcome="Home",
                price=-120,
                book_last_update="2026-09-14T12:07:00Z",
            ),
        ]
        report = analyze(rows, POLICY)
        self.assertEqual(report["lead_lag_signal_count"], 1)
        self.assertEqual(report["lead_lag_signals"][0]["lag_seconds"], 180)


class StalePriceTests(unittest.TestCase):
    def test_pinnacle_no_vig_detects_better_soft_price_same_line(self):
        rows = [
            row(capture="c1", captured_at="2026-09-14T12:00:00Z", book="pinnacle", outcome="Home", price=-120),
            row(capture="c1", captured_at="2026-09-14T12:00:00Z", book="pinnacle", outcome="Away", price=+110),
            row(capture="c1", captured_at="2026-09-14T12:00:00Z", book="draftkings", outcome="Home", price=+100),
            row(capture="c1", captured_at="2026-09-14T12:00:00Z", book="draftkings", outcome="Away", price=-110),
        ]
        report = analyze(rows, POLICY)
        home = [s for s in report["stale_soft_prices"] if s["outcome"] == "Home"]
        self.assertEqual(len(home), 1)
        self.assertGreater(home[0]["fair_probability_gap_pp"], 3.0)
        self.assertFalse(home[0]["model_p_authority"])
        self.assertFalse(home[0]["staking_authority"])

    def test_different_spread_is_line_candidate_not_fake_ev(self):
        rows = [
            row(capture="c1", captured_at="2026-09-14T12:00:00Z", book="pinnacle", outcome="Home", price=-110, market="spreads", point=-3.0),
            row(capture="c1", captured_at="2026-09-14T12:00:00Z", book="pinnacle", outcome="Away", price=-110, market="spreads", point=+3.0),
            row(capture="c1", captured_at="2026-09-14T12:00:00Z", book="draftkings", outcome="Home", price=-110, market="spreads", point=-2.5),
            row(capture="c1", captured_at="2026-09-14T12:00:00Z", book="draftkings", outcome="Away", price=-110, market="spreads", point=+2.5),
        ]
        report = analyze(rows, POLICY)
        self.assertEqual(report["stale_soft_price_count"], 0)
        home = [s for s in report["line_advantage_candidates"] if s["outcome"] == "Home"]
        self.assertEqual(len(home), 1)
        self.assertEqual(home[0]["favorable_line_gap"], 0.5)
        self.assertFalse(home[0]["price_normalized"])
        self.assertIn("CANNOT_BE_CONVERTED_TO_EV_WITHOUT_A_MODEL", home[0]["reason"])


class OutputTests(unittest.TestCase):
    def test_output_cannot_claim_model_or_promotion(self):
        report = analyze([], POLICY)
        self.assertEqual(report["state"], "BLOCKED_NO_ROWS")
        self.assertFalse(report["model_p_authority"])
        self.assertFalse(report["truth_gate_input"])
        self.assertFalse(report["promotion_authority"])
        self.assertFalse(report["eligibility_authority"])
        self.assertFalse(report["staking_authority"])
        self.assertFalse(report["official_authority"])
        self.assertEqual(report["public_split_role"], "ANNOTATION_ONLY_NOT_SIGNAL")


if __name__ == "__main__":
    unittest.main()
