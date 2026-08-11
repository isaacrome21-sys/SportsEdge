"""Capture MLB schedule plus current batting-order state without inventing lineups."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Callable

from .mlb_source import fetch_schedule, fetch_boxscore, parse_confirmed_lineup, GameSnapshot
from .live_slate import LiveGame, make_live_game


@dataclass(frozen=True)
class CaptureResult:
    game_pk: int
    status: str
    live_game: LiveGame | None
    error: str | None


def capture_slate(
    date_iso: str,
    *,
    schedule_fetcher: Callable[[str], list[GameSnapshot]] = fetch_schedule,
    boxscore_fetcher: Callable[[int], dict[str, Any]] = fetch_boxscore,
) -> list[CaptureResult]:
    """Capture every scheduled game; never silently drop a failed game.

    A game with unavailable boxscore/lineup data is returned as CAPTURE_BLOCKED.
    That preserves slate completeness while preventing downstream candidate
    generation from treating missing lineups as confirmed.
    """
    snapshots = schedule_fetcher(date_iso)
    results: list[CaptureResult] = []
    seen: set[int] = set()
    for snap in snapshots:
        if snap.game_pk in seen:
            results.append(CaptureResult(snap.game_pk, "CAPTURE_BLOCKED", None, "duplicate game_pk in schedule"))
            continue
        seen.add(snap.game_pk)
        try:
            box = boxscore_fetcher(snap.game_pk)
            away = parse_confirmed_lineup(box, "away")
            home = parse_confirmed_lineup(box, "home")
            game = make_live_game(snap, away, home)
            if game.away_lineup.confirmed and game.home_lineup.confirmed:
                status = "LINEUPS_CONFIRMED"
            elif game.away_lineup.player_ids or game.home_lineup.player_ids:
                status = "LINEUPS_PARTIAL"
            else:
                status = "LINEUPS_UNAVAILABLE"
            results.append(CaptureResult(snap.game_pk, status, game, None))
        except Exception as exc:
            results.append(CaptureResult(snap.game_pk, "CAPTURE_BLOCKED", None, f"{type(exc).__name__}: {exc}"))
    return results


def capture_result_to_dict(result: CaptureResult) -> dict[str, Any]:
    return asdict(result)
