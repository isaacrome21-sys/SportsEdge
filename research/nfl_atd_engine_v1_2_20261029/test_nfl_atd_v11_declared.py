"""v1.1 ruling: pricer-level refusal codes are declared separately; review
refuses (SCREEN) any undeclared run-record refusal code. Test first.
"""
import inspect
import json
import unittest

import atd_engine as eng
import atd_provenance as pv
import price_nfl_atd_board_v11 as pr
from fake_github_api import FakeGitHub, ledger_to_records
from test_nfl_atd_v11_branchdata import led

BR = pv.RECORDS_BRANCH


def slate_with_reason(reason):
    api = FakeGitHub()
    ledger_to_records(api, led())
    rec = json.loads(api.get_file(BR, pv.run_record_path("S1")))
    rec["rows"].append({"status": "UNPRICED", "reason": reason, "player_id": "z",
                        "game_id": "g1"})
    # port (re-audit 353147d5): an edited run record needs a board record that
    # replays to its rows, else RUN_REPLAY_MISMATCH (now the expected outcome)
    from fake_github_api import republish_run
    republish_run(api, rec, "S2", "2026-10-25T16:45:00Z")
    return pv.load_slate(api, "S2")


class TestDeclaredLists(unittest.TestCase):
    def test_pricer_list(self):
        self.assertEqual(tuple(pr.DECLARED_PRICER_REFUSALS), ("PLAYER_TEAM_UNRESOLVED",))
        self.assertFalse(set(pr.DECLARED_PRICER_REFUSALS) & set(eng.DECLARED_UNPRICED_REASONS))
        self.assertEqual(len(eng.DECLARED_UNPRICED_REASONS), 11)

    def test_pricer_emits_only_declared(self):
        self.assertIn("DECLARED_PRICER_REFUSALS", inspect.getsource(pr.player_team_refusal))

    def test_prereg_section4_declares_it(self):
        from pathlib import Path
        t = Path(pr.__file__).with_name("PREREG_NFL_ATD_ENGINE_V1_1_DRAFT.md").read_text()
        s4 = t[t.index("## 4."):t.index("## 5.")]
        self.assertIn("DECLARED_PRICER_REFUSALS", s4)
        self.assertIn("PLAYER_TEAM_UNRESOLVED", s4)

    def test_declared_engine_and_pricer_codes_count(self):
        for code in ("UNPRICED_INVALID_PRICE", "PLAYER_TEAM_UNRESOLVED"):
            st = slate_with_reason(code)
            self.assertEqual(st["status"], "COUNTS", (code, st["reasons"]))

    def test_undeclared_code_refused(self):
        for code in ("MADE_UP", "unpriced_invalid_price"):
            st = slate_with_reason(code)
            self.assertEqual(st["status"], "SCREEN")
            self.assertIn("RUN_REFUSAL_CODE_UNDECLARED", st["reasons"])

    def test_null_reason_is_malformed_not_undeclared(self):
        # The v1.2 schema gate must refuse invalid types before code lookup.
        st = slate_with_reason(None)
        self.assertEqual(st["status"], "SCREEN")
        self.assertIn("RUN_RECORD_MALFORMED", st["reasons"])

# port (re-audit 8d86e7a9): the fake pricer is patched in by fixture, never
# registered on import.
from fake_github_api import module_fixtures as _mf
setUpModule, tearDownModule = _mf(guard=False)

if __name__ == "__main__":
    unittest.main()
