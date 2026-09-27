"""Point-in-time, separately-ledgered NFL prop research lane.

This module is the card-facing wrapper around ``prop_role_challenger``.  It
adds the governance contracts that the low-level simulation primitive does not
own: point-in-time role inputs, hash-bound context multipliers, component
exposure grouping, a prop-only card, and a prop-only immutable research ledger.

Research only: no Model_P, Truth Gate, promotion, staking, or OFFICIAL authority.
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
    PropSimulation,
    RoleProjection,
    apply_context,
    simulate_player_props,
    stabilize_role,
)

PROP_CARD_SCHEMA = "SPORTSEDGE_NFL_PROP_RESEARCH_CARD_V1"
PROP_LEDGER_SCHEMA = "SPORTSEDGE_NFL_PROP_RESEARCH_LEDGER_V1"
PROP_LEDGER_NAMESPACE = "ledger/nfl_prop_challenger"
CONTEXT_MANIFEST_PATH = "config/research/nfl_prop_role_context_manifest.json"

COMPONENT_BY_MARKET = {
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

_REALIZED_SAME_GAME_KEYS = frozenset(
    {
        "actual_snaps",
        "same_game_snaps",
        "actual_snap_share",
        "same_game_snap_share",
        "actual_routes",
        "same_game_routes",
        "actual_targets",
        "actual_carries",
        "realized_snaps",
        "realized_routes",
        "realized_usage",
    }
)


class PropResearchLaneError(ValueError):
    pass


def _parse_time(value: Any, name: str) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError) as exc:
            raise PropResearchLaneError(f"BAD_TIMESTAMP:{name}") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise PropResearchLaneError(f"TIMESTAMP_TIMEZONE_MISSING:{name}")
    return dt.astimezone(timezone.utc)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _assert_zero_authority(authority: Mapping[str, Any], name: str) -> None:
    if not isinstance(authority, Mapping) or any(bool(v) for v in authority.values()):
        raise PropResearchLaneError(f"AUTHORITY_ESCALATION:{name}")


@dataclass(frozen=True)
class FrozenContextProfile:
    version: str
    profile_id: str
    config_sha256: str
    multipliers: Mapping[str, float]


def load_frozen_context_profile(
    root: str | Path,
    *,
    profile_id: str = "NEUTRAL",
) -> FrozenContextProfile:
    root = Path(root)
    manifest_path = root / CONTEXT_MANIFEST_PATH
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PropResearchLaneError("CONTEXT_MANIFEST_UNREADABLE") from exc
    if manifest.get("schema") != "SPORTSEDGE_NFL_PROP_CONTEXT_MANIFEST_V1":
        raise PropResearchLaneError("CONTEXT_MANIFEST_SCHEMA_INVALID")
    _assert_zero_authority(manifest.get("authority") or {}, "manifest")

    rel = str(manifest.get("active_path") or "")
    if not rel or Path(rel).is_absolute() or ".." in Path(rel).parts:
        raise PropResearchLaneError("CONTEXT_ACTIVE_PATH_INVALID")
    config_path = root / rel
    try:
        raw = config_path.read_bytes()
        config = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PropResearchLaneError("CONTEXT_CONFIG_UNREADABLE") from exc
    digest = sha256(raw).hexdigest()
    if digest != manifest.get("active_sha256"):
        raise PropResearchLaneError("CONTEXT_CONFIG_SHA256_MISMATCH")
    if config.get("schema") != "SPORTSEDGE_NFL_PROP_CONTEXT_CONFIG_V1":
        raise PropResearchLaneError("CONTEXT_CONFIG_SCHEMA_INVALID")
    version = str(config.get("version") or "")
    if version != manifest.get("active_version"):
        raise PropResearchLaneError("CONTEXT_CONFIG_VERSION_MISMATCH")
    _assert_zero_authority(config.get("authority") or {}, "config")
    profiles = config.get("profiles") or {}
    if profile_id not in profiles:
        raise PropResearchLaneError(f"CONTEXT_PROFILE_UNKNOWN:{profile_id}")
    multipliers = profiles[profile_id]
    required = {"pass_volume_multiplier", "rush_volume_multiplier", "target_multiplier"}
    if not isinstance(multipliers, Mapping) or set(multipliers) != required:
        raise PropResearchLaneError("CONTEXT_PROFILE_SHAPE_INVALID")
    clean: dict[str, float] = {}
    for key in sorted(required):
        try:
            value = float(multipliers[key])
        except (TypeError, ValueError) as exc:
            raise PropResearchLaneError(f"CONTEXT_MULTIPLIER_INVALID:{key}") from exc
        if value < 0.0:
            raise PropResearchLaneError(f"CONTEXT_MULTIPLIER_INVALID:{key}")
        clean[key] = value
    return FrozenContextProfile(version, profile_id, digest, clean)


def _reject_realized_same_game_fields(row: Mapping[str, Any], *, where: str) -> None:
    normalized = {str(k).lower() for k in row}
    leaked = sorted(normalized & _REALIZED_SAME_GAME_KEYS)
    if leaked:
        raise PropResearchLaneError(
            f"SAME_GAME_REALIZED_USAGE_FORBIDDEN:{where}:{','.join(leaked)}"
        )


def _known_at(row: Mapping[str, Any], *, where: str, as_of: datetime) -> datetime:
    if "known_at" not in row:
        raise PropResearchLaneError(f"PIT_KNOWN_AT_REQUIRED:{where}")
    stamp = _parse_time(row["known_at"], f"{where}.known_at")
    if stamp > as_of:
        raise PropResearchLaneError(f"PIT_INPUT_AFTER_ASOF:{where}")
    return stamp


@dataclass(frozen=True)
class PreparedRoleSnapshot:
    game_id: str
    entity_id: str
    as_of: str
    kickoff_at: str
    role: RoleProjection
    context_version: str
    context_profile_id: str
    context_sha256: str
    status: str = "RESEARCH_ONLY_PIT_ROLE"
    authority_footer: str = AUTHORITY_FOOTER


def prepare_role_snapshot(
    *,
    root: str | Path,
    game_id: str,
    entity_id: str,
    kickoff_at: Any,
    as_of: Any,
    history: Sequence[Mapping[str, Any]],
    projected_role: Mapping[str, Any],
    availability_probability: float = 1.0,
    context_profile_id: str = "NEUTRAL",
    decay: float = 0.82,
    shrink_games: float = 4.0,
    min_history_games: int = 3,
) -> PreparedRoleSnapshot:
    """Prepare a role using only information knowable at ``as_of`` pre-kickoff.

    Historical rows must carry ``known_at`` and a game id different from the
    game being priced. The projected-role row must carry ``known_at`` and may
    identify the current game, but realized same-game usage fields are forbidden.
    """
    if not game_id or not entity_id:
        raise PropResearchLaneError("GAME_AND_ENTITY_ID_REQUIRED")
    cutoff = _parse_time(as_of, "as_of")
    kickoff = _parse_time(kickoff_at, "kickoff_at")
    if cutoff >= kickoff:
        raise PropResearchLaneError("ROLE_ASOF_MUST_PRECEDE_KICKOFF")

    clean_history: list[dict[str, Any]] = []
    for i, row in enumerate(history):
        if not isinstance(row, Mapping):
            raise PropResearchLaneError(f"PIT_HISTORY_ROW_INVALID:{i}")
        _known_at(row, where=f"history[{i}]", as_of=cutoff)
        _reject_realized_same_game_fields(row, where=f"history[{i}]")
        if str(row.get("game_id") or "") == game_id:
            raise PropResearchLaneError(f"SAME_GAME_HISTORY_FORBIDDEN:{i}")
        clean_history.append(
            {
                key: row[key]
                for key in ("pass_attempts", "rush_attempts", "targets")
                if key in row
            }
        )

    if not isinstance(projected_role, Mapping):
        raise PropResearchLaneError("PROJECTED_ROLE_INVALID")
    _known_at(projected_role, where="projected_role", as_of=cutoff)
    _reject_realized_same_game_fields(projected_role, where="projected_role")
    clean_prior = {
        key: projected_role[key]
        for key in ("pass_attempts", "rush_attempts", "targets")
        if key in projected_role
    }

    frozen = load_frozen_context_profile(root, profile_id=context_profile_id)
    base_role = stabilize_role(
        entity_id=entity_id,
        history=clean_history,
        projected_role=clean_prior,
        availability_probability=availability_probability,
        decay=decay,
        shrink_games=shrink_games,
        min_history_games=min_history_games,
    )
    adjusted = apply_context(base_role, frozen.multipliers)
    return PreparedRoleSnapshot(
        game_id=game_id,
        entity_id=entity_id,
        as_of=cutoff.isoformat().replace("+00:00", "Z"),
        kickoff_at=kickoff.isoformat().replace("+00:00", "Z"),
        role=adjusted,
        context_version=frozen.version,
        context_profile_id=frozen.profile_id,
        context_sha256=frozen.config_sha256,
    )


def simulate_prepared_props(
    prepared: PreparedRoleSnapshot,
    *,
    efficiency: Mapping[str, Any],
    paths: int = 50_000,
    seed: int = 1,
    shared_pace_sigma: float = 0.12,
) -> PropSimulation:
    return simulate_player_props(
        role=prepared.role,
        efficiency=efficiency,
        paths=paths,
        seed=seed,
        shared_pace_sigma=shared_pace_sigma,
    )


def component_for_market(market: str) -> str:
    key = str(market).upper()
    try:
        return COMPONENT_BY_MARKET[key]
    except KeyError as exc:
        raise PropResearchLaneError(f"UNSUPPORTED_COMPONENT_MARKET:{market}") from exc


def exposure_group_id(game_id: str, entity_id: str, market: str) -> str:
    if not game_id or not entity_id:
        raise PropResearchLaneError("EXPOSURE_IDENTITY_REQUIRED")
    component = component_for_market(market)
    return f"{game_id}:{entity_id}:{component}"


@dataclass(frozen=True)
class PropCardRow:
    rank: int
    game_id: str
    entity_id: str
    component: str
    exposure_group_id: str
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


@dataclass(frozen=True)
class PropResearchCard:
    schema: str
    game_id: str
    rows: tuple[PropCardRow, ...]
    independent_exposure_count: int
    ledger_namespace: str = PROP_LEDGER_NAMESPACE
    authority_footer: str = AUTHORITY_FOOTER

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "game_id": self.game_id,
            "rows": [asdict(row) for row in self.rows],
            "independent_exposure_count": self.independent_exposure_count,
            "ledger_namespace": self.ledger_namespace,
            "authority_footer": self.authority_footer,
        }

    def render(self) -> str:
        lines = ["NFL PROPS — RESEARCH CARD"]
        if not self.rows:
            lines.append("No qualifying prop rows.")
        for row in self.rows:
            lines.append(
                f"{row.rank}. {row.entity_id} {row.market} {row.side} {row.line:g} "
                f"{row.price_american:+d}  EV {row.ev_per_dollar * 100:+.1f}% "
                f"[{row.component}]"
            )
        lines.append(f"Independent exposure groups: {self.independent_exposure_count}")
        lines.append(self.authority_footer)
        return "\n".join(lines)


def build_prop_research_card(
    *,
    game_id: str,
    evaluations: Sequence[PropQuoteEvaluation],
    positive_ev_only: bool = True,
) -> PropResearchCard:
    candidates = [row for row in evaluations if not positive_ev_only or row.ev_per_dollar > 0.0]
    candidates.sort(
        key=lambda row: (
            -row.ev_per_dollar,
            -row.edge_probability_points,
            row.entity_id,
            row.market,
            row.side,
        )
    )
    rows: list[PropCardRow] = []
    groups: set[str] = set()
    for rank, row in enumerate(candidates, 1):
        component = component_for_market(row.market)
        group = exposure_group_id(game_id, row.entity_id, row.market)
        groups.add(group)
        rows.append(
            PropCardRow(
                rank=rank,
                game_id=game_id,
                entity_id=row.entity_id,
                component=component,
                exposure_group_id=group,
                market=row.market,
                side=row.side,
                line=row.line,
                book=row.book,
                price_american=row.price_american,
                estimate_p=row.estimate_p,
                push_p=row.push_p,
                market_no_vig_p=row.market_no_vig_p,
                edge_probability_points=row.edge_probability_points,
                ev_per_dollar=row.ev_per_dollar,
            )
        )
    return PropResearchCard(
        schema=PROP_CARD_SCHEMA,
        game_id=game_id,
        rows=tuple(rows),
        independent_exposure_count=len(groups),
    )


def build_prop_ledger_record(card: PropResearchCard, *, generated_at: Any) -> dict[str, Any]:
    stamp = _parse_time(generated_at, "generated_at").isoformat().replace("+00:00", "Z")
    body = {
        "schema": PROP_LEDGER_SCHEMA,
        "lane": "NFL_PROP_RESEARCH_ONLY",
        "game_id": card.game_id,
        "generated_at": stamp,
        "card_schema": card.schema,
        "rows": [asdict(row) for row in card.rows],
        "independent_exposure_count": card.independent_exposure_count,
        "exposure_groups": sorted({row.exposure_group_id for row in card.rows}),
        "authority": {
            "model_p": False,
            "truth_gate": False,
            "promotion": False,
            "staking": False,
            "official": False,
        },
        "authority_footer": AUTHORITY_FOOTER,
    }
    body["content_sha256"] = sha256(_canonical_json(body).encode("utf-8")).hexdigest()
    return body


def prop_ledger_relative_path(record: Mapping[str, Any]) -> str:
    stamp = _parse_time(record.get("generated_at"), "generated_at")
    digest = str(record.get("content_sha256") or "")
    if len(digest) != 64:
        raise PropResearchLaneError("PROP_LEDGER_SHA_REQUIRED")
    return f"{PROP_LEDGER_NAMESPACE}/{stamp.date().isoformat()}/{digest}.json"


def write_prop_ledger(root: str | Path, record: Mapping[str, Any]) -> Path:
    """Create an immutable prop-only research ledger row; never writes game-market ledgers."""
    rel = prop_ledger_relative_path(record)
    path = Path(root) / rel
    payload = json.dumps(dict(record), indent=2, sort_keys=True) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_text(encoding="utf-8") != payload:
            raise PropResearchLaneError("PROP_LEDGER_IMMUTABILITY_VIOLATION")
        return path
    path.write_text(payload, encoding="utf-8")
    return path
