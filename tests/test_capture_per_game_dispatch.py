import asyncio
from datetime import datetime, timedelta, timezone
import threading
import unittest

from scripts.capture_per_game_dispatch import (
    DeliveryFailures, DueGame, dispatch_due_games, dispatch_due_games_async,
)


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


class HardDeadlineDispatchTests(unittest.TestCase):
    @staticmethod
    def game(game_id, seconds=0.3):
        return DueGame(game_id, None, datetime.now(timezone.utc) + timedelta(seconds=seconds))

    def test_hung_capture_cannot_block_healthy_game(self):
        async def scenario():
            delivered = []
            failures = []
            never = asyncio.Event()

            async def capture(game_id, _):
                if game_id == "hung":
                    await never.wait()
                return game_id

            async def deliver(row, cutoff):
                self.assertLess(datetime.now(timezone.utc), cutoff)
                delivered.append(row.game_id)

            async def failure(game_id, reason):
                failures.append((game_id, reason))

            return await asyncio.wait_for(dispatch_due_games_async(
                [self.game("hung"), self.game("healthy")], capture, deliver, failure,
                max_workers=2,
            ), timeout=1)

        result = asyncio.run(scenario())
        self.assertEqual([(r.game_id, r.succeeded) for r in result],
                         [("hung", False), ("healthy", True)])

    def test_slow_issue_post_does_not_block_other_delivery(self):
        async def scenario():
            delivered = []
            failures = []

            async def capture(game_id, _):
                return game_id

            async def deliver(row, _cutoff):
                if row.game_id == "slow_post":
                    await asyncio.Event().wait()
                delivered.append(row.game_id)

            async def failure(game_id, reason):
                failures.append((game_id, reason))

            results = await asyncio.wait_for(dispatch_due_games_async(
                [self.game("slow_post"), self.game("healthy")],
                capture, deliver, failure, max_workers=2,
            ), timeout=1)
            return results, delivered, failures

        results, delivered, failures = asyncio.run(scenario())
        self.assertEqual(delivered, ["healthy"])
        self.assertIn(("slow_post", "DELIVERY_WINDOW_EXPIRED"), failures)
        self.assertTrue(next(r for r in results if r.game_id == "healthy").succeeded)

    def test_missed_queued_window_records_skip_without_capture(self):
        async def scenario():
            failures = []
            called = []

            async def capture(game_id, _):
                called.append(game_id)
                return game_id

            async def deliver(row, cutoff):
                pass

            async def failure(game_id, reason):
                failures.append((game_id, reason))

            overdue = DueGame("missed", None, datetime.now(timezone.utc) - timedelta(seconds=1))
            result = await dispatch_due_games_async(
                [overdue, self.game("due")], capture, deliver, failure,
            )
            return result, called, failures

        result, called, failures = asyncio.run(scenario())
        self.assertEqual(called, ["due"])
        self.assertIn(("missed", "SCHEDULER_SKIPPED"), failures)
        self.assertFalse(result[0].succeeded)

    def test_bounded_capture_concurrency(self):
        async def scenario():
            active = 0
            maximum = 0
            failures = []

            async def capture(game_id, _):
                nonlocal active, maximum
                active += 1
                maximum = max(maximum, active)
                await asyncio.sleep(0.01)
                active -= 1
                return game_id

            async def deliver(row, cutoff):
                pass

            async def failure(game_id, reason):
                failures.append((game_id, reason))

            result = await dispatch_due_games_async(
                [self.game(str(i), seconds=0.8) for i in range(8)],
                capture, deliver, failure, max_workers=2,
            )
            return maximum, result, failures

        maximum, result, failures = asyncio.run(scenario())
        self.assertLessEqual(maximum, 2)
        self.assertEqual(sum(r.succeeded for r in result), 8)
        self.assertEqual(failures, [])

    def test_failed_failure_journal_is_fatal(self):
        async def capture(game_id, _):
            raise RuntimeError("collector failed")

        async def deliver(row, cutoff):
            pass

        async def failure(game_id, reason):
            raise OSError("durable fsync failed")

        with self.assertRaises(DeliveryFailures) as caught:
            asyncio.run(dispatch_due_games_async(
                [self.game("one")], capture, deliver, failure,
            ))
        self.assertIn("FAILURE_LEDGER_WRITE_FAILED", str(caught.exception))

    def test_refuses_sync_callbacks_before_dispatch(self):
        async def capture(game_id, _):
            return game_id

        async def failure(game_id, reason):
            pass

        with self.assertRaisesRegex(ValueError, "P0_CALLBACKS_MUST_BE_ASYNC"):
            asyncio.run(dispatch_due_games_async(
                [self.game("one")], capture, lambda *_: None, failure,
            ))


if __name__ == "__main__":
    unittest.main()
