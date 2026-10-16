"""Synthetic statsapi-shaped raw schedule documents for challenger tests."""
from datetime import datetime, timezone

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


def pinned_index(docs):
    return FixtureIndex.from_statsapi_documents(docs, expected_sha256=FixtureIndex.digest_documents(docs))
