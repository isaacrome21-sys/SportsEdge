#!/usr/bin/env python3
"""Persist the last valid V5 pregame card for every game on the slate.

This never turns archived rows into current bets. It preserves the last card
that was actually generated while each game was still pregame, so a later run
can show the whole day's pregame evidence without pretending started games are
still wagerable.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

from sportsedge.mlb_source import fetch_schedule
from sportsedge.pregame_archive import update_pregame_archive

CARD=Path('artifacts/live_statcast_v5_full_model_card.json')
ARCHIVE=Path('.cache/sportsedge/v5-pregame/pregame_archive.json')
EXPORT=Path('artifacts/v5_pregame_archive.json')


def main()->int:
    card=json.loads(CARD.read_text())
    now=datetime.now(timezone.utc)
    slate=str(card['slate_date_ct'])
    schedule=fetch_schedule(slate,now=now)
    prior=json.loads(ARCHIVE.read_text()) if ARCHIVE.is_file() else None
    # Reuse the generic archive contract by exposing current V5 candidates as
    # result rows. Those rows already carry price, Model_P and Truth Gate state.
    archive=update_pregame_archive(
        schedule=schedule,now=now,prior=prior,
        card_payload={'generated_at_utc':card.get('generated_at_utc'),'results':card.get('game_candidates') or []},
        game_odds_payload=None,
    )
    ARCHIVE.parent.mkdir(parents=True,exist_ok=True)
    ARCHIVE.write_text(json.dumps(archive,indent=2,sort_keys=True)+'\n')
    EXPORT.parent.mkdir(parents=True,exist_ok=True)
    EXPORT.write_text(json.dumps(archive,indent=2,sort_keys=True)+'\n')
    print(json.dumps({'archived_games':len(archive.get('games') or {}),'path':str(EXPORT)},indent=2))
    return 0

if __name__=='__main__': raise SystemExit(main())
