"""Coverage accounting for MLB Manual/Hybrid audit releases.

Every expected game/market-family contract must be represented as SCORED/PRICED,
BLOCKED or UNAVAILABLE. Silent omission is forbidden so coverage selection cannot hide
difficult rows from validation packages.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from typing import Iterable, Mapping, Any


class MLBCoverageError(ValueError):
    pass


@dataclass(frozen=True)
class MLBCoverageItem:
    game_id: str
    market_family: str
    status: str
    reason: str | None = None

    def validate(self) -> "MLBCoverageItem":
        if not self.game_id or not self.market_family:
            raise MLBCoverageError("MLB_COVERAGE_IDENTITY_REQUIRED")
        if self.status not in {"PRICED", "BLOCKED", "UNAVAILABLE"}:
            raise MLBCoverageError("MLB_COVERAGE_STATUS_INVALID")
        if self.status != "PRICED" and not str(self.reason or "").strip():
            raise MLBCoverageError("MLB_COVERAGE_REASON_REQUIRED")
        return self


@dataclass(frozen=True)
class MLBCoverageReport:
    expected_contracts: tuple[tuple[str, str], ...]
    items: tuple[MLBCoverageItem, ...]

    def validate(self) -> "MLBCoverageReport":
        expected = tuple((str(g), str(m)) for g, m in self.expected_contracts)
        if len(expected) != len(set(expected)):
            raise MLBCoverageError("MLB_COVERAGE_EXPECTED_DUPLICATE")
        for item in self.items:
            item.validate()
        actual = tuple((item.game_id, item.market_family) for item in self.items)
        if len(actual) != len(set(actual)):
            raise MLBCoverageError("MLB_COVERAGE_ITEM_DUPLICATE")
        missing = sorted(set(expected) - set(actual))
        extra = sorted(set(actual) - set(expected))
        if missing:
            raise MLBCoverageError("MLB_COVERAGE_SILENT_DROP:" + ",".join(f"{g}:{m}" for g, m in missing))
        if extra:
            raise MLBCoverageError("MLB_COVERAGE_UNEXPECTED:" + ",".join(f"{g}:{m}" for g, m in extra))
        return self

    @property
    def coverage_rate(self) -> float:
        self.validate()
        if not self.items:
            return 0.0
        return sum(item.status == "PRICED" for item in self.items) / len(self.items)

    def status_counts(self) -> dict[str, int]:
        self.validate()
        return {status: sum(item.status == status for item in self.items) for status in ("PRICED", "BLOCKED", "UNAVAILABLE")}

    def content_hash(self) -> str:
        self.validate()
        payload = {"expected_contracts": list(self.expected_contracts), "items": [asdict(x) for x in self.items]}
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        return sha256(raw).hexdigest()


def build_mlb_coverage_report(
    *,
    expected_contracts: Iterable[tuple[str, str]],
    result_rows: Iterable[Mapping[str, Any]],
) -> MLBCoverageReport:
    expected = tuple((str(game_id), str(market_family)) for game_id, market_family in expected_contracts)
    by_key: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for source in result_rows:
        row = dict(source)
        key = (str(row.get("game_id") or ""), str(row.get("market_family") or row.get("market") or ""))
        if key[0] and key[1]:
            by_key.setdefault(key, []).append(row)
    items: list[MLBCoverageItem] = []
    for game_id, market_family in expected:
        rows = by_key.get((game_id, market_family), [])
        if any(str(row.get("status") or row.get("bet_status") or "").upper() in {"PRICED", "BET", "PASS", "OFFICIAL_BET"} for row in rows):
            items.append(MLBCoverageItem(game_id, market_family, "PRICED"))
        elif rows:
            reasons = sorted({str(row.get("reason") or "BLOCKED") for row in rows})
            items.append(MLBCoverageItem(game_id, market_family, "BLOCKED", ";".join(reasons)))
        else:
            items.append(MLBCoverageItem(game_id, market_family, "UNAVAILABLE", "NO_RESULT_RETURNED"))
    return MLBCoverageReport(expected, tuple(items)).validate()
