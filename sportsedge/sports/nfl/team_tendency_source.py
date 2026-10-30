from __future__ import annotations

import csv
from hashlib import sha256
from io import StringIO
from statistics import mean
from typing import Any, Callable, Iterable, Mapping
from urllib.request import Request, urlopen

from ...source_lineage import canonical_json_sha256
from .context_autopull import NFLContextError

TEAM_STATS_URL = "https://github.com/nflverse/nflverse-data/releases/download/stats_team/stats_team_week_{season}.csv"
REQUIRED_COLUMNS = frozenset({
    "season", "week", "team", "season_type", "opponent_team",
    "attempts", "carries", "sacks_suffered", "passing_yards", "rushing_yards",
    "def_sacks", "def_qb_hits", "def_interceptions", "penalties", "penalty_yards",
})


def _number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise NFLContextError("NFLVERSE team-stat numeric invalid") from exc


def _integer(value: Any, field: str) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError) as exc:
        raise NFLContextError(f"NFLVERSE team-stat {field} invalid") from exc


def fetch_nflverse_team_stats(*, season: int, opener: Callable = urlopen) -> tuple[list[dict[str, Any]], str, str]:
    uri = TEAM_STATS_URL.format(season=int(season))
    req = Request(uri, headers={"User-Agent": "SportsEdge/1.0", "Accept": "text/csv"})
    try:
        with opener(req, timeout=25) as response:
            raw = response.read()
    except Exception as exc:
        raise NFLContextError("NFLVERSE team-stats fetch failed") from exc
    try:
        reader = csv.DictReader(StringIO(raw.decode("utf-8-sig")))
        fields = set(reader.fieldnames or ())
        rows = [dict(row) for row in reader]
    except Exception as exc:
        raise NFLContextError("NFLVERSE team-stats CSV invalid") from exc
    if not rows:
        raise NFLContextError("NFLVERSE team-stats CSV empty")
    missing = REQUIRED_COLUMNS - fields
    if missing:
        raise NFLContextError("NFLVERSE team-stats schema unsupported:" + ",".join(sorted(missing)))
    return rows, uri, sha256(raw).hexdigest()


def _prior_rows(
    rows: Iterable[Mapping[str, Any]], *, season: int, target_week: int, team: str, max_games: int = 5,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    target = str(team or "").strip().upper()
    for raw in rows:
        try:
            row_season = _integer(raw.get("season"), "season")
            week = _integer(raw.get("week"), "week")
        except NFLContextError:
            continue
        if row_season != int(season) or week >= int(target_week):
            continue
        if str(raw.get("season_type") or "REG").strip().upper() != "REG":
            continue
        if str(raw.get("team") or "").strip().upper() != target:
            continue
        row = dict(raw)
        row["_week"] = week
        selected.append(row)
    selected.sort(key=lambda row: int(row["_week"]))
    return selected[-int(max_games):]


def _avg(rows: list[Mapping[str, Any]], field: str) -> float | None:
    values = [_number(row.get(field)) for row in rows]
    filtered = [value for value in values if value is not None]
    return None if not filtered else float(mean(filtered))


def _sum_rate(numerator: list[float | None], denominator: list[float | None]) -> float | None:
    nums = [v for v in numerator if v is not None]
    dens = [v for v in denominator if v is not None]
    if not nums or not dens:
        return None
    den = sum(dens)
    if den <= 0:
        return None
    return float(sum(nums) / den)


def build_prior_team_tendency_providers(
    *, rows: Iterable[Mapping[str, Any]], season: int, target_week: int,
    home_team: str, away_team: str, source_uri: str, source_sha256: str,
    max_games: int = 5,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Build strictly-prior lightweight coaching and defensive context.

    The weekly team file cannot identify neutral situation, coverage shell, blitz,
    red-zone or fourth-down decision context, so those fields are never inferred.
    It does provide objective play-volume and defensive pressure-count proxies.
    """
    digest = str(source_sha256 or "").strip().lower()
    if len(digest) != 64:
        raise NFLContextError("team tendencies source_sha256 invalid")
    try:
        int(digest, 16)
    except ValueError as exc:
        raise NFLContextError("team tendencies source_sha256 invalid") from exc
    uri = str(source_uri or "").strip()
    if not uri.startswith("https://"):
        raise NFLContextError("team tendencies source_uri must be https")

    all_rows = [dict(row) for row in rows]
    by_key: dict[tuple[int, str], Mapping[str, Any]] = {}
    for row in all_rows:
        try:
            week = _integer(row.get("week"), "week")
            row_season = _integer(row.get("season"), "season")
        except NFLContextError:
            continue
        if row_season == int(season):
            by_key[(week, str(row.get("team") or "").strip().upper())] = row

    coaching_teams: list[dict[str, Any]] = []
    defensive_splits: list[dict[str, Any]] = []
    for team in (home_team, away_team):
        prior = _prior_rows(all_rows, season=season, target_week=target_week, team=team, max_games=max_games)
        if not prior:
            continue
        attempts = [_number(row.get("attempts")) for row in prior]
        carries = [_number(row.get("carries")) for row in prior]
        sacks = [_number(row.get("sacks_suffered")) for row in prior]
        offensive_plays = [
            (a or 0.0) + (c or 0.0) + (s or 0.0)
            for a, c, s in zip(attempts, carries, sacks)
        ]
        pass_rate = _sum_rate(attempts, [a + c for a, c in zip([x or 0.0 for x in attempts], [x or 0.0 for x in carries])])
        penalty_rate = _sum_rate(
            [_number(row.get("penalties")) for row in prior],
            offensive_plays,
        )
        coaching_teams.append({
            "team_id": str(team).upper(),
            "sample_weeks": [int(row["_week"]) for row in prior],
            "sample_games": len(prior),
            "overall_pass_rate": pass_rate,
            "overall_rush_rate": None if pass_rate is None else 1.0 - pass_rate,
            "offensive_plays_per_game_proxy": float(mean(offensive_plays)) if offensive_plays else None,
            "pass_attempts_per_game": _avg(prior, "attempts"),
            "carries_per_game": _avg(prior, "carries"),
            "sacks_suffered_per_game": _avg(prior, "sacks_suffered"),
            "penalties_per_play_proxy": penalty_rate,
            "neutral_pass_rate": None,
            "early_down_pass_rate": None,
            "pace_seconds_per_play": None,
            "no_huddle_rate": None,
            "fourth_down_go_rate": None,
            "two_minute_pass_rate": None,
            "red_zone_pass_rate": None,
            "unavailable_fields_reason": "WEEKLY_TEAM_STATS_LACK_SITUATIONAL_PLAY_CONTEXT",
        })

        pass_opportunities: list[float | None] = []
        pressure_events: list[float | None] = []
        opponent_pass_yards: list[float | None] = []
        opponent_rush_yards: list[float | None] = []
        for row in prior:
            week = int(row["_week"])
            opponent = str(row.get("opponent_team") or "").strip().upper()
            opp_row = by_key.get((week, opponent))
            opp_attempts = None if opp_row is None else _number(opp_row.get("attempts"))
            own_def_sacks = _number(row.get("def_sacks"))
            own_qb_hits = _number(row.get("def_qb_hits"))
            if opp_attempts is not None:
                pass_opportunities.append(opp_attempts + (own_def_sacks or 0.0))
                pressure_events.append((own_def_sacks or 0.0) + (own_qb_hits or 0.0))
            if opp_row is not None:
                opponent_pass_yards.append(_number(opp_row.get("passing_yards")))
                opponent_rush_yards.append(_number(opp_row.get("rushing_yards")))
        pressure_rate = _sum_rate(pressure_events, pass_opportunities)
        sack_rate = _sum_rate([_number(row.get("def_sacks")) for row in prior], pass_opportunities)
        defensive_splits.append({
            "team_id": str(team).upper(),
            "position_group": "ALL",
            "sample_plays": int(sum(value for value in pass_opportunities if value is not None)),
            "pressure_rate": pressure_rate,
            "sack_rate": sack_rate,
            "interceptions_per_game": _avg(prior, "def_interceptions"),
            "pass_yards_allowed_per_game": None if not opponent_pass_yards else float(mean(v for v in opponent_pass_yards if v is not None)),
            "rush_yards_allowed_per_game": None if not opponent_rush_yards else float(mean(v for v in opponent_rush_yards if v is not None)),
            "epa_per_play": None,
            "success_rate": None,
            "explosive_rate": None,
            "man_rate": None,
            "zone_rate": None,
            "blitz_rate": None,
            "two_high_rate": None,
            "single_high_rate": None,
            "unavailable_fields_reason": "WEEKLY_TEAM_STATS_LACK_COVERAGE_AND_PLAY_LEVEL_CONTEXT",
        })

    coaching = None
    if coaching_teams:
        payload = {"teams": coaching_teams, "pit_policy": "STRICTLY_PRIOR_WEEK_ONLY"}
        coaching = {
            "status": "AVAILABLE",
            "payload": payload,
            "source_name": "NFLVERSE_WEEKLY_TEAM_STATS_PRIOR_ONLY",
            "source_uri": uri,
            "source_sha256": canonical_json_sha256([digest, payload]),
        }
    defensive = None
    if defensive_splits:
        payload = {"teams": defensive_splits, "pit_policy": "STRICTLY_PRIOR_WEEK_ONLY"}
        defensive = {
            "status": "AVAILABLE",
            "payload": payload,
            "source_name": "NFLVERSE_WEEKLY_TEAM_STATS_DEFENSE_PRIOR_ONLY",
            "source_uri": uri,
            "source_sha256": canonical_json_sha256([digest, payload]),
        }
    return coaching, defensive
