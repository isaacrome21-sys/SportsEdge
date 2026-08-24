"""Strict all-market MLB point-in-time observation evidence contract.

This layer joins already-captured quote evidence to canonical MLB identity, strictly
pregame model/history identity, official finalized facts, and a sportsbook-rule
settlement decision. It never guesses unresolved identity or ambiguous settlement.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from math import isfinite, log
import re
from typing import Any, Iterable, Mapping, Sequence

from .behavioral_acceptance import analyze_challenger
from .odds_api_source import normalize_name
from .quote_bridge import SUPPORTED_MARKETS


class MLBPITObservationError(ValueError):
    pass


_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_EVENT_TOLERANCE_SECONDS = 90 * 60
_SETTLEMENT_STATES = {
    "SETTLEMENT_ELIGIBLE",
    "AMBIGUOUS_SETTLEMENT",
    "BOOK_SETTLEMENT_UNVALIDATED",
    "OFFICIAL_FACTS_INCOMPLETE",
    "VOID",
}
_SETTLED_OUTCOMES = {"WIN", "LOSS", "PUSH"}
_LIVE_SOURCE_CLASS = "LIVE_PROVIDER_QUOTE_ARCHIVE"
_SYNTHETIC_SOURCE_CLASS = "SYNTHETIC_CONTRACT_TEST"


def _parse_ts(value: Any, name: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise MLBPITObservationError(f"{name} required")
    text = value.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError as exc:
        raise MLBPITObservationError(f"{name} must be ISO-8601") from exc
    if dt.tzinfo is None:
        raise MLBPITObservationError(f"{name} must be timezone-aware")
    return dt.astimezone(timezone.utc)


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise MLBPITObservationError(f"{name} must be numeric")
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise MLBPITObservationError(f"{name} must be numeric") from exc
    if not isfinite(out):
        raise MLBPITObservationError(f"{name} must be finite")
    return out


def _prob(value: Any, name: str) -> float:
    out = _finite(value, name)
    if not 0.0 <= out <= 1.0:
        raise MLBPITObservationError(f"{name} must be in [0,1]")
    return out


def _sha(value: Any, name: str) -> str:
    text = str(value or "").strip().lower()
    if not _HEX64.fullmatch(text):
        raise MLBPITObservationError(f"{name} must be a SHA-256 hex digest")
    return text


def content_sha256(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _provider_teams(event_snapshot: Mapping[str, Any]) -> tuple[str, str]:
    participants = event_snapshot.get("participants")
    if not isinstance(participants, Sequence) or isinstance(participants, (str, bytes)):
        raise MLBPITObservationError("PROVIDER_EVENT_TEAM_IDENTITY_MISSING")
    home: list[str] = []
    away: list[str] = []
    for raw in participants:
        if not isinstance(raw, Mapping):
            continue
        name = str(raw.get("name") or raw.get("participantName") or "").strip()
        role = str(raw.get("venueRole") or raw.get("role") or "").strip().lower()
        if not name:
            continue
        if role == "home":
            home.append(name)
        elif role == "away":
            away.append(name)
    if len(home) != 1 or len(away) != 1:
        raise MLBPITObservationError("PROVIDER_EVENT_TEAM_IDENTITY_AMBIGUOUS")
    return away[0], home[0]


def bind_provider_event_to_game(
    archived_quote: Mapping[str, Any],
    game_candidates: Iterable[Mapping[str, Any]],
) -> str:
    event = archived_quote.get("provider_event_snapshot")
    if not isinstance(event, Mapping):
        raise MLBPITObservationError("PROVIDER_EVENT_SNAPSHOT_REQUIRED")
    event_hash = _sha(archived_quote.get("provider_event_sha256"), "provider_event_sha256")
    if content_sha256(dict(event)) != event_hash:
        raise MLBPITObservationError("PROVIDER_EVENT_HASH_MISMATCH")
    away_name, home_name = _provider_teams(event)
    first_pitch = _parse_ts(archived_quote.get("first_pitch_at"), "first_pitch_at")
    away_key = normalize_name(away_name)
    home_key = normalize_name(home_name)

    matches: list[str] = []
    for raw in game_candidates:
        if not isinstance(raw, Mapping):
            continue
        if normalize_name(raw.get("away_name")) != away_key:
            continue
        if normalize_name(raw.get("home_name")) != home_key:
            continue
        candidate_start = _parse_ts(raw.get("first_pitch_ts"), "game_candidate.first_pitch_ts")
        if abs((candidate_start - first_pitch).total_seconds()) > _EVENT_TOLERANCE_SECONDS:
            continue
        game_id = str(raw.get("game_id") or "").strip()
        if game_id:
            matches.append(game_id)
    if not matches:
        raise MLBPITObservationError("PROVIDER_EVENT_GAME_NOT_FOUND")
    if len(set(matches)) != 1:
        raise MLBPITObservationError("PROVIDER_EVENT_GAME_AMBIGUOUS")
    return matches[0]


def bind_participant_to_player(
    entity_name: Any,
    player_candidates: Iterable[Mapping[str, Any]],
) -> str:
    key = normalize_name(entity_name)
    if not key:
        raise MLBPITObservationError("PROVIDER_PARTICIPANT_NAME_MISSING")
    matches: set[str] = set()
    for raw in player_candidates:
        if not isinstance(raw, Mapping):
            continue
        if normalize_name(raw.get("player_name")) != key:
            continue
        player_id = str(raw.get("player_id") or "").strip()
        if player_id:
            matches.add(player_id)
    if not matches:
        raise MLBPITObservationError("PROVIDER_PARTICIPANT_PLAYER_NOT_FOUND")
    if len(matches) != 1:
        raise MLBPITObservationError("PROVIDER_PARTICIPANT_PLAYER_AMBIGUOUS")
    return next(iter(matches))


@dataclass(frozen=True)
class PITObservation:
    market: str
    game_id: str
    entity_id: str
    quote_ts: str
    first_pitch_ts: str
    line: float
    side: str
    sportsbook: str
    book_key: str
    source_evidence_class: str
    quote_source_hash: str
    provider_event_hash: str
    identity_binding_hash: str
    history_asof_ts: str
    history_source_hash: str
    model_input_hash: str
    official_facts_hash: str
    settlement_rules_hash: str | None
    settlement_state: str
    settled_outcome: str | None
    candidate_p: float
    incumbent_p: float | None

    @property
    def is_push(self) -> bool:
        return self.settlement_state == "SETTLEMENT_ELIGIBLE" and self.settled_outcome == "PUSH"

    @property
    def is_scored(self) -> bool:
        return self.settlement_state == "SETTLEMENT_ELIGIBLE" and self.settled_outcome in {"WIN", "LOSS"}

    @property
    def reference_p(self) -> float | None:
        if self.settled_outcome == "WIN":
            return 1.0
        if self.settled_outcome == "LOSS":
            return 0.0
        return None


def normalize_pit_observation(raw: Mapping[str, Any]) -> PITObservation:
    if not isinstance(raw, Mapping):
        raise MLBPITObservationError("observation must be an object")
    market = str(raw.get("market") or "").strip().upper()
    if market not in SUPPORTED_MARKETS:
        raise MLBPITObservationError(f"unsupported market {market!r}")
    game_id = str(raw.get("game_id") or "").strip()
    entity_id = str(raw.get("entity_id") or "").strip()
    if not game_id or not entity_id:
        raise MLBPITObservationError("game_id and entity_id required")

    quote_dt = _parse_ts(raw.get("quote_ts"), "quote_ts")
    first_pitch_dt = _parse_ts(raw.get("first_pitch_ts"), "first_pitch_ts")
    history_dt = _parse_ts(raw.get("history_asof_ts"), "history_asof_ts")
    if quote_dt >= first_pitch_dt:
        raise MLBPITObservationError("quote_ts must be before first_pitch_ts")
    if history_dt >= first_pitch_dt:
        raise MLBPITObservationError("history_asof_ts must be before first_pitch_ts")

    source_class = str(raw.get("source_evidence_class") or "").strip().upper()
    if source_class not in {_LIVE_SOURCE_CLASS, _SYNTHETIC_SOURCE_CLASS}:
        raise MLBPITObservationError("source_evidence_class unsupported")
    settlement_state = str(raw.get("settlement_state") or "").strip().upper()
    if settlement_state not in _SETTLEMENT_STATES:
        raise MLBPITObservationError("settlement_state unsupported")
    outcome_raw = raw.get("settled_outcome")
    outcome = None if outcome_raw in (None, "") else str(outcome_raw).strip().upper()
    if settlement_state == "SETTLEMENT_ELIGIBLE":
        if outcome not in _SETTLED_OUTCOMES:
            raise MLBPITObservationError("SETTLEMENT_ELIGIBLE requires WIN, LOSS, or PUSH outcome")
    elif outcome is not None:
        raise MLBPITObservationError("non-eligible settlement must not carry a scored outcome")

    rules_hash: str | None = None
    if settlement_state in {"SETTLEMENT_ELIGIBLE", "VOID", "AMBIGUOUS_SETTLEMENT"}:
        rules_hash = _sha(raw.get("settlement_rules_hash"), "settlement_rules_hash")
    elif raw.get("settlement_rules_hash") not in (None, ""):
        rules_hash = _sha(raw.get("settlement_rules_hash"), "settlement_rules_hash")

    incumbent_raw = raw.get("incumbent_p")
    incumbent = None if incumbent_raw is None else _prob(incumbent_raw, "incumbent_p")
    sportsbook = str(raw.get("sportsbook") or "").strip()
    book_key = str(raw.get("book_key") or "").strip()
    if not sportsbook or not book_key:
        raise MLBPITObservationError("sportsbook and book_key required")

    return PITObservation(
        market=market,
        game_id=game_id,
        entity_id=entity_id,
        quote_ts=quote_dt.isoformat(),
        first_pitch_ts=first_pitch_dt.isoformat(),
        line=_finite(raw.get("line"), "line"),
        side=str(raw.get("side") or "").strip().upper(),
        sportsbook=sportsbook,
        book_key=book_key,
        source_evidence_class=source_class,
        quote_source_hash=_sha(raw.get("quote_source_hash"), "quote_source_hash"),
        provider_event_hash=_sha(raw.get("provider_event_hash"), "provider_event_hash"),
        identity_binding_hash=_sha(raw.get("identity_binding_hash"), "identity_binding_hash"),
        history_asof_ts=history_dt.isoformat(),
        history_source_hash=_sha(raw.get("history_source_hash"), "history_source_hash"),
        model_input_hash=_sha(raw.get("model_input_hash"), "model_input_hash"),
        official_facts_hash=_sha(raw.get("official_facts_hash"), "official_facts_hash"),
        settlement_rules_hash=rules_hash,
        settlement_state=settlement_state,
        settled_outcome=outcome,
        candidate_p=_prob(raw.get("candidate_p"), "candidate_p"),
        incumbent_p=incumbent,
    )


def _binary_metrics(rows: Sequence[PITObservation], attr: str) -> dict[str, float]:
    probs = [float(getattr(row, attr)) for row in rows]
    refs = [float(row.reference_p) for row in rows]
    eps = 1e-15
    brier = sum((p - y) ** 2 for p, y in zip(probs, refs)) / len(rows)
    log_loss = -sum(y * log(max(p, eps)) + (1 - y) * log(max(1 - p, eps)) for p, y in zip(probs, refs)) / len(rows)
    return {"brier": brier, "log_loss": log_loss}


def analyze_pit_observations(raw_rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    rows = [normalize_pit_observation(row) for row in raw_rows]
    if not rows:
        raise MLBPITObservationError("at least one PIT observation is required")

    state_counts = {state: sum(row.settlement_state == state for row in rows) for state in sorted(_SETTLEMENT_STATES)}
    pushes = sum(row.is_push for row in rows)
    scored = [row for row in rows if row.is_scored]
    synthetic = any(row.source_evidence_class == _SYNTHETIC_SOURCE_CLASS for row in rows)
    candidate_metrics = _binary_metrics(scored, "candidate_p") if scored else None

    comparable = [row for row in scored if row.incumbent_p is not None]
    comparison = None
    if comparable:
        comparison = analyze_challenger(
            [
                {
                    "market": row.market,
                    "line": row.line,
                    "side": row.side,
                    "reference_p": row.reference_p,
                    "incumbent_p": row.incumbent_p,
                    "challenger_p": row.candidate_p,
                }
                for row in comparable
            ]
        )

    counts_as_historical = bool(scored and not synthetic and all(row.source_evidence_class == _LIVE_SOURCE_CLASS for row in rows))
    evidence_class = (
        "SYNTHETIC_CONTRACT_TEST"
        if synthetic
        else "HISTORICAL_PIT"
        if counts_as_historical
        else "LIVE_PIT_UNSCORABLE"
    )

    return {
        "schema_version": 2,
        "evidence_class": evidence_class,
        "counts_as_historical_pit": counts_as_historical,
        "source_row_count": len(rows),
        "scored_row_count": len(scored),
        "push_rows_excluded_from_binary_error": pushes,
        "settlement_state_counts": state_counts,
        "void_rows_excluded": state_counts["VOID"],
        "ambiguous_rows_excluded": state_counts["AMBIGUOUS_SETTLEMENT"],
        "book_unvalidated_rows_excluded": state_counts["BOOK_SETTLEMENT_UNVALIDATED"],
        "official_facts_incomplete_rows_excluded": state_counts["OFFICIAL_FACTS_INCOMPLETE"],
        "markets": sorted({row.market for row in rows}),
        "candidate_metrics": candidate_metrics,
        "incumbent_challenger_comparison": comparison,
        "rows": [asdict(row) for row in rows],
    }
