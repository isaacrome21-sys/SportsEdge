from datetime import datetime, timezone
import unittest

from sportsedge.cfbd_cfb_market_context import build_cfbd_cfb_market_context
from sportsedge.market_provider_contract import ProviderContractError, admit_quote


FETCHED = datetime(2026, 9, 15, 18, 30, tzinfo=timezone.utc)


def _game(provider="DraftKings", **line_overrides):
    line = {
        "provider": provider,
        "spread": -3.5,
        "overUnder": 52.5,
        "homeMoneyline": -145,
        "awayMoneyline": 125,
    }
    line.update(line_overrides)
    return {
        "id": 401234567,
        "season": 2026,
        "week": 4,
        "seasonType": "regular",
        "homeTeam": "Home State",
        "awayTeam": "Away Tech",
        "lines": [line],
    }


class CFBDCFBMarketContextTests(unittest.TestCase):
    def test_named_allowlisted_book_is_context_only_and_not_freshness_evidence(self):
        snap = build_cfbd_cfb_market_context([_game()], fetched_at=FETCHED)
        self.assertEqual(snap.disposition, "AVAILABLE")
        self.assertEqual(len(snap.rows), 1)
        self.assertEqual(snap.rejected, ())
        row = snap.rows[0]
        self.assertEqual(row["quote_provider"], "CFBD_LINES")
        self.assertEqual(row["sportsbook"], "DraftKings")
        self.assertEqual(row["fetched_at_utc"], FETCHED.isoformat())
        self.assertIsNone(row["source_native_observed_at"])
        self.assertNotIn("source_updated_at", row)
        self.assertFalse(row["fetched_at_is_quote_observation"])
        self.assertFalse(row["ttl_eligible"])
        self.assertFalse(row["freshness_eligible"])
        self.assertFalse(row["closing_benchmark_eligible"])
        self.assertFalse(row["opening_benchmark_eligible"])
        self.assertFalse(row["exact_book_contract_eligible"])
        self.assertTrue(row["market_context_only"])
        self.assertFalse(row["model_p_eligible"])
        self.assertFalse(row["truth_gate_eligible"])
        self.assertFalse(row["promotion_authority"])
        self.assertFalse(row["staking_authority"])
        self.assertFalse(row["official_authority"])

    def test_paired_moneyline_is_preserved_only_when_both_sides_exist(self):
        paired = build_cfbd_cfb_market_context([_game()], fetched_at=FETCHED).rows[0]
        self.assertEqual(paired["markets"]["moneyline"], {"home": -145, "away": 125, "paired": True})

        unpaired = build_cfbd_cfb_market_context(
            [_game(awayMoneyline=None)], fetched_at=FETCHED
        ).rows[0]
        self.assertNotIn("moneyline", unpaired["markets"])
        self.assertIn("spread", unpaired["markets"])

    def test_graphql_style_provider_and_moneyline_aliases_are_accepted(self):
        game = _game(provider={"name": "FanDuel"})
        line = game["lines"][0]
        line["moneylineHome"] = line.pop("homeMoneyline")
        line["moneylineAway"] = line.pop("awayMoneyline")
        row = build_cfbd_cfb_market_context([game], fetched_at=FETCHED).rows[0]
        self.assertEqual(row["sportsbook"], "FanDuel")
        self.assertIn("moneyline", row["markets"])

    def test_consensus_provider_is_rejected_even_if_it_has_prices(self):
        snap = build_cfbd_cfb_market_context([_game(provider="Consensus")], fetched_at=FETCHED)
        self.assertEqual(snap.rows, ())
        self.assertEqual(snap.disposition, "NO_ELIGIBLE_QUOTES")
        self.assertEqual(snap.rejected[0]["reason"], "CFBD_CONSENSUS_PROVIDER_INELIGIBLE")

    def test_unknown_named_provider_fails_closed(self):
        snap = build_cfbd_cfb_market_context([_game(provider="Unknown Book")], fetched_at=FETCHED)
        self.assertEqual(snap.rows, ())
        self.assertEqual(snap.disposition, "NO_ELIGIBLE_QUOTES")
        self.assertEqual(snap.rejected[0]["reason"], "CFBD_PROVIDER_NOT_ALLOWLISTED")

    def test_empty_top_level_payload_is_valid_no_bet_slate(self):
        snap = build_cfbd_cfb_market_context([], fetched_at=FETCHED)
        self.assertEqual(snap.rows, ())
        self.assertEqual(snap.rejected, ())
        self.assertEqual(snap.disposition, "VALID_NO_BET_SLATE")

    def test_scheduled_game_with_empty_lines_is_blocked_no_odds(self):
        game = _game()
        game["lines"] = []
        snap = build_cfbd_cfb_market_context([game], fetched_at=FETCHED)
        self.assertEqual(snap.rows, ())
        self.assertEqual(snap.disposition, "BLOCKED_NO_ODDS")
        self.assertEqual(snap.rejected[0]["reason"], "CFBD_LINES_EMPTY")

    def test_fetch_time_can_never_satisfy_generic_ttl_router(self):
        quote = {
            "quote_provider": "CFBD_LINES",
            "market": "MONEYLINE",
            "sportsbook": "DraftKings",
            "source_updated_at": FETCHED.isoformat(),
            "provider_last_update": FETCHED.isoformat(),
            "retrieved_at": FETCHED.isoformat(),
        }
        with self.assertRaisesRegex(ProviderContractError, "SOURCE_TTL_INVALID"):
            admit_quote(quote, now=FETCHED)

    def test_top_level_game_line_shape_is_supported_without_inventing_time(self):
        row = {
            "gameId": 401234568,
            "season": 2026,
            "week": 4,
            "provider": {"name": "BetMGM"},
            "spread": 2.5,
            "overUnder": 47,
            "moneylineHome": 110,
            "moneylineAway": -130,
        }
        parsed = build_cfbd_cfb_market_context([row], fetched_at=FETCHED).rows[0]
        self.assertEqual(parsed["sportsbook"], "BetMGM")
        self.assertIsNone(parsed["source_native_observed_at"])
        self.assertFalse(parsed["fetched_at_is_quote_observation"])


if __name__ == "__main__":
    unittest.main()
