#!/usr/bin/env python3
"""Attach full source-backed pregame context to a fresh V5 attestation."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

from sportsedge.catcher_context import load_savant_catcher_boards
from sportsedge.mlb_lineup_projection import build_slate_projections
from sportsedge.mlb_lineup_resolver import resolve_mlb_lineup
from sportsedge.mlb_source import fetch_boxscore, fetch_schedule
from sportsedge.pregame_context import build_full_pregame_context

ATT = Path("artifacts/live_statcast_v5_game_attestation.json")
OUT = Path("artifacts/live_statcast_v5_full_context.json")


def main() -> int:
    now = datetime.now(timezone.utc)
    data = json.loads(ATT.read_text())
    slate = str(data["slate_date_ct"])
    schedule = fetch_schedule(slate, now=now)
    team_ids = {int(g.away_id) for g in schedule} | {int(g.home_id) for g in schedule}
    projected, projection_failures = build_slate_projections(
        team_ids=team_ids, slate_date=datetime.fromisoformat(slate).date(), now=now
    )
    resolved = {}
    for game in data.get("games") or []:
        if game.get("status") != "SCORED_V5_ATTESTATION":
            continue
        gid = str(game["game_id"])
        snap = next((g for g in schedule if str(g.game_pk) == gid), None)
        if snap is None:
            raise SystemExit("CONTEXT_GAME_ID_NOT_IN_SCHEDULE:" + gid)
        box = fetch_boxscore(snap.game_pk)
        for side, tid, top3_key in (
            ("away", snap.away_id, "away_top3"), ("home", snap.home_id, "home_top3")
        ):
            lineup = resolve_mlb_lineup(box, side, int(tid), projected)
            scored_top3 = tuple(int(x) for x in (game.get(top3_key) or []))
            if lineup.top3() != scored_top3:
                raise SystemExit(f"CONTEXT_LINEUP_TOP3_MISMATCH:{gid}:{side}")
            resolved[(gid, side)] = lineup
            game[f"{side}_lineup_1_9"] = list(lineup.player_ids)
            game[f"{side}_full_lineup_basis"] = lineup.basis
            game[f"{side}_full_lineup_source_game_pks"] = list(lineup.source_game_pks)

    boards = load_savant_catcher_boards(int(slate[:4]))
    context = build_full_pregame_context(
        schedule=schedule, resolved_lineups=resolved, catcher_boards=boards, now=now
    )
    for game in data.get("games") or []:
        gid = str(game.get("game_id"))
        if gid in context:
            game["pregame_context"] = context[gid]

    data["context_schema_version"] = "sportsedge_full_pregame_context_v1"
    data["context_enriched_at_utc"] = now.isoformat()
    data["context_sources"] = {
        "weather_roof_umpire": "MLB_STATSAPI_LIVE_FEED",
        "catcher_identity": "MLB_STATSAPI_BOXSCORE_OR_ACTIVE_ROSTER",
        "catcher_metrics": "BASEBALL_SAVANT_VIA_FUNGO_2_0_0",
        "lineup": "CONFIRMED_MLB_OR_MLB_PRIOR_CONFIRMED_ACTIVE_ROSTER",
    }
    data["context_model_p_consumption"] = {
        "statcast": True,
        "lineup_identity": True,
        "weather": False,
        "plate_umpire": False,
        "catcher": False,
        "reason": "GAME_SCORE_V5_STATCAST feature contract is frozen; V6 revalidation required for new predictive inputs",
    }
    data["mlb_projection_failures"] = {str(k): v for k, v in sorted(projection_failures.items())}
    ATT.write_text(json.dumps(data, indent=2, sort_keys=True, default=str) + "\n")
    OUT.write_text(json.dumps({"generated_at_utc": now.isoformat(), "games": context}, indent=2, sort_keys=True, default=str) + "\n")
    print(json.dumps({"scored_games": len(resolved)//2, "context_games": len(context), "catcher_board_rows": {k: len(v) for k,v in boards.items()}}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
