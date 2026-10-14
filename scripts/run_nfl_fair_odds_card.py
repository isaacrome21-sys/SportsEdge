#!/usr/bin/env python3
"""NFL fair-price card: DraftKings vs Pinnacle / multi-book no-vig.

Uses the existing SPORTSEDGE_ODDS_API_KEY[_2.._4] pool. It is lower-priority paid
work under config/nfl_2026_provider_budget_v1.json: it spends credits only if
the remaining quota minus this request stays at or above the frozen 2026
confirmation reserve. One request: 3 markets x 1 bookmaker group = 3 credits.
Keys are never printed. Always writes a markdown file, even when it skips.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from sportsedge.odds_keyring import fetch_with_key_failover
from sportsedge.registry_gate import gate_odds_api_events as _registry_gate_odds_events
from sportsedge.sports.nfl.fair_odds import BOOKMAKERS, MARKETS, now_utc, render_card, upcoming

try:
    from scripts.odds_api_quota_guard import configured_keys, probe_quota
except ImportError:  # pragma: no cover - direct script execution
    from odds_api_quota_guard import configured_keys, probe_quota

BUDGET = Path("config/nfl_2026_provider_budget_v1.json")
REQUEST_COST = len(MARKETS)  # <=10 bookmakers count as one region
URL = "https://api.the-odds-api.com/v4/sports/americanfootball_nfl/odds"


def build_url() -> str:
    return URL + "?" + urlencode({
        "bookmakers": ",".join(BOOKMAKERS),
        "markets": ",".join(MARKETS),
        "oddsFormat": "american",
        "dateFormat": "iso",
    })


def _fetch(key: str) -> list:
    with urlopen(Request(f"{build_url()}&{urlencode({'apiKey': key})}",
                         headers={"Accept": "application/json", "User-Agent": "SportsEdge-NFL-FairOdds/1"}),
                 timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, list):
        raise ValueError("NFL_FAIR_ODDS_RESPONSE_NOT_LIST")
    return payload


def required_remaining(budget_path: Path = BUDGET) -> int:
    budget = json.loads(budget_path.read_text(encoding="utf-8"))
    reserve = int(budget["lower_priority_paid_work"]["minimum_confirmation_reserve_credits"])
    cap = int(budget["lower_priority_paid_work"]["max_single_forward_request_cost_credits"])
    if REQUEST_COST > cap:
        raise SystemExit("NFL_FAIR_ODDS_REQUEST_COST_ABOVE_BUDGET_CAP")
    return reserve + REQUEST_COST


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--from-json", type=Path, help="offline: render from a saved Odds API response")
    args = ap.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    now = now_utc()
    if args.from_json:
        events = json.loads(args.from_json.read_text(encoding="utf-8"))
    else:
        slots = configured_keys()
        quota = probe_quota(slots, minimum_remaining=required_remaining())
        if quota["state"] != "READY":
            args.out.write_text(
                "**NFL fair-price check skipped:** odds credits are low "
                f"({quota['reason']}), so they're saved for the frozen DK line captures. "
                "The main card above is unaffected.\n",
                encoding="utf-8",
            )
            print(json.dumps({"state": quota["state"], "reason": quota["reason"]}))
            return 0
        ready = {name for name in quota["ready_key_slots"]}
        keys = [key for name, key in slots if name in ready]
        try:
            events = fetch_with_key_failover(keys, _fetch).value
        except Exception as exc:  # message never contains a key
            args.out.write_text(f"**NFL fair-price check failed:** {type(exc).__name__}. The main card above is unaffected.\n",
                                encoding="utf-8")
            print(json.dumps({"state": "FETCH_FAILED", "error": type(exc).__name__}))
            return 0
        Path("artifacts").mkdir(exist_ok=True)
        Path("artifacts/nfl_fair_odds_raw.json").write_text(json.dumps(events) + "\n", encoding="utf-8")
    # t126: registry gate BEFORE any fair price is rendered to text.
    events, gate_stats = _registry_gate_odds_events(
        events, "NFL", "scripts/run_nfl_fair_odds_card.py")
    md = render_card(upcoming(events, now), fetched_at=now)
    md += ("\n_Registry gate: {checked} market quotes checked, {blocked} blocked, "
           "{unregistered} unregistered (sportsedge.registry_gate)._\n").format(**gate_stats)
    args.out.write_text(md, encoding="utf-8")
    print(json.dumps({"state": "OK", "events": len(events)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
