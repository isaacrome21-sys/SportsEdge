"""Fail-closed quote -> outcome -> challenger evidence join for MLB props.

This module is deliberately evidence plumbing, not a pricing model. It joins a
point-in-time quote, an official realized fact, an explicit sportsbook settlement
resolution, and incumbent/challenger probabilities from the same prior-history
observation.

Important distinctions:
- Official box-score fact != sportsbook settlement.
- VOID and AMBIGUOUS rows never become scored validation evidence.
- Synthetic fixtures are permanently labeled SYNTHETIC_CONTRACT_TEST and cannot be
  reported as HISTORICAL_PIT.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from math import isfinite
from typing import Any, Iterable, Mapping


SUPPORTED_MARKETS = frozenset({"PITCHER_OUTS", "PITCHER_ER", "RBI"})
ORIGINS = frozenset({"SYNTHETIC_FIXTURE", "REAL_ARCHIVE"})
SETTLEMENT_STATES = frozenset({"SETTLED", "VOID", "AMBIGUOUS"})


class PropOutcomeJoinError(ValueError):
    pass


@dataclass(frozen=True)
class JoinedEvidenceRow:
    market: str
    game_id: str
    entity_id: str
    line: float
    side: str
    quote_ts: str
    first_pitch_ts: str
    realized_count: int
    settlement_state: str
    settlement_reason: str
    quote_archive_sha256: str
    facts_sha256: str
    history_asof_ts: str
    history_source_hash: str
    incumbent_p: float
    challenger_p: float
    evidence_origin: str

    @property
    def realized_push(self) -> bool:
        return abs(self.realized_count - self.line) < 1e-12

    @property
    def realized_win(self) -> bool:
        if self.side == "OVER":
            return self.realized_count > self.line
        return self.realized_count < self.line


def _text(raw: Mapping[str, Any], key: str) -> str:
    value = str(raw.get(key) or "").strip()
    if not value:
        raise PropOutcomeJoinError(f"{key} required")
    return value


def _ts(raw: Mapping[str, Any], key: str) -> datetime:
    value = _text(raw, key)
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        out = datetime.fromisoformat(text)
    except ValueError as exc:
        raise PropOutcomeJoinError(f"{key} must be ISO-8601") from exc
    if out.tzinfo is None:
        raise PropOutcomeJoinError(f"{key} must be timezone-aware")
    return out.astimezone(timezone.utc)


def _sha(raw: Mapping[str, Any], key: str) -> str:
    value = _text(raw, key).lower()
    if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
        raise PropOutcomeJoinError(f"{key} must be SHA-256 hex")
    return value


def _finite(raw: Mapping[str, Any], key: str) -> float:
    value = raw.get(key)
    if isinstance(value, bool):
        raise PropOutcomeJoinError(f"{key} must be numeric")
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise PropOutcomeJoinError(f"{key} must be numeric") from exc
    if not isfinite(out):
        raise PropOutcomeJoinError(f"{key} must be finite")
    return out


def _prob(raw: Mapping[str, Any], key: str) -> float:
    out = _finite(raw, key)
    if not 0.0 <= out <= 1.0:
        raise PropOutcomeJoinError(f"{key} must be in [0,1]")
    return out


def _nonnegative_int(raw: Mapping[str, Any], key: str) -> int:
    value = raw.get(key)
    if isinstance(value, bool):
        raise PropOutcomeJoinError(f"{key} must be a non-negative integer")
    try:
        out = int(value)
    except (TypeError, ValueError) as exc:
        raise PropOutcomeJoinError(f"{key} must be a non-negative integer") from exc
    if out < 0 or float(out) != float(value):
        raise PropOutcomeJoinError(f"{key} must be a non-negative integer")
    return out


def _identity(raw: Mapping[str, Any]) -> tuple[str, str, str]:
    market = _text(raw, "market").upper()
    if market not in SUPPORTED_MARKETS:
        raise PropOutcomeJoinError(f"unsupported market {market!r}")
    return market, _text(raw, "game_id"), _text(raw, "entity_id")


def _assert_same_identity(*rows: Mapping[str, Any]) -> tuple[str, str, str]:
    identities = [_identity(row) for row in rows]
    if any(item != identities[0] for item in identities[1:]):
        raise PropOutcomeJoinError(f"identity mismatch: {identities}")
    return identities[0]


def join_evidence_row(
    quote: Mapping[str, Any],
    fact: Mapping[str, Any],
    settlement: Mapping[str, Any],
    model_eval: Mapping[str, Any],
) -> JoinedEvidenceRow:
    """Join one evidence row or fail closed.

    The caller must resolve sportsbook settlement separately from official facts.
    AMBIGUOUS and VOID are never converted into wins/losses from the box score.
    """
    market, game_id, entity_id = _assert_same_identity(quote, fact, settlement, model_eval)

    settlement_state = _text(settlement, "settlement_state").upper()
    if settlement_state not in SETTLEMENT_STATES:
        raise PropOutcomeJoinError("settlement_state must be SETTLED, VOID, or AMBIGUOUS")
    reason = _text(settlement, "settlement_reason")
    if settlement_state == "AMBIGUOUS":
        raise PropOutcomeJoinError(f"AMBIGUOUS_SETTLEMENT:{reason}")
    if settlement_state == "VOID":
        raise PropOutcomeJoinError(f"VOID_SETTLEMENT:{reason}")

    origin = _text(quote, "evidence_origin").upper()
    if origin not in ORIGINS:
        raise PropOutcomeJoinError("evidence_origin must be SYNTHETIC_FIXTURE or REAL_ARCHIVE")

    quote_dt = _ts(quote, "quote_ts")
    first_pitch_dt = _ts(quote, "first_pitch_ts")
    history_dt = _ts(model_eval, "history_asof_ts")
    if quote_dt >= first_pitch_dt:
        raise PropOutcomeJoinError("quote_ts must be before first_pitch_ts")
    if history_dt >= first_pitch_dt:
        raise PropOutcomeJoinError("history_asof_ts must be before first_pitch_ts")

    side = _text(quote, "side").upper()
    if side not in {"OVER", "UNDER"}:
        raise PropOutcomeJoinError("side must be OVER or UNDER")
    line = _finite(quote, "line")
    if line < 0:
        raise PropOutcomeJoinError("line must be >= 0")

    # The official result adapter must explicitly say the game/player fact is final.
    if _text(fact, "fact_state").upper() != "FINAL_OFFICIAL":
        raise PropOutcomeJoinError("fact_state must be FINAL_OFFICIAL")

    return JoinedEvidenceRow(
        market=market,
        game_id=game_id,
        entity_id=entity_id,
        line=line,
        side=side,
        quote_ts=quote_dt.isoformat(),
        first_pitch_ts=first_pitch_dt.isoformat(),
        realized_count=_nonnegative_int(fact, "realized_count"),
        settlement_state=settlement_state,
        settlement_reason=reason,
        quote_archive_sha256=_sha(quote, "quote_archive_sha256"),
        facts_sha256=_sha(fact, "facts_sha256"),
        history_asof_ts=history_dt.isoformat(),
        history_source_hash=_sha(model_eval, "history_source_hash"),
        incumbent_p=_prob(model_eval, "incumbent_p"),
        challenger_p=_prob(model_eval, "challenger_p"),
        evidence_origin=origin,
    )


def build_join_report(raw_rows: Iterable[Mapping[str, Mapping[str, Any]]]) -> dict[str, Any]:
    """Build a deterministic join report from explicit component rows.

    Any ambiguous settlement blocks the batch classification. Known VOID rows are
    recorded as excluded. Synthetic rows can prove the contract but can never earn
    HISTORICAL_PIT classification.
    """
    joined: list[JoinedEvidenceRow] = []
    excluded: list[dict[str, Any]] = []
    ambiguous: list[dict[str, Any]] = []

    for index, bundle in enumerate(raw_rows):
        quote = bundle.get("quote") or {}
        fact = bundle.get("fact") or {}
        settlement = bundle.get("settlement") or {}
        model_eval = bundle.get("model_eval") or {}
        try:
            joined.append(join_evidence_row(quote, fact, settlement, model_eval))
        except PropOutcomeJoinError as exc:
            reason = str(exc)
            item = {"index": index, "reason": reason}
            if reason.startswith("AMBIGUOUS_SETTLEMENT:"):
                ambiguous.append(item)
            elif reason.startswith("VOID_SETTLEMENT:"):
                excluded.append({**item, "classification": "VOID_EXCLUDED"})
            else:
                raise

    origins = {row.evidence_origin for row in joined}
    if ambiguous:
        state = "BLOCKED_AMBIGUOUS_SETTLEMENT"
        evidence_class = "UNAVAILABLE"
    elif not joined:
        state = "BLOCKED_NO_SCORABLE_ROWS"
        evidence_class = "UNAVAILABLE"
    elif origins == {"REAL_ARCHIVE"}:
        state = "JOIN_READY_FOR_PIT_VALIDATION"
        evidence_class = "HISTORICAL_PIT_CANDIDATE"
    else:
        state = "SYNTHETIC_CONTRACT_PASS"
        evidence_class = "SYNTHETIC_CONTRACT_TEST"

    return {
        "schema_version": 1,
        "state": state,
        "evidence_class": evidence_class,
        "source_row_count": len(joined) + len(excluded) + len(ambiguous),
        "joined_row_count": len(joined),
        "void_excluded_count": len(excluded),
        "ambiguous_count": len(ambiguous),
        "rows": [asdict(row) for row in joined],
        "excluded": excluded,
        "ambiguous": ambiguous,
    }
