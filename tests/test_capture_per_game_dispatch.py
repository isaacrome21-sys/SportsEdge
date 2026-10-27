import threading
import unittest
from scripts.capture_per_game_dispatch import dispatch_due_games, DeliveryFailures


class DispatchTests(unittest.TestCase):
    def test_fast_game_delivered_before_slow_game_finishes(self):
        slow_started = threading.Event()
        release_slow = threading.Event()
        fast_delivered = threading.Event()
        seen = []

        def capture(game_id, _payload):
            if game_id == "slow":
                slow_started.set()
                if not release_slow.wait(5):
                    raise TimeoutError("slow game stalled")
            else:
                self.assertTrue(slow_started.wait(5))
            return game_id

        def deliver(result):
            seen.append(result.game_id)
            if result.game_id == "fast":
                fast_delivered.set()
                release_slow.set()

        results = dispatch_due_games([("slow", None), ("fast", None)],
                                     capture, deliver, max_workers=2)
        self.assertTrue(fast_delivered.is_set())
        self.assertEqual(seen, ["fast", "slow"])
        self.assertTrue(all(r.succeeded for r in results))

    def test_capture_failure_is_delivered_not_dropped(self):
        def capture(game_id, payload):
            raise RuntimeError("source unavailable")
        seen = []
        dispatch_due_games([("g", None)], capture, seen.append)
        self.assertFalse(seen[0].succeeded)
        self.assertIn("source unavailable", seen[0].error)

    def test_one_delivery_failure_does_not_suppress_other_game(self):
        seen = []
        def deliver(result):
            seen.append(result.game_id)
            if result.game_id == "bad":
                raise OSError("issue API unavailable")
        with self.assertRaises(DeliveryFailures) as caught:
            dispatch_due_games([("bad", 1), ("good", 2)],
                               lambda game_id, payload: payload,
                               deliver, max_workers=1)
        self.assertEqual(seen, ["bad", "good"])
        self.assertEqual(caught.exception.errors[0][0], "bad")

    def test_duplicate_game_refused_before_dispatch(self):
        with self.assertRaises(ValueError):
            dispatch_due_games([("g", 1), ("g", 2)], lambda *_: None, lambda _: None)


if __name__ == "__main__":
    unittest.main()
