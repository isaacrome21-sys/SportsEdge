#!/usr/bin/env python3
"""Derive official MLB facts used by settlement validation.

Official MLB data proves on-field facts only. Sportsbook rule evidence remains a
separate required layer.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from sportsedge.mlb_settlement_evidence import as_int, batter_fact, build_settlement_report, canonical_bytes, pitcher_fact

GAME_PK = int(os.getenv("SPORTSEDGE_SETTLEMENT_PROBE_GAME_PK", "822696"))
BASE = "https://statsapi.mlb.com"
SOURCE = "MLB_STATSAPI_BOX_SCORE_AND_LIVE_FEED"


def get(path: str) -> dict[str, Any]:
    req = Request(BASE + path, headers={"Accept": "application/json", "User-Agent": "SportsEdge-settlement-probe/4"})
    with urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    feed = get(f"/api/v1.1/game/{GAME_PK}/feed/live")
    game_data = feed.get("gameData") or {}; status_payload = game_data.get("status") or {}
    abstract_state = str(status_payload.get("abstractGameState") or "")
    if abstract_state != "Final": raise SystemExit(f"PROBE_GAME_NOT_FINAL:{abstract_state}")
    teams = game_data.get("teams") or {}
    away_team_id = str(((teams.get("away") or {}).get("id")) or "")
    home_team_id = str(((teams.get("home") or {}).get("id")) or "")
    if not away_team_id or not home_team_id or away_team_id == home_team_id:
        raise SystemExit("GAME_TEAM_IDENTITY_MISSING")

    live = feed.get("liveData") or {}; box = get(f"/api/v1/game/{GAME_PK}/boxscore")
    linescore = live.get("linescore") or {}; innings = linescore.get("innings") or []
    if not innings: raise SystemExit("NO_INNINGS")
    away_runs = as_int(((linescore.get("teams") or {}).get("away") or {}).get("runs")); home_runs = as_int(((linescore.get("teams") or {}).get("home") or {}).get("runs"))
    if away_runs == home_runs: raise SystemExit("FINAL_GAME_TIE_UNSUPPORTED")
    f5_away = sum(as_int((((inning or {}).get("teams") or {}).get("away") or {}).get("runs")) for inning in innings if 1 <= as_int((inning or {}).get("num")) <= 5)
    f5_home = sum(as_int((((inning or {}).get("teams") or {}).get("home") or {}).get("runs")) for inning in innings if 1 <= as_int((inning or {}).get("num")) <= 5)
    first = next((inning for inning in innings if as_int((inning or {}).get("num")) == 1), None)
    if not first: raise SystemExit("FIRST_INNING_MISSING")
    first_away = as_int((((first or {}).get("teams") or {}).get("away") or {}).get("runs")); first_home = as_int((((first or {}).get("teams") or {}).get("home") or {}).get("runs"))

    batters: list[dict[str, Any]] = []; pitchers: list[dict[str, Any]] = []
    for side in ("away", "home"):
        players = ((((box.get("teams") or {}).get(side) or {}).get("players")) or {})
        for key, player in sorted(players.items()):
            player = player or {}; pid = str((player.get("person") or {}).get("id") or key.removeprefix("ID")); stats = player.get("stats") or {}; batting = stats.get("batting") or {}; pitching = stats.get("pitching") or {}
            if batting and as_int(batting.get("plateAppearances")) > 0: batters.append(batter_fact(pid, batting))
            if pitching:
                innings_text = str(pitching.get("inningsPitched") or "")
                appeared = as_int(pitching.get("battersFaced")) > 0 or innings_text not in {"", "0", "0.0"} or any(as_int(pitching.get(field)) > 0 for field in ("baseOnBalls", "strikeOuts", "hits", "earnedRuns"))
                if appeared: pitchers.append(pitcher_fact(pid, pitching))
    if not batters or not pitchers: raise SystemExit("PLAYER_FACTS_MISSING")

    all_plays = ((live.get("plays") or {}).get("allPlays") or []); hr_plays = []
    for sequence, play in enumerate(all_plays):
        result = (play or {}).get("result") or {}; event_type = str(result.get("eventType") or "").lower().replace(" ", "_")
        if event_type not in {"home_run", "home_run_inside_the_park"}: continue
        batter = ((play or {}).get("matchup") or {}).get("batter") or {}; pid = str(batter.get("id") or "")
        if not pid: raise SystemExit("HOME_RUN_BATTER_ID_MISSING")
        about = (play or {}).get("about") or {}
        hr_plays.append({"sequence": sequence, "at_bat_index": as_int(about.get("atBatIndex")), "inning": as_int(about.get("inning")), "half_inning": about.get("halfInning"), "batter_id": pid})
    first_home_run = {"occurred": False, "batter_id": None, "sequence": None, "at_bat_index": None, "inning": None, "half_inning": None}
    if hr_plays: first_home_run = {"occurred": True, **min(hr_plays, key=lambda row: (row["sequence"], row["at_bat_index"]))}
    winner_id = str(((live.get("decisions") or {}).get("winner") or {}).get("id") or "") or None

    box_teams = box.get("teams") or {}; team_hits = sum(as_int((((box_teams.get(side) or {}).get("teamStats") or {}).get("batting") or {}).get("hits")) for side in ("away", "home"))
    if sum(row["hits"] for row in batters) != team_hits: raise SystemExit("BATTER_HITS_RECONCILIATION_FAILED")
    if not (0 <= first_away + first_home <= away_runs + home_runs): raise SystemExit("FIRST_INNING_RECONCILIATION_FAILED")
    if not (0 <= f5_away + f5_home <= away_runs + home_runs): raise SystemExit("F5_RECONCILIATION_FAILED")
    if sum(row["home_runs"] for row in batters) != len(hr_plays): raise SystemExit("HOME_RUN_ORDER_RECONCILIATION_FAILED")
    if winner_id and winner_id not in {row["player_id"] for row in pitchers}: raise SystemExit("WINNING_PITCHER_NOT_IN_PITCHER_FACTS")

    inning_numbers = [as_int((inning or {}).get("num")) for inning in innings]
    score_identity = {"away_team_id": away_team_id, "home_team_id": home_team_id}
    facts = {
        "game_pk": str(GAME_PK), "status": "Final", "source": SOURCE,
        "game_context": {"abstract_game_state": abstract_state, "detailed_state": status_payload.get("detailedState"), "status_reason": status_payload.get("reason"), "completed_innings_observed": max(inning_numbers) if inning_numbers else 0},
        "game": {**score_identity, "away_runs": away_runs, "home_runs": home_runs, "run_diff_home": home_runs - away_runs, "total_runs": away_runs + home_runs},
        "f5": {**score_identity, "away_runs": f5_away, "home_runs": f5_home, "run_diff_home": f5_home - f5_away, "total_runs": f5_away + f5_home},
        "first_inning": {"away_runs": first_away, "home_runs": first_home, "nrfi": int(first_away + first_home == 0), "yrfi": int(first_away + first_home > 0)},
        "first_home_run": first_home_run, "winning_pitcher": {"pitcher_id": winner_id}, "batters": batters, "pitchers": pitchers,
    }
    report = build_settlement_report(facts, source=SOURCE, evidence_class="LIVE_OFFICIAL_FACT_PROBE")
    out = Path("artifacts/mlb-settlement-semantics/report.json"); out.parent.mkdir(parents=True, exist_ok=True); out.write_bytes(canonical_bytes(report))
    print(json.dumps({"official_facts_state": report["official_facts_state"], "book_settlement_state": report["book_settlement_state"], "settlement_semantics_validation_gate": report["settlement_semantics_validation_gate"], "game_pk": GAME_PK, "official_fact_markets": report["official_fact_market_count"], "market_count": report["market_count"], "facts_sha256": report["facts_sha256"]}, indent=2))
    return 0


if __name__ == "__main__": raise SystemExit(main())
