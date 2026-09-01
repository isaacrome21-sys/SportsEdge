from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from ...source_lineage import canonical_json_sha256
from .context_autopull import NFLContextError, make_observation


@dataclass(frozen=True)
class DefensiveSplit:
    team_id: str
    position_group: str
    sample_plays: int
    epa_per_play: float | None
    success_rate: float | None
    pressure_rate: float | None
    sack_rate: float | None
    explosive_rate: float | None
    man_rate: float | None
    zone_rate: float | None
    blitz_rate: float | None
    two_high_rate: float | None
    single_high_rate: float | None
    interceptions_per_game: float | None
    pass_yards_allowed_per_game: float | None
    rush_yards_allowed_per_game: float | None


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
    if not (0.0 <= x <= 1.0):
        raise NFLContextError(f"{field} outside [0,1]")
    return x


def _epa(value: Any) -> float | None:
    if value in (None, ""):
        return None
    x = float(value)
    if not (-5.0 <= x <= 5.0):
        raise NFLContextError("epa_per_play outside allowed range")
    return x


def _optional_nonnegative(value: Any, field: str) -> float | None:
    if value in (None, ""):
        return None
    x = float(value)
    if x < 0:
        raise NFLContextError(f"{field} invalid")
    return x


def build_defensive_split(row: Mapping[str, Any]) -> DefensiveSplit:
    sample = int(row.get("sample_plays") or 0)
    if sample < 0:
        raise NFLContextError("sample_plays invalid")
    team = str(row.get("team_id") or "").strip().upper()
    group = str(row.get("position_group") or "").strip().upper()
    if not team or not group:
        raise NFLContextError("team_id and position_group required")
    return DefensiveSplit(
        team_id=team,
        position_group=group,
        sample_plays=sample,
        epa_per_play=_epa(row.get("epa_per_play")),
        success_rate=_rate(row.get("success_rate"), "success_rate"),
        pressure_rate=_rate(row.get("pressure_rate"), "pressure_rate"),
        sack_rate=_rate(row.get("sack_rate"), "sack_rate"),
        explosive_rate=_rate(row.get("explosive_rate"), "explosive_rate"),
        man_rate=_rate(row.get("man_rate"), "man_rate"),
        zone_rate=_rate(row.get("zone_rate"), "zone_rate"),
        blitz_rate=_rate(row.get("blitz_rate"), "blitz_rate"),
        two_high_rate=_rate(row.get("two_high_rate"), "two_high_rate"),
        single_high_rate=_rate(row.get("single_high_rate"), "single_high_rate"),
        interceptions_per_game=_optional_nonnegative(row.get("interceptions_per_game"), "interceptions_per_game"),
        pass_yards_allowed_per_game=_optional_nonnegative(row.get("pass_yards_allowed_per_game"), "pass_yards_allowed_per_game"),
        rush_yards_allowed_per_game=_optional_nonnegative(row.get("rush_yards_allowed_per_game"), "rush_yards_allowed_per_game"),
    )


def build_defensive_matchup_provider(
    *,
    game_id: str,
    offense_team_id: str,
    defense_team_id: str,
    as_of: Any,
    source_uri: str,
    source_sha256: str,
    splits: Sequence[Mapping[str, Any]],
) -> Mapping[str, Any]:
    if not str(source_uri).startswith("https://"):
        raise NFLContextError("defensive source_uri must be https")
    pit = _utc(as_of, "as_of")
    normalized = [build_defensive_split(row) for row in splits]
    payload = {
        "game_id": str(game_id),
        "offense_team_id": str(offense_team_id).upper(),
        "defense_team_id": str(defense_team_id).upper(),
        "splits": [asdict(row) for row in normalized],
        "sample_total": sum(row.sample_plays for row in normalized),
    }
    return {
        "status": "AVAILABLE" if normalized else "MISSING",
        "payload": payload,
        "source_name": "PIT_DEFENSIVE_SPLITS",
        "source_uri": str(source_uri),
        "source_sha256": str(source_sha256),
        "observed_at": pit,
    }


def defensive_matchup_observation(**kwargs: Any):
    raw = build_defensive_matchup_provider(**kwargs)
    return make_observation(
        context_class="defensive_matchup",
        status=raw["status"],
        payload=raw["payload"],
        source_name=raw["source_name"],
        source_uri=raw["source_uri"],
        source_sha256=raw["source_sha256"],
        source_type="AUTO",
        collection_mode="AUTO",
        observed_at=raw["observed_at"],
        pit_as_of=kwargs["as_of"],
    )


def shadow_validation_key(payload: Mapping[str, Any]) -> str:
    """Stable hash for PIT/shadow evaluation; does not imply Model_P eligibility."""
    return canonical_json_sha256({"contract": "NFL_DEFENSIVE_MATCHUP_SHADOW_V1", "payload": dict(payload)})
