"""Deterministic MLB-native projected batting orders.

Projection facts come only from prior official MLB batting orders and today's
MLB game roster.  They are never marked confirmed and never use sportsbook
information.  Today's official batting order always wins in auto_runner.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import json
from typing import Any, Callable, Mapping
from urllib.request import Request, urlopen

from .mlb_source import GameSnapshot, fetch_boxscore, parse_confirmed_lineup

BASE = "https://statsapi.mlb.com"
LOOKBACK_DAYS = 14
MAX_PRIOR_ORDERS = 7
TTL_SECONDS = 900


class MLBProjectedLineupError(RuntimeError):
    pass


def _get_json(url: str, opener: Callable = urlopen) -> dict[str, Any]:
    req = Request(url, headers={"User-Agent": "SportsEdge/1.0", "Accept": "application/json"})
    try:
        with opener(req, timeout=15) as response:
            value = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise MLBProjectedLineupError(f"MLB_PROJECTED_LINEUP_FETCH_FAILED: {type(exc).__name__}: {exc}") from exc
    if not isinstance(value, dict):
        raise MLBProjectedLineupError("MLB_PROJECTED_LINEUP_PAYLOAD_NOT_OBJECT")
    return value


def _current_roster_ids(boxscore: Mapping[str, Any], side: str) -> set[int]:
    players = (((boxscore.get("teams") or {}).get(side) or {}).get("players") or {})
    if not isinstance(players, Mapping):
        return set()
    out: set[int] = set()
    for row in players.values():
        if not isinstance(row, Mapping):
            continue
        person = row.get("person") or {}
        try:
            pid = int(person.get("id"))
        except (TypeError, ValueError):
            continue
        if pid > 0:
            out.add(pid)
    return out


def _recent_team_games(*, team_id: int, target_date: date, opener: Callable = urlopen) -> list[tuple[int, str]]:
    start = target_date - timedelta(days=LOOKBACK_DAYS)
    end = target_date - timedelta(days=1)
    url = (
        f"{BASE}/api/v1/schedule?sportId=1&teamId={int(team_id)}"
        f"&startDate={start.isoformat()}&endDate={end.isoformat()}&gameType=R"
    )
    payload = _get_json(url, opener)
    rows: list[tuple[str, int, str]] = []
    for block in payload.get("dates") or []:
        for game in block.get("games") or []:
            if not isinstance(game, Mapping):
                continue
            status = ((game.get("status") or {}).get("abstractGameState"))
            if status != "Final":
                continue
            teams = game.get("teams") or {}
            away_id = (((teams.get("away") or {}).get("team") or {}).get("id"))
            home_id = (((teams.get("home") or {}).get("team") or {}).get("id"))
            if int(away_id or 0) == int(team_id):
                side = "away"
            elif int(home_id or 0) == int(team_id):
                side = "home"
            else:
                continue
            try:
                pk = int(game["gamePk"])
            except (KeyError, TypeError, ValueError):
                continue
            game_date = str(game.get("gameDate") or block.get("date") or "")
            rows.append((game_date, pk, side))
    rows.sort(reverse=True)
    return [(pk, side) for _, pk, side in rows[:MAX_PRIOR_ORDERS]]


def _primary_order(boxscore: Mapping[str, Any], side: str) -> list[dict[str, int]]:
    rows = parse_confirmed_lineup(dict(boxscore), side)
    primary = [r for r in rows if int(r.get("sequence", 0)) == 0]
    if {int(r["slot"]) for r in primary} != set(range(1, 10)):
        return []
    return [{"player_id": int(r["player_id"]), "slot": int(r["slot"]), "sequence": 0} for r in primary]


def project_team_lineup(
    *,
    game: GameSnapshot,
    side: str,
    current_boxscore: Mapping[str, Any],
    now: datetime,
    opener: Callable = urlopen,
) -> dict[str, Any] | None:
    """Project one complete 1-9 order or return None when evidence is insufficient."""
    if side not in {"away", "home"}:
        raise MLBProjectedLineupError("side must be away or home")
    if now.tzinfo is None or now.utcoffset() is None:
        raise MLBProjectedLineupError("now must be timezone-aware")
    team_id = int(game.away_id if side == "away" else game.home_id)
    roster = _current_roster_ids(current_boxscore, side)
    if len(roster) < 9:
        return None
    target = date.fromisoformat(str(game.official_date)) if game.official_date else now.astimezone(timezone.utc).date()
    recent = _recent_team_games(team_id=team_id, target_date=target, opener=opener)
    if not recent:
        return None

    # Slot/player score combines appearance frequency with strong recency.
    scores: dict[tuple[int, int], int] = {}
    evidence_games: list[int] = []
    for recency_index, (game_pk, prior_side) in enumerate(recent):
        try:
            order = _primary_order(fetch_boxscore(game_pk, opener=opener), prior_side)
        except Exception:
            continue
        if not order:
            continue
        evidence_games.append(game_pk)
        weight = MAX_PRIOR_ORDERS - recency_index
        for row in order:
            pid, slot = int(row["player_id"]), int(row["slot"])
            if pid in roster:
                scores[(slot, pid)] = scores.get((slot, pid), 0) + weight
    if not evidence_games:
        return None

    # Deterministic maximum-score assignment.  Nine slots is tiny; recurse to
    # avoid a greedy duplicate-player mistake while keeping the contract exact.
    candidates: dict[int, list[tuple[int, int]]] = {}
    for slot in range(1, 10):
        vals = [(score, pid) for (s, pid), score in scores.items() if s == slot]
        vals.sort(key=lambda x: (-x[0], x[1]))
        if not vals:
            return None
        candidates[slot] = vals

    best_score = -1
    best_ids: tuple[int, ...] | None = None
    def search(slot: int, used: set[int], total: int, chosen: list[int]) -> None:
        nonlocal best_score, best_ids
        if slot == 10:
            ids = tuple(chosen)
            if total > best_score or (total == best_score and (best_ids is None or ids < best_ids)):
                best_score, best_ids = total, ids
            return
        for score, pid in candidates[slot]:
            if pid in used:
                continue
            used.add(pid); chosen.append(pid)
            search(slot + 1, used, total + score, chosen)
            chosen.pop(); used.remove(pid)
    search(1, set(), 0, [])
    if best_ids is None or len(best_ids) != 9:
        return None

    return {
        "game_pk": int(game.game_pk),
        "team_id": team_id,
        "side": side,
        "retrieved_at": now.astimezone(timezone.utc).isoformat(),
        "ttl_seconds": TTL_SECONDS,
        "rows": [{"player_id": pid, "slot": slot, "sequence": 0} for slot, pid in enumerate(best_ids, 1)],
        "projection_source": "MLB_PRIOR_OFFICIAL_ORDERS_PLUS_CURRENT_GAME_ROSTER",
        "evidence_game_pks": evidence_games,
        "projection_status": "PROJECTED",
    }


def build_native_projected_lineups(
    *,
    schedule: list[GameSnapshot],
    boxscores_by_game: Mapping[int, Mapping[str, Any]],
    now: datetime,
    opener: Callable = urlopen,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for game in schedule:
        box = boxscores_by_game.get(int(game.game_pk))
        if not isinstance(box, Mapping):
            failures.append({"stage": "MLB_PROJECTED_LINEUP", "game_id": str(game.game_pk), "reason": "CURRENT_BOXSCORE_MISSING"})
            continue
        for side in ("away", "home"):
            # Do not waste historical calls if MLB has already posted a complete order.
            if len(_primary_order(box, side)) == 9:
                continue
            try:
                projection = project_team_lineup(game=game, side=side, current_boxscore=box, now=now, opener=opener)
                if projection is None:
                    failures.append({"stage": "MLB_PROJECTED_LINEUP", "game_id": str(game.game_pk), "side": side, "reason": "INSUFFICIENT_PRIOR_ORDER_EVIDENCE"})
                else:
                    rows.append(projection)
            except Exception as exc:
                failures.append({"stage": "MLB_PROJECTED_LINEUP", "game_id": str(game.game_pk), "side": side, "reason": f"{type(exc).__name__}: {exc}"})
    return rows, failures
