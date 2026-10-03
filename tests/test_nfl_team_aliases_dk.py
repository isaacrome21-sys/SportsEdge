"""DraftKings screenshot team names ("PIT Steelers") resolve; mismatches still fail closed."""
from __future__ import annotations

import unittest

from sportsedge.nfl_lines_intake import parse_nfl_lines
from sportsedge.nfl_team_aliases import NflTeamAliasError, resolve_team


class DkTeamAliasTests(unittest.TestCase):
    def test_dk_prefixed_names(self):
        cases = {
            "PIT Steelers": "PIT",
            "LA Rams": "LAR",
            "LA Chargers": "LAC",
            "NY Jets": "NYJ",
            "NY Giants": "NYG",
            "WSH Commanders": "WAS",
            "SF 49ers": "SF",
            "KC Chiefs": "KC",
        }
        for text, abbr in cases.items():
            self.assertEqual(resolve_team(text), abbr, text)

    def test_mismatched_prefix_fails_closed(self):
        for text in ("PIT Browns", "NY Rams", "LA"):
            with self.assertRaises(NflTeamAliasError):
                resolve_team(text)

    def test_dk_header_parses(self):
        tickets = parse_nfl_lines("PIT Steelers @ CLE Browns\nSpread -2.5 -120 +100\nTotal 38.5 -105 -115")
        self.assertEqual((tickets[0].away, tickets[0].home), ("PIT", "CLE"))


if __name__ == "__main__":
    unittest.main()
