"""Offline regression coverage for the MoneyPuck research collector.

The team fixture carries the real EDM 2024-25 'all'-situations values
captured from teams_2008_to_2024.csv during the 2026-10-24 admission
probe (82 GP, 259 GF, 235 GA, xGF 276.87, xGA 228.8). Live paths run
against a fake opener returning an in-memory zip; no test touches the
network.
"""
import io
import json
import unittest
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.error import HTTPError

from scripts import collect_moneypuck as m

NOW = datetime(2026, 10, 24, 22, 30, tzinfo=timezone.utc)

TEAMS_CSV = (
    "team,season,situation,games_played,goalsFor,goalsAgainst,"
    "xGoalsFor,xGoalsAgainst,shotsOnGoalFor,shotsOnGoalAgainst\n"
    "EDM,2024,all,82,259.0,235.0,276.87,228.8,2623.0,2211.0\n"
    "EDM,2024,5on5,82,168.0,171.0,189.29,171.5,2113.0,1900.0\n"
    "WPG,2024,all,82,277.0,191.0,270.1,215.4,2600.0,2050.0\n"
)


def zip_bytes(member, text):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(member, text)
    return buffer.getvalue()


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def opener_returning(payload):
    def opener(request, timeout=None):
        return FakeResponse(payload)
    return opener


def exploding_opener(request, timeout=None):
    raise AssertionError("network must not be touched")


class MoneyPuckCollectorTests(unittest.TestCase):
    def test_default_run_makes_zero_requests(self):
        out = m.collect("teams-history", opener=exploding_opener)
        self.assertEqual(out["status"], "NO_LIVE_CALL")
        self.assertEqual(out["requests"], 0)
        self.assertTrue(out["url"].endswith(
            "historicalOneRowPerSeason/teams_2008_to_2024.zip"))

    def test_dataset_url_and_season_validation(self):
        self.assertEqual(
            m.dataset_url("shots", season="2024"),
            "https://peter-tanner.com/moneypuck/downloads/shots_2024.zip")
        for bad in ("24", "20245", "abcd", None, 2024):
            with self.assertRaises(m.IntakeRefusal):
                m.dataset_url("shots", season=bad)
        with self.assertRaises(m.IntakeRefusal):
            m.dataset_url("shifts-history")

    def test_team_season_recorded_values(self):
        rows = m.parse_rows(TEAMS_CSV)
        edm = m.team_season(rows, "EDM", 2024)
        self.assertEqual(edm, {
            "team": "EDM", "season": "2024", "situation": "all",
            "games_played": 82, "goals_for": 259, "goals_against": 235,
            "x_goals_for": 276.87, "x_goals_against": 228.8,
            "shots_on_goal_for": 2623, "shots_on_goal_against": 2211})
        five = m.team_season(rows, "EDM", 2024, situation="5on5")
        self.assertEqual(five["goals_for"], 168)
        self.assertIsNone(m.team_season(rows, "EDM", 1999))

    def test_extract_csv_requires_expected_member(self):
        good = zip_bytes("teams_2008_to_2024.csv", TEAMS_CSV)
        self.assertEqual(m.extract_csv(good, "teams_2008_to_2024.csv"),
                         TEAMS_CSV)
        wrong = zip_bytes("something_else.csv", TEAMS_CSV)
        with self.assertRaises(m.IntakeRefusal):
            m.extract_csv(wrong, "teams_2008_to_2024.csv")
        with self.assertRaises(m.IntakeRefusal):
            m.extract_csv(b"not a zip", "teams_2008_to_2024.csv")

    def test_live_collect_writes_csv_and_manifest(self):
        payload = zip_bytes("teams_2008_to_2024.csv", TEAMS_CSV)
        with TemporaryDirectory() as tmp:
            out = m.collect("teams-history", live=True, out_dir=tmp,
                            opener=opener_returning(payload), now=NOW)
            self.assertEqual(out["status"], "RESEARCH_CAPTURED")
            self.assertEqual(out["rows"], 3)
            self.assertEqual(out["seasons"], ["2024"])
            saved_csv = (Path(tmp) / out["file"]).read_text()
            self.assertEqual(saved_csv, TEAMS_CSV)
            manifest = json.loads((Path(tmp) / out["manifest"]).read_text())
        self.assertEqual(manifest["source"], "moneypuck")
        self.assertTrue(manifest["research_only"])
        self.assertFalse(manifest["pricing_input"])
        self.assertFalse(manifest["play_eligible"])
        self.assertIsNone(manifest["model_p"])
        self.assertEqual(len(manifest["zip_sha256"]), 64)
        self.assertEqual(manifest["csv_sha256"], out["csv_sha256"])

    def test_http_error_fails_closed(self):
        def opener(request, timeout=None):
            raise HTTPError(request.full_url, 404, "missing", {}, None)
        with self.assertRaises(m.IntakeRefusal):
            m.collect("teams-history", live=True, opener=opener)


if __name__ == "__main__":
    unittest.main()
