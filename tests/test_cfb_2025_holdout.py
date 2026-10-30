from __future__ import annotations

import json
from pathlib import Path
import unittest

from sportsedge.sports.cfb.holdout_2025 import (
    CFB2025HoldoutError,
    CLOSE_SEMANTICS,
    PHONE_NO_MODEL_PASS_UNPROMOTED,
    PHONE_NO_MODEL_PENDING,
    grade_cfb_2025_holdout,
    saturday_card_status,
)

ROOT = Path(__file__).resolve().parents[1]


def _lock(**overrides):
    payload = json.loads((ROOT / "config/cfb_2025_holdout_lock_v1.json").read_text())
    payload.update(overrides)
    return payload


def _row(*, pred_home, pred_away, home, away, spread, total=None, ml=None, extra_score=None):
    score = {"pred_home": pred_home, "pred_away": pred_away}
    if extra_score:
        score.update(extra_score)
    close = {"semantics": CLOSE_SEMANTICS, "home_spread": spread}
    if total is not None:
        close["total"] = total
    if ml is not None:
        close["home_moneyline"] = ml
    return {
        "game_id": "g1",
        "home_score": home,
        "away_score": away,
        "score": score,
        "cfbd_last_stored_close": close,
    }


class CFB2025HoldoutTests(unittest.TestCase):
    def test_committed_lock_denies_saturday_pricing(self):
        lock = _lock()
        self.assertEqual(lock["status"], "HOLD_PENDING")
        self.assertFalse(lock["promotion_authority"])
        self.assertFalse(lock["saturday_pricing_allowed"])
        self.assertFalse(lock["model_p_authority"])
        self.assertEqual(saturday_card_status(lock), PHONE_NO_MODEL_PENDING)
        self.assertEqual(lock["do_not_merge_as_pricing_card"], 1251)

    def test_game_freeze_registry_still_unfrozen(self):
        freeze = json.loads((ROOT / "config/cfb_game_model_freeze.json").read_text())
        self.assertEqual(freeze["status"], "UNFROZEN")
        self.assertFalse(freeze["promotion_authority"])

    def test_contaminated_score_fails_closed(self):
        lock = _lock()
        with self.assertRaisesRegex(CFB2025HoldoutError, "SCORE_CONTAMINATED"):
            grade_cfb_2025_holdout(
                [_row(pred_home=28, pred_away=21, home=31, away=17, spread=-3, extra_score={"sp_plus": 12})],
                lock=lock,
            )

    def test_wrong_close_semantics_fail_closed(self):
        lock = _lock()
        row = _row(pred_home=28, pred_away=21, home=31, away=17, spread=-3)
        row["cfbd_last_stored_close"]["semantics"] = "TIMESTAMPED_SNAPSHOT"
        with self.assertRaisesRegex(CFB2025HoldoutError, "CLOSE_SEMANTICS"):
            grade_cfb_2025_holdout([row], lock=lock)

    def test_empty_bundle_is_pending_not_pass(self):
        report = grade_cfb_2025_holdout([], lock=_lock())
        self.assertEqual(report.status, "HOLD_PENDING")
        self.assertEqual(report.phone_card_status, PHONE_NO_MODEL_PENDING)
        self.assertFalse(report.saturday_pricing_allowed)
        self.assertFalse(report.promotion_authority)

    def test_high_confidence_failure_is_hold_fail(self):
        rows = []
        for i in range(200):
            # Model strongly likes home; home fails to cover.
            rows.append(_row(pred_home=38, pred_away=10, home=14, away=21, spread=-3, total=50, ml=-180))
        report = grade_cfb_2025_holdout(rows, lock=_lock())
        self.assertEqual(report.status, "HOLD_FAIL")
        self.assertGreaterEqual(report.markets["ATS"].n_high, 40)

    def test_hold_pass_still_blocks_pricing(self):
        rows = []
        for i in range(200):
            rows.append(_row(pred_home=35, pred_away=14, home=34, away=10, spread=-3, total=48, ml=-200))
        report = grade_cfb_2025_holdout(rows, lock=_lock())
        self.assertEqual(report.status, "HOLD_PASS")
        self.assertEqual(report.phone_card_status, PHONE_NO_MODEL_PASS_UNPROMOTED)
        self.assertFalse(report.saturday_pricing_allowed)

    def test_saturday_helper_rejects_promotion_flags(self):
        with self.assertRaisesRegex(CFB2025HoldoutError, "DENY_PROMOTION"):
            saturday_card_status(_lock(promotion_authority=True))
        with self.assertRaisesRegex(CFB2025HoldoutError, "SATURDAY_PRICING"):
            saturday_card_status(_lock(saturday_pricing_allowed=True))


if __name__ == "__main__":
    unittest.main()
