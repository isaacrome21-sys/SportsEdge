from __future__ import annotations

import csv
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from sportsedge.football_prop_run_machine import canonical_hash
from sportsedge.sports.cfb.prop_artifact_training import fit_cfb_prop_artifact


FIELDS = [
    "game_id", "season", "seasonType", "status_type_completed",
    "homeTeamId", "awayTeamId", "homeTeamName", "awayTeamName",
    "start.pos_team.id", "start.pos_team.name", "pass", "rush", "sack",
    "pass_attempt", "completion", "EPA_success", "statYardage", "int",
    "fumble_lost", "penalty_no_play", "start.adj_TimeSecsRem", "down",
    "start.yardsToEndzone", "fg_attempt", "fg_made", "pointAfterAttempt.value",
    "type.text", "pos_score_pts", "gameSpread", "overUnder", "homeTeamSpread",
]


def _row(*, game: str, team_id: str, team: str, opponent_id: str, opponent: str,
         clock: int, kind: str = "rush", yards: int = 5, success: bool = True,
         completion: bool = False, interception: bool = False, fumble_lost: bool = False,
         down: int = 1, yte: int = 70, fg_attempt: bool = False, fg_made: bool = False,
         try_value: str = "", type_text: str = "", points: str = "",
         spread: str = "-3.5", total: str = "55.5") -> dict[str, str]:
    return {
        "game_id": game, "season": "2025", "seasonType": "2",
        "status_type_completed": "TRUE", "homeTeamId": team_id,
        "awayTeamId": opponent_id, "homeTeamName": team, "awayTeamName": opponent,
        "start.pos_team.id": team_id, "start.pos_team.name": team,
        "pass": "TRUE" if kind == "pass" else "FALSE",
        "rush": "TRUE" if kind == "rush" else "FALSE", "sack": "FALSE",
        "pass_attempt": "TRUE" if kind == "pass" else "FALSE",
        "completion": "TRUE" if completion else "FALSE",
        "EPA_success": "TRUE" if success else "FALSE", "statYardage": str(yards),
        "int": "TRUE" if interception else "FALSE",
        "fumble_lost": "TRUE" if fumble_lost else "FALSE", "penalty_no_play": "FALSE",
        "start.adj_TimeSecsRem": str(clock), "down": str(down),
        "start.yardsToEndzone": str(yte), "fg_attempt": "TRUE" if fg_attempt else "FALSE",
        "fg_made": "TRUE" if fg_made else "FALSE", "pointAfterAttempt.value": try_value,
        "type.text": type_text, "pos_score_pts": points,
        "gameSpread": spread, "overUnder": total, "homeTeamSpread": spread,
    }


def _fixture(path: Path, *, market_variant: bool = False) -> None:
    rows: list[dict[str, str]] = []
    for idx, (team_id, team, opp_id, opp) in enumerate((
        ("1", "Alpha", "2", "Beta"), ("2", "Beta", "1", "Alpha")
    )):
        game = f"g{idx+1}"
        clock = 3600
        for play in range(8):
            kind = "pass" if play % 2 == 0 else "rush"
            clock -= 25
            rows.append(_row(
                game=game, team_id=team_id, team=team, opponent_id=opp_id, opponent=opp,
                clock=clock, kind=kind, yards=25 if play == 0 else 6,
                completion=(kind == "pass"), down=4 if play == 6 else 1,
                yte=30 if play == 6 else 70,
                fg_attempt=(play == 6), fg_made=(play == 6),
                spread="99" if market_variant else "-3.5",
                total="1" if market_variant else "55.5",
            ))
        rows.append(_row(game=game, team_id=team_id, team=team, opponent_id=opp_id, opponent=opp,
                         clock=3300, kind="admin", try_value="1", type_text="Extra Point Good", points="1"))
        rows.append(_row(game=game, team_id=team_id, team=team, opponent_id=opp_id, opponent=opp,
                         clock=3290, kind="admin", try_value="2", type_text="Two-Point Conversion Good", points="2"))
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


class CFBPropArtifactTrainingTests(unittest.TestCase):
    def _fit(self, path: Path):
        with patch("sportsedge.sports.cfb.prop_artifact_training.MIN_TEAM_COUNT", 2), patch(
            "sportsedge.sports.cfb.prop_artifact_training.MIN_SCRIMMAGE_PLAYS", 4
        ):
            return fit_cfb_prop_artifact(
                [path], code_git_sha="a" * 40,
                artifact_version="CFB_PROP_TEST_V1", seasons=[2025]
            )

    def test_fits_market_blind_cfb_artifact(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / "play_by_play_2025.csv"
            _fixture(path)
            artifact, diagnostics = self._fit(path)
        self.assertEqual(artifact["sport"], "CFB")
        self.assertEqual(artifact["schema_version"], "FOOTBALL_PROP_MODEL_ARTIFACT_V1")
        self.assertEqual(set(artifact["team_drive_profiles"]), {"Alpha", "Beta"})
        self.assertEqual(set(artifact["team_special_teams_rates"]), {"Alpha", "Beta"})
        self.assertEqual(diagnostics["status"], "PASS")
        self.assertFalse(diagnostics["governance"]["sportsbook_fields_consumed"])
        self.assertEqual(len(canonical_hash(artifact)), 64)

    def test_sportsbook_columns_cannot_change_fitted_artifact(self):
        with TemporaryDirectory() as temp:
            first = Path(temp) / "a.csv"
            second = Path(temp) / "b.csv"
            _fixture(first, market_variant=False)
            _fixture(second, market_variant=True)
            artifact_a, _ = self._fit(first)
            artifact_b, _ = self._fit(second)
        # Source-manifest SHA changes because the frozen source bytes changed; the
        # predictive profiles themselves must remain byte-for-byte identical.
        self.assertEqual(artifact_a["team_drive_profiles"], artifact_b["team_drive_profiles"])
        self.assertEqual(artifact_a["team_special_teams_rates"], artifact_b["team_special_teams_rates"])

    def test_penalty_no_play_and_nonregular_rows_do_not_enter_fit(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / "play_by_play_2025.csv"
            _fixture(path)
            rows = list(csv.DictReader(path.open(encoding="utf-8")))
            bad = dict(rows[0]); bad["penalty_no_play"] = "TRUE"; bad["statYardage"] = "99"
            post = dict(rows[0]); post["seasonType"] = "3"; post["statYardage"] = "99"
            with path.open("a", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=FIELDS)
                writer.writerow(bad); writer.writerow(post)
            artifact, _ = self._fit(path)
        self.assertLess(artifact["team_drive_profiles"]["Alpha"]["explosive_rate"], 0.5)


if __name__ == "__main__":
    unittest.main()
