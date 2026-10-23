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
        # PRICED rows, and engine team mismatches (so the outcome does not
        # depend on stats row order when a same-week tie exists)
        eligible = r.get("status") == "PRICED" or r.get("reason") == "UNPRICED_PLAYER_TEAM_MISMATCH"
        if not eligible or pteams.get(r.get("player_id")) in gt:
            continue
        keep = {k: v for k, v in r.items() if k in _KEEP_ON_REFUSAL or k in LABEL_KEYS}
        r.clear()
        r.update(keep, status="UNPRICED", reason=DECLARED_PRICER_REFUSALS[0])
        n += 1
    return n


LABEL_KEYS = tuple(getattr(eng, "LABELS", {}).keys())


PRICER_FILES = ("atd_engine.py", "atd_refresh.py", "atd_provenance.py",
                "price_nfl_atd_board_v11.py")


def pricer_sha256() -> str:
    """sha256 of the frozen pricer: its code files and the data pin list."""
    import hashlib
    h = hashlib.sha256()
    here = Path(__file__).resolve().parent
    for n in PRICER_FILES:
        b = (here / n).read_bytes()
        h.update(f"{n}\0{len(b)}\0".encode() + b)
    b = Path(eng.PART2_HASHES).read_bytes()
    h.update(f"PINS\0{len(b)}\0".encode() + b)
    return h.hexdigest()


class PricingFailed(Exception):
    def __init__(self, code, detail=""):
        super().__init__(f"{code}: {detail}")
        self.code, self.detail = code, detail


def price_core(board, stats_path, schedule_path, player_data, *, now,
               fetched_at=None, run_record_path=None, extra_record=None):
    """The pricer proper, shared by pricing and the review replay. Pure in
    its inputs: files + board + injected `now` (+ fetched_at). Returns
    (rows, meta)."""
    import tempfile
    try:
        pins = eng.check_data_pins(Path(player_data))
    except SystemExit as e:
        raise PricingFailed("DATA_PIN_FAILED", str(e))
    try:
        sk = rf.schedule_kickoff(Path(schedule_path), int(board["season"]),
                                 board.get("game_teams"), board.get("kickoff"))
    except rf.RefreshFailed as e:
        raise PricingFailed(e.code, e.detail)
    base = eng.load_data(Path(player_data))
    pteams = pv.stats_teams(Path(stats_path).read_bytes(), int(board["season"]))
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

    with tempfile.TemporaryDirectory() as td:
        rrp = Path(run_record_path) if run_record_path else Path(td) / "run.json"
        try:
            rows = rf.run_slate(stats_path=Path(stats_path), schedule_path=Path(schedule_path),
                                season=int(board["season"]),
                                captured_at=board.get("captured_at"),
                                kickoff=board.get("kickoff"), run_record_path=rrp,
                                base_data=base, pricer=pricer,
                                extra_record=extra_record, now=now, fetched_at=fetched_at)
        except rf.RefreshFailed as e:
            raise PricingFailed(e.code, e.detail)
        refresh = json.loads(rrp.read_text())
    return rows, {"sk": sk, "pins": pins, "refusals": refusals, "refresh": refresh}


def replay(inputs: dict, *, now, fetched_at):
    """Re-run the pricer on exactly the branch records' bytes (review)."""
    import tempfile
    from datetime import datetime
    if isinstance(now, str):
        now = datetime.fromisoformat(now)
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        (td / "pd").mkdir()
        for n, b in inputs["player_data"].items():
            if "/" in n or n.startswith("."):
                raise PricingFailed("REPLAY_INPUT_INVALID", n)
            (td / "pd" / n).write_bytes(b)
        (td / "stats.csv.gz").write_bytes(inputs["stats"])
        (td / "games.csv").write_bytes(inputs["schedule"])
        board = json.loads(inputs["board"])
        rows, _ = price_core(board, td / "stats.csv.gz", td / "games.csv", td / "pd",
                             now=now, fetched_at=fetched_at)
    return rows


def _sha_file(p):
    import hashlib
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    for a in ("--player-data", "--stats-2026", "--schedule",
              "--board", "--out", "--run-record"):
        ap.add_argument(a, required=True)
    args = ap.parse_args()
    board = json.loads(Path(args.board).read_text())
    if not board.get("slate_id"):
        print("FAILED_CLOSED SLATE_ID_MISSING")
        return 2
    shas = {"stats": rf._sha(Path(args.stats_2026)),
            "schedule": rf._sha(Path(args.schedule))}
    bsha = _sha_file(args.board)
    try:
        pins = eng.check_data_pins(Path(args.player_data))
    except SystemExit as e:
        print(f"FAILED_CLOSED {e}")
        return 2
    # Every pricer input must already be a single-commit branch record
    # (re-audit of 353147d5): stats/schedule data + fetch records before
    # capture; the board capture and the player-data pins before the run.
    try:
        api = pv.GitHubAPI()
        prov = pv.require_fetch_provenance(api, shas, board.get("captured_at"))
        pv.prove_record(api, pv.board_record_path(bsha, board["season"], board["week"]))
        for n, h in pins.items():
            pv.load_data_record(api, h, "csv.gz", require_fetch=False)
    except (pv.ProvenanceFailed, ValueError, TypeError, OSError, KeyError) as e:
        # code + detail only; the token is never part of either
        print(f"FAILED_CLOSED {getattr(e, 'code', 'PROVENANCE_UNAVAILABLE')}: "
              f"{getattr(e, 'detail', type(e).__name__)}")
        return 2
    try:
        rows, meta = price_core(
            board, args.stats_2026, args.schedule, args.player_data,
            now=rf._utcnow(), run_record_path=Path(args.run_record),
            extra_record={"data_sha256": pins, "game_id": board["game_id"],
                          "slate_id": board.get("slate_id"), "fetch_provenance": prov,
                          "push_to": f"{pv.RECORDS_BRANCH}:"
                                     f"{pv.run_record_path(board.get('slate_id'))}",
                          "counts_only_if": "run record pushed (server time) before first kickoff"})
    except PricingFailed as e:
        print(f"FAILED_CLOSED {e.code}: {e.detail}")
        return 2
    sk, refusals = meta["sk"], meta["refusals"]
    # Run record = the slate's sole source at review (rule B): rows, hashes,
    # capture/kickoff and the raw fetch activity events (rule F).
    rr = json.loads(Path(args.run_record).read_text())
    rr.update(slate_id=board.get("slate_id"), captured_at=board.get("captured_at"),
              season=int(board["season"]), week=int(board["week"]),
              pricer_sha256=pricer_sha256(),
              inputs={"board": bsha, "stats": shas["stats"],
                      "schedule": shas["schedule"], "player_data": pins},
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
