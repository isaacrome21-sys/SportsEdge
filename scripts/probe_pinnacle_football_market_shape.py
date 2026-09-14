#!/usr/bin/env python3
"""Freeze the live response shape needed for a direct Pinnacle normalizer.

This is a one-shot, read-only, zero-authority probe. It fetches the Football
matchup list, selects the first provider-ordered matchup with ``hasMarkets=true``,
then preserves that matchup's detail and straight-market payload byte-for-byte.
The selection rule is deterministic and deliberately does not infer league/team
identity.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.request import urlopen

from scripts.probe_direct_market_feeds import (
    PINNACLE_ROOT,
    DirectMarketProbeError,
    _authority,
    _fetch,
    _persist_raw,
    _shape,
)

UTC = timezone.utc
FOOTBALL_SPORT_ID = 15


def _first_market_matchup(payload: Any) -> Mapping[str, Any]:
    if not isinstance(payload, list):
        raise DirectMarketProbeError("PINNACLE_FOOTBALL_MATCHUPS_NOT_LIST")
    for item in payload:
        if not isinstance(item, Mapping):
            continue
        if item.get("hasMarkets") is True and item.get("id") is not None:
            return item
    raise DirectMarketProbeError("PINNACLE_FOOTBALL_NO_MARKET_MATCHUP")


def probe(
    *,
    out_dir: Path,
    opener: Callable[..., Any] = urlopen,
    now: datetime | None = None,
) -> dict[str, Any]:
    captured_at = (now or datetime.now(UTC)).astimezone(UTC)
    out_dir.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "contract": "PINNACLE_FOOTBALL_MARKET_SHAPE_PROBE_V1",
        "state": "BLOCKED",
        "captured_at": captured_at.isoformat().replace("+00:00", "Z"),
        "selection_rule": "FIRST_PROVIDER_ORDERED_HASMARKETS_TRUE",
        "football_sport_id": FOOTBALL_SPORT_ID,
        "authority": _authority(),
        "captures": {},
    }

    try:
        matchups_url = f"{PINNACLE_ROOT}/sports/{FOOTBALL_SPORT_ID}/matchups"
        raw, payload, status, content_type = _fetch(
            matchups_url, provider="pinnacle", opener=opener
        )
        report["captures"]["matchups"] = {
            "http_status": status,
            "content_type": content_type,
            **_persist_raw(out_dir, "pinnacle", "football-matchups", raw),
            "shape": _shape(payload),
        }
        selected = _first_market_matchup(payload)
        matchup_id = int(selected["id"])
        report["selected_matchup"] = {
            "matchup_id": matchup_id,
            "item_keys": sorted(str(k) for k in selected.keys()),
            "has_markets": True,
        }

        for label, path in (
            ("matchup_detail", f"/matchups/{matchup_id}"),
            ("straight_markets", f"/matchups/{matchup_id}/markets/related/straight"),
        ):
            raw, payload, status, content_type = _fetch(
                f"{PINNACLE_ROOT}{path}", provider="pinnacle", opener=opener
            )
            report["captures"][label] = {
                "http_status": status,
                "content_type": content_type,
                **_persist_raw(out_dir, "pinnacle", label, raw),
                "shape": _shape(payload),
            }

        report["state"] = "REACHABLE"
    except DirectMarketProbeError as exc:
        report["reason"] = str(exc)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--status-out", required=True)
    args = parser.parse_args(argv)
    report = probe(out_dir=Path(args.out_dir))
    target = Path(args.status_out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["state"] == "REACHABLE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
