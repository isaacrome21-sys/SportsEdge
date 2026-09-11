import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sportsedge.generic_card_pipeline import GenericCardResult
from sportsedge.live_slate import make_live_game
from sportsedge.mlb_source import GameSnapshot
from sportsedge.orchestrator import RunResult
from sportsedge.unified_card import run_unified_card

UTC = timezone.utc
NOW = datetime(2026, 8, 25, 20, 0, tzinfo=UTC)


def _rows(start):
    return [{"player_id": start + i, "slot": i + 1, "sequence": 0} for i in range(9)]


def _game():
    snap = GameSnapshot(
        game_pk=777,
        game_date="2026-08-25T23:00:00Z",
        status="Preview",
        away_id=1,
        away_name="Away",
        home_id=2,
        home_name="Home",
        away_probable_pitcher_id=11,
        away_probable_pitcher_name="Away SP",
        home_probable_pitcher_id=22,
        home_probable_pitcher_name="Home SP",
        retrieved_at="2026-08-25T19:59:00+00:00",
    )
    return make_live_game(snap, _rows(100), _rows(200))


def _feature():
    return {
        "game_pk": 777,
        "player_id": 100,
        "team_id": 1,
        "market": "HITS",
        "features": {
            "b_rate": 0.31,
            "p_rate": 0.29,
            "pa_pool": [4, 5, 4, 5],
        },
    }


def _quote(side, odds):
    return {
        "game_id": "777",
        "period": "FG",
        "market": "HITS",
        "entity_id": "100",
        "line": 0.5,
        "side": side,
        "book_key": "draftkings",
        "is_alternate": False,
        "raw_market_name": "Player Hits",
        "american_odds": odds,
        "retrieved_at": NOW,
        "ttl_seconds": 300,
    }


def _registry(path):
    path.write_text(json.dumps({
        "schema_version": 1,
        "markets": {
            "HITS": {"eligible": True, "stage": "DEPLOYED", "reason": "b3-ledger-test"}
        },
    }))


def _decision_run(**kwargs):
    quote = kwargs["quote"]
    status = "OFFICIAL_BET" if float(quote["american_odds"]) >= 100 else "PASS"
    return RunResult(
        market="HITS",
        model_p=0.60,
        bet_status=status,
        decision=SimpleNamespace(push_probability=0.0),
        reason="ok",
    )


def _one_sided_candidate(**kwargs):
    return RunResult(
        market="HITS",
        model_p=0.60,
        bet_status="MODEL_CANDIDATE",
        decision=None,
        reason="OFFICIAL_BLOCKED:PAIRED_PRICE_REQUIRED_FOR_DEVIG",
    )


class PricedRowLedgerTests(unittest.TestCase):
    def _run(self, quotes):
        with tempfile.TemporaryDirectory() as td:
            registry_path = Path(td) / "deployments.json"
            _registry(registry_path)
            with patch("sportsedge.generic_card_pipeline.run_candidate", side_effect=_decision_run):
                return run_unified_card(
                    games=[_game()],
                    feature_rows=[_feature()],
                    quotes=quotes,
                    ingestion_now=NOW,
                    finalization_now=NOW,
                    registry_path=str(registry_path),
                )

    def test_bet_and_pass_rows_both_persist_with_full_cardinality(self):
        out = self._run([_quote("OVER", 120), _quote("UNDER", -140)])
        self.assertEqual(len(out), 2)
        self.assertEqual([row.bet_status for row in out], ["OFFICIAL_BET", "PASS"])
        self.assertTrue(all(row.model_p is not None for row in out))

    def test_price_counterfactual_can_flip_bet_to_pass_without_dropping_row(self):
        baseline = self._run([_quote("OVER", 120), _quote("UNDER", -140)])
        worse_price = self._run([_quote("OVER", -180), _quote("UNDER", 160)])
        self.assertEqual(len(baseline), len(worse_price))
        self.assertEqual(len(worse_price), 2)
        self.assertEqual(
            (baseline[0].game_id, baseline[0].market, baseline[0].entity_id, baseline[0].line, baseline[0].side),
            (worse_price[0].game_id, worse_price[0].market, worse_price[0].entity_id, worse_price[0].line, worse_price[0].side),
        )
        self.assertEqual(baseline[0].bet_status, "OFFICIAL_BET")
        self.assertEqual(worse_price[0].bet_status, "PASS")
        self.assertIsNotNone(worse_price[0].model_p)

    def test_unpaired_price_still_runs_model_but_cannot_create_novig_probability(self):
        with tempfile.TemporaryDirectory() as td:
            registry_path = Path(td) / "deployments.json"
            _registry(registry_path)
            with patch("sportsedge.generic_card_pipeline.run_candidate", side_effect=_one_sided_candidate) as run_candidate:
                out = run_unified_card(
                    games=[_game()],
                    feature_rows=[_feature()],
                    quotes=[_quote("OVER", 120)],
                    ingestion_now=NOW,
                    finalization_now=NOW,
                    registry_path=str(registry_path),
                )
        run_candidate.assert_called_once()
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].bet_status, "MODEL_CANDIDATE")
        self.assertEqual(out[0].model_p, 0.60)
        self.assertEqual(out[0].market_no_vig_p_status, "UNAVAILABLE_ONE_SIDED")
        self.assertIsNone(out[0].implied_probability)
        self.assertIsNotNone(out[0].raw_implied_probability)
        self.assertIsNotNone(out[0].ev_per_dollar)
        self.assertIn("PAIRED_PRICE_REQUIRED_FOR_DEVIG", out[0].reason)

    def test_unified_boundary_rejects_modeled_blocked_row(self):
        malformed = GenericCardResult(
            "777", "HITS", "100", 0.5, "OVER", 120,
            0.60, "BLOCKED", "synthetic invariant violation",
        )
        with patch("sportsedge.unified_card.run_generic_card", return_value=[malformed]):
            with self.assertRaisesRegex(RuntimeError, "priced decision ledger invariant violated"):
                run_unified_card(
                    games=[_game()],
                    feature_rows=[_feature()],
                    quotes=[_quote("OVER", 120)],
                    ingestion_now=NOW,
                    finalization_now=NOW,
                )


if __name__ == "__main__":
    unittest.main()
