from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

SCHEMA_VERSION = "mlb_evidence_archive_v8_1"
FORWARD_EPOCH_UTC = "2026-09-03T00:00:00Z"

PIT_TIMESTAMPED = "PIT_TIMESTAMPED"
CLOSE_TIMESTAMPED = "CLOSE_TIMESTAMPED"
OPEN_CLOSE_ONLY = "OPEN_CLOSE_ONLY"
RESULT_ONLY = "RESULT_ONLY"
CONTEXT_REPLAY = "CONTEXT_REPLAY"
UNVERIFIED_IMPORT = "UNVERIFIED_IMPORT"

SOURCE_REGISTRY: dict[str, dict[str, Any]] = {
    "SPORTSEDGE_V8_FORWARD": {
        "evidence_class": PIT_TIMESTAMPED,
        "decision_eligible": True,
        "close_eligible": True,
        "coverage": "SportsEdge-owned immutable forward snapshots beginning 2026-09-03",
        "access": "internal",
        "notes": "Canonical forward evidence. Exact source bytes and model/distribution identity must be hash-bound.",
    },
    "THE_ODDS_API": {
        "evidence_class": PIT_TIMESTAMPED,
        "decision_eligible": True,
        "close_eligible": True,
        "coverage": "Featured historical snapshots from 2020; 5-minute snapshots since 2022-09; additional markets since 2023-05",
        "access": "paid historical API",
        "notes": "Historical endpoint returns closest snapshot at or before requested timestamp.",
    },
    "THEODDSAPI_COM": {
        "evidence_class": PIT_TIMESTAMPED,
        "decision_eligible": True,
        "close_eligible": True,
        "coverage": "Timestamped archive since 2026-05-13; standard MLB markets plus a documented subset of props",
        "access": "Business tier",
        "notes": "Separate provider from the-odds-api.com; never co-mingle provider identity.",
    },
    "OPTICODDS": {
        "evidence_class": PIT_TIMESTAMPED,
        "decision_eligible": True,
        "close_eligible": True,
        "coverage": "Full price-change history from posting to prestart; rolling two-month retention",
        "access": "licensed API",
        "notes": "Best suited to July-August rescue when queried before retention rolls off.",
    },
    "SPORTSDATAIO": {
        "evidence_class": PIT_TIMESTAMPED,
        "decision_eligible": True,
        "close_eligible": True,
        "coverage": "Opening, timestamped line movement, and closing prices for MLB game lines and props",
        "access": "licensed betting feeds",
        "notes": "General historical records are not arbitrary as-of revisions; betting line movement is the documented exception.",
    },
    "SPORTSGAMEODDS": {
        "evidence_class": OPEN_CLOSE_ONLY,
        "decision_eligible": False,
        "close_eligible": True,
        "coverage": "Historical events generally from 2024; bookmaker open/close fields documented from 2026-01",
        "access": "Pro+ historical",
        "notes": "Open/close can support close benchmarks but not a claimed mid-window decision timestamp.",
    },
    "THE_ODDS_GAP": {
        "evidence_class": PIT_TIMESTAMPED,
        "decision_eligible": True,
        "close_eligible": True,
        "coverage": "Per-scan game-line snapshots with a rolling window; prop checkpoints began early 2026-08",
        "access": "recent public / longer beta or licensed export",
        "notes": "Import only. Respect attribution and anti-bulk-scraping terms; do not build a sustained scraper.",
    },
    "MLB_STATSAPI": {
        "evidence_class": RESULT_ONLY,
        "decision_eligible": False,
        "close_eligible": False,
        "coverage": "Official schedule, game identity, and final outcomes",
        "access": "public",
        "notes": "Outcome/schedule authority only, never a market-price source.",
    },
    "BASEBALL_SAVANT": {
        "evidence_class": CONTEXT_REPLAY,
        "decision_eligible": False,
        "close_eligible": False,
        "coverage": "Historical pitch-level Statcast context",
        "access": "public",
        "notes": "Useful for strictly-prior feature replay; historical revisions mean source bytes should be archived and hashed.",
    },
}


def _utc(value: Any, field: str) -> datetime:
    if isinstance(value, datetime):
        out = value
    else:
        text = str(value or "").strip().replace("Z", "+00:00")
        if not text:
            raise ValueError(f"{field} missing")
        out = datetime.fromisoformat(text)
    if out.tzinfo is None or out.utcoffset() is None:
        raise ValueError(f"{field} timezone required")
    return out.astimezone(timezone.utc)


def iso_utc(value: Any, field: str) -> str:
    return _utc(value, field).isoformat().replace("+00:00", "Z")


def canonical_json_sha256(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")
    return sha256(raw).hexdigest()


def bytes_sha256(raw: bytes) -> str:
    return sha256(raw).hexdigest()


def american_implied_probability(price: int | float) -> float:
    p = float(price)
    if not math.isfinite(p) or p == 0:
        raise ValueError("american odds invalid")
    return (-p / (-p + 100.0)) if p < 0 else (100.0 / (p + 100.0))


def multiplicative_no_vig(prices: Sequence[int | float]) -> tuple[float, ...]:
    if len(prices) < 2:
        raise ValueError("paired/multiway prices required")
    raw = [american_implied_probability(p) for p in prices]
    total = sum(raw)
    if total <= 0:
        raise ValueError("invalid implied probability sum")
    return tuple(x / total for x in raw)


@dataclass(frozen=True)
class EvidenceRow:
    source_name: str
    source_uri: str
    source_record_sha256: str
    collected_at_utc: str
    observed_at_utc: str
    event_id: str
    commence_time_utc: str
    home_team: str
    away_team: str
    market: str
    side: str
    bookmaker: str | None
    american_odds: int | float | None
    line: float | None
    participant: str | None
    checkpoint: str
    evidence_class: str
    provider_last_update_utc: str | None = None
    provider_event_id: str | None = None
    source_tier: str | None = None
    metadata: Mapping[str, Any] | None = None
    schema_version: str = SCHEMA_VERSION

    def validate(self) -> "EvidenceRow":
        if self.source_name not in SOURCE_REGISTRY and self.evidence_class != UNVERIFIED_IMPORT:
            raise ValueError(f"unregistered source:{self.source_name}")
        if len(str(self.source_record_sha256)) != 64:
            raise ValueError("source_record_sha256 invalid")
        try:
            int(str(self.source_record_sha256), 16)
        except ValueError as exc:
            raise ValueError("source_record_sha256 invalid") from exc
        collected = _utc(self.collected_at_utc, "collected_at_utc")
        observed = _utc(self.observed_at_utc, "observed_at_utc")
        commence = _utc(self.commence_time_utc, "commence_time_utc")
        if self.evidence_class in {PIT_TIMESTAMPED, CLOSE_TIMESTAMPED} and observed > commence:
            raise ValueError("pregame PIT evidence observed after commence")
        if collected < observed and self.source_name == "SPORTSEDGE_V8_FORWARD":
            raise ValueError("forward collection precedes observation")
        if not all(str(x or "").strip() for x in (self.event_id, self.market, self.side, self.checkpoint)):
            raise ValueError("event/market/side/checkpoint required")
        if self.american_odds is not None:
            american_implied_probability(self.american_odds)
        return self

    @property
    def decision_eligible(self) -> bool:
        source = SOURCE_REGISTRY.get(self.source_name, {})
        return bool(source.get("decision_eligible")) and self.evidence_class == PIT_TIMESTAMPED

    @property
    def close_eligible(self) -> bool:
        source = SOURCE_REGISTRY.get(self.source_name, {})
        return bool(source.get("close_eligible")) and self.evidence_class in {
            PIT_TIMESTAMPED, CLOSE_TIMESTAMPED, OPEN_CLOSE_ONLY
        }

    @property
    def row_sha256(self) -> str:
        return canonical_json_sha256(asdict(self))

    def as_record(self) -> dict[str, Any]:
        self.validate()
        out = asdict(self)
        out["decision_eligible"] = self.decision_eligible
        out["close_eligible"] = self.close_eligible
        out["row_sha256"] = self.row_sha256
        return out


def threshold_key(row: EvidenceRow | Mapping[str, Any]) -> tuple[str, str, str, str, str, float | None, str | None]:
    get = (lambda k: getattr(row, k)) if isinstance(row, EvidenceRow) else row.get
    line = get("line")
    return (
        str(get("event_id")),
        str(get("market")),
        str(get("side")),
        str(get("bookmaker") or ""),
        str(get("participant") or ""),
        None if line is None else float(line),
        str(get("source_name") or ""),
    )


def pair_decision_to_close(
    decisions: Iterable[EvidenceRow], closes: Iterable[EvidenceRow]
) -> list[dict[str, Any]]:
    """Pair only comparable decision/close rows at the exact wager threshold.

    For moneyline ``line`` is None. For spread/total/prop rows the line is part of
    the key; a closing quote at a different threshold is deliberately not CLV.
    """
    close_index: dict[tuple[str, str, str, str, str, float | None, str | None], EvidenceRow] = {}
    for row in closes:
        row.validate()
        if not row.close_eligible:
            continue
        key = threshold_key(row)
        prior = close_index.get(key)
        if prior is None or _utc(row.observed_at_utc, "observed_at") > _utc(prior.observed_at_utc, "observed_at"):
            close_index[key] = row

    out: list[dict[str, Any]] = []
    for decision in decisions:
        decision.validate()
        if not decision.decision_eligible:
            continue
        close = close_index.get(threshold_key(decision))
        record = {
            "decision_row_sha256": decision.row_sha256,
            "close_row_sha256": None if close is None else close.row_sha256,
            "event_id": decision.event_id,
            "market": decision.market,
            "side": decision.side,
            "bookmaker": decision.bookmaker,
            "participant": decision.participant,
            "wager_line": decision.line,
            "decision_price": decision.american_odds,
            "close_price_same_threshold": None if close is None else close.american_odds,
            "comparable_close": close is not None,
            "reason": None if close is not None else "NO_EXACT_THRESHOLD_CLOSE",
        }
        out.append(record)
    return out


def append_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("a", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(dict(row), sort_keys=True, separators=(",", ":"), default=str) + "\n")
            count += 1
    return count
