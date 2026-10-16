"""Synthetic statsapi-shaped raw schedule documents for challenger tests."""
from datetime import datetime, timezone

import hashlib
import json
import tempfile
from pathlib import Path

import sportsedge.research.mlb_total_offense_defense_challenger as ch
from sportsedge.research.mlb_total_offense_defense_challenger import FixtureIndex

NAMES = {"NYY": "New York Yankees", "BOS": "Boston Red Sox", "TOR": "Toronto Blue Jays",
         "BAL": "Baltimore Orioles", "A": "A", "B": "B", "C": "C", "D": "D"}


def raw_game(pk, away, home, start, *, away_runs=3, home_runs=4, game_number=1,
             double_header="N", final=True, **extra):
    if isinstance(start, datetime):
        start = start.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    game = {
        "gamePk": pk, "gameDate": start, "officialDate": start[:10],
        "gameNumber": game_number, "doubleHeader": double_header, "gameType": "R",
        "status": {"abstractGameState": "Final" if final else "Live",
                   "detailedState": "Final" if final else "In Progress"},
        "teams": {"away": {"team": {"id": 9000 + sum(map(ord, away)) % 900, "name": NAMES.get(away, away)},
                           "score": away_runs},
                  "home": {"team": {"id": 9000 + sum(map(ord, home)) % 900, "name": NAMES.get(home, home)},
                           "score": home_runs}},
    }
    game.update(extra)
    return {"dates": [{"date": start[:10], "games": [game]}]}


def row_for(doc, *, event_id=None, **override):
    g = doc["dates"][0]["games"][0]
    row = {"event_id": event_id or f"pk-{g['gamePk']}", "game_pk": g["gamePk"],
           "away_id": g["teams"]["away"]["team"]["name"],
           "home_id": g["teams"]["home"]["team"]["name"],
           "event_start_ts": g["gameDate"].replace("Z", "+00:00"),
           "final_observed_ts": "2099-01-01T00:00:00+00:00",
           "status": "FINAL",
           "away_runs": g["teams"]["away"]["score"], "home_runs": g["teams"]["home"]["score"]}
    row.update(override)
    return row


_TEST_PINS = set()
_MANIFEST = Path(tempfile.mkdtemp(prefix="mlb_fixture_manifest_")) / "manifest.json"


def trust(docs):
    """TEST ONLY: register these documents' digest in a test manifest and point
    the module's trusted-manifest constants at it (simulates an owner-reviewed
    manifest + code constant change)."""
    _TEST_PINS.add(FixtureIndex.digest_documents(docs))
    raw = json.dumps({"pinned_index_sha256": sorted(_TEST_PINS)}).encode()
    _MANIFEST.write_bytes(raw)
    ch.TRUSTED_MANIFEST_PATH = _MANIFEST
    ch.TRUSTED_MANIFEST_SHA256 = hashlib.sha256(raw).hexdigest()


def trusted_index(docs):
    trust(docs)
    return FixtureIndex.from_statsapi_documents(docs)


pinned_index = trusted_index
