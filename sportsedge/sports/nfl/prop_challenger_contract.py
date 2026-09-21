"""Strict research contract for the NFL role-based prop challenger.

This wrapper is the only supported card/ledger entry point for the challenger.
It keeps the underlying shared simulation research-only while enforcing:
- point-in-time role inputs;
- hash-bound frozen context multipliers;
- prop-only card and ledger identities;
- player/component correlation grouping so related rows are not counted as
  independent plays.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from sportsedge.sports.nfl.prop_role_challenger import (
    AUTHORITY_FOOTER,
    PropQuoteEvaluation,
    RoleProjection,
    apply_context,
    stabilize_role,
)

PROP_CARD_SCHEMA = "SPORTSEDGE_NFL_PROP_RESEARCH_CARD_V1"
PROP_LEDGER_SCHEMA = "SPORTSEDGE_NFL_PROP_RESEARCH_LEDGER_V1"
PROP_LEDGER_DIR = "ledger/nfl_prop_research"
STATUS = "RESEARCH_ONLY_NO_MODEL_P"
DEFAULT_POLICY_PATH = Path("config/research/nfl_prop_challenger_context_v1.json")

_COMPONENT = {
    "PASS_ATTEMPTS": "USAGE",
    "COMPLETIONS": "USAGE",
    "RUSH_ATTEMPTS": "USAGE",
    "RECEPTIONS": "USAGE",
    "PASSING_YARDS": "YARDAGE",
    "RUSHING_YARDS": "YARDAGE",
    "RECEIVING_YARDS": "YARDAGE",
    "RUSH_RECEIVING_YARDS": "YARDAGE",
    "PASSING_TDS": "TD",
    "INTERCEPTIONS": "TURNOVER",
}


class PropContractError(ValueError):
    pass


def _parse_time(value: Any, name: str) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError as exc:
            raise PropContractError(f"BAD_TIMESTAMP:{name}") from exc
    if dt.tzinfo is None:
        raise PropContractError(f"TIMESTAMP_TIMEZONE_MISSING:{name}")
    return dt.astimezone(timezone.utc)


def _load_policy(path: Path = DEFAULT_POLICY_PATH) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    policy = json.loads(raw)
    if policy.get("policy_id") != "NFL_PROP_CHALLENGER_CONTEXT_V1":
        raise PropContractError("CONTEXT_POLICY_ID_MISMATCH")
    if any(bool(v) for v in (policy.get("authority") or {}).values()):
        raise PropContractError("CONTEXT_POLICY_AUTHORITY_ESCALATION")
    return policy, sha256(raw).hexdigest()


@dataclass(frozen=True)
class PITRoleProjection:
    role: RoleProjection
    as_of: str
    current_game_id: str
    projected_role_retrieved_at: str
    max_history_observed_at: str | None
    status: str = STATUS
    authority_footer: str = AUTHORITY_FOOTER


@dataclass(frozen=True)
class FrozenContextProjection:
    role: RoleProjection
    policy_id: str
    policy_sha256: str
    multipliers: Mapping[str, float]
    status: str = STATUS
    authority_footer: str = AUTHORITY_FOOTER


@dataclass(frozen=True)
class PropCardRow:
    rank: int
    entity_id: str
    market: str
    side: str
    line: float
    book: str
    price_american: int
    estimate_p: float
    push_p: float
    market_no_vig_p: float
    edge_probability_points: float
    ev_per_dollar: float
    component: str
    component_group_id: str
    correlation_group_id: str
    independence_unit_id: str


@dataclass(frozen=True)
class PropCard:
    schema: str
    rows: tuple[PropCardRow, ...]
    independent_play_count: int
    component_group_count: int
    status: str = STATUS
    authority_footer: str = AUTHORITY_FOOTER


def prepare_pit_role(
    *,
    entity_id: str,
    history: Sequence[Mapping[str, Any]],
    projected_role: Mapping[str, Any],
    as_of: Any,
    current_game_id: str,
    availability_probability: float = 1.0,
    decay: float = 0.82,
    shrink_games: float = 4.0,
    min_history_games: int = 3,
) -> PITRoleProjection:
    """Build a role estimate using only information available before ``as_of``.

    Every history row must carry ``game_id`` and ``observed_at``. Rows from the
    current game are forbidden even if they are otherwise timestamped. This
    explicitly blocks realized same-game snaps/usage from entering the fallback.
    ``projected_role`` must carry ``retrieved_at`` and may not be created after
    the decision timestamp.
    """
    if not current_game_id:
        raise PropContractError("CURRENT_GAME_ID_REQUIRED")
    cutoff = _parse_time(as_of, "as_of")
    projected_at = _parse_time(projected_role.get("retrieved_at"), "projected_role.retrieved_at")
    if projected_at > cutoff:
        raise PropContractError("PROJECTED_ROLE_FROM_FUTURE")

    clean_history: list[dict[str, Any]] = []
    max_seen: datetime | None = None
    for row in history:
        game_id = str(row.get("game_id") or "")
        if not game_id:
            raise PropContractError("HISTORY_GAME_ID_REQUIRED")
        observed = _parse_time(row.get("observed_at"), "history.observed_at")
        if game_id == current_game_id:
            raise PropContractError("SAME_GAME_REALIZED_USAGE_FORBIDDEN")
        if observed >= cutoff:
            raise PropContractError("HISTORY_NOT_STRICTLY_PRIOR")
        max_seen = observed if max_seen is None or observed > max_seen else max_seen
        clean_history.append({
            k: v for k, v in row.items()
            if k not in {"game_id", "observed_at", "actual_same_game_snaps", "same_game_snaps"}
        })

    if "actual_same_game_snaps" in projected_role or "same_game_snaps" in projected_role:
        raise PropContractError("SAME_GAME_REALIZED_USAGE_FORBIDDEN")
    clean_projected = {
        k: v for k, v in projected_role.items()
        if k not in {"retrieved_at", "game_id", "source"}
    }
    role = stabilize_role(
        entity_id=entity_id,
        history=clean_history,
        projected_role=clean_projected,
        availability_probability=availability_probability,
        decay=decay,
        shrink_games=shrink_games,
        min_history_games=min_history_games,
    )
    return PITRoleProjection(
        role=role,
        as_of=cutoff.isoformat().replace("+00:00", "Z"),
        current_game_id=current_game_id,
        projected_role_retrieved_at=projected_at.isoformat().replace("+00:00", "Z"),
        max_history_observed_at=(max_seen.isoformat().replace("+00:00", "Z") if max_seen else None),
    )


def _bounded(value: float, bounds: Sequence[float]) -> float:
    return max(float(bounds[0]), min(float(bounds[1]), float(value)))


def apply_frozen_context(
    pit_role: PITRoleProjection,
    *,
    context: Mapping[str, Any],
    policy_path: Path = DEFAULT_POLICY_PATH,
) -> FrozenContextProjection:
    """Apply only the versioned V1 research coefficients and return their hash."""
    policy, policy_sha = _load_policy(policy_path)
    inputs = policy["inputs"]

    def numeric(name: str, default: float = 0.0) -> float:
        value = float(context.get(name, default))
        spec = inputs[name]
        if value < float(spec["min"]) or value > float(spec["max"]):
            raise PropContractError(f"CONTEXT_INPUT_OUT_OF_RANGE:{name}")
        return value

    proe = numeric("team_proe_z")
    pass_epa = numeric("opponent_pass_epa_z")
    rush_epa = numeric("opponent_rush_epa_z")
    wind = numeric("wind_mph")
    roof_closed = bool(context.get("roof_closed", False))
    coeff = policy["coefficients"]
    bounds = policy["multiplier_bounds"]

    pass_mult = 1.0 + coeff["pass_volume"]["team_proe_z"] * proe + coeff["pass_volume"]["opponent_pass_epa_z"] * pass_epa
    rush_mult = 1.0 + coeff["rush_volume"]["team_proe_z"] * proe + coeff["rush_volume"]["opponent_rush_epa_z"] * rush_epa
    target_mult = 1.0 + coeff["target_volume"]["team_proe_z"] * proe + coeff["target_volume"]["opponent_pass_epa_z"] * pass_epa

    if not roof_closed:
        if wind >= coeff["pass_volume"]["high_wind_threshold_mph"]:
            pass_mult *= coeff["pass_volume"]["high_wind_multiplier"]
        if wind >= coeff["rush_volume"]["high_wind_threshold_mph"]:
            rush_mult *= coeff["rush_volume"]["high_wind_multiplier"]
        if wind >= coeff["target_volume"]["high_wind_threshold_mph"]:
            target_mult *= coeff["target_volume"]["high_wind_multiplier"]

    multipliers = {
        "pass_volume_multiplier": _bounded(pass_mult, bounds),
        "rush_volume_multiplier": _bounded(rush_mult, bounds),
        "target_multiplier": _bounded(target_mult, bounds),
    }
    adjusted = apply_context(pit_role.role, multipliers)
    return FrozenContextProjection(
        role=adjusted,
        policy_id=policy["policy_id"],
        policy_sha256=policy_sha,
        multipliers=multipliers,
    )


def component_for_market(market: str) -> str:
    key = str(market).upper()
    if key not in _COMPONENT:
        raise PropContractError(f"UNSUPPORTED_COMPONENT_MARKET:{market}")
    return _COMPONENT[key]


def build_prop_card(evaluations: Sequence[PropQuoteEvaluation]) -> PropCard:
    """Build the prop-only card and count correlated rows conservatively.

    Multiple rows for the same player remain visible, but all of them share one
    ``independence_unit_id``. Therefore three edges on the same player count as
    one independent play. Component grouping is preserved separately for usage,
    yardage, TD and turnover evidence accounting.
    """
    ordered = sorted(
        evaluations,
        key=lambda row: (-row.ev_per_dollar, -row.edge_probability_points, row.entity_id, row.market, row.side),
    )
    rows: list[PropCardRow] = []
    for rank, ev in enumerate(ordered, start=1):
        component = component_for_market(ev.market)
        rows.append(PropCardRow(
            rank=rank,
            entity_id=ev.entity_id,
            market=ev.market,
            side=ev.side,
            line=ev.line,
            book=ev.book,
            price_american=ev.price_american,
            estimate_p=ev.estimate_p,
            push_p=ev.push_p,
            market_no_vig_p=ev.market_no_vig_p,
            edge_probability_points=ev.edge_probability_points,
            ev_per_dollar=ev.ev_per_dollar,
            component=component,
            component_group_id=f"{ev.entity_id}:{component}",
            correlation_group_id=f"PLAYER:{ev.entity_id}",
            independence_unit_id=f"PLAYER:{ev.entity_id}",
        ))
    return PropCard(
        schema=PROP_CARD_SCHEMA,
        rows=tuple(rows),
        independent_play_count=len({row.independence_unit_id for row in rows}),
        component_group_count=len({row.component_group_id for row in rows}),
    )


def make_prop_ledger(card: PropCard, *, card_id: str, captured_at: Any) -> dict[str, Any]:
    if not card_id:
        raise PropContractError("CARD_ID_REQUIRED")
    stamp = _parse_time(captured_at, "captured_at").isoformat().replace("+00:00", "Z")
    payload = {
        "schema": PROP_LEDGER_SCHEMA,
        "lane": "NFL_PROP_RESEARCH",
        "ledger_dir": PROP_LEDGER_DIR,
        "card_id": card_id,
        "captured_at": stamp,
        "independent_play_count": card.independent_play_count,
        "component_group_count": card.component_group_count,
        "rows": [asdict(row) for row in card.rows],
        "status": STATUS,
        "authority_footer": AUTHORITY_FOOTER,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    payload["content_sha256"] = sha256(raw).hexdigest()
    return payload
