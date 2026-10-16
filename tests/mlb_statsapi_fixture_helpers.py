"""Synthetic statsapi-shaped raw schedule documents for challenger tests."""
from datetime import datetime, timezone

import hashlib
import json
import tempfile

import pytest
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


ORIGINALS = {"path": ch.TRUSTED_MANIFEST_PATH, "sha": ch.TRUSTED_MANIFEST_SHA256,
             "config": ch.IDENTITY_CONFIG_PATH}
_STATE = {"dir": None, "pins": set()}


def _write_manifest():
    cfg = hashlib.sha256(Path(ch.IDENTITY_CONFIG_PATH).read_bytes()).hexdigest()
    raw = json.dumps({"pinned_index_sha256": sorted(_STATE["pins"]),
                      "identity_config_sha256": cfg}).encode()
    path = _STATE["dir"] / "manifest.json"
    path.write_bytes(raw)
    ch.TRUSTED_MANIFEST_PATH = path
    ch.TRUSTED_MANIFEST_SHA256 = hashlib.sha256(raw).hexdigest()


def _manifest_session():
    """TEST ONLY: a temporary trusted manifest (simulating an owner-reviewed
    manifest + constant change).  Always restores the production constants."""
    _STATE["dir"] = Path(tempfile.mkdtemp(prefix="mlb_fixture_manifest_"))
    _STATE["pins"] = set()
    _write_manifest()
    try:
        yield
    finally:
        ch.TRUSTED_MANIFEST_PATH = ORIGINALS["path"]
        ch.TRUSTED_MANIFEST_SHA256 = ORIGINALS["sha"]
        ch.IDENTITY_CONFIG_PATH = ORIGINALS["config"]
        _STATE["dir"] = None


@pytest.fixture(autouse=True)
def trusted_manifest():
    yield from _manifest_session()


def trust(docs):
    if _STATE["dir"] is None:
        raise RuntimeError("trust() requires the trusted_manifest fixture")
    _STATE["pins"].add(FixtureIndex.digest_documents(docs))
    _write_manifest()


def use_config(path):
    """TEST ONLY: point at a threshold config and pin its sha in the test manifest."""
    ch.IDENTITY_CONFIG_PATH = Path(path)
    _write_manifest()


def trusted_index(docs):
    trust(docs)
    return FixtureIndex.from_statsapi_documents(docs)


pinned_index = trusted_index
