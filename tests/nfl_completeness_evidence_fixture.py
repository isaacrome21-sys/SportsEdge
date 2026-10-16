"""Test fixture for the #2274 completeness proof (t207u + audits).

* The official game-day roster is a FIXED, independently declared list
  per team (OFFICIAL_GAMEDAY_ROSTERS) -- it is NOT derived from the
  inactive list or the depth chart.
* Manifests are real bytes under allowlisted sources from the committed
  config.  Their pins are returned SEPARATELY (operator_pins), modelling
  the operator flag; the evidence dict carries no pins at all.
"""
import hashlib
import json

INACTIVES_SCHEMA = "SPORTSEDGE_NFL_INACTIVES_MANIFEST_V1"
ROSTER_SCHEMA = "SPORTSEDGE_NFL_GAMEDAY_ROSTER_MANIFEST_V1"
OFFICIAL_INACTIVES_SOURCE = "NFL_GAMEDAY_INACTIVES"
OFFICIAL_ROSTER_SOURCE = "NFL_GSIS_GAMEDAY_ROSTER"

OFFICIAL_GAMEDAY_ROSTERS = {
    "CHI": (["qb1", "rb1", "rb2", "wr1", "wr2", "te1"]
            + [f"chi-inactive-{i}" for i in range(1, 7)]
            + [f"chi-dressed-{i:02d}" for i in range(1, 39)]),
    "GB": (["gqb", "grb", "gwr1", "gwr2"]
           + [f"gb-inactive-{i}" for i in range(1, 7)]
           + [f"gb-dressed-{i:02d}" for i in range(1, 39)]),
}


def canonical_sha256(obj):
    return hashlib.sha256(json.dumps(
        obj, sort_keys=True, separators=(",", ":"),
        ensure_ascii=True).encode()).hexdigest()


def official_roster(game_id, team, published, *, player_ids=None,
                    source=OFFICIAL_ROSTER_SOURCE):
    return {"game_id": game_id, "team": team, "published_at": published,
            "source": source,
            "player_ids": list(OFFICIAL_GAMEDAY_ROSTERS[team]
                               if player_ids is None else player_ids)}


def publisher_actives(snapshot):
    """The publisher's active list: official roster minus its inactives."""
    roster = OFFICIAL_GAMEDAY_ROSTERS[snapshot["team"]]
    missing = [p for p in snapshot["player_ids"] if p not in roster]
    assert not missing, f"fixture inactive ids not on official roster: {missing}"
    return [p for p in roster if p not in snapshot["player_ids"]]


def manifests(snapshots, rosters, *, inactives_source=OFFICIAL_INACTIVES_SOURCE,
              roster_source=OFFICIAL_ROSTER_SOURCE):
    inact = json.dumps({"schema": INACTIVES_SCHEMA, "source": inactives_source,
                        "entries": [{"game_id": s["game_id"], "team": s["team"],
                                     "snapshot_sha256": canonical_sha256(s)}
                                    for s in snapshots]}).encode()
    ros = json.dumps({"schema": ROSTER_SCHEMA, "source": roster_source,
                      "entries": [{"game_id": r["game_id"], "team": r["team"],
                                   "roster_sha256": canonical_sha256(r)}
                                  for r in rosters]}).encode()
    return {"inactives_manifest": inact, "roster_manifest": ros,
            "official_rosters": list(rosters)}


def operator_pins(evidence):
    """What an operator would pass on the trusted flag (never in evidence)."""
    return {"inactives": [hashlib.sha256(evidence["inactives_manifest"]).hexdigest()],
            "roster": [hashlib.sha256(evidence["roster_manifest"]).hexdigest()]}


def with_actives(snapshots):
    for s in snapshots:
        s["active_player_ids"] = publisher_actives(s)
    return snapshots


def prove(snapshots):
    """Independent official rosters + allowlisted manifests; returns
    (evidence, operator_pins)."""
    rosters = [official_roster(s["game_id"], s["team"], s["published_at"])
               for s in snapshots]
    ev = manifests(snapshots, rosters)
    return ev, operator_pins(ev)
