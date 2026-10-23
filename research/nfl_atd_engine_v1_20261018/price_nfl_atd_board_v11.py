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
import atd_provenance as pv
import atd_refresh as rf


# Pricer-level refusal codes (prereg §4); separate from the engine's
# DECLARED_UNPRICED_REASONS. The pricer emits no others.
DECLARED_PRICER_REFUSALS = ("PLAYER_TEAM_UNRESOLVED",)

_KEEP_ON_REFUSAL = ("family", "label", "status_label", "promotable", "game_id",
                    "board_game_id", "player_name", "player_id", "yes_price",
                    "captured_at", "kickoff")


def player_team_refusal(rows, pteams, game_teams) -> int:
    """Refuse (before any price is recorded) every PRICED row whose player is
    absent from the pinned stats or whose latest stats team is not one of
    the game's two teams: UNPRICED / PLAYER_TEAM_UNRESOLVED. Mutates rows;
    returns the refusal count. Pinned data only, so the refusal set is fixed
    before capture and cannot depend on outcomes."""
    gt, n = set(game_teams or []), 0
    for r in rows:
        if r.get("status") != "PRICED" or pteams.get(r.get("player_id")) in gt:
            continue
        keep = {k: v for k, v in r.items() if k in _KEEP_ON_REFUSAL or k in LABEL_KEYS}
        r.clear()
        r.update(keep, status="UNPRICED", reason=DECLARED_PRICER_REFUSALS[0])
        n += 1
    return n


LABEL_KEYS = tuple(getattr(eng, "LABELS", {}).keys())


def main() -> int:
    ap = argparse.ArgumentParser()
    for a in ("--player-data", "--stats-2026", "--schedule",
              "--board", "--out", "--run-record"):
        ap.add_argument(a, required=True)
    args = ap.parse_args()
    pins = eng.check_data_pins(Path(args.player_data))
    board = json.loads(Path(args.board).read_text())
    if not board.get("slate_id"):
        print("FAILED_CLOSED SLATE_ID_MISSING")
        return 2
    # Server-side fetch provenance (re-audit #1): refuse unless each data
    # file's sha256 matches a fetch record on the records branch whose push
    # GitHub timestamps strictly before the entry capture.
    shas = {"stats": rf._sha(Path(args.stats_2026)),
            "schedule": rf._sha(Path(args.schedule))}
    try:
        sk = rf.schedule_kickoff(Path(args.schedule), int(board["season"]),
                                 board.get("game_teams"), board.get("kickoff"))
    except rf.RefreshFailed as e:
        print(f"FAILED_CLOSED {e.code}")
        return 2
    try:
        prov = pv.require_fetch_provenance(pv.GitHubAPI(), shas,
                                           board.get("captured_at"))
    except (pv.ProvenanceFailed, ValueError, TypeError, OSError) as e:
        # code + detail only; the token is never part of either
        print(f"FAILED_CLOSED {getattr(e, 'code', 'PROVENANCE_UNAVAILABLE')}: "
              f"{getattr(e, 'detail', type(e).__name__)}")
        return 2
    base = eng.load_data(Path(args.player_data))
    pteams = pv.stats_teams(Path(args.stats_2026).read_bytes(), int(board["season"]))
    refusals = {"PLAYER_TEAM_UNRESOLVED": 0}

    def pricer(data):
        idx = eng.build_name_index(data)
        rows = []
        for raw in board["rows"]:
            rows.append(eng.price_board_row(data, idx, {
                "game_id": sk["game_id"], "board_game_id": board["game_id"],
                "player_name": raw.get("player_name"),
                "player_id": raw.get("player_id"), "game_teams": board["game_teams"],
                "yes_price": raw.get("yes_price"),
                "captured_at": board.get("captured_at"), "kickoff": board.get("kickoff"),
                "season": int(board["season"]), "week": int(board["week"])}))
        refusals["PLAYER_TEAM_UNRESOLVED"] += player_team_refusal(
            rows, pteams, board["game_teams"])
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
                                          "game_id": board["game_id"],
                                          "slate_id": board.get("slate_id"),
                                          "fetch_provenance": prov,
                                          "push_to": f"{pv.RECORDS_BRANCH}:"
                                                     f"{pv.run_record_path(board.get('slate_id'))}",
                                          "counts_only_if": "run record pushed (server time) before first kickoff"})
    except rf.RefreshFailed as e:
        print(f"FAILED_CLOSED {e.code}: {e.detail}")
        return 2
    # Run record = the slate's sole source at review (rule B): rows, hashes,
    # capture/kickoff and the raw fetch activity events (rule F).
    rr = json.loads(Path(args.run_record).read_text())
    rr.update(slate_id=board.get("slate_id"), captured_at=board.get("captured_at"),
              season=int(board["season"]),
              schedule_kickoffs={sk["game_id"]: board.get("kickoff")},
              game_teams={sk["game_id"]: list(board["game_teams"])},
              schedule_game={"board_game_id": board["game_id"], **sk},
              first_kickoff=board.get("kickoff"), stats_sha256=shas["stats"],
              schedule_sha256=shas["schedule"],
              fetch_provenance={k: {"event": v["event"], "commit": v["commit"],
                                    "pushed_at": v["pushed_at"],
                                    "data_event": v["data_event"],
                                    "data_pushed_at": v["data_pushed_at"]}
                                for k, v in prov.items()},
              refusals=refusals, rows=rows)
    Path(args.run_record).write_text(json.dumps(rr, indent=1, sort_keys=True) + "\n")
    out = {"label": "NFL ANYTIME TD ENGINE V1.1 (DRAFT) — board pricing",
           "refusals": refusals,
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
