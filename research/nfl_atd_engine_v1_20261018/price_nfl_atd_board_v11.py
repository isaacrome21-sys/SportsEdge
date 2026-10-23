"""NFL anytime-TD engine v1.1 board pricer (DRAFT, pending owner freeze).

Same row contract and frozen math as price_nfl_atd_board.py, plus the v1.1
current-season refresh (atd_refresh): refresh -> run record with sha256 ->
price. A missing/failed/stale refresh exits non-zero; never 2025-only.

Usage:
  python3 price_nfl_atd_board_v11.py --player-data DIR --stats-2026 FILE \
      --schedule games.csv --board FILE --out FILE --run-record FILE
fetched_at is never a CLI argument: it is read from each file's download
sidecar (<file>.fetch.json, written by `python3 atd_refresh.py URL DEST`).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import atd_engine as eng
import atd_refresh as rf


def main() -> int:
    ap = argparse.ArgumentParser()
    for a in ("--player-data", "--stats-2026", "--schedule",
              "--board", "--out", "--run-record"):
        ap.add_argument(a, required=True)
    args = ap.parse_args()
    pins = eng.check_data_pins(Path(args.player_data))
    board = json.loads(Path(args.board).read_text())
    base = eng.load_data(Path(args.player_data))

    def pricer(data):
        idx = eng.build_name_index(data)
        rows = []
        for raw in board["rows"]:
            rows.append(eng.price_board_row(data, idx, {
                "game_id": board["game_id"], "player_name": raw.get("player_name"),
                "player_id": raw.get("player_id"), "game_teams": board["game_teams"],
                "yes_price": raw.get("yes_price"),
                "captured_at": board.get("captured_at"), "kickoff": board.get("kickoff"),
                "season": int(board["season"]), "week": int(board["week"])}))
        return rows

    try:
        rows = rf.run_slate(stats_path=Path(args.stats_2026),
                            schedule_path=Path(args.schedule),
                            season=int(board["season"]),
                            captured_at=board.get("captured_at"),
                            kickoff=board.get("kickoff"),
                            run_record_path=Path(args.run_record),
                            base_data=base, pricer=pricer,
                            extra_record={"data_sha256": pins,
                                          "game_id": board["game_id"]})
    except rf.RefreshFailed as e:
        print(f"FAILED_CLOSED {e.code}: {e.detail}")
        return 2
    out = {"label": "NFL ANYTIME TD ENGINE V1.1 (DRAFT) — board pricing",
           "status_label": "RESEARCH_ONLY", "validation_status": "NOT_VALIDATED",
           "run_record": str(args.run_record), "game_id": board["game_id"],
           "n_rows": len(rows),
           "n_priced": sum(r["status"] == "PRICED" for r in rows),
           "n_unpriced": sum(r["status"] == "UNPRICED" for r in rows),
           "rows": rows}
    Path(args.out).write_text(json.dumps(out, indent=1, sort_keys=True) + "\n")
    print(json.dumps({k: out[k] for k in ("n_rows", "n_priced", "n_unpriced")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
