import hashlib
import json
import unittest

from sportsedge.mlb_prop_official_facts import (
    OfficialPropFactError,
    prop_fact_from_settlement_report,
)


def _canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode()


class MLBPropOfficialFactsTests(unittest.TestCase):
    """Synthetic settlement-report fixtures only; not real evidence."""

    def _report(self):
        facts = {
            "game_pk": "999001",
            "status": "Final",
            "pitchers": [
                {"player_id": "p1", "outs": 19, "earned_runs": 2},
                {"player_id": "p2", "outs": 15, "earned_runs": 4},
            ],
            "batters": [
                {"player_id": "b1", "rbi": 2},
                {"player_id": "b2", "rbi": 0},
            ],
        }
        return {
            "state": "SETTLEMENT_SEMANTICS_PASS",
            "game_pk": "999001",
            "source": "SYNTHETIC_MLB_STATSAPI_FIXTURE",
            "facts_sha256": hashlib.sha256(_canonical(facts)).hexdigest(),
            "facts": facts,
        }

    def test_pitcher_outs_uses_proven_outs_fact(self):
        row = prop_fact_from_settlement_report(
            self._report(), market="PITCHER_OUTS", game_id="999001", entity_id="p1"
        )
        self.assertEqual(row["realized_count"], 19)
        self.assertEqual(row["fact_state"], "FINAL_OFFICIAL")

    def test_pitcher_er_uses_proven_earned_runs_fact(self):
        row = prop_fact_from_settlement_report(
            self._report(), market="PITCHER_ER", game_id="999001", entity_id="p2"
        )
        self.assertEqual(row["realized_count"], 4)

    def test_rbi_uses_proven_batter_rbi_fact(self):
        row = prop_fact_from_settlement_report(
            self._report(), market="RBI", game_id="999001", entity_id="b1"
        )
        self.assertEqual(row["realized_count"], 2)

    def test_tampered_facts_hash_fails_closed(self):
        report = self._report()
        report["facts"]["pitchers"][0]["outs"] = 20
        with self.assertRaisesRegex(OfficialPropFactError, "facts_sha256 mismatch"):
            prop_fact_from_settlement_report(
                report, market="PITCHER_OUTS", game_id="999001", entity_id="p1"
            )

    def test_nonfinal_or_unproven_report_fails_closed(self):
        report = self._report()
        report["state"] = "PENDING"
        with self.assertRaisesRegex(OfficialPropFactError, "not PASS"):
            prop_fact_from_settlement_report(
                report, market="PITCHER_ER", game_id="999001", entity_id="p1"
            )

    def test_missing_player_fails_closed(self):
        with self.assertRaisesRegex(OfficialPropFactError, "player fact not found"):
            prop_fact_from_settlement_report(
                self._report(), market="RBI", game_id="999001", entity_id="b999"
            )


if __name__ == "__main__":
    unittest.main()
