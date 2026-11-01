"""Count player-prop coverage in a saved OddsPapi DraftKings board capture (no API calls).

Why: the NFL props step (#2916) needs the book's prop lines ("copy the book" half).
The daily board feed (#3009) saves DK odds per fixture; this checks whether those
files contain any player-prop markets or outcomes with a playerName.

usage: python simple/props_coverage.py MARKETS.json TOURN_A.json[,TOURN_B.json] DRAFTKINGS_HHMM.json [...]
"""
import json, sys
from collections import Counter


def coverage(markets_path, tournaments_path, dk_paths):
    M = {x["marketId"]: x for x in json.load(open(markets_path))}
    T = {x["tournamentId"]: x.get("tournamentName") for tp in tournaments_path.split(",") for x in json.load(open(tp))}
    out = {}
    for p in dk_paths:
        fx, mk, prop_mk, named, unknown = Counter(), Counter(), Counter(), Counter(), Counter()
        for f in json.load(open(p)):
            lg = "%s/%s" % (f.get("sportId"), T.get(f.get("tournamentId"), f.get("tournamentId")))
            fx[lg] += 1
            for mid, m in f.get("bookmakerOdds", {}).get("draftkings", {}).get("markets", {}).items():
                x = M.get(int(mid))
                mk[lg] += 1
                if x is None:
                    unknown[lg] += 1
                elif x.get("playerProp"):
                    prop_mk[lg] += 1
                for o in m.get("outcomes", {}).values():
                    for k, pl in o.get("players", {}).items():
                        if k != "0" or pl.get("playerName"):
                            named[lg] += 1
        out[p.split("/")[-1]] = {lg: {"fixtures": fx[lg], "markets": mk[lg], "player_prop_markets": prop_mk[lg],
                       "outcomes_with_player": named[lg], "markets_not_in_catalog": unknown[lg]}
                  for lg in sorted(fx)}
    return out


if __name__ == "__main__":
    print(json.dumps(coverage(sys.argv[1], sys.argv[2], sys.argv[3:]), indent=1))
