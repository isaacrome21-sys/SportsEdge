"""NFL anytime-TD engine v1 — board pricer (PREREG_NFL_ATD_ENGINE_V1.md §2).

Prices a captured DraftKings anytime-TD board (Yes-only) with the frozen
engine and emits per-row records under the locked forward-test contract
(docs/football/NFL_ANYTIME_TD_FORWARD_TEST_V1.md): model_p, raw implied,
descriptive edge (Rule 9), YES/PASS (Rule 1), or UNPRICED + reason (Rule 2).
Every priced row is a RESEARCH_ONLY unvalidated estimate; nothing is PLAY.

Usage:
  python3 price_nfl_atd_board.py --player-data DIR --board FILE --out FILE

Board JSON contract:
  {"season": 2026, "week": 7, "game_id": "...", "game_teams": ["DAL", "GB"],
   "captured_at": "...", "kickoff": "...",
   "rows": [{"player_name": "...", "yes_price": -230,
             "player_id": "<nflverse id, optional>"}]}
Rows carrying player_id (the Thursday capture standard, locked Rule 7) skip
name resolution entirely.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import atd_engine as eng

HERE = Path(__file__).resolve().parent
PREREG_NAME = "PREREG_NFL_ATD_ENGINE_V1.md"
PLAN_SHA256 = "c3907b08041ccd36827aedc7cb3de57c172d41269dde76fbd28a82cd8565e099"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--player-data", required=True)
    ap.add_argument("--board", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    got_plan = eng.sha256_bytes((HERE / PREREG_NAME).read_bytes())
    if got_plan != PLAN_SHA256:
        raise SystemExit(f"PREREG_HASH_MISMATCH: {got_plan} != {PLAN_SHA256}")
    pins = eng.check_data_pins(Path(args.player_data))
    board = json.loads(Path(args.board).read_text())
    data = eng.load_data(Path(args.player_data))
    idx = eng.build_name_index(data)
    rows = []
    for raw in board["rows"]:
        row = {
            "game_id": board["game_id"],
            "player_name": raw.get("player_name"),
            "player_id": raw.get("player_id"),
            "game_teams": board["game_teams"],
            "yes_price": raw["yes_price"],
            "captured_at": board.get("captured_at"),
            "kickoff": board.get("kickoff"),
            "season": int(board["season"]), "week": int(board["week"]),
        }
        rows.append(eng.price_board_row(data, idx, row))
    out = {
        "label": board.get("label",
                           "NFL ANYTIME TD ENGINE V1 — board pricing"),
        "status_label": "RESEARCH_ONLY", "validation_status": "NOT_VALIDATED",
        "prereg": PREREG_NAME, "prereg_sha256": PLAN_SHA256,
        "data_sha256": pins,
        "game_id": board["game_id"], "season": int(board["season"]),
        "week": int(board["week"]),
        "n_rows": len(rows),
        "n_priced": sum(1 for r in rows if r["status"] == "PRICED"),
        "n_unpriced": sum(1 for r in rows if r["status"] == "UNPRICED"),
        "rows": rows,
    }
    Path(args.out).write_text(json.dumps(out, indent=1, sort_keys=True) + "\n")
    print(json.dumps({"n_rows": out["n_rows"], "n_priced": out["n_priced"],
                      "n_unpriced": out["n_unpriced"]}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
