from __future__ import annotations

import csv
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.request import Request, urlopen

from .types import DKPlayer, DKSlate, parse_positions

LOBBY_URL = "https://www.draftkings.com/lobby/getcontests?sport={sport}"
DRAFTABLES_URL = "https://api.draftkings.com/draftgroups/v1/draftgroups/{draft_group_id}/draftables"


class DraftKingsError(RuntimeError):
    pass


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _num(obj: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in obj and obj[key] is not None:
            return obj[key]
    return None


def _http_json(url: str, timeout: int = 15) -> dict[str, Any]:
    req = Request(
        url,
        headers={
            "User-Agent": "SportsEdge-DFS/1.0 (+https://github.com/isaacrome21-sys/SportsEdge)",
            "Accept": "application/json,text/plain,*/*",
        },
    )
    try:
        with urlopen(req, timeout=timeout) as resp:  # noqa: S310 - intentional public HTTPS source
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        raise DraftKingsError(f"DK_HTTP_FAILED:{type(exc).__name__}:{exc}") from exc
    if not isinstance(payload, dict):
        raise DraftKingsError("DK_JSON_SHAPE_INVALID")
    return payload


class DraftKingsClient:
    """Thin, fail-closed client around DraftKings' public-facing lobby/draft-group JSON."""

    def __init__(self, getter: Callable[[str], dict[str, Any]] | None = None) -> None:
        self._getter = getter or _http_json

    def lobby(self, sport: str) -> dict[str, Any]:
        return self._getter(LOBBY_URL.format(sport=sport.upper()))

    def discover_slates(self, sport: str) -> list[DKSlate]:
        sport = sport.upper()
        payload = self.lobby(sport)
        contests = payload.get("Contests") or payload.get("contests") or []
        groups = payload.get("DraftGroups") or payload.get("draftGroups") or []
        group_meta: dict[int, dict[str, Any]] = {}
        for g in groups if isinstance(groups, list) else []:
            if not isinstance(g, dict):
                continue
            gid = _num(g, "DraftGroupId", "draftGroupId", "id")
            if gid is None:
                continue
            try:
                group_meta[int(gid)] = g
            except (TypeError, ValueError):
                continue

        best: dict[int, DKSlate] = {}
        for c in contests if isinstance(contests, list) else []:
            if not isinstance(c, dict):
                continue
            gid = _num(c, "dg", "DraftGroupId", "draftGroupId")
            if gid is None:
                continue
            try:
                gid_i = int(gid)
            except (TypeError, ValueError):
                continue
            g = group_meta.get(gid_i, {})
            start = _parse_dt(_num(c, "sd", "StartDate", "startDate", "startTime") or _num(g, "StartDate", "startDate", "startTime"))
            if start is None:
                continue
            game_type = _num(c, "gameTypeId", "GameTypeId", "gt") or _num(g, "GameTypeId", "gameTypeId")
            game_count = _num(c, "gameCount", "GameCount") or _num(g, "GameCount", "gameCount")
            contest_name = str(_num(c, "n", "name", "Name") or "")
            slate = DKSlate(
                sport=sport,
                draft_group_id=gid_i,
                start_time=start,
                name=str(_num(g, "DraftGroupTag", "draftGroupTag", "name") or contest_name),
                game_count=int(game_count) if game_count is not None else None,
                game_type_id=int(game_type) if game_type is not None else None,
                contest_id=int(_num(c, "id", "ContestId", "contestId")) if _num(c, "id", "ContestId", "contestId") is not None else None,
                contest_name=contest_name,
                entry_fee=float(_num(c, "a", "entryFee", "EntryFee")) if _num(c, "a", "entryFee", "EntryFee") is not None else None,
                total_prizes=float(_num(c, "po", "totalPrizes", "TotalPrizes")) if _num(c, "po", "totalPrizes", "TotalPrizes") is not None else None,
                raw={"contest": c, "draft_group": g},
            )
            prior = best.get(gid_i)
            if prior is None or (slate.total_prizes or 0.0) > (prior.total_prizes or 0.0):
                best[gid_i] = slate

        for gid_i, g in group_meta.items():
            if gid_i in best:
                continue
            start = _parse_dt(_num(g, "StartDate", "startDate", "startTime"))
            if start is None:
                continue
            best[gid_i] = DKSlate(
                sport=sport,
                draft_group_id=gid_i,
                start_time=start,
                name=str(_num(g, "DraftGroupTag", "draftGroupTag", "name") or ""),
                game_count=int(_num(g, "GameCount", "gameCount")) if _num(g, "GameCount", "gameCount") is not None else None,
                game_type_id=int(_num(g, "GameTypeId", "gameTypeId")) if _num(g, "GameTypeId", "gameTypeId") is not None else None,
                raw={"draft_group": g},
            )
        return sorted(best.values(), key=lambda s: (s.start_time, s.draft_group_id))

    def load_salary_csv(self, path: str | Path) -> list[DKPlayer]:
        """Load an official user-exported DraftKings salary CSV as transport fallback."""
        players: list[DKPlayer] = []
        with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
            rows = csv.DictReader(handle)
            for row in rows:
                pid = row.get("ID") or row.get("Id") or row.get("id")
                name = row.get("Name") or row.get("Name + ID") or ""
                salary = row.get("Salary")
                team = str(row.get("TeamAbbrev") or row.get("TeamAbbreviation") or "").upper()
                if not pid or not salary or not name:
                    continue
                if " (" in name and row.get("Name") is None:
                    name = name.rsplit(" (", 1)[0]
                positions = parse_positions(row.get("Position") or row.get("Roster Position") or "")
                game_info = str(row.get("Game Info") or "")
                matchup = game_info.split(" ", 1)[0].upper()
                opponent = ""
                if "@" in matchup:
                    away, home = matchup.split("@", 1)
                    if team == away:
                        opponent = home
                    elif team == home:
                        opponent = away
                fppg = None
                try:
                    fppg = float(row.get("AvgPointsPerGame") or "")
                except ValueError:
                    pass
                try:
                    salary_i = int(float(salary))
                except (TypeError, ValueError):
                    continue
                players.append(DKPlayer(
                    player_id=str(pid),
                    name=str(name).strip(),
                    team=team,
                    opponent=opponent,
                    positions=positions,
                    salary=salary_i,
                    dk_fppg=fppg,
                    raw={"salary_csv": dict(row)},
                ))
        if not players:
            raise DraftKingsError("DK_SALARY_CSV_EMPTY")
        return players

    def fetch_draftables(self, draft_group_id: int) -> list[DKPlayer]:
        payload = self._getter(DRAFTABLES_URL.format(draft_group_id=int(draft_group_id)))
        rows = payload.get("draftables") or payload.get("Draftables") or []
        if not isinstance(rows, list):
            raise DraftKingsError("DK_DRAFTABLES_SHAPE_INVALID")
        players: list[DKPlayer] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            disabled = bool(row.get("isDisabled", False))
            salary = row.get("salary")
            if salary is None:
                continue
            comp = row.get("competition") if isinstance(row.get("competition"), dict) else {}
            team = str(row.get("teamAbbreviation") or row.get("team") or "").upper()
            game_name = str(comp.get("name") or "")
            opponent = ""
            if " @ " in game_name:
                away, home = [x.strip().upper() for x in game_name.split(" @ ", 1)]
                if team == away:
                    opponent = home
                elif team == home:
                    opponent = away
            stat_attrs = row.get("draftStatAttributes") if isinstance(row.get("draftStatAttributes"), list) else []
            fppg = None
            for attr in stat_attrs:
                if not isinstance(attr, dict):
                    continue
                if attr.get("id") == 90 or str(attr.get("name", "")).lower() in {"fppg", "fantasy points per game"}:
                    try:
                        fppg = float(attr.get("value"))
                    except (TypeError, ValueError):
                        pass
                    break
            pid = row.get("playerDkId") or row.get("playerId") or row.get("draftableId")
            if pid is None:
                continue
            positions = parse_positions(row.get("position") or row.get("rosterSlot") or "")
            if not positions:
                continue
            players.append(
                DKPlayer(
                    player_id=str(pid),
                    name=str(row.get("displayName") or row.get("name") or "").strip(),
                    team=team,
                    opponent=opponent,
                    positions=positions,
                    salary=int(salary),
                    game_id=str(comp.get("competitionId") or ""),
                    game_start=_parse_dt(comp.get("startTime")),
                    dk_fppg=fppg,
                    status=str(row.get("status") or ""),
                    is_disabled=disabled,
                    draftable_id=str(row.get("draftableId") or ""),
                    raw=row,
                )
            )
        if not players:
            raise DraftKingsError("DK_DRAFTABLES_EMPTY")
        return players


def resolve_slate(slates: Iterable[DKSlate], *, requested_start: datetime, tolerance_minutes: int = 20) -> DKSlate:
    if requested_start.tzinfo is None:
        raise ValueError("DFS_REQUESTED_START_MUST_BE_TIMEZONE_AWARE")
    requested = requested_start.astimezone(timezone.utc)
    ranked = sorted(slates, key=lambda s: (abs((s.start_time - requested).total_seconds()), -(s.game_count or 0), -(s.total_prizes or 0.0)))
    if not ranked:
        raise DraftKingsError("DK_NO_SLATES_DISCOVERED")
    delta = abs((ranked[0].start_time - requested).total_seconds()) / 60.0
    if delta > tolerance_minutes:
        raise DraftKingsError(f"DK_SLATE_NOT_FOUND_WITHIN_{tolerance_minutes}M")
    return ranked[0]
