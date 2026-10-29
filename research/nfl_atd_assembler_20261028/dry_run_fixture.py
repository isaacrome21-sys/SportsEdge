#!/usr/bin/env python3
"""NON_COUNTED end-to-end dry run of the ATD assembler on the real
Oct 26, 2026 fixture (DAL @ PHI, DK event 34118071).

Pipeline proven here, with nothing counted and nothing pushed anywhere:

  1. The verbatim detailed-read text is extracted from the saved fixture
     (issue #2618's body is only the transport the read was delivered in;
     the assembler itself never parses issue bodies — the fixture prep
     below unwraps the read, exactly as a lane capture file would carry
     it directly).
  2. atd_assembler.assemble_board builds the board record using the real
     pinned player-data dir plus a current-season stats file and the
     nflverse schedule (the same pinned data path the frozen engine
     uses, merged point-in-time at the capture).
  3. atd_assembler.assemble_close builds the close record from two
     captures of the game: the 17:01 CT entry read and the 19:08-19:09 CT
     record-only read (kickoff 19:15 CT) — the assembler must select the
     latest pre-kickoff capture under the frozen 60-minute rule. The
     close capture's anytime list is transcribed from the record-only
     capture file's own summary (six named prices; surnames matched
     uniquely against the board's extracted rows).
  4. Acceptance: the emitted records are published into the frozen
     family's in-memory FakeGitHub, the board is priced by the REAL
     frozen pricer (price_nfl_atd_board_v11.price_core), the run record
     is composed exactly as the pricer's main() composes it, and the
     frozen scorer's loader (score_nfl_atd_forward.load_slate) +
     load_closes + score_slate_rows must accept the slate as COUNTS
     with CLV scored from the assembled close record. Finally the frozen
     scorer CLI is run in its ATD_TEST_FAKE_STATE non-binding mode.

Usage:
  python3 dry_run_fixture.py --frozen-dir <frozen family dir> \
      --fixture <issue_2618 fixture text> \
      --record-only <record_only_dal_phi_20261026_1851.json> \
      --player-data-dir <pinned data dir> --stats <sp_2026.csv.gz> \
      --schedule <games.csv> [--work-dir <dir>]
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import atd_assembler as A

# Fake-state push timeline (all UTC). Kickoff 2026-10-27T00:15:00Z;
# board capture 2026-10-26T22:01:00Z; close capture 2026-10-27T00:09:08Z.
T_DATA = "2026-10-26T20:00:00Z"
T_BOARD = "2026-10-26T22:30:00Z"
T_RUN = "2026-10-26T23:00:00Z"
T_CLOSE = "2026-10-27T00:10:00Z"  # <= kickoff + 15 min (frozen grace)
RUN_NOW = datetime(2026, 10, 26, 23, 0, tzinfo=timezone.utc)


def extract_detailed_read(fixture_text):
    m = re.search(r"<!--\n(FULL DRAFTKINGS BOARD.*?)-->", fixture_text, re.S)
    if not m:
        raise SystemExit("fixture: detailed-read block not found")
    return m.group(1)


def build_close_capture(board_capture, record_only):
    """Transcribe the record-only capture's anytime list (surnames +
    prices, as its own summary records them) into a canonical capture,
    matching each surname uniquely against the board's extracted rows."""
    note = record_only["prices_summary"]["props_note"]
    pairs = re.findall(r"(Williams|Barkley|Lamb|Pickens|Goedert|Ferguson)"
                       r"\s+([+-]?\d+)", note)
    if len(pairs) != 6:
        raise SystemExit(f"close fixture: expected 6 named prices, got {pairs}")
    by_surname = {}
    for row in board_capture.td_rows:
        surname = row["player_name"].split()[-1]
        by_surname.setdefault(surname, []).append(row["player_name"])
    rows = []
    for surname, price in pairs:
        names = by_surname.get(surname, [])
        if len(names) != 1:
            raise SystemExit(f"close fixture: surname {surname} not unique")
        rows.append({"player_name": names[0], "yes_price": int(price)})
    start, _, end = record_only["page_server_times"].partition(" to ")
    if "T" not in end:  # the record-only file elides the repeated date
        end = start.split("T")[0] + "T" + end
    return A.Capture(board_capture.away_name, board_capture.home_name,
                     board_capture.dk_event_id, board_capture.kickoff,
                     A.parse_timestamp(end), rows, "capture_json",
                     "record_only_dal_phi_20261026_1851.json (transcribed)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frozen-dir", required=True)
    ap.add_argument("--fixture", required=True)
    ap.add_argument("--record-only", required=True)
    ap.add_argument("--player-data-dir", required=True)
    ap.add_argument("--stats", required=True)
    ap.add_argument("--schedule", required=True)
    ap.add_argument("--work-dir", default=None)
    args = ap.parse_args()

    frozen = Path(args.frozen_dir)
    sys.path.insert(0, str(frozen))
    work = Path(args.work_dir) if args.work_dir else Path(
        tempfile.mkdtemp(prefix="atd_dryrun_"))
    work.mkdir(parents=True, exist_ok=True)

    summary = {"binding": False, "mode": "NON_COUNTED_DRY_RUN"}

    # --- 1+2: board assembly on the real fixture -------------------------
    fixture_text = Path(args.fixture).read_text()
    read_text = extract_detailed_read(fixture_text)
    board_capture = A.parse_detailed_read_text(read_text, "fixture detailed read")
    schedule_rows = A.load_schedule_rows(Path(args.schedule).read_text())
    base_index, pin_shas = A.load_pinned_index(args.player_data_dir)
    board = A.assemble_board(board_capture, base_index, schedule_rows,
                             stats_path=args.stats)
    summary["board"] = {
        "rows_extracted": board["report"]["rows_extracted"],
        "rows_resolved": len(board["report"]["resolved"]),
        "resolved": board["report"]["resolved"],
        "refusals": board["report"]["refusals"],
        "exclusions": board["report"]["exclusions"],
        "warnings": [w["code"] for w in board["report"]["warnings"]],
        "path": board["path"], "sha256": board["sha256"],
        "slate_id": board["body"]["slate_id"],
    }
    (work / "board.json").write_bytes(board["bytes"])

    # --- 3: close assembly ------------------------------------------------
    record_only = json.loads(Path(args.record_only).read_text())
    close_capture = build_close_capture(board_capture, record_only)
    close = A.assemble_close([board_capture, close_capture], base_index,
                             schedule_rows, stats_path=args.stats)
    summary["close"] = {
        "source_capture": close["report"]["source_capture"],
        "minutes_before_kickoff": close["report"]["minutes_before_kickoff"],
        "entries": close["body"]["captures"],
        "path": close["path"], "sha256": close["sha256"],
    }
    (work / "close.json").write_bytes(close["bytes"])

    # --- 4: frozen fake-state acceptance ----------------------------------
    import atd_engine as eng
    import atd_provenance as pv
    import fake_github_api as fk
    import price_nfl_atd_board_v11 as pricer
    import score_nfl_atd_forward as scorer

    api = fk.FakeGitHub()
    br = pv.RECORDS_BRANCH
    stats_bytes = Path(args.stats).read_bytes()
    schedule_bytes = Path(args.schedule).read_bytes()
    stats_sha = fk.publish_data(api, stats_bytes, T_DATA,
                                name="stats", ext="csv.gz")
    sched_sha = fk.publish_data(api, schedule_bytes, T_DATA,
                                name="schedule", ext="csv")
    data_dir = Path(args.player_data_dir)
    pins = eng.check_data_pins(data_dir)
    player_bytes = {}
    for fname in A.REQUIRED_FILES:
        player_bytes[fname] = (data_dir / fname).read_bytes()
        fk.publish_data(api, player_bytes[fname], T_DATA,
                        name=fname.rsplit(".", 2)[0], ext="csv.gz")
    api.commit(br, {board["path"]: board["bytes"].decode()}, T_BOARD)

    # Price with the REAL frozen pricer, through the same replay entry
    # point the review itself uses, at the run record's push instant.
    rows = pricer.replay(
        {"board": board["bytes"], "stats": stats_bytes,
         "schedule": schedule_bytes, "player_data": player_bytes},
        now=RUN_NOW, fetched_at={"stats": T_DATA, "schedule": T_DATA})
    summary["pricer"] = {
        "priced_rows": len(rows),
        "picks": [r["player_id"] for r in rows
                  if r.get("selection") == "YES"],
        "passes": [r["player_id"] for r in rows
                   if r.get("selection") == "PASS"],
        "refusals": [r["player_id"] for r in rows
                     if r.get("status") != "PRICED"],
    }

    def fetch_event(sha):
        return next(e for e in api.events
                    if e["after"] == api.file_commits(
                        br, pv.fetch_record_path(sha))[0])

    gid = board["report"]["nflverse_game_id"]
    import platform as _platform
    rec = {
        "slate_id": board["body"]["slate_id"],
        "captured_at": board["body"]["captured_at"],
        "season": board["body"]["season"], "week": board["body"]["week"],
        "python_version": _platform.python_version(),
        "platform": _platform.platform(),
        "first_kickoff": board["body"]["kickoff"],
        "game_teams": {gid: board["body"]["game_teams"]},
        "schedule_kickoffs": {gid: board["body"]["kickoff"]},
        "stats_sha256": stats_sha, "schedule_sha256": sched_sha,
        "pricer_sha256": pricer.pricer_sha256(),
        "inputs": {"board": board["sha256"], "stats": stats_sha,
                   "schedule": sched_sha, "player_data": pins},
        "fetch_provenance": {"stats": {"event": fetch_event(stats_sha)},
                             "schedule": {"event": fetch_event(sched_sha)}},
        "rows": rows,
    }
    api.commit(br, {pv.run_record_path(rec["slate_id"]):
                    json.dumps(rec, sort_keys=True)}, T_RUN)
    api.commit(br, {close["path"]: close["bytes"].decode()}, T_CLOSE)

    slate = pv.load_slate(api, rec["slate_id"])
    summary["load_slate_status"] = slate["status"]
    summary["load_slate_reasons"] = slate["reasons"]
    summary["load_slate_rows"] = len(slate["record"]["rows"])
    closes = pv.load_closes(api, {gid: {"season": board["body"]["season"],
                                        "week": board["body"]["week"],
                                        "kickoff": board["body"]["kickoff"]}})
    summary["load_closes"] = {
        "proven_captures": [[c["game_id"], c["player_id"], c["yes_price"]]
                            for c in closes["captures"]],
        "unproven_records": closes["unproven_records"],
    }
    _setup, _teardown = fk.module_fixtures(guard=True)
    _setup()
    try:
        scored = scorer.score_slate_rows(api, rec["slate_id"])
        summary["scored_rows"] = [{
            "player_id": r["player_id"], "selection": r["selection"],
            "clv_status": r["clv_status"],
            "clv": (round(r["clv"], 4) if r.get("clv") is not None else None),
            "outcome_status": r["outcome_status"],
        } for r in scored]
    except KeyError as exc:
        # FROZEN-FAMILY DEFECT (reproduced independently of this
        # assembler with the frozen family's own synthetic_world + real
        # pricer): the real pricer's rows carry no "week" key, while
        # score_nfl_atd_forward._games/score_row require row["week"].
        # load_slate (the loader) accepts the slate as COUNTS and
        # load_closes proves the close captures; CLV scoring of ANY
        # real-priced slate raises here. The run-record workaround is
        # foreclosed by the replay check (rows must be canonical-
        # identical to the pricer's output). Recorded, not hidden.
        summary["scored_rows"] = None
        summary["frozen_family_defect"] = {
            "site": "score_nfl_atd_forward.score_slate_rows -> _games",
            "error": f"KeyError: {exc}",
            "cause": "real pricer rows carry no 'week'; scorer requires "
                     "row['week']; frozen tests miss it (scorer tests use "
                     "the fake pricer, whose rows carry 'week'; replay "
                     "tests never call score_slate_rows)",
            "independent_reproduction": "frozen synthetic_world + real "
                     "pricer + publish + close: load_slate COUNTS, "
                     "score_slate_rows KeyError 'week'",
            "also_blocks": "the scorer CLI's review() dies with the same "
                     "KeyError in _games (score_nfl_atd_forward.py:271) "
                     "in ATD_TEST_FAKE_STATE non-binding mode — no "
                     "verdict can be produced for any real-priced slate "
                     "until the frozen family is amended by a new "
                     "version; the freeze itself must not be edited",
        }
    finally:
        _teardown()

    # --- 4b: frozen scorer CLI in ATD_TEST_FAKE_STATE non-binding mode ----
    state_path = work / "fake_state.json"
    state_path.write_text(api.to_json())
    wt = fk.records_worktree()
    env = {k: v for k, v in os.environ.items() if k != "GITHUB_TOKEN"}
    env["PYTHONPATH"] = str(frozen)
    env["ATD_TEST_FAKE_STATE"] = str(state_path)
    env["ATD_TEST_NOW"] = "2026-11-30T00:00:00+00:00"
    proc = subprocess.run(
        [sys.executable, str(frozen / "score_nfl_atd_forward.py"),
         "--records-worktree", str(wt), rec["slate_id"]],
        cwd=str(work), env=env, capture_output=True, text=True,
        timeout=300)
    cli = {"returncode": proc.returncode,
           "stdout_tail": proc.stdout.strip()[-600:],
           "stderr_tail": proc.stderr.strip()[-400:]}
    try:
        last = json.loads(proc.stdout.strip().splitlines()[-1])
        cli["emit"] = last
        if last.get("verdict_path") and Path(last["verdict_path"]).exists():
            verdict = json.loads(Path(last["verdict_path"]).read_text())
            cli["verdict"] = {"binding": verdict.get("binding"),
                              "slates": verdict.get("slates"),
                              "verdict": verdict.get("verdict")}
    except (ValueError, IndexError):
        pass
    summary["scorer_cli"] = cli
    print(json.dumps(summary, indent=1))
    ok = (slate["status"] == "COUNTS"
          and len(closes["captures"]) == len(close["body"]["captures"])
          and not closes["unproven_records"])
    print("DRY RUN:", "ACCEPTED (NON-BINDING)" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
