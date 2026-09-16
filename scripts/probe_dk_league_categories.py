from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Mapping
from urllib.request import Request, urlopen

from sportsedge.draftkings_game_market_source import (
    DK_ROOT,
    FULL_GAME_CATEGORY_ID,
    LEAGUE_IDS,
    RawDraftKingsBoard,
    normalize_board,
)

SPORTS = ("baseball_mlb", "americanfootball_nfl")
MAX_CATEGORY_PROBES = 60


def _fetch(url: str) -> tuple[bytes, Mapping[str, Any]]:
    req = Request(url, headers={
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 SportsEdge-DK-Category-Probe/1",
        "Referer": "https://sportsbook.draftkings.com/",
        "Origin": "https://sportsbook.draftkings.com",
    })
    with urlopen(req, timeout=20) as response:
        raw = response.read()
    payload = json.loads(raw)
    if not isinstance(payload, Mapping):
        raise RuntimeError("DK_PROBE_RESPONSE_NOT_OBJECT")
    return raw, payload


def _count_events(payload: Mapping[str, Any]) -> int:
    events = payload.get("events")
    return len(events) if isinstance(events, list) else 0


def _moneyline_market_count(payload: Mapping[str, Any]) -> int:
    markets = payload.get("markets")
    if not isinstance(markets, list):
        return 0
    return sum(1 for m in markets if isinstance(m, Mapping) and str(m.get("name") or "").strip() == "Moneyline")


def _valid_pair_count(sport_key: str, url: str, raw: bytes, payload: Mapping[str, Any]) -> int:
    board = RawDraftKingsBoard(
        sport_key=sport_key,
        source_uri=url,
        raw=raw,
        received_at=datetime.now(timezone.utc),
        payload=payload,
    )
    rows = [r for r in normalize_board(board) if r.get("market") == "h2h"]
    by_event: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_event.setdefault(str(row["provider_event_id"]), []).append(row)
    return sum(1 for event_rows in by_event.values() if len(event_rows) == 2)


def _category_candidates(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    found: dict[int, str | None] = {}

    def walk(value: Any, path: tuple[str, ...] = ()) -> None:
        if isinstance(value, Mapping):
            lower_path = "/".join(path).lower()
            category_context = "categor" in lower_path or any("categor" in str(k).lower() for k in value.keys())
            if category_context:
                raw_id = value.get("categoryId", value.get("categoryID", value.get("id")))
                try:
                    category_id = int(raw_id)
                except (TypeError, ValueError):
                    category_id = -1
                if category_id > 0:
                    name = value.get("name", value.get("displayName", value.get("label")))
                    found.setdefault(category_id, str(name) if name is not None else None)
            for key, child in value.items():
                walk(child, path + (str(key),))
        elif isinstance(value, list):
            for child in value:
                walk(child, path)

    walk(payload)
    return [{"category_id": cid, "name": found[cid]} for cid in sorted(found)]


def probe_sport(sport_key: str) -> dict[str, Any]:
    league_id = LEAGUE_IDS[sport_key]
    category_url = f"{DK_ROOT}/leagues/{league_id}/categories/{FULL_GAME_CATEGORY_ID}"
    bare_url = f"{DK_ROOT}/leagues/{league_id}"

    category_raw, category_payload = _fetch(category_url)
    bare_raw, bare_payload = _fetch(bare_url)
    current_pairs = _valid_pair_count(sport_key, category_url, category_raw, category_payload)
    bare_events = _count_events(bare_payload)
    category_events = _count_events(category_payload)

    advertised = _category_candidates(bare_payload)
    verified: list[dict[str, Any]] = []
    probed: list[dict[str, Any]] = []
    for item in advertised[:MAX_CATEGORY_PROBES]:
        cid = int(item["category_id"])
        url = f"{DK_ROOT}/leagues/{league_id}/categories/{cid}"
        try:
            raw, payload = (category_raw, category_payload) if cid == FULL_GAME_CATEGORY_ID else _fetch(url)
            pairs = _valid_pair_count(sport_key, url, raw, payload)
            result = {
                **item,
                "events": _count_events(payload),
                "moneyline_markets": _moneyline_market_count(payload),
                "valid_two_sided_moneyline_pairs": pairs,
                "raw_sha256": hashlib.sha256(raw).hexdigest(),
                "source_uri": url,
            }
            probed.append(result)
            if pairs > 0:
                verified.append(result)
        except Exception as exc:
            probed.append({**item, "source_uri": url, "error": type(exc).__name__})

    if current_pairs > 0:
        verdict = "CATEGORY_RETURNS_VALID_TWO_SIDED_MONEYLINE"
    elif category_events == 0 and bare_events > 0:
        verdict = "CATEGORY_ID_LIKELY_WRONG_FOR_THIS_LEAGUE"
    elif bare_events == 0:
        verdict = "LEAGUE_RETURNS_NO_EVENTS_AT_ALL"
    else:
        verdict = "CATEGORY_HAS_EVENTS_NO_VALID_MONEYLINE"

    return {
        "sport_key": sport_key,
        "league_id": league_id,
        "current_category_id": FULL_GAME_CATEGORY_ID,
        "current_category_uri": category_url,
        "current_category_raw_sha256": hashlib.sha256(category_raw).hexdigest(),
        "current_category_events": category_events,
        "current_category_moneyline_markets": _moneyline_market_count(category_payload),
        "current_category_valid_two_sided_moneyline_pairs": current_pairs,
        "bare_league_uri": bare_url,
        "bare_league_raw_sha256": hashlib.sha256(bare_raw).hexdigest(),
        "bare_league_events": bare_events,
        "advertised_categories": advertised,
        "category_probe_results": probed,
        "verified_category_candidates": verified,
        "verdict": verdict,
        "promotion_authority": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sports", nargs="*", default=list(SPORTS))
    parser.add_argument("--output", default="artifacts/dk_category_probe/latest.json")
    args = parser.parse_args()
    invalid = [s for s in args.sports if s not in LEAGUE_IDS]
    if invalid:
        raise SystemExit(f"unsupported sports: {invalid}")
    report = {
        "schema_version": 1,
        "observed_at_utc": datetime.now(timezone.utc).isoformat(),
        "acceptance_criterion": "category response must contain Moneyline markets that normalize to exact two-sided pairs",
        "sports": [probe_sport(s) for s in args.sports],
        "read_only_diagnostic": True,
        "promotion_authority": False,
    }
    from pathlib import Path
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
