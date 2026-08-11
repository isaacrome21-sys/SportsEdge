import unittest
from types import SimpleNamespace

from sportsedge.game_state import GameStateError, require_mlb_pregame


class GameStateTests(unittest.TestCase):
    def test_preview_is_only_current_eligible_state(self):
        require_mlb_pregame(SimpleNamespace(status="Preview"))

    def test_live_final_missing_and_unknown_fail_closed(self):
        for state in ("Live", "Final", None, "UNKNOWN", "Scheduled"):
            with self.subTest(state=state), self.assertRaisesRegex(GameStateError, "GAME_NOT_PREGAME"):
                require_mlb_pregame(SimpleNamespace(status=state))

    def test_missing_status_attribute_fails_closed(self):
        with self.assertRaisesRegex(GameStateError, "GAME_NOT_PREGAME"):
            require_mlb_pregame(SimpleNamespace())


if __name__ == "__main__":
    unittest.main()
