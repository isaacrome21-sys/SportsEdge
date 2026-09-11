from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Iterable, Mapping, Sequence

from sportsedge.mlb_validation_dashboard import MLBValidationDashboardRow

DEFAULT_MARKETS = (
    "NRFI", "YRFI", "MONEYLINE", "RUN_LINE", "FULL_GAME_TOTAL",
    "PITCHER_OUTS", "PITCHER_STRIKEOUTS", "HOME_RUN",
)


class MLBMarketSnapshotError(ValueError):
    pass


@dataclass(frozen=True)
class MLBMarketSnapshot:
    snapshot_id: str
    snapshot_timestamp: str
    git_sha: str
    branch: str
    evaluator_sha: str
    model_sha: str
    feature_sha: str
    is_immutable: bool
    notes: str | None
    markets: tuple[dict[str, Any], ...]
    content_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))


def _canonical_payload(metadata: Mapping[str, Any], markets: Sequence[dict[str, Any]]) -> str:
    return json.dumps({"metadata": dict(metadata), "markets": list(markets)}, sort_keys=True,
                      separators=(",", ":"), default=str)


def build_market_snapshot(*, rows: Iterable[MLBValidationDashboardRow], git_sha: str, branch: str,
                          evaluator_sha: str, model_sha: str, feature_sha: str,
                          snapshot_timestamp: datetime | None = None, notes: str | None = None,
                          required_markets: Sequence[str] = DEFAULT_MARKETS) -> MLBMarketSnapshot:
    ts = snapshot_timestamp or datetime.now(timezone.utc)
    if ts.tzinfo is None:
        raise MLBMarketSnapshotError("snapshot_timestamp must be timezone-aware")
    ts = ts.astimezone(timezone.utc).replace(microsecond=0)
    by_market = {r.market: r.to_dict() for r in rows}
    missing = [m for m in required_markets if m not in by_market]
    if missing:
        raise MLBMarketSnapshotError(f"missing required market rows: {','.join(missing)}")
    ordered = tuple(by_market[m] for m in required_markets)
    stamp = ts.isoformat().replace("+00:00", "Z")
    snapshot_id = f"research-{stamp}"
    meta = {"snapshot_id": snapshot_id, "snapshot_timestamp": stamp, "git_sha": git_sha,
            "branch": branch, "evaluator_sha": evaluator_sha, "model_sha": model_sha,
            "feature_sha": feature_sha, "is_immutable": True, "notes": notes}
    digest = hashlib.sha256(_canonical_payload(meta, ordered).encode("utf-8")).hexdigest()
    return MLBMarketSnapshot(snapshot_id, stamp, git_sha, branch, evaluator_sha, model_sha,
                             feature_sha, True, notes, ordered, digest)


def snapshot_path(snapshot: MLBMarketSnapshot) -> str:
    safe = snapshot.snapshot_timestamp.replace(":", "").replace("-", "")
    return f"data/research/mlb/validation_snapshots/{safe}_{snapshot.content_sha256[:12]}.json"
