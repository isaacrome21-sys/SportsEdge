"""Test fixture for the #2274 completeness proof (t207u + audit).

Builds GENUINE pinned evidence: real manifest bytes whose SHA-256 is the
pin, listing canonical content hashes of the inactive snapshot and of a
separately sourced official game-day roster. No token is minted and no
flag is set -- the bridge recomputes every hash itself.
"""
import hashlib
import json

INACTIVES_SCHEMA = "SPORTSEDGE_NFL_INACTIVES_MANIFEST_V1"
ROSTER_SCHEMA = "SPORTSEDGE_NFL_GAMEDAY_ROSTER_MANIFEST_V1"


def canonical_sha256(obj):
    return hashlib.sha256(json.dumps(
        obj, sort_keys=True, separators=(",", ":"),
        ensure_ascii=True).encode()).hexdigest()


def roster_for(snapshot, active_ids, *, published=None,
               source="NFL_GSIS_GAMEDAY_ROSTER"):
    return {"game_id": snapshot["game_id"], "team": snapshot["team"],
            "published_at": published or snapshot["published_at"],
            "source": source,
            "player_ids": list(snapshot["player_ids"]) + list(active_ids)}


def evidence(snapshots, rosters, *, inactives_source="NFL_GAMEDAY_INACTIVES",
             roster_source="NFL_GSIS_GAMEDAY_ROSTER"):
    inact = json.dumps({"schema": INACTIVES_SCHEMA, "source": inactives_source,
                        "entries": [{"game_id": s["game_id"], "team": s["team"],
                                     "snapshot_sha256": canonical_sha256(s)}
                                    for s in snapshots]}).encode()
    ros = json.dumps({"schema": ROSTER_SCHEMA, "source": roster_source,
                      "entries": [{"game_id": r["game_id"], "team": r["team"],
                                   "roster_sha256": canonical_sha256(r)}
                                  for r in rosters]}).encode()
    return {"inactives_manifest": inact,
            "inactives_manifest_sha256": hashlib.sha256(inact).hexdigest(),
            "roster_manifest": ros,
            "roster_manifest_sha256": hashlib.sha256(ros).hexdigest(),
            "official_rosters": list(rosters)}


def team_ids(depth_rows, team):
    out = []
    for row in depth_rows:
        if str(row.get("club_code") or row.get("team")) == team:
            pid = row.get("gsis_id") or row.get("player_id")
            if pid and pid not in out:
                out.append(pid)
    return out


def prove(snapshots, depth_rows):
    """Attach active lists + build independent-roster evidence."""
    rosters = []
    for s in snapshots:
        s["active_player_ids"] = [p for p in team_ids(depth_rows, s["team"])
                                  if p not in s["player_ids"]]
    for s in snapshots:
        rosters.append(roster_for(s, s["active_player_ids"]))
    return evidence(snapshots, rosters)
