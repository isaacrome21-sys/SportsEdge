#!/usr/bin/env python3
"""Audit public 2025 NFL prop/lineup sources without scoring any model rows.

This is intentionally source-only. It does not read outcomes, generate
predictions, compute Brier/calibration, or spend the frozen 2025 prop
validation window.

Market source is pinned to an immutable public GitHub commit. nflverse roster,
injury and depth assets are exact-byte hashed at audit time and are reported as
capabilities only; no source is silently promoted into "known inactive list".
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
import io
import json
from pathlib import Path
from typing import Any

import pandas as pd
import pyreadr
import requests

EXT_REPO_COMMIT = "d3fbfe1bece2f095e775f08d476cc5936ba37e13"
PROP_URLS = {
    "props_rows": (
        "https://raw.githubusercontent.com/emets393/new-wagerproof/"
        f"{EXT_REPO_COMMIT}/research/nfl-extreme-outcomes/data/props_rows.parquet"
    ),
    "props_rows_extra": (
        "https://raw.githubusercontent.com/emets393/new-wagerproof/"
        f"{EXT_REPO_COMMIT}/research/nfl-extreme-outcomes/data/props_rows_extra.parquet"
    ),
}
NFLVERSE_URLS = {
    "injuries": (
        "https://github.com/nflverse/nflverse-data/releases/download/"
        "injuries/injuries_2025.csv"
    ),
    "weekly_rosters": (
        "https://github.com/nflverse/nflverse-data/releases/download/"
        "weekly_rosters/roster_weekly_2025.csv"
    ),
    "depth_charts": (
        "https://github.com/nflverse/nflverse-data/releases/download/"
        "depth_charts/depth_charts_2025.rds"
    ),
}
TARGET_MARKETS = {
    "player_pass_yds",
    "player_rush_yds",
    "player_reception_yds",
}
DK_ALIASES = {"draftkings", "dk", "68"}


class SourceAuditError(ValueError):
    pass


def _fetch(url: str, *, timeout: int = 120) -> tuple[bytes, dict[str, Any]]:
    response = requests.get(
        url,
        timeout=timeout,
        headers={"User-Agent": "SportsEdge-NFL-prop-source-audit/1.0"},
    )
    response.raise_for_status()
    raw = response.content
    if not raw:
        raise SourceAuditError(f"SOURCE_EMPTY:{url}")
    return raw, {
        "url": url,
        "bytes": len(raw),
        "sha256": sha256(raw).hexdigest(),
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
    }


def _book_col(df: pd.DataFrame) -> str:
    for col in ("bookmaker", "book", "book_id"):
        if col in df.columns:
            return col
    raise SourceAuditError("PROP_BOOK_COLUMN_MISSING")


def _normalize_book(series: pd.Series) -> pd.Series:
    return series.astype("string").fillna("").str.strip().str.lower()


def _prop_source_audit(raw_files: dict[str, bytes]) -> dict[str, Any]:
    frames = []
    per_file = {}
    for label, raw in raw_files.items():
        df = pd.read_parquet(io.BytesIO(raw))
        per_file[label] = {
            "rows": int(len(df)),
            "columns": sorted(str(c) for c in df.columns),
        }
        frames.append(df)

    props = pd.concat(frames, ignore_index=True, sort=False)
    required = {
        "season",
        "week",
        "event_id",
        "player_id",
        "market",
        "line",
        "over_odds",
        "under_odds",
        "commence_time",
        "snapshot_time",
    }
    missing = sorted(required - set(props.columns))
    if missing:
        raise SourceAuditError("PROP_REQUIRED_COLUMNS_MISSING:" + ",".join(missing))

    props = props[pd.to_numeric(props["season"], errors="coerce").eq(2025)].copy()
    props["market"] = props["market"].astype("string").fillna("").str.strip().str.lower()
    props = props[props["market"].isin(TARGET_MARKETS)].copy()
    if props.empty:
        raise SourceAuditError("PROP_2025_TARGET_MARKETS_EMPTY")

    props["snapshot_time"] = pd.to_datetime(props["snapshot_time"], utc=True, errors="coerce")
    props["commence_time"] = pd.to_datetime(props["commence_time"], utc=True, errors="coerce")
    props["lead_minutes"] = (
        props["commence_time"] - props["snapshot_time"]
    ).dt.total_seconds() / 60.0

    book_col = _book_col(props)
    props["book_norm"] = _normalize_book(props[book_col])
    dk = props[props["book_norm"].isin(DK_ALIASES)].copy()

    identity = ["event_id", "player_id", "market", "book_norm"]
    pre = dk[
        dk["snapshot_time"].notna()
        & dk["commence_time"].notna()
        & dk["lead_minutes"].gt(0)
        & dk["line"].notna()
    ].copy()
    pre = pre.sort_values(identity + ["snapshot_time"])
    close = pre.drop_duplicates(identity, keep="last").copy()

    paired = close["over_odds"].notna() & close["under_odds"].notna()
    by_market = {}
    for market in sorted(TARGET_MARKETS):
        m = close[close["market"].eq(market)]
        leads = pd.to_numeric(m["lead_minutes"], errors="coerce").dropna()
        by_market[market] = {
            "close_rows": int(len(m)),
            "events": int(m["event_id"].nunique()),
            "players": int(m["player_id"].nunique()),
            "weeks": sorted(
                int(x)
                for x in pd.to_numeric(m["week"], errors="coerce").dropna().unique()
            ),
            "paired_price_rows": int(
                (m["over_odds"].notna() & m["under_odds"].notna()).sum()
            ),
            "lead_min": float(leads.min()) if len(leads) else None,
            "lead_p50": float(leads.median()) if len(leads) else None,
            "lead_max": float(leads.max()) if len(leads) else None,
            "within_15m": int(leads.le(15).sum()),
            "within_10m": int(leads.le(10).sum()),
            "within_7m": int(leads.le(7).sum()),
        }

    duplicate_close_keys = int(close.duplicated(identity, keep=False).sum())
    result = {
        "external_repository": "emets393/new-wagerproof",
        "external_commit": EXT_REPO_COMMIT,
        "files": per_file,
        "book_column": book_col,
        "2025_target_rows_all_books": int(len(props)),
        "2025_target_rows_draftkings": int(len(dk)),
        "draftkings_last_pre_kick_rows": int(len(close)),
        "draftkings_last_pre_kick_paired_rows": int(paired.sum()),
        "duplicate_close_keys": duplicate_close_keys,
        "markets": by_market,
        "post_kick_rows_draftkings": int((dk["lead_minutes"] <= 0).fillna(False).sum()),
        "market_source_admissible_for_close_research": bool(
            len(close)
            and paired.all()
            and duplicate_close_keys == 0
            and all(by_market[m]["close_rows"] > 0 for m in TARGET_MARKETS)
        ),
        "authority": "RESEARCH_VALIDATION_SOURCE_ONLY_NOT_FORWARD_EVIDENCE",
    }
    return result


def _status_counts(series: pd.Series) -> dict[str, int]:
    values = (
        series.astype("string")
        .fillna("")
        .str.strip()
        .str.upper()
    )
    counts = Counter(v for v in values if v)
    return dict(sorted(counts.items()))


def _injury_audit(raw: bytes) -> dict[str, Any]:
    df = pd.read_csv(io.BytesIO(raw), low_memory=False)
    out: dict[str, Any] = {
        "rows": int(len(df)),
        "columns": sorted(str(c) for c in df.columns),
    }
    for col in ("report_status", "practice_status"):
        out[f"{col}_counts"] = _status_counts(df[col]) if col in df.columns else {}
    if "date_modified" in df.columns:
        stamp = pd.to_datetime(df["date_modified"], utc=True, errors="coerce")
        out["date_modified_nonnull"] = int(stamp.notna().sum())
        out["date_modified_min"] = stamp.min().isoformat() if stamp.notna().any() else None
        out["date_modified_max"] = stamp.max().isoformat() if stamp.notna().any() else None
    else:
        out["date_modified_nonnull"] = 0
    statuses = set(out.get("report_status_counts", {}))
    out["explicit_inactive_status_present"] = "INACTIVE" in statuses
    out["explicit_out_status_present"] = "OUT" in statuses
    return out


def _roster_audit(raw: bytes) -> dict[str, Any]:
    df = pd.read_csv(io.BytesIO(raw), low_memory=False)
    out: dict[str, Any] = {
        "rows": int(len(df)),
        "columns": sorted(str(c) for c in df.columns),
        "status_counts": _status_counts(df["status"]) if "status" in df.columns else {},
    }
    weeks = pd.to_numeric(df.get("week"), errors="coerce") if "week" in df.columns else pd.Series(dtype=float)
    out["weeks"] = sorted(int(x) for x in weeks.dropna().unique())
    statuses = set(out["status_counts"])
    out["explicit_inactive_status_present"] = bool(
        statuses & {"INA", "INACTIVE"}
    )
    return out


def _depth_audit(raw: bytes, temp_dir: Path) -> dict[str, Any]:
    path = temp_dir / "depth_charts_2025.rds"
    path.write_bytes(raw)
    result = pyreadr.read_r(str(path))
    if not result:
        raise SourceAuditError("DEPTH_RDS_EMPTY")
    df = next(iter(result.values()))
    out: dict[str, Any] = {
        "rows": int(len(df)),
        "columns": sorted(str(c) for c in df.columns),
    }
    if "dt" in df.columns:
        stamps = pd.to_datetime(df["dt"], utc=True, errors="coerce")
        out["dt_nonnull"] = int(stamps.notna().sum())
        out["dt_min"] = stamps.min().isoformat() if stamps.notna().any() else None
        out["dt_max"] = stamps.max().isoformat() if stamps.notna().any() else None
    else:
        out["dt_nonnull"] = 0
    if "pos_rank" in df.columns:
        rank = pd.to_numeric(df["pos_rank"], errors="coerce")
        pos = (
            df.get("pos_abb", pd.Series("", index=df.index))
            .astype("string").fillna("").str.upper()
        )
        qb1 = df[pos.eq("QB") & rank.eq(1)]
        out["qb_rank1_rows"] = int(len(qb1))
        team_col = "team" if "team" in qb1.columns else "club_code" if "club_code" in qb1.columns else None
        out["qb_rank1_teams"] = int(qb1[team_col].nunique()) if team_col else 0
    else:
        out["qb_rank1_rows"] = 0
        out["qb_rank1_teams"] = 0
    return out


def run_audit(out_path: Path) -> dict[str, Any]:
    source_bytes: dict[str, bytes] = {}
    receipts: dict[str, Any] = {}

    for label, url in PROP_URLS.items():
        raw, receipt = _fetch(url)
        source_bytes[label] = raw
        receipts[label] = receipt

    nfl_bytes: dict[str, bytes] = {}
    for label, url in NFLVERSE_URLS.items():
        raw, receipt = _fetch(url)
        nfl_bytes[label] = raw
        receipts[label] = receipt

    with __import__("tempfile").TemporaryDirectory(prefix="sportsedge-prop-source-audit-") as tmp:
        depth = _depth_audit(nfl_bytes["depth_charts"], Path(tmp))

    props = _prop_source_audit(source_bytes)
    injuries = _injury_audit(nfl_bytes["injuries"])
    rosters = _roster_audit(nfl_bytes["weekly_rosters"])

    inactive_capability = bool(
        injuries["explicit_inactive_status_present"]
        or rosters["explicit_inactive_status_present"]
    )
    starter_capability = bool(depth["dt_nonnull"] and depth["qb_rank1_rows"])

    report = {
        "schema": "SPORTSEDGE_NFL_PROP_V1_SOURCE_AUDIT_V1",
        "status": "SOURCE_AUDIT_ONLY_NO_2025_MODEL_SCORING",
        "receipts": receipts,
        "prop_market_source": props,
        "injury_source": injuries,
        "weekly_roster_source": rosters,
        "depth_chart_source": depth,
        "capability": {
            "timestamped_2025_dk_yardage_close_tape": props[
                "market_source_admissible_for_close_research"
            ],
            "timestamped_qb_starter_depth_evidence": starter_capability,
            "explicit_inactive_status_available": inactive_capability,
            "frozen_2025_validation_window_spent": False,
        },
        "authority": {
            "source_admission_only": True,
            "model_scoring": False,
            "creates_model_p": False,
            "truth_gate": False,
            "official": False,
            "promotion": False,
            "staking": False,
            "forward_evidence": False,
        },
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print("NFL_PROP_V1_SOURCE_AUDIT=" + json.dumps(report, sort_keys=True))
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out",
        default="artifacts/nfl_prop_v1_source_audit/source_audit.json",
    )
    args = parser.parse_args()
    run_audit(Path(args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
