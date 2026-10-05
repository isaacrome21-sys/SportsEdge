"""PIT-safe live NFL role inputs for the unified market engine.

Uses timestamped nflverse depth charts to identify the current starting QB and
skill-player pool, then strictly-prior nflverse weekly player stats to build
market-blind workload/efficiency priors.  No current-game sportsbook fields are
accepted and no post-kickoff participation is inferred.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from hashlib import sha256
from io import StringIO
import csv
import json
from math import isfinite
from typing import Any, Callable, Iterable, Mapping, Sequence
from urllib.request import Request, urlopen

from .context_autopull import NFLContextError

PLAYER_STATS_URL = "https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_{season}.csv"
SKILL_POSITIONS = frozenset({"RB", "HB", "FB", "WR", "TE"})
TEAM_ALIASES = {"LA": "LAR", "WSH": "WAS"}
FORBIDDEN = ("odds", "price", "vig", "sportsbook", "market", "closing_line", "implied")
SIGNED_YARD_FIELDS = frozenset({"passing_yards", "rushing_yards", "receiving_yards"})
COUNT_FIELDS = (
    "attempts", "completions", "passing_yards", "passing_tds", "interceptions",
    "carries", "rushing_yards", "rushing_tds", "targets", "receptions",
    "receiving_yards", "receiving_tds",
)
DEFAULT_LOOKBACK_GAMES = 8
DEFAULT_DECAY = 0.85


def _team(value: Any) -> str:
    raw = str(value or "").strip().upper()
    return TEAM_ALIASES.get(raw, raw)


def _utc(value: Any, field: str) -> datetime:
    try:
        out = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise NFLContextError(f"{field} invalid") from exc
    if out.tzinfo is None or out.utcoffset() is None:
        raise NFLContextError(f"{field} timezone required")
    return out.astimezone(timezone.utc)


def _number(value: Any, field: str) -> float:
    if value in (None, ""):
        return 0.0
    if isinstance(value, bool):
        raise NFLContextError(f"{field} numeric required")
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise NFLContextError(f"{field} numeric required") from exc
    if not isfinite(out):
        raise NFLContextError(f"{field} finite required")
    if out < 0 and field not in SIGNED_YARD_FIELDS:
        raise NFLContextError(f"{field} nonnegative finite required")
    return out


def _assert_market_blind(node: Any, path: str = "root") -> None:
    if isinstance(node, Mapping):
        for key, value in node.items():
            low = str(key).lower()
            if any(token in low for token in FORBIDDEN):
                raise NFLContextError(f"market input forbidden at {path}.{key}")
            _assert_market_blind(value, f"{path}.{key}")
    elif isinstance(node, Sequence) and not isinstance(node, (str, bytes, bytearray)):
        for i, value in enumerate(node):
            _assert_market_blind(value, f"{path}[{i}]")


def _hash_rows(rows: Sequence[Mapping[str, Any]]) -> str:
    raw = json.dumps(list(rows), sort_keys=True, separators=(",", ":"), default=str).encode()
    return sha256(raw).hexdigest()


def fetch_nflverse_player_stats(
    *,
    seasons: Iterable[int],
    opener: Callable = urlopen,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Fetch weekly player stats and retain exact-byte receipts per season."""
    rows: list[dict[str, Any]] = []
    receipts: list[dict[str, str]] = []
    for season in sorted({int(s) for s in seasons}):
        uri = PLAYER_STATS_URL.format(season=season)
        req = Request(uri, headers={"User-Agent": "SportsEdge/1.0", "Accept": "text/csv"})
        try:
            with opener(req, timeout=30) as response:
                raw = response.read()
        except Exception as exc:
            raise NFLContextError(f"NFLVERSE player-stats fetch failed:{season}") from exc
        try:
            season_rows = [dict(row) for row in csv.DictReader(StringIO(raw.decode("utf-8-sig")))]
        except Exception as exc:
            raise NFLContextError(f"NFLVERSE player-stats CSV invalid:{season}") from exc
        if not season_rows:
            raise NFLContextError(f"NFLVERSE player-stats CSV empty:{season}")
        required = {"player_id", "player_name", "position", "season", "week", "season_type"}
        missing = required - set(season_rows[0])
        columns = set(season_rows[0])
        if missing or not ({"recent_team", "team"} & columns):
            detail = sorted(missing | (set() if {"recent_team", "team"} & columns else {"recent_team|team"}))
            raise NFLContextError("NFLVERSE player-stats schema unsupported:" + ",".join(detail))
        # nflverse 2026 renamed recent_team -> team and interceptions -> passing_interceptions.
        # Normalize the live transport schema into the frozen role-model contract.
        for row in season_rows:
            if row.get("recent_team") in (None, "") and row.get("team") not in (None, ""):
                row["recent_team"] = row.get("team")
            if row.get("interceptions") in (None, "") and row.get("passing_interceptions") not in (None, ""):
                row["interceptions"] = row.get("passing_interceptions")
        rows.extend(season_rows)
        receipts.append({"season": str(season), "source_uri": uri, "raw_sha256": sha256(raw).hexdigest()})
    return rows, receipts


def _prior_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    target_season: int,
    target_week: int,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for raw in rows:
        try:
            season = int(float(raw.get("season")))
            week = int(float(raw.get("week")))
        except (TypeError, ValueError):
            continue
        if str(raw.get("season_type") or "REG").strip().upper() != "REG":
            continue
        if season > target_season or (season == target_season and week >= target_week):
            continue
        row = dict(raw)
        row["_season"] = season
        row["_week"] = week
        out.append(row)
    return out


def _rank(row: Mapping[str, Any]) -> int | None:
    raw = row.get("pos_rank")
    if raw in (None, ""):
        return None
    try:
        value = int(float(raw))
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _latest_depth_snapshot(
    rows: Sequence[Mapping[str, Any]],
    *,
    team: str,
    as_of: datetime,
) -> tuple[datetime, list[dict[str, Any]]]:
    eligible: list[tuple[datetime, dict[str, Any]]] = []
    for raw in rows:
        if _team(raw.get("team") or raw.get("club_code")) != team:
            continue
        if raw.get("dt") in (None, ""):
            continue
        stamp = _utc(raw.get("dt"), "depth dt")
        if stamp <= as_of:
            eligible.append((stamp, dict(raw)))
    if not eligible:
        raise NFLContextError(f"PIT depth snapshot missing:{team}")
    latest = max(stamp for stamp, _ in eligible)
    return latest, [row for stamp, row in eligible if stamp == latest]


def _player_id(row: Mapping[str, Any]) -> str:
    return str(row.get("gsis_id") or row.get("player_id") or "").strip()


def _pit_injury_statuses(
    rows: Sequence[Mapping[str, Any]],
    *,
    team: str,
    target_season: int,
    target_week: int,
    as_of: datetime,
) -> dict[str, str]:
    """Latest report status known by the PIT timestamp for this team/week."""
    latest: dict[str, tuple[datetime, str]] = {}
    for raw in rows:
        try:
            season = int(float(raw.get("season")))
            week = int(float(raw.get("week")))
        except (TypeError, ValueError):
            continue
        if season != target_season or week != target_week:
            continue
        if _team(raw.get("team")) != team:
            continue
        pid = str(raw.get("gsis_id") or raw.get("player_id") or "").strip()
        if not pid or raw.get("date_modified") in (None, ""):
            continue
        modified = _utc(raw.get("date_modified"), "injury date_modified")
        if modified > as_of:
            continue
        status = str(raw.get("report_status") or "").strip().upper()
        if status not in {"", "OUT", "INACTIVE", "DOUBTFUL", "QUESTIONABLE", "PROBABLE", "ACTIVE"}:
            raise NFLContextError(f"injury report status unsupported:{status}")
        prior = latest.get(pid)
        if prior is None or modified > prior[0]:
            latest[pid] = (modified, status or "MISSING")
    return {pid: status for pid, (_stamp, status) in latest.items()}


def _weighted_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    lookback_games: int,
    decay: float,
) -> list[tuple[float, Mapping[str, Any]]]:
    ordered = sorted(rows, key=lambda r: (int(r["_season"]), int(r["_week"])))[-lookback_games:]
    if not ordered:
        return []
    return [
        (decay ** (len(ordered) - 1 - i), row)
        for i, row in enumerate(ordered)
    ]


def _weighted_avg(weighted: Sequence[tuple[float, Mapping[str, Any]]], field: str) -> float:
    den = sum(w for w, _ in weighted)
    return sum(w * _number(row.get(field), field) for w, row in weighted) / den if den > 0 else 0.0


def _weighted_rate(
    weighted: Sequence[tuple[float, Mapping[str, Any]]],
    numerator: str,
    denominator: str,
) -> float:
    num = sum(w * _number(row.get(numerator), numerator) for w, row in weighted)
    den = sum(w * _number(row.get(denominator), denominator) for w, row in weighted)
    return num / den if den > 0 else 0.0


def _role_from_history(
    rows: Sequence[Mapping[str, Any]],
    *,
    name: str,
    position: str,
    lookback_games: int,
    decay: float,
    player_id: str | None = None,
) -> dict[str, Any]:
    weighted = _weighted_rows(rows, lookback_games=lookback_games, decay=decay)
    if not weighted:
        raise NFLContextError(f"prior player history missing:{name}")
    role = {
        "pass_attempts": _weighted_avg(weighted, "attempts"),
        "completion_rate": _weighted_rate(weighted, "completions", "attempts"),
        "pass_yards_per_completion": _weighted_rate(weighted, "passing_yards", "completions"),
        "pass_td_rate": _weighted_rate(weighted, "passing_tds", "attempts"),
        "interception_rate": _weighted_rate(weighted, "interceptions", "attempts"),
        "rush_attempts": _weighted_avg(weighted, "carries"),
        "rush_yards_per_attempt": _weighted_rate(weighted, "rushing_yards", "carries"),
        "targets": _weighted_avg(weighted, "targets"),
        "catch_rate": _weighted_rate(weighted, "receptions", "targets"),
        "receiving_yards_per_reception": _weighted_rate(weighted, "receiving_yards", "receptions"),
    }
    return {
        "player": name,
        "player_id": player_id,
        "position": position,
        "role_prior": role,
        "trailing": {},
        "sample_size": 0,
        "context": {"source": "participation", "shared_workload_sigma": 0.12},
        "pit_sample_games": len(weighted),
    }


def _aggregate_week_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Aggregate arbitrary player rows to one count row per season/week."""
    grouped: dict[tuple[int, int], dict[str, Any]] = {}
    for row in rows:
        key = (int(row["_season"]), int(row["_week"]))
        agg = grouped.setdefault(
            key,
            {"_season": key[0], "_week": key[1], **{field: 0.0 for field in COUNT_FIELDS}},
        )
        for field in COUNT_FIELDS:
            agg[field] += _number(row.get(field), field)
    return [grouped[key] for key in sorted(grouped)]


def _team_week_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    team: str,
    lookback_games: int,
) -> list[dict[str, Any]]:
    filtered = [
        row for row in rows
        if _team(row.get("recent_team") or row.get("team")) == team
    ]
    return _aggregate_week_rows(filtered)[-lookback_games:]


def build_live_team_model(
    *,
    team: str,
    target_season: int,
    target_week: int,
    kickoff: Any,
    observed_at: Any,
    depth_rows: Sequence[Mapping[str, Any]],
    player_rows: Sequence[Mapping[str, Any]],
    injury_rows: Sequence[Mapping[str, Any]] = (),
    lookback_games: int = DEFAULT_LOOKBACK_GAMES,
    decay: float = DEFAULT_DECAY,
) -> dict[str, Any]:
    """Build one unified-engine team model from only pre-kickoff/pre-week data."""
    team_id = _team(team)
    kick = _utc(kickoff, "kickoff")
    seen = _utc(observed_at, "observed_at")
    if seen >= kick:
        raise NFLContextError("live role snapshot must be observed before kickoff")
    if isinstance(lookback_games, bool) or int(lookback_games) <= 0:
        raise NFLContextError("lookback_games positive integer required")
    if not 0.0 < float(decay) <= 1.0:
        raise NFLContextError("decay must be in (0,1]")
    _assert_market_blind(depth_rows)
    _assert_market_blind(player_rows)
    _assert_market_blind(injury_rows)

    prior = _prior_rows(player_rows, target_season=int(target_season), target_week=int(target_week))
    depth_at, snapshot = _latest_depth_snapshot(depth_rows, team=team_id, as_of=seen)
    injury_status = _pit_injury_statuses(
        injury_rows,
        team=team_id,
        target_season=int(target_season),
        target_week=int(target_week),
        as_of=seen,
    )
    unavailable = {pid for pid, status in injury_status.items() if status in {"OUT", "INACTIVE"}}

    qb_rows = [
        row for row in snapshot
        if str(row.get("pos_abb") or "").strip().upper() == "QB" and _rank(row) == 1 and _player_id(row)
    ]
    if len(qb_rows) != 1:
        raise NFLContextError(f"exactly one PIT starting QB required:{team_id}")
    qb_id = _player_id(qb_rows[0])
    if qb_id in unavailable:
        raise NFLContextError(f"PIT starting QB unavailable:{team_id}:{qb_id}")
    qb_name = str(qb_rows[0].get("player_name") or qb_id).strip()
    qb_hist = [row for row in prior if str(row.get("player_id") or "").strip() == qb_id]
    qb = _role_from_history(
        qb_hist,
        name=qb_name,
        position="QB",
        lookback_games=int(lookback_games),
        decay=float(decay),
        player_id=qb_id,
    )

    skill_depth: dict[str, dict[str, Any]] = {}
    for row in snapshot:
        pos = str(row.get("pos_abb") or "").strip().upper()
        rank = _rank(row)
        pid = _player_id(row)
        if pos not in SKILL_POSITIONS or pid == "" or rank is None or rank > 3:
            continue
        if pid in unavailable:
            continue
        skill_depth[pid] = dict(row)

    skills: list[dict[str, Any]] = []
    selected_ids: set[str] = set()
    for pid in sorted(skill_depth):
        history = [row for row in prior if str(row.get("player_id") or "").strip() == pid]
        if not history:
            continue
        depth = skill_depth[pid]
        name = str(depth.get("player_name") or history[-1].get("player_name") or pid).strip()
        pos = str(depth.get("pos_abb") or history[-1].get("position") or "OTHER").strip().upper()
        skills.append(_role_from_history(
            history,
            name=name,
            position=pos,
            lookback_games=int(lookback_games),
            decay=float(decay),
            player_id=pid,
        ))
        selected_ids.add(pid)

    if not skills:
        raise NFLContextError(f"PIT skill-player history missing:{team_id}")

    team_weeks = _team_week_rows(prior, team=team_id, lookback_games=int(lookback_games))
    weighted_team = _weighted_rows(team_weeks, lookback_games=int(lookback_games), decay=float(decay))
    team_pass_tds = sum(w * _number(row.get("passing_tds"), "passing_tds") for w, row in weighted_team)
    team_rush_tds = sum(w * _number(row.get("rushing_tds"), "rushing_tds") for w, row in weighted_team)
    td_total = team_pass_tds + team_rush_tds
    pass_td_share = team_pass_tds / td_total if td_total > 0 else 0.5

    team_recv_tds = sum(w * _number(row.get("receiving_tds"), "receiving_tds") for w, row in weighted_team)
    current_team_prior = [row for row in prior if _team(row.get("recent_team") or row.get("team")) == team_id]
    week_weights = {
        (int(row["_season"]), int(row["_week"])): float(weight)
        for weight, row in weighted_team
    }

    def current_td_share(pid: str, field: str, denominator: float) -> float:
        if denominator <= 0:
            return 0.0
        value = 0.0
        for row in current_team_prior:
            if str(row.get("player_id") or "").strip() != pid:
                continue
            weight = week_weights.get((int(row["_season"]), int(row["_week"])))
            if weight is not None:
                value += weight * _number(row.get(field), field)
        share = value / denominator
        if share < -1e-12 or share > 1.0 + 1e-12:
            raise NFLContextError(f"TD share out of range:{pid}:{field}")
        return min(1.0, max(0.0, share))

    qb["receiving_td_share"] = 0.0
    qb["rushing_td_share"] = current_td_share(qb_id, "rushing_tds", team_rush_tds)

    for skill in skills:
        pid = str(skill.get("player_id") or "").strip()
        if not pid or pid not in skill_depth:
            raise NFLContextError(f"skill identity binding missing:{skill.get('player')}")
        skill["receiving_td_share"] = current_td_share(pid, "receiving_tds", team_recv_tds)
        skill["rushing_td_share"] = current_td_share(pid, "rushing_tds", team_rush_tds)

    # Residual observed team usage gets one team-week-aggregated OTHER bucket.
    # This prevents multiple residual players in a week from diluting volume by
    # accidentally counting each player row as a separate game.
    residual_rows = [
        row for row in current_team_prior
        if str(row.get("player_id") or "").strip() not in selected_ids | {qb_id}
    ]
    residual_week_rows = _aggregate_week_rows(residual_rows)
    if residual_week_rows:
        other = _role_from_history(
            residual_week_rows,
            name=f"{team_id}_OTHER",
            position="OTHER",
            lookback_games=int(lookback_games),
            decay=float(decay),
            player_id=f"{team_id}:OTHER",
        )
        selected_recv = sum(float(row["receiving_td_share"]) for row in skills)
        selected_rush = float(qb["rushing_td_share"]) + sum(float(row["rushing_td_share"]) for row in skills)
        if selected_recv > 1.0 + 1e-9 or selected_rush > 1.0 + 1e-9:
            raise NFLContextError("selected TD shares exceed team mass")
        other["receiving_td_share"] = max(0.0, 1.0 - selected_recv) if team_recv_tds > 0 else 0.0
        other["rushing_td_share"] = max(0.0, 1.0 - selected_rush) if team_rush_tds > 0 else 0.0
        skills.append(other)

    return {
        "team": team_id,
        "qb": qb,
        "skill_players": skills,
        "pass_td_share": pass_td_share,
        "source": {
            "observed_at": seen.isoformat(),
            "kickoff": kick.isoformat(),
            "depth_as_of": depth_at.isoformat(),
            "depth_rows_sha256": _hash_rows(snapshot),
            "player_rows_sha256": _hash_rows(prior),
            "injury_rows_sha256": _hash_rows(injury_rows),
            "injury_status_by_player": dict(sorted(injury_status.items())),
            "target_season": int(target_season),
            "target_week": int(target_week),
            "lookback_games": int(lookback_games),
            "decay": float(decay),
        },
        "authority": {
            "research_only": True,
            "market_fields_used": False,
            "post_kickoff_role_inference": False,
            "out_inactive_players_excluded": True,
            "creates_model_p": False,
            "truth_gate_authority": False,
            "official_authority": False,
        },
    }


__all__ = [
    "DEFAULT_DECAY",
    "DEFAULT_LOOKBACK_GAMES",
    "PLAYER_STATS_URL",
    "build_live_team_model",
    "fetch_nflverse_player_stats",
]
