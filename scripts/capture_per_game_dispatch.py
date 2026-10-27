"""Bounded independent per-game dispatch for P0 #2792.

Workers run concurrently; each completed result is delivered immediately in
completion order, never after the slowest peer. Failures are delivered as
failures, not discarded. This is orchestration, not a sportsbook adapter.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Callable, Iterable, TypeVar

T = TypeVar("T")
R = TypeVar("R")


@dataclass(frozen=True)
class DeliveryResult:
    game_id: str
    succeeded: bool
    value: object = None
    error: str | None = None


def dispatch_due_games(
    due_games: Iterable[tuple[str, T]],
    capture_one: Callable[[str, T], R],
    deliver_one: Callable[[DeliveryResult], None],
    *,
    max_workers: int = 12,
) -> list[DeliveryResult]:
    """Submit one task per unique due game and deliver each on completion.

    A delivery failure is fatal (not reported as successful). The caller must
    durably record each attempt/failure; this helper does not confer credit.
    """
    games = list(due_games)
    ids = [game_id for game_id, _ in games]
    if not ids or len(ids) != len(set(ids)) or any(not x for x in ids):
        raise ValueError("due games must be nonempty and have unique IDs")
    if max_workers < 1:
        raise ValueError("max_workers must be positive")
    delivered = []
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
            deliver_one(result)
            delivered.append(result)
    return delivered
