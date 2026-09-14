import copy
import math
import unittest

from scripts.normalize_pinnacle_nfl_markets import (
    PinnacleNormalizationError,
    american_to_implied,
    normalize,
)

MATCHUP = {
    "matchup_id": 1636268497,
    "home_team": "New England Patriots",
    "away_team": "Pittsburgh Steelers",
    "start_time": "2026-09-20T17:00:00Z",
    "league": "NFL",
    "type": "matchup",
}
CAPTURED = "2026-09-14T03:18:36.089587Z"
RAW_SHA = "3e9c025b42a463e9374f610828d4966ed790346b43cc09e8a6fea23ad31113d4"
VERSION = 3728784265


def _market(market_type, key, prices, *, alt=False, period=0, status="open", matchup_id=1636268497):
    return {
        "cutoffAt": "2026-09-20T17:00:00+00:00",
        "isAlternate": alt,
        "key": key,
        "limits": [{"amount": 5000, "type": "maxRiskStake"}],
        "matchupId": matchup_id,
        "period": period,
        "prices": prices,
        "status": status,
        "type": market_type,
        "version": VERSION,
    }


def _core():
    return [
        _market(
            "moneyline",
            "s;0;m",
            [
                {"designation": "home", "price": -239},
                {"designation": "away", "price": 204},
            ],
        ),
        _market(
            "spread",
            "s;0;s;-5.5",
            [
                {"designation": "home", "points": -5.5, "price": -104},
                {"designation": "away", "points": 5.5, "price": -108},
            ],
        ),
        _market(
            "total",
            "s;0;ou;42.0",
            [
                {"designation": "over", "points": 42.0, "price": -111},
                {"designation": "under", "points": 42.0, "price": -105},
            ],
        ),
    ]


class PinnacleNFLNormalizerTests(unittest.TestCase):
    def test_live_shape_core_normalizes_to_six_zero_authority_quotes(self):
        markets = _core() + [
            _market(
                "spread",
                "s;0;s;-3.5",
                [
                    {"designation": "home", "points": -3.5, "price": -135},
                    {"designation": "away", "points": 3.5, "price": 116},
                ],
                alt=True,
            ),
            _market(
                "team_total",
                "s;0;tt;23.5;home",
                [
                    {"designation": "over", "points": 23.5, "price": -117},
                    {"designation": "under", "points": 23.5, "price": 100},
                ],
            ),
            _market(
                "moneyline",
                "s;1;m",
                [
                    {"designation": "home", "price": -203},
                    {"designation": "away", "price": 176},
                ],
                period=1,
            ),
        ]
        result = normalize(matchup=MATCHUP, markets=markets, captured_at=CAPTURED, raw_sha256=RAW_SHA)
        self.assertEqual(result["state"], "NORMALIZED")
        self.assertEqual(result["quote_count"], 6)
        self.assertEqual({q["market"] for q in result["quotes"]}, {"h2h", "spreads", "totals"})
        self.assertTrue(all(q["period"] == 0 and not q["is_alternate"] for q in result["quotes"]))
        self.assertTrue(all(q["timestamp_source"] == "CAPTURED_AT" for q in result["quotes"]))
        self.assertTrue(all(q["provider_cutoff_is_quote_timestamp"] is False for q in result["quotes"]))
        self.assertTrue(all(v is False for v in result["authority"].values()))
        self.assertEqual(result["skipped"]["alternate"], 1)
        self.assertEqual(result["skipped"]["unsupported_type"], 1)
        self.assertEqual(result["skipped"]["derivative_period"], 1)

    def test_no_vig_pair_sums_to_one_and_preserves_exact_spread_contract(self):
        result = normalize(matchup=MATCHUP, markets=_core(), captured_at=CAPTURED, raw_sha256=RAW_SHA)
        spread = [q for q in result["quotes"] if q["market"] == "spreads"]
        self.assertEqual([q["point"] for q in spread], [-5.5, 5.5])
        self.assertTrue(math.isclose(sum(q["no_vig_probability"] for q in spread), 1.0, abs_tol=1e-12))
        self.assertTrue(math.isclose(spread[0]["contract_line"], -5.5, abs_tol=1e-12))
        total = [q for q in result["quotes"] if q["market"] == "totals"]
        self.assertEqual([q["point"] for q in total], [42.0, 42.0])
        self.assertTrue(math.isclose(sum(q["no_vig_probability"] for q in total), 1.0, abs_tol=1e-12))

    def test_moneyline_fair_probability_uses_multiplicative_devig_only_with_pair(self):
        result = normalize(matchup=MATCHUP, markets=_core(), captured_at=CAPTURED, raw_sha256=RAW_SHA)
        h2h = [q for q in result["quotes"] if q["market"] == "h2h"]
        raw_home = american_to_implied(-239)
        raw_away = american_to_implied(204)
        self.assertTrue(math.isclose(h2h[0]["no_vig_probability"], raw_home / (raw_home + raw_away), abs_tol=1e-12))
        self.assertTrue(math.isclose(h2h[1]["no_vig_probability"], raw_away / (raw_home + raw_away), abs_tol=1e-12))

    def test_missing_side_fails_closed(self):
        markets = _core()
        markets[0]["prices"] = [{"designation": "home", "price": -239}]
        with self.assertRaisesRegex(PinnacleNormalizationError, "PAIR_MISSING"):
            normalize(matchup=MATCHUP, markets=markets, captured_at=CAPTURED, raw_sha256=RAW_SHA)

    def test_spread_point_mismatch_fails_closed(self):
        markets = _core()
        markets[1]["prices"][1]["points"] = 6.0
        with self.assertRaisesRegex(PinnacleNormalizationError, "SPREAD_CONTRACT_MISMATCH"):
            normalize(matchup=MATCHUP, markets=markets, captured_at=CAPTURED, raw_sha256=RAW_SHA)

    def test_total_point_mismatch_fails_closed(self):
        markets = _core()
        markets[2]["prices"][1]["points"] = 42.5
        with self.assertRaisesRegex(PinnacleNormalizationError, "TOTAL_CONTRACT_MISMATCH"):
            normalize(matchup=MATCHUP, markets=markets, captured_at=CAPTURED, raw_sha256=RAW_SHA)

    def test_duplicate_primary_market_fails_closed(self):
        markets = _core()
        markets.append(copy.deepcopy(markets[1]))
        with self.assertRaisesRegex(PinnacleNormalizationError, "CORE_MARKET_DUPLICATE:spread"):
            normalize(matchup=MATCHUP, markets=markets, captured_at=CAPTURED, raw_sha256=RAW_SHA)

    def test_missing_core_market_fails_closed(self):
        with self.assertRaisesRegex(PinnacleNormalizationError, "CORE_MARKET_MISSING:total"):
            normalize(matchup=MATCHUP, markets=_core()[:2], captured_at=CAPTURED, raw_sha256=RAW_SHA)

    def test_wrong_matchup_and_closed_rows_cannot_replace_core_contract(self):
        markets = _core()
        markets[0]["matchupId"] = 1
        markets.append(
            _market(
                "moneyline",
                "s;0;m",
                [{"designation": "home", "price": -200}, {"designation": "away", "price": 180}],
                status="closed",
            )
        )
        with self.assertRaisesRegex(PinnacleNormalizationError, "CORE_MARKET_MISSING:moneyline"):
            normalize(matchup=MATCHUP, markets=markets, captured_at=CAPTURED, raw_sha256=RAW_SHA)

    def test_invalid_zero_price_fails_closed(self):
        markets = _core()
        markets[2]["prices"][0]["price"] = 0
        with self.assertRaisesRegex(PinnacleNormalizationError, "PRICE_INVALID"):
            normalize(matchup=MATCHUP, markets=markets, captured_at=CAPTURED, raw_sha256=RAW_SHA)


if __name__ == "__main__":
    unittest.main()
