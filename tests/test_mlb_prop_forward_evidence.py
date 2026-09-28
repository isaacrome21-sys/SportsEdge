from __future__ import annotations

import copy
import unittest

from sportsedge.mlb_prop_forward_evidence import (
    EVIDENCE_GROUPS,
    MlbPropForwardEvidenceError,
    build_pregame_receipt,
    build_settlement_receipt,
    canonical_sha256,
)
from sportsedge.prop_evidence import expected_market_identities


def _feed(state: str = "Preview") -> dict:
    return {
        "gamePk": 999001,
        "gameData": {
            "game": {"pk": 999001},
            "datetime": {"dateTime": "2026-09-29T23:00:00Z"},
            "status": {"abstractGameState": state, "detailedState": state},
        },
        "liveData": {
            "plays": {
                "allPlays": [
                    {
                        "atBatIndex": 0,
                        "about": {"inning": 1, "halfInning": "top"},
                        "matchup": {"batter": {"id": 101, "fullName": "Away Slugger"}},
                        "result": {"event": "Home Run", "eventType": "home_run"},
                        "runners": [
                            {
                                "details": {"runner": {"id": 101}},
                                "movement": {"end": "score"},
                            }
                        ],
                    },
                    {
                        "atBatIndex": 1,
                        "about": {"inning": 1, "halfInning": "bottom"},
                        "matchup": {"batter": {"id": 102, "fullName": "Home Hitter"}},
                        "result": {"event": "Single", "eventType": "single"},
                        "runners": [],
                    },
                ]
            },
            "boxscore": {
                "teams": {
                    "away": {
                        "players": {
                            "ID201": {
                                "person": {"id": 201, "fullName": "Away Pitcher"},
                                "stats": {
                                    "pitching": {
                                        "inningsPitched": "6.0",
                                        "outs": 18,
                                        "numberOfPitches": 91,
                                        "battersFaced": 24,
                                        "gamesStarted": 1,
                                        "hits": 5,
                                        "runs": 2,
                                        "earnedRuns": 2,
                                        "homeRuns": 1,
                                        "baseOnBalls": 2,
                                        "strikeOuts": 7,
                                    }
                                },
                            }
                        }
                    },
                    "home": {
                        "players": {
                            "ID202": {
                                "person": {"id": 202, "fullName": "Home Pitcher"},
                                "stats": {
                                    "pitching": {
                                        "inningsPitched": "5.0",
                                        "outs": 15,
                                        "numberOfPitches": 82,
                                        "battersFaced": 22,
                                        "gamesStarted": 1,
                                        "hits": 6,
                                        "runs": 3,
                                        "earnedRuns": 3,
                                        "homeRuns": 1,
                                        "baseOnBalls": 1,
                                        "strikeOuts": 5,
                                    }
                                },
                            }
                        }
                    },
                }
            },
        },
    }


class MlbPropForwardEvidenceTests(unittest.TestCase):
    def test_canonical_hash_is_key_order_independent(self):
        self.assertEqual(canonical_sha256({"a": 1, "b": 2}), canonical_sha256({"b": 2, "a": 1}))

    def test_pregame_capture_requires_before_scheduled_start(self):
        receipt = build_pregame_receipt(feed=_feed(), captured_at_utc="2026-09-29T22:45:00Z")
        self.assertEqual(receipt["status"], "CAPTURED")
        self.assertIn("NOT_MODEL_P", receipt["authority"])
        with self.assertRaisesRegex(MlbPropForwardEvidenceError, "AT_OR_AFTER"):
            build_pregame_receipt(feed=_feed(), captured_at_utc="2026-09-29T23:00:00Z")

    def test_settlement_rejects_non_final_feed(self):
        pregame = build_pregame_receipt(feed=_feed(), captured_at_utc="2026-09-29T22:45:00Z")
        with self.assertRaisesRegex(MlbPropForwardEvidenceError, "NOT_FINAL"):
            build_settlement_receipt(
                feed=_feed(),
                pregame_receipt=pregame,
                settled_at_utc="2026-09-30T03:00:00Z",
            )

    def test_final_settlement_emits_six_observation_only_groups(self):
        preview = _feed()
        pregame = build_pregame_receipt(feed=preview, captured_at_utc="2026-09-29T22:45:00Z")
        final = copy.deepcopy(preview)
        final["gameData"]["status"] = {"abstractGameState": "Final", "detailedState": "Final"}
        receipt = build_settlement_receipt(
            feed=final,
            pregame_receipt=pregame,
            settled_at_utc="2026-09-30T03:00:00Z",
        )
        self.assertEqual(receipt["status"], "SETTLED_OBSERVATION_ONLY")
        self.assertEqual(set(receipt["groups"]), set(EVIDENCE_GROUPS))
        for group, row in receipt["groups"].items():
            self.assertEqual(row["status"], "OBSERVED")
            self.assertNotEqual(row["status"], "PASS")
            self.assertEqual(row["evidence_group"], group)
            self.assertEqual(row["market_identities"], list(expected_market_identities(group)))
            self.assertEqual(len(row["observation_sha256"]), 64)

        self.assertEqual(receipt["groups"]["FIRST_HR_ORDERING"]["observation"][0]["batter_id"], 101)
        self.assertEqual(receipt["groups"]["HITTER_RUN_SEQUENCE"]["observation"][0]["runner_id"], 101)
        self.assertEqual(receipt["groups"]["HITTER_PA"]["observation"][0]["plate_appearances"], 1)
        pitcher_ids = {row["player_id"] for row in receipt["groups"]["PITCHER_WORKLOAD"]["observation"]}
        self.assertEqual(pitcher_ids, {201, 202})

    def test_pregame_game_identity_must_match_final(self):
        pregame = build_pregame_receipt(feed=_feed(), captured_at_utc="2026-09-29T22:45:00Z")
        pregame["game_pk"] = 123
        final = _feed("Final")
        with self.assertRaisesRegex(MlbPropForwardEvidenceError, "GAME_ID_MISMATCH"):
            build_settlement_receipt(
                feed=final,
                pregame_receipt=pregame,
                settled_at_utc="2026-09-30T03:00:00Z",
            )


if __name__ == "__main__":
    unittest.main()
