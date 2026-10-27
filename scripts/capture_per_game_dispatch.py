"""Bounded per-game capture delivery orchestration for P0 #2792.

The legacy synchronous helper remains for research callers. The async helper
has deadline-aware tasks and independent issue delivery. Neither helper is a
sportsbook adapter or a source-quote attestation.
"""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
import inspect
from typing import Awaitable, Callable, Iterable, TypeVar

T = TypeVar("T")
R = TypeVar("R")


@dataclass(frozen=True)
class DeliveryResult:
    game_id: str
    succeeded: bool
    value: object = None
    error: str | None = None


@dataclass(frozen=True)
class DueGame:
    """An already-preregistered game; this layer never changes its cutoff."""

    game_id: str
    payload: object
    cutoff_utc: datetime


class DeliveryFailures(RuntimeError):
    """One or more delivery calls failed; no failed row earns clock credit."""

    def __init__(self, errors: list[tuple[str, str]]):
        self.errors = errors
        super().__init__(f"delivery failed for {len(errors)} game(s): {errors}")


def dispatch_due_games(
    due_games: Iterable[tuple[str, T]],
    capture_one: Callable[[str, T], R],
    deliver_one: Callable[[DeliveryResult], None],
    *,
    max_workers: int = 12,
) -> list[DeliveryResult]:
    """Legacy synchronous adapter; NOT suitable for hard browser deadlines.

    ThreadPoolExecutor waits for hung threads on exit. Production P0 callers
    must use cancellable async browser tasks and dispatch_due_games_async.
    """
    games = list(due_games)
    ids = [game_id for game_id, _ in games]
    if not ids or len(ids) != len(set(ids)) or any(not x for x in ids):
        raise ValueError("due games must be nonempty and have unique IDs")
    if max_workers < 1:
        raise ValueError("max_workers must be positive")
    delivered = []
    delivery_errors = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(capture_one, game_id, payload): game_id
                   for game_id, payload in games}
        for future in as_completed(futures):
            game_id = futures[future]
            try:
                result = DeliveryResult(game_id, True, value=future.result())
            except Exception as exc:
                result = DeliveryResult(game_id, False,
                                        error=f"{type(exc).__name__}: {exc}")
            try:
                deliver_one(result)
            except Exception as exc:
                delivery_errors.append((game_id, f"{type(exc).__name__}: {exc}"))
            else:
                delivered.append(result)
    if delivery_errors:
        raise DeliveryFailures(delivery_errors)
    return delivered


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


async def dispatch_due_games_async(
    due_games: Iterable[DueGame],
    capture_one: Callable[[str, object], Awaitable[R]],
    deliver_one: Callable[[DeliveryResult, datetime], Awaitable[None]],
    record_failure: Callable[[str, str], Awaitable[None]],
    *,
    max_workers: int = 12,
    now: Callable[[], datetime] = _utc_now,
) -> list[DeliveryResult]:
    """Issue each eligible game independently; never await a hung sibling.

    All three callbacks MUST be genuinely asynchronous. In particular,
    capture_one must not create an issue, archive data or otherwise commit
    an irreversible side effect: cancellations can only stop cooperative
    async capture tasks. deliver_one MUST independently verify cutoff
    before committing its durable issue write. A browser adapter that
    blocks synchronously or ignores cancellation cannot meet #2792.
    record_failure must durably append late/skipped/error receipts and may
    not retroactively mark a failed attempt successful.

    This helper is NOT authenticated quote evidence or verified CLV.
    """
    games = list(due_games)
    ids = [g.game_id for g in games]
    if not ids or len(set(ids)) != len(ids) or any(not isinstance(x, str) or not x for x in ids):
        raise ValueError("due games must be nonempty with unique event IDs")
    if type(max_workers) is not int or max_workers < 1:
        raise ValueError("max_workers must be a positive integer")
    if not all(inspect.iscoroutinefunction(fn) for fn in
               (capture_one, deliver_one, record_failure)):
        raise ValueError("P0_CALLBACKS_MUST_BE_ASYNC")
    if any(
        not isinstance(g.cutoff_utc, datetime)
        or g.cutoff_utc.tzinfo is None
        or g.cutoff_utc.utcoffset() is None
        for g in games
    ):
        raise ValueError("all due-game cutoffs must be timezone-aware")

    sem = asyncio.Semaphore(max_workers)
    outcomes: list[DeliveryResult] = []
    ledger_errors: list[tuple[str, str]] = []

    async def fail(game_id: str, reason: str) -> DeliveryResult:
        result = DeliveryResult(game_id, False, error=reason)
        try:
            await record_failure(game_id, reason)
        except Exception as exc:
            ledger_errors.append((game_id, f"FAILURE_LEDGER_WRITE_FAILED:{type(exc).__name__}"))
        return result

    async def run_one(game: DueGame) -> DeliveryResult:
        async with sem:
            remaining = (game.cutoff_utc - now()).total_seconds()
            if remaining <= 0:
                return await fail(game.game_id, "SCHEDULER_SKIPPED")

            # asyncio.wait does not wait for a cancellation-resistant task
            # after timeout. The result of a late capture is never consumed.
            capture = asyncio.create_task(capture_one(game.game_id, game.payload))
            done, _ = await asyncio.wait({capture}, timeout=remaining)
            if not done:
                capture.cancel()
                return await fail(game.game_id, "LATE_CAPTURE")
            try:
                captured = capture.result()
            except Exception as exc:
                return await fail(game.game_id, f"CAPTURE_FAILED:{type(exc).__name__}")
            if now() >= game.cutoff_utc:
                return await fail(game.game_id, "LATE_CAPTURE")

            # Delivery runs inside the *same per-game task*, so a slow post
            # for one event cannot create a batch barrier for other games.
            result = DeliveryResult(game.game_id, True, value=captured)
            delivery = asyncio.create_task(deliver_one(result, game.cutoff_utc))
            done, _ = await asyncio.wait(
                {delivery}, timeout=max(0, (game.cutoff_utc - now()).total_seconds()),
            )
            if not done:
                delivery.cancel()
                return await fail(game.game_id, "DELIVERY_WINDOW_EXPIRED")
            try:
                delivery.result()
            except Exception as exc:
                return await fail(game.game_id, f"DELIVERY_FAILED:{type(exc).__name__}")
            if now() >= game.cutoff_utc:
                return await fail(game.game_id, "DELIVERY_WINDOW_EXPIRED")
            return result

    outcomes = await asyncio.gather(*(run_one(g) for g in games))
    if ledger_errors:
        raise DeliveryFailures(ledger_errors)
    return outcomes
