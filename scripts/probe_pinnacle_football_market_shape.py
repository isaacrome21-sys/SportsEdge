#!/usr/bin/env python3
"""Freeze the live response shape needed for a direct Pinnacle NFL normalizer.

This is a one-shot, read-only, zero-authority probe. It fetches Pinnacle's
Football matchup list and deterministically selects the first provider-ordered
*upcoming NFL game* that is structurally a two-team home/away matchup with open
period-0 game markets. Specials, futures, props, live/started games, and neutral
multiway markets are excluded without fuzzy team-name inference.

The selected row already contains the game identity fields needed by SportsEdge,
so the probe does not depend on the redundant `/matchups/{id}` detail endpoint.
It preserves the matchup-list bytes and the selected game's straight-market
payload byte-for-byte. No Model_P or promotion authority is created here.
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
NFL_LEAGUE_NAME = "NFL"
SELECTION_RULE = "FIRST_PROVIDER_ORDERED_UPCOMING_NFL_MATCHUP_HOME_AWAY_PERIOD0_OPEN"


def _parse_ts(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def _is_upcoming_nfl_game(item: Mapping[str, Any], *, now: datetime) -> bool:
    league = item.get("league")
    if not isinstance(league, Mapping) or str(league.get("name") or "") != NFL_LEAGUE_NAME:
        return False
    if str(item.get("type") or "").lower() != "matchup":
        return False
    if item.get("special") is not None:
        return False
    if item.get("hasMarkets") is not True or item.get("id") is None:
        return False
    if str(item.get("status") or "").lower() != "pending":
        return False
    start = _parse_ts(item.get("startTime"))
    if start is None or start <= now:
        return False

    participants = item.get("participants")
    if not isinstance(participants, list) or len(participants) != 2:
        return False
    alignments = {str(p.get("alignment") or "").lower() for p in participants if isinstance(p, Mapping)}
    if alignments != {"home", "away"}:
        return False
    if any(not str(p.get("name") or "").strip() for p in participants if isinstance(p, Mapping)):
        return False

    periods = item.get("periods")
    if not isinstance(periods, list):
        return False
    period0 = next(
        (
            p for p in periods
            if isinstance(p, Mapping)
            and p.get("period") == 0
            and str(p.get("status") or "").lower() == "open"
        ),
        None,
    )
    if period0 is None:
        return False
    return bool(
        period0.get("hasMoneyline")
        and period0.get("hasSpread")
        and period0.get("hasTotal")
    )


def _first_upcoming_nfl_game(payload: Any, *, now: datetime) -> Mapping[str, Any]:
    if not isinstance(payload, list):
        raise DirectMarketProbeError("PINNACLE_FOOTBALL_MATCHUPS_NOT_LIST")
    for item in payload:
        if isinstance(item, Mapping) and _is_upcoming_nfl_game(item, now=now):
            return item
    raise DirectMarketProbeError("PINNACLE_FOOTBALL_NO_UPCOMING_NFL_GAME_MATCHUP")


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
        "selection_rule": SELECTION_RULE,
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
        selected = _first_upcoming_nfl_game(payload, now=captured_at)
        matchup_id = int(selected["id"])
        participants = {
            str(p.get("alignment") or "").lower(): str(p.get("name") or "").strip()
            for p in selected.get("participants") or []
            if isinstance(p, Mapping)
        }
        report["selected_matchup"] = {
            "matchup_id": matchup_id,
            "league": NFL_LEAGUE_NAME,
            "type": "matchup",
            "home_team": participants["home"],
            "away_team": participants["away"],
            "start_time": selected.get("startTime"),
            "has_markets": True,
            "item_keys": sorted(str(k) for k in selected.keys()),
        }

        raw, markets, status, content_type = _fetch(
            f"{PINNACLE_ROOT}/matchups/{matchup_id}/markets/related/straight",
            provider="pinnacle",
            opener=opener,
        )
        report["captures"]["straight_markets"] = {
            "http_status": status,
            "content_type": content_type,
            **_persist_raw(out_dir, "pinnacle", "straight_markets", raw),
            "shape": _shape(markets),
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
