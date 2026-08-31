from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Mapping

from ...source_lineage import canonical_json_sha256

NFL_CONTEXT_SCHEMA_VERSION = "nfl_hybrid_context_v1"

CONTEXT_CLASSES = (
    "venue_surface",
    "weather",
    "rest_travel",
    "injury_availability",
    "snap_usage_workload",
    "personnel_packages",
    "defensive_matchup",
    "special_teams",
    "coaching_tendencies",
    "workload_leash",
)

COLLECTION_MODES = frozenset({"AUTO", "MANUAL", "HYBRID"})

PROHIBITED_TOKENS = frozenset({
    "social_pick",
    "handicapper_pick",
    "public_betting",
    "ticket_pct",
    "money_pct",
    "handle_pct",
    "sportsbook",
    "bookmaker",
    "american_odds",
    "decimal_odds",
    "market_probability",
    "implied_probability",
    "market_price",
    "closing_line",
    "consensus_line",
})


class NFLContextError(ValueError):
    pass


@dataclass(frozen=True)
class ContextObservation:
    context_class: str
    status: str
    payload: Any
    source_name: str
    source_uri: str
    source_sha256: str
    source_type: str
    collection_mode: str
    observed_at_utc: str
    pit_as_of_utc: str
    operator_id: str | None = None
    justification: str | None = None
    model_p_eligible: bool = False
    truth_gate_eligible: bool = False
    lane: str = "NFL_HYBRID_CONTEXT"


def _utc(value: Any, field: str) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value or "").replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(text)
        except ValueError as exc:
            raise NFLContextError(f"invalid {field}") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise NFLContextError(f"{field} must be timezone-aware")
    return dt.astimezone(timezone.utc)


def _sha(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if len(raw) != 64:
        raise NFLContextError("source_sha256 invalid")
    try:
        int(raw, 16)
    except ValueError as exc:
        raise NFLContextError("source_sha256 invalid") from exc
    return raw


def _assert_objective_only(value: Any, *, path: str = "root") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = str(key).strip().lower()
            if normalized in PROHIBITED_TOKENS:
                raise NFLContextError(f"prohibited context field: {path}.{key}")
            _assert_objective_only(child, path=f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for idx, child in enumerate(value):
            _assert_objective_only(child, path=f"{path}[{idx}]")


def build_source_plan() -> dict[str, dict[str, Any]]:
    return {
        "venue_surface": {
            "primary": "OFFICIAL_NFL_OR_TEAM_VENUE+PIT_SURFACE_TABLE",
            "auto_pull": True,
        },
        "weather": {
            "primary": "NWS_HOURLY+STADIUM_COORDINATES",
            "auto_pull": True,
        },
        "rest_travel": {
            "primary": "NFL_SCHEDULE+PIT_TRAVEL_TABLE",
            "auto_pull": True,
        },
        "injury_availability": {
            "primary": "OFFICIAL_NFL_TEAM_INJURY_REPORTS",
            "auto_pull": True,
        },
        "snap_usage_workload": {
            "primary": "NFL_GAME_LOGS+PIT_USAGE_HISTORY",
            "auto_pull": True,
        },
        "personnel_packages": {
            "primary": "OFFICIAL_DEPTH_CHARTS+PIT_GAME_LOGS",
            "auto_pull": True,
        },
        "defensive_matchup": {
            "primary": "PIT_DEFENSIVE_SPLITS",
            "auto_pull": True,
        },
        "special_teams": {
            "primary": "OFFICIAL_ROSTERS+PIT_SPECIAL_TEAMS_HISTORY",
            "auto_pull": True,
        },
        "coaching_tendencies": {
            "primary": "PIT_PLAY_BY_PLAY_COACHING_HISTORY",
            "auto_pull": True,
        },
        "workload_leash": {
            "primary": "PIT_SNAP_AND_USAGE_HISTORY+OFFICIAL_INJURY_STATUS",
            "auto_pull": True,
        },
    }


def make_observation(
    *,
    context_class: str,
    status: str,
    payload: Any,
    source_name: str,
    source_uri: str,
    source_sha256: str,
    source_type: str,
    collection_mode: str,
    observed_at: Any,
    pit_as_of: Any,
    operator_id: str | None = None,
    justification: str | None = None,
) -> ContextObservation:
    key = str(context_class).strip().lower()
    if key not in CONTEXT_CLASSES:
        raise NFLContextError(f"unknown context class: {key}")
    mode = str(collection_mode).upper().strip()
    if mode not in COLLECTION_MODES:
        raise NFLContextError(f"invalid collection mode: {mode}")
    source_type_norm = str(source_type).upper().strip()
    if source_type_norm not in {"AUTO", "MANUAL"}:
        raise NFLContextError("source_type must be AUTO or MANUAL")
    if source_type_norm == "MANUAL" and not str(operator_id or "").strip():
        raise NFLContextError("manual observation requires operator_id")
    observed = _utc(observed_at, "observed_at")
    pit = _utc(pit_as_of, "pit_as_of")
    if observed > pit:
        raise NFLContextError("observation occurs after PIT as-of")
    _assert_objective_only(payload)
    return ContextObservation(
        context_class=key,
        status=str(status).upper().strip(),
        payload=payload,
        source_name=str(source_name).strip(),
        source_uri=str(source_uri).strip(),
        source_sha256=_sha(source_sha256),
        source_type=source_type_norm,
        collection_mode=mode,
        observed_at_utc=observed.isoformat(),
        pit_as_of_utc=pit.isoformat(),
        operator_id=str(operator_id).strip() if operator_id else None,
        justification=str(justification).strip() if justification else None,
    )


def collect_auto_context(
    *,
    game_id: str,
    as_of: Any,
    providers: Mapping[str, Callable[[str, datetime], Mapping[str, Any] | None]],
) -> dict[str, Any]:
    """Collect objective NFL context from approved PIT-safe providers.

    Every class is attempted. Missing providers or values become explicit MISSING
    observations; no numeric zero-fill or inference occurs.
    """
    pit = _utc(as_of, "as_of")
    rows: dict[str, ContextObservation] = {}
    plan = build_source_plan()
    for key in CONTEXT_CLASSES:
        provider = providers.get(key)
        if provider is None:
            rows[key] = make_observation(
                context_class=key,
                status="MISSING_PROVIDER",
                payload=None,
                source_name=plan[key]["primary"],
                source_uri="provider://missing",
                source_sha256="0" * 64,
                source_type="AUTO",
                collection_mode="AUTO",
                observed_at=pit,
                pit_as_of=pit,
            )
            continue
        try:
            raw = provider(str(game_id), pit)
        except Exception as exc:
            raise NFLContextError(f"auto provider failed: {key}") from exc
        if raw is None:
            rows[key] = make_observation(
                context_class=key,
                status="MISSING",
                payload=None,
                source_name=plan[key]["primary"],
                source_uri="provider://empty",
                source_sha256="0" * 64,
                source_type="AUTO",
                collection_mode="AUTO",
                observed_at=pit,
                pit_as_of=pit,
            )
            continue
        rows[key] = make_observation(
            context_class=key,
            status=str(raw.get("status") or "AVAILABLE"),
            payload=raw.get("payload"),
            source_name=str(raw.get("source_name") or plan[key]["primary"]),
            source_uri=str(raw.get("source_uri") or "provider://objective"),
            source_sha256=str(raw.get("source_sha256") or ""),
            source_type="AUTO",
            collection_mode="AUTO",
            observed_at=raw.get("observed_at") or pit,
            pit_as_of=pit,
        )
    return _bundle(game_id=game_id, mode="AUTO", as_of=pit, observations=rows, audit=[])


def manual_context(
    *,
    game_id: str,
    as_of: Any,
    observations: Iterable[ContextObservation],
) -> dict[str, Any]:
    pit = _utc(as_of, "as_of")
    rows: dict[str, ContextObservation] = {}
    for row in observations:
        if row.source_type != "MANUAL":
            raise NFLContextError("manual context contains non-manual observation")
        if _utc(row.pit_as_of_utc, "pit_as_of") != pit:
            raise NFLContextError("manual observation PIT as-of mismatch")
        rows[row.context_class] = replace(row, collection_mode="MANUAL")
    return _bundle(game_id=game_id, mode="MANUAL", as_of=pit, observations=rows, audit=[])


def merge_hybrid_context(
    *,
    auto_bundle: Mapping[str, Any],
    manual_bundle: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Merge AUTO base with MANUAL class-level overrides.

    Manual wins only when present for the same context class. The audit log keeps
    both the prior AUTO source hash and replacement MANUAL source hash.
    """
    if str(auto_bundle.get("collection_mode")) != "AUTO":
        raise NFLContextError("hybrid merge requires AUTO base")
    game_id = str(auto_bundle.get("game_id") or "")
    pit = _utc(auto_bundle.get("as_of_utc"), "as_of")
    merged: dict[str, ContextObservation] = {}
    for key, raw in (auto_bundle.get("observations") or {}).items():
        merged[key] = ContextObservation(**dict(raw))
    audit: list[dict[str, Any]] = []
    if manual_bundle is not None:
        if str(manual_bundle.get("collection_mode")) != "MANUAL":
            raise NFLContextError("manual bundle has wrong mode")
        if str(manual_bundle.get("game_id") or "") != game_id:
            raise NFLContextError("hybrid game_id mismatch")
        if _utc(manual_bundle.get("as_of_utc"), "as_of") != pit:
            raise NFLContextError("hybrid PIT as-of mismatch")
        for key, raw in (manual_bundle.get("observations") or {}).items():
            replacement = ContextObservation(**dict(raw))
            prior = merged.get(key)
            merged[key] = replace(replacement, collection_mode="HYBRID")
            audit.append({
                "context_class": key,
                "action": "MANUAL_OVERRIDE" if prior is not None else "MANUAL_FILL",
                "auto_source_sha256": prior.source_sha256 if prior is not None else None,
                "manual_source_sha256": replacement.source_sha256,
                "operator_id": replacement.operator_id,
                "justification": replacement.justification,
            })
    for key, row in list(merged.items()):
        if row.source_type == "AUTO":
            merged[key] = replace(row, collection_mode="HYBRID")
    return _bundle(game_id=game_id, mode="HYBRID", as_of=pit, observations=merged, audit=audit)


def run_context_mode(
    *,
    mode: str,
    game_id: str,
    as_of: Any,
    providers: Mapping[str, Callable[[str, datetime], Mapping[str, Any] | None]] | None = None,
    manual_observations: Iterable[ContextObservation] | None = None,
) -> dict[str, Any]:
    requested = str(mode).upper().strip()
    if requested not in COLLECTION_MODES:
        raise NFLContextError(f"invalid collection mode: {requested}")
    if requested == "AUTO":
        return collect_auto_context(game_id=game_id, as_of=as_of, providers=dict(providers or {}))
    manual = manual_context(
        game_id=game_id,
        as_of=as_of,
        observations=list(manual_observations or []),
    )
    if requested == "MANUAL":
        return manual
    auto = collect_auto_context(game_id=game_id, as_of=as_of, providers=dict(providers or {}))
    return merge_hybrid_context(auto_bundle=auto, manual_bundle=manual)


def _bundle(
    *,
    game_id: str,
    mode: str,
    as_of: datetime,
    observations: Mapping[str, ContextObservation],
    audit: list[dict[str, Any]],
) -> dict[str, Any]:
    payload = {
        "schema_version": NFL_CONTEXT_SCHEMA_VERSION,
        "sport": "NFL",
        "game_id": str(game_id),
        "as_of_utc": as_of.isoformat(),
        "lane": "NFL_HYBRID_CONTEXT",
        "collection_mode": mode,
        "model_p_eligible": False,
        "truth_gate_eligible": False,
        "observations": {key: asdict(row) for key, row in observations.items()},
        "audit_log": list(audit),
    }
    _assert_objective_only(payload)
    payload["payload_sha256"] = canonical_json_sha256(payload)
    return payload


def missing_context_classes(bundle: Mapping[str, Any]) -> tuple[str, ...]:
    observations = bundle.get("observations") or {}
    missing: list[str] = []
    for key in CONTEXT_CLASSES:
        row = observations.get(key)
        if row is None or str(row.get("status") or "").upper() != "AVAILABLE":
            missing.append(key)
    return tuple(missing)
