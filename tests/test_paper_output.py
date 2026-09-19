from __future__ import annotations

import unittest

from sportsedge.paper_output import assert_not_official, paper_candidate


class TestPaperOutput(unittest.TestCase):
    def test_paper_candidate_cannot_be_official(self):
        row = paper_candidate(
            sport="CFB",
            market="spread",
            selection="HOME",
            note="Visible model output only.",
        )
        self.assertEqual(row["output_class"], "PAPER")
        self.assertEqual(row["label"], "PAPER_NOT_OFFICIAL")
        self.assertIs(row["official_authority"], False)
        assert_not_official(row)

    def test_assert_rejects_official_flag(self):
        with self.assertRaisesRegex(ValueError, "CANNOT_SET_OFFICIAL"):
            assert_not_official({"official_authority": True, "output_class": "PAPER"})


if __name__ == "__main__":
    unittest.main()
