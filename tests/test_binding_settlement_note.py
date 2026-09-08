from pathlib import Path
import unittest
class SettlementNoteTests(unittest.TestCase):
    def test_record_win_not_team_result(self):self.assertIn("must not be settled from team moneyline",Path("docs/BINDING_SETTLEMENT_NOTE.md").read_text())
if __name__=="__main__":unittest.main()
