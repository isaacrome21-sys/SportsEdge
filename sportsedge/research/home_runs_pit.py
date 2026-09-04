"""Point-in-time model-row builder for the research HOME_RUNS challenger.

This module does not fetch odds, Statcast, lineups, or outcomes. It converts an
already-frozen pregame baseball payload into the exact model-row shape consumed by
``sportsedge.mlb_pit_joiner``. That separation is deliberate: source collectors own
timestamps/provenance, this module owns model identity/probabilities, and the PIT
joiner owns quote/game/player/settlement binding.

Version 0.2 is frozen here as the candidate. Its stable no-surge baseline is the
incumbent. v0.3 ablation arms live in ``home_runs_ablations`` and are not allowed to
silently replace either probability.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from math import isfinite
from typing import Any, Mapping

from .home_runs_engine import (
    ENGINE_VERSION,
    FEATURE_CONTRACT_VERSION,
    HomeRunsEngineError,
    simulate_home_runs,
)

MODEL_EVIDENCE_CLASSES = frozenset({"LIVE_PIT_MODEL", "SYNTHETIC_CONTRACT_TEST"})
MODEL_ROW_SCHEMA_VERSION = "hr_research_pit_model_row_v1"
MARKET = "HOME_RUNS"

_BANNED_MODEL_TOKENS = (
    "sportsbook", "book_odds", "american_odds", "decimal_odds", "market_prob",
    "implied_prob", "novig", "no_vig", "closing_prob", "closing_odds", "price",
    "consensus_prob", "ballparkpal", "bpp_probability", "benchmark_probability",
    "external_model_probability",
)


class HomeRunsPITError(ValueError):
    pass


def _dt(value: Any, field: str) -> datetime:
    text = str(value or "").strip().replace("Z", "+00:00")
    if not text:
        raise HomeRunsPITError(f"{field} required")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError as exc:
        raise HomeRunsPITError(f"{field} invalid") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise HomeRunsPITError(f"{field} timezone required")
    return dt.astimezone(timezone.utc)


def _sha256(value: Any) -> str:
    raw = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _valid_sha(value: Any, field: str) -> str:
    text = str(value or "").strip().lower()
    if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text):
        raise HomeRunsPITError(f"{field} must be SHA-256 hex")
    return text


def _assert_market_blind(value: Any, path: str = "model_input") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            name = str(key).strip().lower()
            if any(token in name for token in _BANNED_MODEL_TOKENS):
                raise HomeRunsPITError(f"market/external model field prohibited: {path}.{key}")
            _assert_market_blind(child, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _assert_market_blind(child, f"{path}[{index}]")


def _line(value: Any) -> float:
    if isinstance(value, bool):
        raise HomeRunsPITError("line must be numeric")
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise HomeRunsPITError("line must be numeric") from exc
    if not isfinite(out) or out != 0.5:
        raise HomeRunsPITError("research HOME_RUNS PIT currently supports only line 0.5")
    return out


def _side_probability(over_probability: float, side: str) -> float:
    direction = str(side or "").strip().upper()
    if direction == "OVER":
        return float(over_probability)
    if direction == "UNDER":
        return 1.0 - float(over_probability)
    raise HomeRunsPITError("HOME_RUNS side must be OVER or UNDER")


def build_home_runs_pit_model_row(
    *,
    game_id: Any,
    entity_id: Any,
    line: Any,
    side: Any,
    quote_ts: Any,
    first_pitch_ts: Any,
    history_asof_ts: Any,
    history_source_hash: Any,
    model_input: Mapping[str, Any],
    evidence_class: str = "LIVE_PIT_MODEL",
) -> dict[str, Any]:
    """Build one immutable-ready v0.2-vs-baseline model row for PIT joining.

    ``history_asof_ts`` must be at or before the quote timestamp, and the quote
    timestamp must precede first pitch. No post-quote feature material is accepted.
    """

    gid = str(game_id or "").strip()
    eid = str(entity_id or "").strip()
    if not gid or not eid:
        raise HomeRunsPITError("game_id and entity_id required")

    market_line = _line(line)
    direction = str(side or "").strip().upper()
    if direction not in {"OVER", "UNDER"}:
        raise HomeRunsPITError("HOME_RUNS side must be OVER or UNDER")

    quote = _dt(quote_ts, "quote_ts")
    first_pitch = _dt(first_pitch_ts, "first_pitch_ts")
    history_asof = _dt(history_asof_ts, "history_asof_ts")
    if not history_asof <= quote < first_pitch:
        raise HomeRunsPITError("PIT timestamp order requires history_asof <= quote < first_pitch")

    source_hash = _valid_sha(history_source_hash, "history_source_hash")
    klass = str(evidence_class or "").strip().upper()
    if klass not in MODEL_EVIDENCE_CLASSES:
        raise HomeRunsPITError("unsupported evidence_class")

    if not isinstance(model_input, Mapping):
        raise HomeRunsPITError("model_input must be a mapping")
    _assert_market_blind(model_input)

    internal = dict(model_input)
    # The public research engine uses a lowercase internal market identity while the
    # PIT row uses the canonical uppercase market identity.
    internal["market"] = "home_runs"
    try:
        output = simulate_home_runs(internal, thresholds=(0.5,))
    except HomeRunsEngineError as exc:
        raise HomeRunsPITError(str(exc)) from exc

    candidate_over = float(output.haircut_home_run_probability)
    incumbent_over = float(output.baseline_home_run_probability)
    candidate_p = _side_probability(candidate_over, direction)
    incumbent_p = _side_probability(incumbent_over, direction)

    identity = {
        "schema_version": MODEL_ROW_SCHEMA_VERSION,
        "game_id": gid,
        "market": MARKET,
        "entity_id": eid,
        "line": market_line,
        "side": direction,
        "quote_ts": quote.isoformat(),
        "first_pitch_ts": first_pitch.isoformat(),
        "history_asof_ts": history_asof.isoformat(),
        "history_source_hash": source_hash,
        "engine_version": ENGINE_VERSION,
        "feature_contract": FEATURE_CONTRACT_VERSION,
        "model_input_hash": output.model_input_hash,
        "candidate_p": candidate_p,
        "incumbent_p": incumbent_p,
    }
    return {
        **identity,
        "evidence_class": klass,
        "model_row_sha256": _sha256(identity),
        "candidate_model": "SURGE_HAIRCUT_V02",
        "incumbent_model": "STABLE_BASELINE_V01",
        "candidate_over_probability": candidate_over,
        "incumbent_over_probability": incumbent_over,
        "raw_over_probability": float(output.raw_home_run_probability),
        "contact_signal": float(output.contact_signal),
        "contact_reliability": float(output.contact_reliability),
        "surge_ratio": float(output.surge_ratio),
        "surge_label": str(output.surge_label),
    }
