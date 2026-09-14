import csv
import io
import unittest
from unittest.mock import patch

import scripts.build_nfl_signed_key_reference as mod


def fixture(rows):
    out = io.StringIO(newline="")
    cols = ["season","game_type","home_score","away_score","location","overtime"]
    w = csv.DictWriter(out, fieldnames=cols)
    w.writeheader(); w.writerows(rows)
    return out.getvalue().encode()


class NFLKeyReferenceTests(unittest.TestCase):
    def test_sign_convention_ot_and_neutral_rules_are_explicit(self):
        rows=[]
        # 1004 rows ensures the production minimum remains exercised.
        for i in range(1000):
            rows.append({"season":2024,"game_type":"REG","home_score":20,"away_score":20+(i%2),"location":"Home","overtime":"0"})
        rows += [
            {"season":2024,"game_type":"REG","home_score":24,"away_score":21,"location":"Neutral","overtime":"1"},
            {"season":2024,"game_type":"REG","home_score":21,"away_score":24,"location":"Home","overtime":"0"},
            {"season":2024,"game_type":"REG","home_score":28,"away_score":21,"location":"Home","overtime":"0"},
            {"season":2024,"game_type":"REG","home_score":21,"away_score":28,"location":"Home","overtime":"0"},
        ]
        data=fixture(rows)
        with patch.object(mod,"SOURCE_SIZE_BYTES",len(data)), patch.object(mod,"SOURCE_GIT_BLOB_SHA1",mod.git_blob_sha1(data)):
            result=mod.build(data)
        self.assertEqual(result["population"]["sign_convention"],"HOME_SCORE_MINUS_AWAY_SCORE")
        self.assertEqual(result["population"]["overtime_rule"],"FINAL_SCORE_INCLUDES_OVERTIME")
        self.assertEqual(result["population"]["neutral_sites"],"INCLUDED_USING_SOURCE_DESIGNATED_HOME")
        self.assertEqual(result["signed_keys"]["3"]["count"],1)
        self.assertEqual(result["signed_keys"]["-3"]["count"],1)
        self.assertEqual(result["signed_keys"]["7"]["count"],1)
        self.assertEqual(result["signed_keys"]["-7"]["count"],1)
        self.assertEqual(result["absolute_key_mass"]["3"]["count"],2)
        self.assertEqual(result["absolute_key_mass"]["7"]["count"],2)
        self.assertEqual(result["population"]["neutral_game_count"],1)
        self.assertEqual(result["population"]["overtime_game_count_if_source_flag_available"],1)
        for key in ("-7","-3","3","7"):
            self.assertEqual(len(result["signed_keys"][key]["wilson95"]),2)

    def test_postseason_and_out_of_window_are_excluded(self):
        rows=[{"season":2024,"game_type":"REG","home_score":20,"away_score":17,"location":"Home","overtime":"0"} for _ in range(1000)]
        rows += [
            {"season":2024,"game_type":"POST","home_score":20,"away_score":17,"location":"Home","overtime":"0"},
            {"season":2001,"game_type":"REG","home_score":20,"away_score":17,"location":"Home","overtime":"0"},
        ]
        data=fixture(rows)
        with patch.object(mod,"SOURCE_SIZE_BYTES",len(data)), patch.object(mod,"SOURCE_GIT_BLOB_SHA1",mod.git_blob_sha1(data)):
            result=mod.build(data)
        self.assertEqual(result["population"]["n"],1000)
        self.assertEqual(result["signed_keys"]["3"]["count"],1000)

    def test_source_identity_fails_closed(self):
        data=fixture([])
        with self.assertRaisesRegex(ValueError,"SOURCE_SIZE_MISMATCH"):
            mod.build(data)


if __name__ == "__main__":
    unittest.main()
