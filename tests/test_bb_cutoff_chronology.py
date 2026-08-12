import json
from pathlib import Path
import tempfile
import unittest

import scripts.rebuild_pitcher_bb_v4 as rebuild


def team_box(pitcher_id, *, bf, bb, er, hits, pa=38, team_bb=3, runs=4, team_hits=8):
    return {
        "pitchers": [pitcher_id],
        "players": {
            f"ID{pitcher_id}": {
                "stats": {
                    "pitching": {
                        "gamesStarted": 1,
                        "battersFaced": bf,
                        "baseOnBalls": bb,
                        "earnedRuns": er,
                        "hits": hits,
                    }
                }
            }
        },
        "teamStats": {
            "batting": {
                "plateAppearances": pa,
                "baseOnBalls": team_bb,
                "runs": runs,
                "hits": team_hits,
            }
        },
    }


def write_box(root: Path, pk: int, away_pitcher=101, home_pitcher=201, *, away_bb=1, home_bb=2):
    payload = {
        "teams": {
            "away": team_box(away_pitcher, bf=24, bb=away_bb, er=2, hits=5),
            "home": team_box(home_pitcher, bf=25, bb=home_bb, er=3, hits=6),
        }
    }
    (root / f"{pk}.json").write_text(json.dumps(payload), encoding="utf-8")


class BBCutoffChronologyTests(unittest.TestCase):
    def test_doubleheader_game_two_cannot_see_game_one_boxscore(self):
        games = [
            {"game_pk": 1, "officialDate": "2026-07-04", "date": "2026-07-04", "year": 2026, "away_id": 10, "home_id": 20},
            {"game_pk": 2, "officialDate": "2026-07-04", "date": "2026-07-04", "year": 2026, "away_id": 10, "home_id": 20},
            {"game_pk": 3, "officialDate": "2026-07-05", "date": "2026-07-05", "year": 2026, "away_id": 10, "home_id": 20},
        ]
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_box(root, 1, away_bb=1, home_bb=2)
            write_box(root, 2, away_bb=4, home_bb=5)
            write_box(root, 3, away_bb=2, home_bb=1)
            X, walks, years, ids = rebuild.build_cutoff(games, root)

        prior_starts_idx = rebuild.FEATURES.index("prior_starts")
        opp_bb_idx = rebuild.FEATURES.index("opp_bb_hist")

        # Two starter rows per game. Both same-day games must use the identical
        # prior-day snapshot even though Game 1 and Game 2 finals differ sharply.
        self.assertEqual(X[0, prior_starts_idx], 0.0)
        self.assertEqual(X[1, prior_starts_idx], 0.0)
        self.assertEqual(X[2, prior_starts_idx], 0.0)
        self.assertEqual(X[3, prior_starts_idx], 0.0)
        self.assertEqual(X[0, opp_bb_idx], X[2, opp_bb_idx])
        self.assertEqual(X[1, opp_bb_idx], X[3, opp_bb_idx])

        # The next date may see both July 4 starts/results.
        self.assertEqual(X[4, prior_starts_idx], 2.0)
        self.assertEqual(X[5, prior_starts_idx], 2.0)
        self.assertEqual(len(walks), 6)
        self.assertEqual(list(years), [2026] * 6)
        self.assertEqual([x[0] for x in ids], [1, 1, 2, 2, 3, 3])

    def test_rebuild_is_deterministic(self):
        games = [
            {"game_pk": 1, "officialDate": "2026-07-04", "date": "2026-07-04", "year": 2026, "away_id": 10, "home_id": 20},
            {"game_pk": 2, "officialDate": "2026-07-05", "date": "2026-07-05", "year": 2026, "away_id": 20, "home_id": 10},
        ]
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_box(root, 1)
            write_box(root, 2)
            first = rebuild.build_cutoff(games, root)
            second = rebuild.build_cutoff(games, root)
        for a, b in zip(first[:3], second[:3]):
            self.assertTrue((a == b).all())
        self.assertEqual(first[3], second[3])


if __name__ == "__main__":
    unittest.main()
