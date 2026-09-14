import unittest

from scripts.normalize_fanduel_nfl_markets import (
    FanDuelNormalizationError,
    SOURCE_FAMILY_ID,
    normalize,
)

CAPTURED_AT = "2026-09-14T03:35:27.233879Z"
RAW_SHA = "38ac11cfa127f0f6ba92a5481d3368d2e8408d9e0b3a55718592f5c5ec38ffd7"


def _runner(selection_id, name, handicap, american, decimal):
    return {
        "selectionId": selection_id,
        "runnerName": name,
        "handicap": handicap,
        "winRunnerOdds": {
            "americanDisplayOdds": {
                "americanOdds": american,
                "americanOddsInt": american,
            },
            "trueOdds": {"decimalOdds": {"decimalOdds": decimal}},
        },
    }


def _market(
    market_id,
    name,
    market_type,
    betting_type,
    runners,
    *,
    status="OPEN",
    in_play=False,
):
    return {
        "marketId": market_id,
        "eventId": 35599552,
        "marketName": name,
        "marketType": market_type,
        "bettingType": betting_type,
        "marketStatus": status,
        "inPlay": in_play,
        "runners": runners,
    }


def _event_page():
    return {
        "attachments": {
            "events": {
                "35599552": {
                    "eventId": 35599552,
                    "inPlay": False,
                    "name": "Detroit Lions @ Buffalo Bills",
                    "openDate": "2026-09-18T00:15:00.000Z",
                    "primaryMarketId": "734.168628449",
                }
            },
            "markets": {
                "734.168628452": _market(
                    "734.168628452",
                    "Winning Margin (4-Way)",
                    "WINNING_MARGIN_(4-WAY)",
                    "ODDS",
                    [
                        _runner(1, "Detroit Lions by 1-13 Pts", 0, 200, 3.0),
                        _runner(2, "Detroit Lions 14+", 0, 1000, 11.0),
                    ],
                ),
                "734.168628451": _market(
                    "734.168628451",
                    "Moneyline",
                    "MONEY_LINE",
                    "ODDS",
                    [
                        _runner(50193, "Detroit Lions", 0, 164, 2.64),
                        _runner(50203, "Buffalo Bills", 0, -196, 1.510204081632653),
                    ],
                ),
                "734.168628450": _market(
                    "734.168628450",
                    "Total Points",
                    "TOTAL_POINTS_(OVER/UNDER)",
                    "MOVING_HANDICAP",
                    [
                        _runner(7017916, "Over", 52.5, -118, 1.847457627118644),
                        _runner(7017917, "Under", 52.5, -104, 1.961538461538462),
                    ],
                ),
                "734.168628449": _market(
                    "734.168628449",
                    "Spread",
                    "MATCH_HANDICAP_(2-WAY)",
                    "MOVING_HANDICAP",
                    [
                        _runner(50193, "Detroit Lions", 3.5, -110, 1.909090909090909),
                        _runner(50203, "Buffalo Bills", -3.5, -110, 1.909090909090909),
                    ],
                ),
            },
        },
        "layout": {"tabs": []},
    }


class FanDuelNFLMarketNormalizerTests(unittest.TestCase):
    def test_live_shape_normalizes_exactly_six_core_quotes(self):
        result = normalize(
            event_page=_event_page(),
            captured_at=CAPTURED_AT,
            raw_sha256=RAW_SHA,
        )
        self.assertEqual(result["state"], "NORMALIZED")
        self.assertEqual(result["quote_count"], 6)
        self.assertEqual(result["source_family_id"], SOURCE_FAMILY_ID)
        self.assertEqual(result["event"]["away_team"], "Detroit Lions")
        self.assertEqual(result["event"]["home_team"], "Buffalo Bills")
        self.assertEqual({q["market"] for q in result["quotes"]}, {"h2h", "spreads", "totals"})
        self.assertTrue(all(q["book"] == "fanduel" for q in result["quotes"]))
        self.assertTrue(all(q["book_last_update"] is None for q in result["quotes"]))
        self.assertTrue(all(q["timestamp_source"] == "CAPTURED_AT" for q in result["quotes"]))
        self.assertTrue(all(q["provider_quote_timestamp_available"] is False for q in result["quotes"]))
        self.assertTrue(all(q["raw_sha256"] == RAW_SHA for q in result["quotes"]))
        self.assertTrue(all(v is False for v in result["authority"].values()))
        self.assertTrue(all(all(v is False for v in q["authority"].values()) for q in result["quotes"]))

        ml = {q["outcome_name"]: q for q in result["quotes"] if q["market"] == "h2h"}
        self.assertEqual(ml["Buffalo Bills"]["american_price"], -196)
        self.assertEqual(ml["Detroit Lions"]["american_price"], 164)

        spread = {q["outcome_name"]: q for q in result["quotes"] if q["market"] == "spreads"}
        self.assertEqual(spread["Buffalo Bills"]["point"], -3.5)
        self.assertEqual(spread["Detroit Lions"]["point"], 3.5)

        total = {q["designation"]: q for q in result["quotes"] if q["market"] == "totals"}
        self.assertEqual(total["over"]["point"], 52.5)
        self.assertEqual(total["under"]["point"], 52.5)

    def test_unrelated_winning_margin_is_ignored(self):
        page = _event_page()
        page["attachments"]["markets"]["extra"] = _market(
            "extra",
            "Winning Margin (4-Way)",
            "WINNING_MARGIN_(4-WAY)",
            "ODDS",
            [_runner(1, "A", 0, 100, 2.0), _runner(2, "B", 0, 100, 2.0)],
        )
        result = normalize(event_page=page, captured_at=CAPTURED_AT, raw_sha256=RAW_SHA)
        self.assertEqual(result["quote_count"], 6)

    def test_missing_core_market_fails_closed(self):
        page = _event_page()
        del page["attachments"]["markets"]["734.168628449"]
        with self.assertRaisesRegex(FanDuelNormalizationError, "FANDUEL_CORE_MARKET_MISSING:spread"):
            normalize(event_page=page, captured_at=CAPTURED_AT, raw_sha256=RAW_SHA)

    def test_duplicate_core_market_fails_closed(self):
        page = _event_page()
        duplicate = dict(page["attachments"]["markets"]["734.168628451"])
        duplicate["marketId"] = "duplicate"
        page["attachments"]["markets"]["duplicate"] = duplicate
        with self.assertRaisesRegex(FanDuelNormalizationError, "FANDUEL_CORE_MARKET_DUPLICATE:moneyline"):
            normalize(event_page=page, captured_at=CAPTURED_AT, raw_sha256=RAW_SHA)

    def test_spread_contract_mismatch_fails_closed(self):
        page = _event_page()
        page["attachments"]["markets"]["734.168628449"]["runners"][1]["handicap"] = -2.5
        with self.assertRaisesRegex(FanDuelNormalizationError, "FANDUEL_SPREAD_CONTRACT_MISMATCH"):
            normalize(event_page=page, captured_at=CAPTURED_AT, raw_sha256=RAW_SHA)

    def test_total_contract_mismatch_fails_closed(self):
        page = _event_page()
        page["attachments"]["markets"]["734.168628450"]["runners"][1]["handicap"] = 51.5
        with self.assertRaisesRegex(FanDuelNormalizationError, "FANDUEL_TOTAL_CONTRACT_MISMATCH"):
            normalize(event_page=page, captured_at=CAPTURED_AT, raw_sha256=RAW_SHA)

    def test_live_event_fails_closed(self):
        page = _event_page()
        page["attachments"]["events"]["35599552"]["inPlay"] = True
        with self.assertRaisesRegex(FanDuelNormalizationError, "FANDUEL_EVENT_IN_PLAY"):
            normalize(event_page=page, captured_at=CAPTURED_AT, raw_sha256=RAW_SHA)

    def test_event_name_requires_explicit_away_at_home(self):
        page = _event_page()
        page["attachments"]["events"]["35599552"]["name"] = "Detroit Lions vs Buffalo Bills"
        with self.assertRaisesRegex(FanDuelNormalizationError, "FANDUEL_EVENT_NAME_NOT_AWAY_AT_HOME"):
            normalize(event_page=page, captured_at=CAPTURED_AT, raw_sha256=RAW_SHA)

    def test_team_runner_mismatch_fails_closed(self):
        page = _event_page()
        page["attachments"]["markets"]["734.168628451"]["runners"][0]["runnerName"] = "Detroit Tigers"
        with self.assertRaisesRegex(FanDuelNormalizationError, "FANDUEL_MONEYLINE_TEAM_MISMATCH"):
            normalize(event_page=page, captured_at=CAPTURED_AT, raw_sha256=RAW_SHA)


if __name__ == "__main__":
    unittest.main()
