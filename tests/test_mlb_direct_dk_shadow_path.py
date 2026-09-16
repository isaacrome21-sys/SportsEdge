import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sportsedge.draftkings_game_market_source import RawDraftKingsBoard
from sportsedge.mlb_direct_dk_game_source import normalize_direct_dk_mlb_board
from scripts.run_mlb_direct_shadow import _write_shadow_ledger

UTC = timezone.utc
RECEIVED = datetime(2026, 9, 15, 16, 0, tzinfo=UTC)


def payload(*, bad_spread=False, drop_under=False, omit_total_market=False):
    spread_away = 2.5 if not bad_spread else 3.5
    selections = [
        {"marketId": "m1", "label": "Chicago Cubs", "displayOdds": {"american": "-120"}},
        {"marketId": "m1", "label": "Pittsburgh Pirates", "displayOdds": {"american": "+105"}},
        {"marketId": "m2", "label": "Chicago Cubs -2.5", "points": -2.5, "displayOdds": {"american": "+140"}},
        {"marketId": "m2", "label": "Pittsburgh Pirates +2.5", "points": spread_away, "displayOdds": {"american": "-165"}},
        {"marketId": "m3", "label": "Over 8.5", "points": 8.5, "displayOdds": {"american": "-105"}},
        {"marketId": "m3", "label": "Under 8.5", "points": 8.5, "displayOdds": {"american": "-115"}},
    ]
    if drop_under:
        selections = [x for x in selections if not str(x["label"]).startswith("Under")]
    markets = [
        {"id": "m1", "eventId": "dk1", "name": "Moneyline"},
        {"id": "m2", "eventId": "dk1", "name": "Run Line"},
        {"id": "m3", "eventId": "dk1", "name": "Total"},
    ]
    if omit_total_market:
        markets = [m for m in markets if m["id"] != "m3"]
        selections = [s for s in selections if s["marketId"] != "m3"]
    return {
        "events": [{"id": "dk1", "name": "Chicago Cubs @ Pittsburgh Pirates", "startEventDate": "2026-09-15T23:40:00Z"}],
        "markets": markets,
        "selections": selections,
    }


def game():
    return SimpleNamespace(
        game_pk=777,
        game_date="2026-09-15T23:40:00Z",
        home_name="Pittsburgh Pirates",
        away_name="Chicago Cubs",
        home_id=134,
        away_id=112,
    )


def board(p):
    raw = ("  " + json.dumps(p, separators=(",", ":")) + "\n").encode()
    return RawDraftKingsBoard("baseball_mlb", "https://sportsbook-nash.draftkings.com/direct", raw, RECEIVED, p)


class DirectDKMLBSourceTests(unittest.TestCase):
    def test_exact_game_markets_bind_to_statsapi_and_preserve_raw_identity(self):
        b = board(payload())
        snap = normalize_direct_dk_mlb_board(board=b, schedule=[game()])
        self.assertEqual(len(snap.quotes), 6)
        self.assertEqual(snap.raw, b.raw)
        self.assertEqual(snap.raw_sha256, hashlib.sha256(b.raw).hexdigest())
        self.assertEqual({q["market"] for q in snap.quotes}, {"MONEYLINE", "RUN_LINE", "TOTALS"})
        self.assertTrue(all(q["game_id"] == "777" for q in snap.quotes))
        self.assertTrue(all(q["source_provider"] == "DRAFTKINGS_DIRECT_WEB_V1" for q in snap.quotes))
        self.assertTrue(all(q["retrieved_at"] == RECEIVED for q in snap.quotes))
        self.assertTrue(all("raw_sha256=" + snap.raw_sha256 in q["source"] for q in snap.quotes))

    def test_spread_pair_mismatch_is_rejected_not_repaired(self):
        snap = normalize_direct_dk_mlb_board(board=board(payload(bad_spread=True)), schedule=[game()])
        self.assertFalse(any(q["market"] == "RUN_LINE" for q in snap.quotes))
        self.assertTrue(any("DIRECT_DK_SPREAD_LINE_MISMATCH" in f["reason"] for f in snap.failures))

    def test_one_sided_total_is_rejected_and_observable(self):
        snap = normalize_direct_dk_mlb_board(board=board(payload(drop_under=True)), schedule=[game()])
        self.assertFalse(any(q["market"] == "TOTALS" for q in snap.quotes))
        failures = [f for f in snap.failures if f.get("market") == "totals"]
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]["stage"], "MARKET_ADMISSION")
        self.assertIn("DIRECT_DK_MARKET_PRESENT_BUT_NOT_ADMISSIBLE", failures[0]["reason"])

    def test_truly_absent_total_is_not_misclassified_as_rejected(self):
        snap = normalize_direct_dk_mlb_board(board=board(payload(omit_total_market=True)), schedule=[game()])
        self.assertFalse(any(q["market"] == "TOTALS" for q in snap.quotes))
        self.assertFalse(any(f.get("market") == "totals" for f in snap.failures))

    def test_unbound_provider_event_emits_no_quotes(self):
        wrong = game()
        wrong.home_name = "New York Mets"
        snap = normalize_direct_dk_mlb_board(board=board(payload()), schedule=[wrong])
        self.assertEqual(snap.quotes, ())
        self.assertTrue(any(f["stage"] == "IDENTITY_BIND" for f in snap.failures))


class ShadowLedgerTests(unittest.TestCase):
    @patch("scripts.run_mlb_direct_shadow.mlb_model_artifact_sha256", return_value="a" * 64)
    def test_model_candidate_shadow_bet_is_content_addressed_and_non_official(self, _artifact):
        report = {
            "slate_date_ct": "2026-09-15",
            "generated_at_utc": "2026-09-15T16:00:00+00:00",
            "results": [{
                "game_id": "777", "market": "MONEYLINE", "entity_id": "134",
                "side": "HOME", "line": 0.0, "american_odds": -120,
                "model_p": 0.61, "bet_status": "MODEL_CANDIDATE",
                "shadow_status": "SHADOW_BET", "edge": 0.05, "ev_per_dollar": 0.08,
            }],
        }
        source = {"source_class": "DRAFTKINGS_DIRECT_WEB_V1", "raw_sha256": "b" * 64}
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            first = _write_shadow_ledger(report=report, source=source, root=root)
            second = _write_shadow_ledger(report=report, source=source, root=root)
            self.assertIsNotNone(first)
            self.assertTrue(first["created"])
            self.assertFalse(second["created"])
            saved = json.loads(Path(first["path"]).read_text())
            self.assertFalse(saved["official_authority"])
            self.assertFalse(saved["promotion_authority"])
            self.assertFalse(saved["deployment_eligibility_changed"])
            self.assertEqual(saved["rows"][0]["bet_status"], "MODEL_CANDIDATE")
            self.assertEqual(saved["rows"][0]["shadow_status"], "SHADOW_BET")


if __name__ == "__main__":
    unittest.main()
