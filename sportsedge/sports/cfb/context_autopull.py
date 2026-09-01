from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Mapping

from ...source_lineage import canonical_json_sha256

CFB_CONTEXT_SCHEMA_VERSION = "cfb_hybrid_context_v1"
CONTEXT_CLASSES = (
    "game_metadata",
    "venue_weather",
    "rest_travel",
    "injury_availability",
    "depth_chart_role",
    "team_efficiency_pace",
    "defensive_matchup",
    "coaching_tendencies",
    "player_usage_workload",
    "workload_leash",
)
COLLECTION_MODES = frozenset({"AUTO", "MANUAL", "HYBRID"})
PROHIBITED_TOKENS = frozenset({
    "social_pick", "handicapper_pick", "public_betting", "ticket_pct",
    "money_pct", "handle_pct", "sportsbook", "bookmaker", "odds",
    "american_odds", "decimal_odds", "market_probability",
    "implied_probability", "market_price", "closing_line", "consensus_line",
})


class CFBContextError(ValueError):
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
    lane: str = "CFB_HYBRID_CONTEXT"


def _utc(value: Any, field: str) -> datetime:
    if isinstance(value, datetime):
        out = value
    else:
        text = str(value or "").strip().replace("Z", "+00:00")
        if not text:
            raise CFBContextError(f"{field} required")
        try:
            out = datetime.fromisoformat(text)
        except ValueError as exc:
            raise CFBContextError(f"{field} invalid") from exc
    if out.tzinfo is None or out.utcoffset() is None:
        raise CFBContextError(f"{field} timezone required")
    return out.astimezone(timezone.utc)


def _sha(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if len(raw) != 64:
        raise CFBContextError("source_sha256 invalid")
    try:
        int(raw, 16)
    except ValueError as exc:
        raise CFBContextError("source_sha256 invalid") from exc
    return raw


def _assert_objective_only(value: Any, *, path: str = "root") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            norm = str(key).strip().lower()
            if norm in PROHIBITED_TOKENS:
                raise CFBContextError(f"prohibited context field: {path}.{key}")
            _assert_objective_only(child, path=f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for idx, child in enumerate(value):
            _assert_objective_only(child, path=f"{path}[{idx}]")


def make_observation(*, context_class: str, status: str, payload: Any,
                     source_name: str, source_uri: str, source_sha256: str,
                     source_type: str, collection_mode: str, observed_at: Any,
                     pit_as_of: Any, operator_id: str | None = None,
                     justification: str | None = None) -> ContextObservation:
    key = str(context_class).strip().lower()
    if key not in CONTEXT_CLASSES:
        raise CFBContextError(f"unknown context class: {key}")
    mode = str(collection_mode).upper().strip()
    if mode not in COLLECTION_MODES:
        raise CFBContextError(f"invalid collection mode: {mode}")
    source_type_norm = str(source_type).upper().strip()
    if source_type_norm not in {"AUTO", "MANUAL"}:
        raise CFBContextError("source_type must be AUTO or MANUAL")
    if source_type_norm == "MANUAL" and not str(operator_id or "").strip():
        raise CFBContextError("manual observation requires operator_id")
    observed, pit = _utc(observed_at, "observed_at"), _utc(pit_as_of, "pit_as_of")
    if observed > pit:
        raise CFBContextError("observation occurs after PIT as-of")
    _assert_objective_only(payload)
    return ContextObservation(
        context_class=key, status=str(status).upper().strip(), payload=payload,
        source_name=str(source_name).strip(), source_uri=str(source_uri).strip(),
        source_sha256=_sha(source_sha256), source_type=source_type_norm,
        collection_mode=mode, observed_at_utc=observed.isoformat(),
        pit_as_of_utc=pit.isoformat(), operator_id=str(operator_id).strip() if operator_id else None,
        justification=str(justification).strip() if justification else None,
    )


def collect_auto_context(*, game_id: str, as_of: Any,
                         providers: Mapping[str, Callable[[str, datetime], Mapping[str, Any] | None]]) -> dict[str, Any]:
    pit = _utc(as_of, "as_of")
    rows: dict[str, ContextObservation] = {}
    for key in CONTEXT_CLASSES:
        provider = providers.get(key)
        if provider is None:
            rows[key] = make_observation(
                context_class=key, status="MISSING_PROVIDER", payload=None,
                source_name="CFB_OBJECTIVE_PROVIDER", source_uri="provider://missing",
                source_sha256="0" * 64, source_type="AUTO", collection_mode="AUTO",
                observed_at=pit, pit_as_of=pit,
            )
            continue
        try:
            raw = provider(str(game_id), pit)
        except Exception as exc:
            raise CFBContextError(f"auto provider failed: {key}") from exc
        if raw is None:
            rows[key] = make_observation(
                context_class=key, status="MISSING", payload=None,
                source_name="CFB_OBJECTIVE_PROVIDER", source_uri="provider://empty",
                source_sha256="0" * 64, source_type="AUTO", collection_mode="AUTO",
                observed_at=pit, pit_as_of=pit,
            )
            continue
        rows[key] = make_observation(
            context_class=key, status=str(raw.get("status") or "AVAILABLE"),
            payload=raw.get("payload"), source_name=str(raw.get("source_name") or "CFB_OBJECTIVE_PROVIDER"),
            source_uri=str(raw.get("source_uri") or "provider://objective"),
            source_sha256=str(raw.get("source_sha256") or ""), source_type="AUTO",
            collection_mode="AUTO", observed_at=raw.get("observed_at") or pit, pit_as_of=pit,
        )
    return _bundle(game_id=game_id, mode="AUTO", as_of=pit, observations=rows, audit=[])


def manual_context(*, game_id: str, as_of: Any,
                   observations: Iterable[ContextObservation]) -> dict[str, Any]:
    pit = _utc(as_of, "as_of")
    rows: dict[str, ContextObservation] = {}
    for row in observations:
        if row.source_type != "MANUAL":
            raise CFBContextError("manual context contains non-manual observation")
        if _utc(row.pit_as_of_utc, "pit_as_of") != pit:
            raise CFBContextError("manual observation PIT as-of mismatch")
        rows[row.context_class] = replace(row, collection_mode="MANUAL")
    return _bundle(game_id=game_id, mode="MANUAL", as_of=pit, observations=rows, audit=[])


def merge_hybrid_context(*, auto_bundle: Mapping[str, Any],
                         manual_bundle: Mapping[str, Any] | None = None) -> dict[str, Any]:
    if str(auto_bundle.get("collection_mode")) != "AUTO":
        raise CFBContextError("hybrid merge requires AUTO base")
    game_id = str(auto_bundle.get("game_id") or "")
    pit = _utc(auto_bundle.get("as_of_utc"), "as_of")
    merged = {key: ContextObservation(**dict(raw)) for key, raw in (auto_bundle.get("observations") or {}).items()}
    audit: list[dict[str, Any]] = []
    if manual_bundle is not None:
        if str(manual_bundle.get("collection_mode")) != "MANUAL" or str(manual_bundle.get("game_id") or "") != game_id:
            raise CFBContextError("hybrid manual bundle mismatch")
        if _utc(manual_bundle.get("as_of_utc"), "as_of") != pit:
            raise CFBContextError("hybrid PIT as-of mismatch")
        for key, raw in (manual_bundle.get("observations") or {}).items():
            replacement = ContextObservation(**dict(raw))
            prior = merged.get(key)
            merged[key] = replace(replacement, collection_mode="HYBRID")
            audit.append({"context_class": key, "action": "MANUAL_OVERRIDE" if prior else "MANUAL_FILL",
                          "auto_source_sha256": prior.source_sha256 if prior else None,
                          "manual_source_sha256": replacement.source_sha256,
                          "operator_id": replacement.operator_id, "justification": replacement.justification})
    for key, row in list(merged.items()):
        if row.source_type == "AUTO":
            merged[key] = replace(row, collection_mode="HYBRID")
    return _bundle(game_id=game_id, mode="HYBRID", as_of=pit, observations=merged, audit=audit)


def run_context_mode(*, mode: str, game_id: str, as_of: Any,
                     providers: Mapping[str, Callable[[str, datetime], Mapping[str, Any] | None]] | None = None,
                     manual_observations: Iterable[ContextObservation] | None = None) -> dict[str, Any]:
    requested = str(mode).upper().strip()
    if requested not in COLLECTION_MODES:
        raise CFBContextError(f"invalid collection mode: {requested}")
    if requested == "AUTO":
        return collect_auto_context(game_id=game_id, as_of=as_of, providers=dict(providers or {}))
    manual = manual_context(game_id=game_id, as_of=as_of, observations=list(manual_observations or []))
    if requested == "MANUAL":
        return manual
    auto = collect_auto_context(game_id=game_id, as_of=as_of, providers=dict(providers or {}))
    return merge_hybrid_context(auto_bundle=auto, manual_bundle=manual)


def _bundle(*, game_id: str, mode: str, as_of: datetime,
            observations: Mapping[str, ContextObservation], audit: list[dict[str, Any]]) -> dict[str, Any]:
    payload = {
        "schema_version": CFB_CONTEXT_SCHEMA_VERSION, "sport": "CFB", "subdivision": "FBS",
        "game_id": str(game_id), "as_of_utc": as_of.isoformat(), "lane": "CFB_HYBRID_CONTEXT",
        "collection_mode": mode, "model_p_eligible": False, "truth_gate_eligible": False,
        "observations": {key: asdict(row) for key, row in observations.items()}, "audit_log": list(audit),
    }
    _assert_objective_only(payload)
    payload["payload_sha256"] = canonical_json_sha256(payload)
    return payload


def missing_context_classes(bundle: Mapping[str, Any]) -> tuple[str, ...]:
    observations = bundle.get("observations") or {}
    return tuple(key for key in CONTEXT_CLASSES
                 if key not in observations or str(observations[key].get("status") or "").upper() != "AVAILABLE")
