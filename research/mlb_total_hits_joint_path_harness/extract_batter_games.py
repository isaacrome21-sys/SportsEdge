"""Per-batter per-game batting lines from the archived boxscores.

Emits batter_games.jsonl.gz: {d, g, b, h, s} — date, gamePk, batter id,
hits in that game, started (battingOrder slot x00). Used only by the
independence_convolution baseline (per-batter marginal game-hit
distributions). Same archive as dataset_build.py; no collectors.
"""
from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

CACHE = Path.home() / "workspace/tmp/bt_data"


def main() -> None:
    out_path = Path(sys.argv[1])
    games = [json.loads(line) for line in
             (out_path.parent / "games.jsonl").read_text().splitlines()]
    n = 0
    with gzip.open(out_path, "wt") as out:
        for facts in games:
            pk = facts["game_id"]
            box = json.loads((CACHE / f"boxscore_cache/{pk}.json").read_text())
            for side in ("away", "home"):
                for p in box["teams"][side]["players"].values():
                    bat = (p.get("stats") or {}).get("batting") or {}
                    if not bat:
                        continue
                    bo = str(p.get("battingOrder") or "")
                    out.write(json.dumps({
                        "d": facts["date"], "g": int(pk),
                        "b": p["person"]["id"], "h": bat.get("hits", 0),
                        "s": 1 if bo.endswith("00") else 0,
                    }) + "\n")
                    n += 1
    print("batter game rows:", n)


if __name__ == "__main__":
    main()
