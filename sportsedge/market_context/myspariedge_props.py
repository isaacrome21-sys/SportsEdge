"""MySpariEdge NFL player-prop trend research sidecar.

This module deliberately does **not** scrape MySpariEdge and does not invent a
private/public API.  It accepts structured records supplied by an authorized
acquisition/export adapter, validates their provenance and canonical identity,
and exposes them only as research context.

Historical hit rates are not probabilities.  Nothing in this module is allowed
to create or modify SportsEdge Model_P, Truth Gate eligibility, edge, EV, Kelly,
or an OFFICIAL recommendation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from typing import Any, Iterable, Mapping, Sequence


MYSPARIEDGE_PROP_CONTRACT = "NFL_MYSPARIEDGE_PROP_TRENDS_V1"
MYSPARIEDGE_SOURCE = "MYSPARIEDGE"
CONTEXT_LANE = "NFL_PROP_TREND_RESEARCH"
SUPPORTED_WINDOWS = ("L5", "L10", "L20", "SEASON", "H2H")
SUPPORTED_SIDES = frozenset({"OVER", "UNDER"})
MODEL_P_ELIGIBLE = False
TRUTH_GATE_ELIGIBLE = False
DECISION_EFFECT = "NONE"


class MySpariEdgeContextError(ValueError):
    """Raised when trend context is malformed, ambiguous, or unverifiable."""


def _utc(value: Any, field_name: str) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError) as exc:
            raise MySpariEdgeContextError(f"INVALID_TIMESTAMP:{field_name}") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise MySpariEdgeContextError(f"TIMESTAMP_MUST_BE_AWARE:{field_name}")
    return dt.astimezone(timezone.utc)


def _required_text(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise MySpariEdgeContextError(f"MISSING_IDENTITY:{field_name}")
    return text


def _source_url(value: Any) -> str:
    url = _required_text(value, "source_url")
    if not url.startswith("https://"):
        raise MySpariEdgeContextError("SOURCE_URL_MUST_BE_HTTPS")
    return url


def _sha256(value: Any, field_name: str = "source_sha256") -> str:
    digest = _required_text(value, field_name).lower()
    if len(digest) != 64:
        raise MySpariEdgeContextError(f"INVALID_SHA256:{field_name}")
    try:
        int(digest, 16)
    except ValueError as exc:
        raise MySpariEdgeContextError(f"INVALID_SHA256:{field_name}") from exc
    return digest


def _finite_line(value: Any) -> float:
    try:
        line = float(value)
    except (TypeError, ValueError) as exc:
        raise MySpariEdgeContextError("INVALID_PROP_LINE") from exc
    if not math.isfinite(line):
        raise MySpariEdgeContextError("INVALID_PROP_LINE")
    return line


def _canonical_payload_hash(records: Sequence[Mapping[str, Any]]) -> str:
    payload = json.dumps(list(records), sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class TrendWindow:
    """Observed historical hit count for one displayed MySpariEdge window."""

    label: str
    hits: int
    attempts: int
    reported_pct: float | None = None

    def __post_init__(self) -> None:
        label = str(self.label).strip().upper()
        if label not in SUPPORTED_WINDOWS:
            raise MySpariEdgeContextError(f"UNSUPPORTED_TREND_WINDOW:{label}")
        object.__setattr__(self, "label", label)
        if isinstance(self.hits, bool) or isinstance(self.attempts, bool):
            raise MySpariEdgeContextError(f"INVALID_SAMPLE_COUNT:{label}")
        try:
            hits = int(self.hits)
            attempts = int(self.attempts)
        except (TypeError, ValueError) as exc:
            raise MySpariEdgeContextError(f"INVALID_SAMPLE_COUNT:{label}") from exc
        if attempts <= 0 or hits < 0 or hits > attempts:
            raise MySpariEdgeContextError(f"INVALID_SAMPLE_COUNT:{label}")
        object.__setattr__(self, "hits", hits)
        object.__setattr__(self, "attempts", attempts)
        if self.reported_pct is not None:
            pct = float(self.reported_pct)
            if not math.isfinite(pct) or not 0.0 <= pct <= 100.0:
                raise MySpariEdgeContextError(f"INVALID_REPORTED_PCT:{label}")
            expected = 100.0 * hits / attempts
            # A displayed whole-number percentage may be rounded; tolerate <= 0.51pp.
            if abs(pct - expected) > 0.51:
                raise MySpariEdgeContextError(f"PCT_SAMPLE_CONTRADICTION:{label}")
            object.__setattr__(self, "reported_pct", pct)

    @property
    def hit_rate_pct(self) -> float:
        return 100.0 * self.hits / self.attempts


@dataclass(frozen=True)
class MySpariEdgePropObservation:
    """One exact player/market/side/line trend observation.

    Canonical IDs are required.  If the upstream page/export only contains
    names, an independent orchestration identity resolver must bind those names
    before constructing this object; this layer will not infer IDs from names.
    """

    observed_at: datetime
    captured_at: datetime
    source_url: str
    source_sha256: str
    player_id: str
    player_name: str
    opponent_team_id: str
    market_id: str
    side: str
    line: float
    trends: tuple[TrendWindow, ...]
    opponent_team_name: str | None = None
    source: str = field(default=MYSPARIEDGE_SOURCE, init=False)
    sport: str = field(default="NFL", init=False)
    contract: str = field(default=MYSPARIEDGE_PROP_CONTRACT, init=False)
    context_lane: str = field(default=CONTEXT_LANE, init=False)
    model_p_eligible: bool = field(default=False, init=False)
    truth_gate_eligible: bool = field(default=False, init=False)
    decision_effect: str = field(default=DECISION_EFFECT, init=False)

    def __post_init__(self) -> None:
        observed = _utc(self.observed_at, "observed_at")
        captured = _utc(self.captured_at, "captured_at")
        if observed > captured:
            raise MySpariEdgeContextError("OBSERVED_AFTER_CAPTURED")
        object.__setattr__(self, "observed_at", observed)
        object.__setattr__(self, "captured_at", captured)
        object.__setattr__(self, "source_url", _source_url(self.source_url))
        object.__setattr__(self, "source_sha256", _sha256(self.source_sha256))
        object.__setattr__(self, "player_id", _required_text(self.player_id, "player_id"))
        object.__setattr__(self, "player_name", _required_text(self.player_name, "player_name"))
        object.__setattr__(self, "opponent_team_id", _required_text(self.opponent_team_id, "opponent_team_id"))
        object.__setattr__(self, "market_id", _required_text(self.market_id, "market_id").upper())
        side = _required_text(self.side, "side").upper()
        if side not in SUPPORTED_SIDES:
            raise MySpariEdgeContextError(f"INVALID_PROP_SIDE:{side}")
        object.__setattr__(self, "side", side)
        object.__setattr__(self, "line", _finite_line(self.line))
        trends = tuple(self.trends)
        if not trends:
            raise MySpariEdgeContextError("TREND_SAMPLE_COUNTS_REQUIRED")
        labels = [trend.label for trend in trends]
        if len(labels) != len(set(labels)):
            raise MySpariEdgeContextError("DUPLICATE_TREND_WINDOW")
        object.__setattr__(self, "trends", trends)
        if self.opponent_team_name is not None:
            team_name = str(self.opponent_team_name).strip()
            object.__setattr__(self, "opponent_team_name", team_name or None)


@dataclass(frozen=True)
class MySpariEdgeSnapshot:
    captured_at: datetime
    source_url: str
    source_sha256: str
    observations: tuple[MySpariEdgePropObservation, ...]
    state: str
    content_hash: str
    notes: tuple[str, ...] = ()
    contract: str = field(default=MYSPARIEDGE_PROP_CONTRACT, init=False)
    context_lane: str = field(default=CONTEXT_LANE, init=False)
    model_p_eligible: bool = field(default=False, init=False)
    truth_gate_eligible: bool = field(default=False, init=False)
    decision_effect: str = field(default=DECISION_EFFECT, init=False)


@dataclass(frozen=True)
class PropTrendMatch:
    state: str
    reasons: tuple[str, ...]
    observation: MySpariEdgePropObservation | None
    line_delta: float | None
    as_of: datetime
    model_p_eligible: bool = field(default=False, init=False)
    truth_gate_eligible: bool = field(default=False, init=False)
    decision_effect: str = field(default=DECISION_EFFECT, init=False)


@dataclass(frozen=True)
class ModelTrendDiagnostic:
    """Descriptive comparison only; never an ensemble or probability adjustment."""

    model_p: float
    trend_hit_rates_pct: tuple[tuple[str, float], ...]
    directional_disagreement: bool
    decision_effect: str = field(default=DECISION_EFFECT, init=False)
    model_p_eligible: bool = field(default=False, init=False)
    truth_gate_eligible: bool = field(default=False, init=False)


def _parse_trend_window(raw: Mapping[str, Any]) -> TrendWindow:
    label = _required_text(raw.get("label"), "trend.label").upper()
    # Percent-only trend rows are deliberately rejected.  A displayed rate
    # without numerator/denominator hides sample size and cannot be audited.
    if raw.get("hits") in (None, "") or raw.get("attempts") in (None, ""):
        raise MySpariEdgeContextError(f"TREND_SAMPLE_COUNTS_REQUIRED:{label}")
    return TrendWindow(
        label=label,
        hits=raw.get("hits"),
        attempts=raw.get("attempts"),
        reported_pct=raw.get("reported_pct"),
    )


def parse_myspariedge_records(
    records: Sequence[Mapping[str, Any]],
    *,
    captured_at: Any,
    source_url: str,
    source_sha256: str | None = None,
) -> MySpariEdgeSnapshot:
    """Validate an authorized structured MySpariEdge export/acquisition payload.

    This function performs no network access and no name-to-ID inference.
    ``source_sha256`` should be the acquisition-layer hash when available.  If
    omitted, a deterministic hash of the exact structured records supplied to
    this boundary is recorded instead.
    """

    captured = _utc(captured_at, "captured_at")
    url = _source_url(source_url)
    raw_records = list(records)
    digest = _sha256(source_sha256) if source_sha256 is not None else _canonical_payload_hash(raw_records)
    observations: list[MySpariEdgePropObservation] = []
    for raw in raw_records:
        trend_rows = raw.get("trends")
        if not isinstance(trend_rows, Sequence) or isinstance(trend_rows, (str, bytes)):
            raise MySpariEdgeContextError("TREND_SAMPLE_COUNTS_REQUIRED")
        trends = tuple(_parse_trend_window(row) for row in trend_rows)
        observations.append(
            MySpariEdgePropObservation(
                observed_at=_utc(raw.get("observed_at", captured), "observed_at"),
                captured_at=captured,
                source_url=url,
                source_sha256=digest,
                player_id=raw.get("player_id"),
                player_name=raw.get("player_name"),
                opponent_team_id=raw.get("opponent_team_id"),
                opponent_team_name=raw.get("opponent_team_name"),
                market_id=raw.get("market_id"),
                side=raw.get("side"),
                line=raw.get("line"),
                trends=trends,
            )
        )
    state = "OK" if observations else "NO_DATA"
    canonical = {
        "contract": MYSPARIEDGE_PROP_CONTRACT,
        "source_url": url,
        "source_sha256": digest,
        "captured_at": captured.isoformat(),
        "observations": [
            {
                "observed_at": obs.observed_at.isoformat(),
                "player_id": obs.player_id,
                "opponent_team_id": obs.opponent_team_id,
                "market_id": obs.market_id,
                "side": obs.side,
                "line": obs.line,
                "trends": [(t.label, t.hits, t.attempts, t.reported_pct) for t in obs.trends],
            }
            for obs in observations
        ],
    }
    content_hash = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return MySpariEdgeSnapshot(
        captured_at=captured,
        source_url=url,
        source_sha256=digest,
        observations=tuple(observations),
        state=state,
        content_hash=content_hash,
        notes=("CONTEXT_ONLY_NOT_MODEL_P", "HISTORICAL_HIT_RATE_IS_NOT_PROBABILITY"),
    )


def find_prop_context(
    snapshot: MySpariEdgeSnapshot,
    *,
    player_id: str,
    opponent_team_id: str,
    market_id: str,
    side: str,
    line: float,
    as_of: Any,
    max_age: timedelta,
    line_tolerance: float = 1e-9,
) -> PropTrendMatch:
    """Match context to an exact canonical prop identity and report mismatches."""

    target_player = _required_text(player_id, "player_id")
    target_opp = _required_text(opponent_team_id, "opponent_team_id")
    target_market = _required_text(market_id, "market_id").upper()
    target_side = _required_text(side, "side").upper()
    target_line = _finite_line(line)
    pit = _utc(as_of, "as_of")
    if max_age.total_seconds() < 0:
        raise MySpariEdgeContextError("INVALID_MAX_AGE")
    if target_side not in SUPPORTED_SIDES:
        raise MySpariEdgeContextError(f"INVALID_PROP_SIDE:{target_side}")

    # Never use future context in a PIT decision.
    available = [obs for obs in snapshot.observations if obs.observed_at <= pit]
    if not available:
        return PropTrendMatch("NO_MATCH", ("NO_PIT_CONTEXT",), None, None, pit)

    player_rows = [obs for obs in available if obs.player_id == target_player]
    if not player_rows:
        return PropTrendMatch("IDENTITY_MISMATCH", ("PLAYER_ID_MISMATCH",), None, None, pit)
    opp_rows = [obs for obs in player_rows if obs.opponent_team_id == target_opp]
    if not opp_rows:
        return PropTrendMatch("IDENTITY_MISMATCH", ("OPPONENT_TEAM_ID_MISMATCH",), None, None, pit)
    market_rows = [obs for obs in opp_rows if obs.market_id == target_market]
    if not market_rows:
        return PropTrendMatch("IDENTITY_MISMATCH", ("MARKET_ID_MISMATCH",), None, None, pit)
    side_rows = [obs for obs in market_rows if obs.side == target_side]
    if not side_rows:
        return PropTrendMatch("IDENTITY_MISMATCH", ("SIDE_MISMATCH",), None, None, pit)

    # Prefer the freshest exact line.  If only another displayed line exists,
    # surface LINE_MISMATCH rather than silently treating its hit rate as equal.
    side_rows.sort(key=lambda obs: obs.observed_at, reverse=True)
    exact = [obs for obs in side_rows if abs(obs.line - target_line) <= line_tolerance]
    chosen = exact[0] if exact else min(side_rows, key=lambda obs: abs(obs.line - target_line))
    age = pit - chosen.observed_at
    if age > max_age:
        return PropTrendMatch(
            "STALE",
            ("SOURCE_STALE",),
            chosen,
            chosen.line - target_line,
            pit,
        )
    delta = chosen.line - target_line
    if abs(delta) > line_tolerance:
        return PropTrendMatch("LINE_MISMATCH", ("PROP_LINE_MISMATCH",), chosen, delta, pit)
    return PropTrendMatch("EXACT", (), chosen, 0.0, pit)


def compare_to_model(
    observation: MySpariEdgePropObservation,
    *,
    model_p: float,
) -> ModelTrendDiagnostic:
    """Return a non-actionable disagreement diagnostic without changing Model_P."""

    p = float(model_p)
    if not math.isfinite(p) or not 0.0 <= p <= 1.0:
        raise MySpariEdgeContextError("INVALID_MODEL_P")
    rates = tuple((trend.label, trend.hit_rate_pct) for trend in observation.trends)
    # Direction only: all displayed samples disagree with the model's side of
    # 50%.  This does not imply calibration, independence, or predictive power.
    if p > 0.5:
        disagreement = bool(rates) and all(rate < 50.0 for _, rate in rates)
    elif p < 0.5:
        disagreement = bool(rates) and all(rate > 50.0 for _, rate in rates)
    else:
        disagreement = False
    return ModelTrendDiagnostic(
        model_p=p,
        trend_hit_rates_pct=rates,
        directional_disagreement=disagreement,
    )


def research_sidecar(match: PropTrendMatch) -> Mapping[str, Any]:
    """Serialize a safe sidecar for RUN IT/reporting; never a model payload."""

    obs = match.observation
    return {
        "contract": MYSPARIEDGE_PROP_CONTRACT,
        "lane": CONTEXT_LANE,
        "source": MYSPARIEDGE_SOURCE,
        "state": match.state,
        "reason_codes": list(match.reasons),
        "line_delta": match.line_delta,
        "as_of": match.as_of.isoformat(),
        "model_p_eligible": False,
        "truth_gate_eligible": False,
        "decision_effect": DECISION_EFFECT,
        "historical_hit_rate_is_probability": False,
        "observation": None
        if obs is None
        else {
            "observed_at": obs.observed_at.isoformat(),
            "captured_at": obs.captured_at.isoformat(),
            "source_url": obs.source_url,
            "source_sha256": obs.source_sha256,
            "player_id": obs.player_id,
            "player_name": obs.player_name,
            "opponent_team_id": obs.opponent_team_id,
            "opponent_team_name": obs.opponent_team_name,
            "market_id": obs.market_id,
            "side": obs.side,
            "line": obs.line,
            "trends": [
                {
                    "label": trend.label,
                    "hits": trend.hits,
                    "attempts": trend.attempts,
                    "hit_rate_pct": trend.hit_rate_pct,
                }
                for trend in obs.trends
            ],
        },
    }


__all__ = [
    "CONTEXT_LANE",
    "DECISION_EFFECT",
    "MODEL_P_ELIGIBLE",
    "MYSPARIEDGE_PROP_CONTRACT",
    "MYSPARIEDGE_SOURCE",
    "TRUTH_GATE_ELIGIBLE",
    "ModelTrendDiagnostic",
    "MySpariEdgeContextError",
    "MySpariEdgePropObservation",
    "MySpariEdgeSnapshot",
    "PropTrendMatch",
    "TrendWindow",
    "compare_to_model",
    "find_prop_context",
    "parse_myspariedge_records",
    "research_sidecar",
]
