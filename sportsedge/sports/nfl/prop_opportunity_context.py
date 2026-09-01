from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from .context_autopull import NFLContextError


@dataclass(frozen=True)
class PropOpportunitySnapshot:
    player_id: str
    team_id: str
    position: str
    sample_games: int
    snap_share: float | None
    route_participation: float | None
    target_share: float | None
    targets_per_route_run: float | None
    adot: float | None
    air_yard_share: float | None
    carry_share: float | None
    early_down_snap_share: float | None
    third_down_snap_share: float | None
    two_minute_snap_share: float | None
    goal_line_carries: int | None
    red_zone_targets: int | None
    red_zone_snap_share: float | None
    designed_qb_run_rate: float | None
    scramble_rate: float | None
    pass_attempt_share: float | None
    pass_rush_snap_share: float | None
    pressure_rate_allowed: float | None
    run_block_success_rate: float | None
    man_coverage_target_rate: float | None
    zone_coverage_target_rate: float | None
    explosive_target_rate: float | None


def _utc(value: Any, field: str) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError as exc:
            raise NFLContextError(f"invalid {field}") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise NFLContextError(f"{field} must be timezone-aware")
    return dt.astimezone(timezone.utc)


def _rate(value: Any, field: str) -> float | None:
    if value in (None, ""):
        return None
    x = float(value)
    if not 0.0 <= x <= 1.0:
        raise NFLContextError(f"{field} outside [0,1]")
    return x


def _nonnegative_float(value: Any, field: str) -> float | None:
    if value in (None, ""):
        return None
    x = float(value)
    if x < 0:
        raise NFLContextError(f"{field} must be nonnegative")
    return x


def _nonnegative_int(value: Any, field: str) -> int | None:
    if value in (None, ""):
        return None
    x = int(value)
    if x < 0:
        raise NFLContextError(f"{field} must be nonnegative")
    return x


def build_prop_opportunity_snapshot(row: Mapping[str, Any]) -> PropOpportunitySnapshot:
    player_id = str(row.get("player_id") or "").strip()
    team_id = str(row.get("team_id") or "").strip().upper()
    position = str(row.get("position") or "").strip().upper()
    sample_games = int(row.get("sample_games") or 0)
    if not player_id or not team_id or not position:
        raise NFLContextError("prop opportunity identity required")
    if sample_games < 0:
        raise NFLContextError("sample_games invalid")
    return PropOpportunitySnapshot(
        player_id=player_id,
        team_id=team_id,
        position=position,
        sample_games=sample_games,
        snap_share=_rate(row.get("snap_share"), "snap_share"),
        route_participation=_rate(row.get("route_participation"), "route_participation"),
        target_share=_rate(row.get("target_share"), "target_share"),
        targets_per_route_run=_rate(row.get("targets_per_route_run"), "targets_per_route_run"),
        adot=_nonnegative_float(row.get("adot"), "adot"),
        air_yard_share=_rate(row.get("air_yard_share"), "air_yard_share"),
        carry_share=_rate(row.get("carry_share"), "carry_share"),
        early_down_snap_share=_rate(row.get("early_down_snap_share"), "early_down_snap_share"),
        third_down_snap_share=_rate(row.get("third_down_snap_share"), "third_down_snap_share"),
        two_minute_snap_share=_rate(row.get("two_minute_snap_share"), "two_minute_snap_share"),
        goal_line_carries=_nonnegative_int(row.get("goal_line_carries"), "goal_line_carries"),
        red_zone_targets=_nonnegative_int(row.get("red_zone_targets"), "red_zone_targets"),
        red_zone_snap_share=_rate(row.get("red_zone_snap_share"), "red_zone_snap_share"),
        designed_qb_run_rate=_rate(row.get("designed_qb_run_rate"), "designed_qb_run_rate"),
        scramble_rate=_rate(row.get("scramble_rate"), "scramble_rate"),
        pass_attempt_share=_rate(row.get("pass_attempt_share"), "pass_attempt_share"),
        pass_rush_snap_share=_rate(row.get("pass_rush_snap_share"), "pass_rush_snap_share"),
        pressure_rate_allowed=_rate(row.get("pressure_rate_allowed"), "pressure_rate_allowed"),
        run_block_success_rate=_rate(row.get("run_block_success_rate"), "run_block_success_rate"),
        man_coverage_target_rate=_rate(row.get("man_coverage_target_rate"), "man_coverage_target_rate"),
        zone_coverage_target_rate=_rate(row.get("zone_coverage_target_rate"), "zone_coverage_target_rate"),
        explosive_target_rate=_rate(row.get("explosive_target_rate"), "explosive_target_rate"),
    )


PROP_FAMILY_FIELDS: dict[str, tuple[str, ...]] = {
    "QB_PASSING": (
        "pass_attempt_share", "pressure_rate_allowed", "snap_share",
    ),
    "WR_TE_RECEIVING": (
        "snap_share", "route_participation", "target_share", "targets_per_route_run",
        "adot", "air_yard_share", "man_coverage_target_rate", "zone_coverage_target_rate",
    ),
    "RB_RUSHING": (
        "carry_share", "snap_share", "early_down_snap_share", "run_block_success_rate",
    ),
    "RB_RECEIVING": (
        "route_participation", "target_share", "third_down_snap_share", "two_minute_snap_share",
    ),
    "ANYTIME_TD": (
        "goal_line_carries", "red_zone_targets", "red_zone_snap_share",
    ),
    "LONGEST_RECEPTION": (
        "adot", "air_yard_share", "explosive_target_rate", "man_coverage_target_rate", "zone_coverage_target_rate",
    ),
    "QB_RUSHING": (
        "designed_qb_run_rate", "scramble_rate", "red_zone_snap_share",
    ),
    "PASS_RUSH": (
        "pass_rush_snap_share", "snap_share",
    ),
}


def build_prop_opportunity_provider(
    *,
    game_id: str,
    as_of: Any,
    source_uri: str,
    source_sha256: str,
    rows: Sequence[Mapping[str, Any]],
) -> Mapping[str, Any]:
    if not str(source_uri).startswith("https://"):
        raise NFLContextError("prop opportunity source_uri must be https")
    raw_sha = str(source_sha256 or "").strip().lower()
    if len(raw_sha) != 64:
        raise NFLContextError("prop opportunity source_sha256 invalid")
    try:
        int(raw_sha, 16)
    except ValueError as exc:
        raise NFLContextError("prop opportunity source_sha256 invalid") from exc
    pit = _utc(as_of, "as_of")
    normalized = [build_prop_opportunity_snapshot(row) for row in rows]
    payload = {
        "game_id": str(game_id),
        "players": [asdict(row) for row in normalized],
        "prop_family_fields": {key: list(value) for key, value in PROP_FAMILY_FIELDS.items()},
        "process": ["OPPORTUNITY", "ROLE", "GAME_SCRIPT", "MATCHUP", "DISTRIBUTION", "MARKET_PRICE", "EV", "EXECUTION_GATE"],
        "market_fields_in_payload": False,
    }
    return {
        "status": "AVAILABLE" if normalized else "MISSING",
        "payload": payload,
        "source_name": "PIT_NFL_PROP_OPPORTUNITY_FEATURES",
        "source_uri": str(source_uri),
        "source_sha256": raw_sha,
        "observed_at": pit,
    }
