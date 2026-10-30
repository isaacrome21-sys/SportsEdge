import unittest
from sportsedge.postgame_ledger_audit import audit, american_profit

BASE = dict(selection_id="s1", event_id="e1", sport="NFL", market="spread",
            model_version="v1", captured_at="2026-10-25T12:00:00-05:00",
            event_start="2026-10-25T12:05:00-05:00", status="WIN",
            american_odds=-110, stake=1)


class PostgameAuditTests(unittest.TestCase):
    def test_win(self): self.assertEqual(audit([BASE])["profit_units"], str(american_profit(-110, 1)))
    def test_loss(self): self.assertEqual(audit([{**BASE, "status": "LOSS"}])["profit_units"], "-1")
    def test_push(self): self.assertEqual(audit([{**BASE, "status": "PUSH"}])["profit_units"], "0")
    def test_void(self): self.assertEqual(audit([{**BASE, "status": "VOID"}])["profit_units"], "0")
    def test_duplicate(self): self.assertEqual(audit([BASE, BASE])["findings"][0][1], "DUPLICATE_SELECTION")
    def test_pending(self): self.assertEqual(audit([{**BASE, "status": "PENDING"}])["accepted"], 0)
    def test_poststart(self): self.assertEqual(audit([{**BASE, "captured_at": "2026-10-25T12:06:00-05:00"}])["accepted"], 0)
    def test_naive(self): self.assertEqual(audit([{**BASE, "captured_at": "2026-10-25T12:00:00"}])["accepted"], 0)
    def test_bad_odds(self): self.assertEqual(audit([{**BASE, "american_odds": -90}])["accepted"], 0)
    def test_nan(self): self.assertEqual(audit([{**BASE, "stake": "NaN"}])["accepted"], 0)
    def test_missing(self): self.assertEqual(audit([{"status": "WIN"}])["findings"][0][1], "MISSING_FIELDS")
    def test_plus_money(self): self.assertEqual(audit([{**BASE, "american_odds": 150}])["profit_units"], "1.5")
    def test_noninteger_odds(self): self.assertEqual(audit([{**BASE, "american_odds": -110.5}])["accepted"], 0)
    def test_invalid_first_row_does_not_poison_later_valid_row(self):
        invalid = {**BASE, "status": "PENDING"}
        result = audit([invalid, BASE])
        self.assertEqual(result["accepted"], 1)
        self.assertEqual(result["findings"][0][1], "UNSETTLED_OR_UNKNOWN")

    def test_bad_price_does_not_poison_later_valid_row(self):
        invalid = {**BASE, "american_odds": -90}
        self.assertEqual(audit([invalid, BASE])["accepted"], 1)

    def test_invalid_row(self): self.assertEqual(audit([None])["findings"][0][1], "INVALID_ROW")


if __name__ == "__main__":
    unittest.main()
