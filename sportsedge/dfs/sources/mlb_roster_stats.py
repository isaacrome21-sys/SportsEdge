from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from hashlib import sha256
import json
from typing import Any, Callable, Iterable, Mapping
from urllib.parse import quote, urlencode

from .common import normalize_name, normalize_team, public_json
from ..types import DKPlayer

BASE = "https://statsapi.mlb.com/api/v1"
SOURCE_NAME = "MLB_STATSAPI_ROSTER_SEASON_STATS"


def _canonical_sha(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return sha256(raw).hexdigest()


def _num(value: Any) -> float:
    if value in (None, "", "-", "--"):
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _innings_to_outs(value: Any) -> float:
    text = str(value or "").strip()
    if not text:
        return 0.0
    if "." not in text:
        return 3.0 * _num(text)
    whole, frac = text.split(".", 1)
    try:
        innings = int(whole)
        outs = int(frac[:1] or "0")
    except ValueError:
        return 0.0
    if outs not in {0, 1, 2}:
        return 3.0 * _num(text)
    return float(3 * innings + outs)


def _stat_group(stat_block: Mapping[str, Any]) -> str:
    group = stat_block.get("group") if isinstance(stat_block.get("group"), Mapping) else {}
    return str(group.get("displayName") or group.get("name") or group.get("code") or "").casefold()


def _stat_type(stat_block: Mapping[str, Any]) -> str:
    typ = stat_block.get("type") if isinstance(stat_block.get("type"), Mapping) else {}
    return str(typ.get("displayName") or typ.get("name") or typ.get("code") or "").casefold()


def _merge_stat_splits(person: Mapping[str, Any], group_name: str) -> dict[str, Any]:
    """Return the most complete season stat object for a group.

    StatsAPI can expose one aggregate split or multiple team splits after a trade.
    Prefer an aggregate-style split when present; otherwise sum additive counting
    fields and retain denominator fields for rate construction downstream.
    """
    blocks = person.get("stats") if isinstance(person.get("stats"), list) else []
    candidates: list[Mapping[str, Any]] = []
    for block in blocks:
        if not isinstance(block, Mapping) or group_name not in _stat_group(block):
            continue
        if "season" not in _stat_type(block):
            continue
        splits = block.get("splits") if isinstance(block.get("splits"), list) else []
        for split in splits:
            if isinstance(split, Mapping) and isinstance(split.get("stat"), Mapping):
                candidates.append(split)
    if not candidates:
        return {}
    aggregate = [
        split for split in candidates
        if not isinstance(split.get("team"), Mapping) or split.get("team") in ({}, None)
    ]
    if aggregate:
        return dict(aggregate[-1]["stat"])
    # Hydrated roster responses commonly contain one season split. If traded-player
    # team splits appear, additive fields are summed so current-roster identity is
    # not mistaken for current-team-only production.
    additive = {
        "gamesPlayed", "plateAppearances", "atBats", "hits", "doubles", "triples",
        "homeRuns", "baseOnBalls", "hitByPitch", "runs", "rbi", "stolenBases",
        "caughtStealing", "strikeOuts", "battersFaced", "pitchesThrown", "earnedRuns",
        "hitBatsmen", "gamesStarted", "wins", "losses", "saves", "holds",
    }
    out: dict[str, Any] = {}
    for split in candidates:
        stat = split["stat"]
        for key, value in stat.items():
            if key in additive:
                out[key] = _num(out.get(key)) + _num(value)
            elif key == "inningsPitched":
                out["outs"] = _num(out.get("outs")) + _innings_to_outs(value)
            elif key not in out:
                out[key] = value
    return out


def _hitting_row(person: Mapping[str, Any]) -> dict[str, float]:
    stat = _merge_stat_splits(person, "hitting")
    hits = _num(stat.get("hits"))
    doubles = _num(stat.get("doubles"))
    triples = _num(stat.get("triples"))
    homers = _num(stat.get("homeRuns"))
    return {
        "games": _num(stat.get("gamesPlayed")),
        "plate_appearances": _num(stat.get("plateAppearances")),
        "at_bats": _num(stat.get("atBats")),
        "hits": hits,
        "singles": max(0.0, hits - doubles - triples - homers),
        "doubles": doubles,
        "triples": triples,
        "home_runs": homers,
        "walks": _num(stat.get("baseOnBalls")),
        "hbp": _num(stat.get("hitByPitch")),
        "runs": _num(stat.get("runs")),
        "rbi": _num(stat.get("rbi")),
        "stolen_bases": _num(stat.get("stolenBases")),
        "caught_stealing": _num(stat.get("caughtStealing")),
        "strikeouts": _num(stat.get("strikeOuts")),
    }


def _pitching_row(person: Mapping[str, Any]) -> dict[str, float]:
    stat = _merge_stat_splits(person, "pitching")
    outs = _num(stat.get("outs")) or _innings_to_outs(stat.get("inningsPitched"))
    return {
        "games": _num(stat.get("gamesPlayed")),
        "games_started": _num(stat.get("gamesStarted")),
        "outs": outs,
        "batters_faced": _num(stat.get("battersFaced")),
        "pitches_thrown": _num(stat.get("pitchesThrown")),
        "strikeouts": _num(stat.get("strikeOuts")),
        "walks_allowed": _num(stat.get("baseOnBalls")),
        "hits_allowed": _num(stat.get("hits")),
        "earned_runs": _num(stat.get("earnedRuns")),
        "hbp_allowed": _num(stat.get("hitBatsmen")),
        "home_runs_allowed": _num(stat.get("homeRuns")),
        "wins": _num(stat.get("wins")),
        "losses": _num(stat.get("losses")),
    }


class MLBSeasonStatsClient:
    def __init__(self, getter: Callable[[str], dict[str, Any]] | None = None) -> None:
        self._getter = getter or public_json

    def teams(self, season: int) -> dict[str, int]:
        query = urlencode({"sportId": 1, "season": int(season)})
        payload = self._getter(f"{BASE}/teams?{query}")
        out: dict[str, int] = {}
        for row in payload.get("teams") or []:
            if not isinstance(row, Mapping) or row.get("id") is None:
                continue
            aliases = {
                normalize_team(str(row.get("abbreviation") or "")),
                normalize_team(str(row.get("teamCode") or "")),
                normalize_team(str(row.get("fileCode") or "")),
            }
            for alias in aliases:
                if alias:
                    out[alias] = int(row["id"])
        if not out:
            raise ValueError("MLB_STATSAPI_TEAM_INDEX_EMPTY")
        return out

    def roster(self, team_id: int, season: int) -> dict[str, Any]:
        hydrate = f"person(stats(group=[hitting,pitching],type=[season],season={int(season)}))"
        query = urlencode({"season": int(season), "hydrate": hydrate}, safe="[],()=")
        return self._getter(f"{BASE}/teams/{int(team_id)}/roster/Active?{query}")

    def build_snapshot(
        self,
        *,
        players: Iterable[DKPlayer],
        season: int,
        workers: int = 8,
    ) -> dict[str, Any]:
        pool = [p for p in players if not p.is_disabled]
        teams = sorted({normalize_team(p.team) for p in pool if p.team})
        team_index = self.teams(season)
        missing_teams = sorted(team for team in teams if team not in team_index)
        if missing_teams:
            raise ValueError("MLB_STATSAPI_TEAM_ID_MISSING:" + ",".join(missing_teams))

        payloads: dict[str, dict[str, Any]] = {}
        with ThreadPoolExecutor(max_workers=max(1, min(int(workers), 10))) as executor:
            futures = {
                executor.submit(self.roster, team_index[team], season): team
                for team in teams
            }
            for future in as_completed(futures):
                payloads[futures[future]] = future.result()

        by_mlb_id: dict[str, dict[str, Any]] = {}
        by_name_team: dict[tuple[str, str], dict[str, Any]] = {}
        for team, payload in payloads.items():
            for item in payload.get("roster") or []:
                if not isinstance(item, Mapping):
                    continue
                person = item.get("person") if isinstance(item.get("person"), Mapping) else {}
                mlb_id = str(person.get("id") or "").strip()
                name = str(person.get("fullName") or "").strip()
                if not mlb_id or not name:
                    continue
                row = {
                    "mlb_id": mlb_id,
                    "name": name,
                    "team": team,
                    "position": str((person.get("primaryPosition") or {}).get("abbreviation") or item.get("position", {}).get("abbreviation") or ""),
                    "hitting": _hitting_row(person),
                    "pitching": _pitching_row(person),
                }
                by_mlb_id[mlb_id] = row
                by_name_team[(normalize_name(name), team)] = row

        bound: list[dict[str, Any]] = []
        missing_players: list[str] = []
        for player in pool:
            mlb_id = str(player.raw.get("mlb_id") or "").strip()
            row = by_mlb_id.get(mlb_id) if mlb_id else None
            if row is None:
                row = by_name_team.get((normalize_name(player.name), normalize_team(player.team)))
            if row is None:
                missing_players.append(f"{player.team}:{player.name}")
                continue
            bound.append({
                "dk_player_id": player.player_id,
                "mlb_id": row["mlb_id"],
                "name": player.name,
                "team": normalize_team(player.team),
                "position": row["position"],
                "hitting": row["hitting"],
                "pitching": row["pitching"],
            })
        coverage = len(bound) / max(1, len(pool))
        if coverage < .90:
            raise ValueError(f"MLB_STATSAPI_PLAYER_BIND_COVERAGE_LOW:{coverage:.3f}")
        manifest = {
            "season": int(season),
            "team_index_sha256": _canonical_sha(team_index),
            "roster_sha256": {team: _canonical_sha(payload) for team, payload in sorted(payloads.items())},
        }
        return {
            "schema_version": 1,
            "sport": "MLB",
            "season": int(season),
            "source": SOURCE_NAME,
            "source_manifest_sha256": _canonical_sha(manifest),
            "provenance_mode": "LIVE_PIT_STATSAPI_NOT_ARCHIVAL_REPLAY",
            "team_count": len(teams),
            "player_count": len(bound),
            "coverage": coverage,
            "missing_players": sorted(missing_players),
            "players": bound,
        }
