"""Driver for the FROZEN NFL team-totals forward runner.

``sportsedge/nfl_team_total_runner.py`` (``NFL_TEAM_TOTAL_RUNNER_V1``,
sha256-pinned by the freeze recorded in
``research/nfl_team_totals_forward_20261028/FREEZE_RECORD.md``) is
library-only. This driver is the operational shell around it:

- ``price`` reads a RUN-IT handoff capture file (``captures_all.json``
  shape: a mapping of DK event id -> capture entry whose
  ``game_lines.team_totals`` carries, per team, the main team-total
  line, both prices, and the capture timestamp), joins every game to
  the nflverse schedules record (the preregistration's section 3
  settlement source), builds the runner's ``SlateGame`` inputs, calls
  ``price_slate``, and writes the create-only entry records plus a
  run report (operational monitoring only: counts and refusal codes,
  never accuracy or CLV figures — preregistration section 4).
- ``settle`` reads a written entry-record file, attaches the section 7
  close from a later capture file of the same shape, and settles each
  row against the final team points in the schedules record via the
  runner's ``evaluate_close``.

Discipline:

- The driver is NOT part of the freeze pin set and never modifies the
  pinned engine, runner, config, or preregistration. It computes no
  section 6 metric: the family evaluator is PENDING (pinned later by
  amendment), and no interim looks are taken here.
- Authoritative identity (game_id, season, week, gameday, team codes)
  comes from the schedules record, never from the capture file's own
  labels; a capture game that cannot be matched to exactly one
  schedules row on its kickoff date is refused at the driver level
  (``DRIVER_SCHEDULE_MATCH_MISSING``) and never priced under an
  invented identity. The capture's claimed game_id, when it disagrees
  with the schedules record, is noted in the run report.
- Raw capture values (line, prices, timestamps) pass through to the
  runner unaltered: malformed rows earn the runner's own named
  refusals (``ENTRY_SINGLE_SIDED``, ``PRICE_INVALID``, ...), never a
  driver-side coercion into validity, and never a fabricated line.
- History is point-in-time: the runner's snapshot is the final
  regular-season games in the schedules record with gameday strictly
  before the slate's earliest gameday. Same-day and future rows in
  the schedules file never enter the snapshot.
- Record and report files are create-only (the runner's writer
  refuses to overwrite): a re-run against an existing slate file
  refuses rather than rewriting history.

PAPER / research only. Pricing a slate counts it toward the forward
test only under the freeze's own terms (first slate priced by the
pinned runner after the freeze-act merge); this driver starts no
clock by itself.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional, Sequence

from sportsedge import nfl_team_total_dist as eng
from sportsedge import nfl_team_total_runner as runner
from sportsedge.nfl_team_aliases import NflTeamAliasError, resolve_team

DRIVER_ID = "NFL_TEAM_TOTAL_DRIVER_V1"

# The alias table resolves the Rams to LAR; the nflverse schedules
# record (and therefore the engine's history) codes them LA. SlateGame
# team codes are always taken from the matched schedules row, so this
# normalization is used only to find that row.
_CODE_NORMALIZE = {"LAR": "LA"}

DRIVER_REFUSALS = (
    "DRIVER_SCHEDULE_MATCH_MISSING",
    "DRIVER_SCHEDULE_MATCH_AMBIGUOUS",
    "DRIVER_TEAM_UNRESOLVED",
    "DRIVER_TEAM_TOTAL_KEY_UNRESOLVED",
    "DRIVER_CAPTURE_MALFORMED",
)


class DriverRefusal(Exception):
    """Driver-level refusal: the run writes no records at all."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _parse_ts(value) -> Optional[datetime]:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _resolve_code(text) -> str:
    code = resolve_team(text)
    return _CODE_NORMALIZE.get(code, code)


# ---------------------------------------------------------------------------
# Schedules record (nflverse games file): the identity + settlement source
# ---------------------------------------------------------------------------

def load_schedules(games_path) -> list[eng.GameRecord]:
    """Load the nflverse games file (``.csv`` or ``.csv.gz``) as
    GameRecords, mirroring the freeze package's reproduction harness."""
    path = Path(games_path)
    if path.suffix == ".gz":
        fh = gzip.open(path, "rt", newline="", encoding="utf-8")
    else:
        fh = path.open("rt", newline="", encoding="utf-8")
    records: dict[str, eng.GameRecord] = {}
    with fh:
        for row in csv.DictReader(fh):
            def _score(value):
                value = (value or "").strip()
                return None if value == "" else int(float(value))
            rec = eng.GameRecord(
                season=int(row["season"]), week=int(row["week"]),
                gameday=str(row["gameday"]), game_id=str(row["game_id"]),
                home_team=str(row["home_team"]),
                away_team=str(row["away_team"]),
                home_score=_score(row.get("home_score")),
                away_score=_score(row.get("away_score")),
                game_type=str(row["game_type"]))
            records[rec.game_id] = rec
    return list(records.values())


def history_before(schedules: Sequence[eng.GameRecord],
                   slate_gameday: str) -> list[eng.GameRecord]:
    """The point-in-time history snapshot: final regular-season games
    strictly before the slate's earliest gameday."""
    return [g for g in schedules
            if g.is_final_regular and g.gameday < slate_gameday]


def _match_schedule(schedules: Sequence[eng.GameRecord], gameday: str,
                    away_code: str, home_code: str):
    hits = [g for g in schedules if g.gameday == gameday
            and g.away_team == away_code and g.home_team == home_code]
    if not hits:
        raise DriverRefusal(
            "DRIVER_SCHEDULE_MATCH_MISSING",
            f"{gameday} {away_code}@{home_code}")
    if len(hits) > 1:
        raise DriverRefusal(
            "DRIVER_SCHEDULE_MATCH_AMBIGUOUS",
            f"{gameday} {away_code}@{home_code}: "
            f"{[g.game_id for g in hits]}")
    return hits[0]


# ---------------------------------------------------------------------------
# Capture file (RUN-IT handoff shape) -> runner inputs
# ---------------------------------------------------------------------------

def load_captures(captures_path) -> dict:
    data = json.loads(Path(captures_path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise DriverRefusal("DRIVER_CAPTURE_MALFORMED",
                            "captures file is not a JSON object")
    return data


def _team_total_quotes(entry: dict, sched) -> dict:
    """Map the capture's team_totals block onto schedules team codes.

    Keys in the capture shape are team nicknames (e.g. "49ers"); each
    key must resolve to exactly one of the game's two teams. Values
    pass through raw — the runner validates them, not the driver.
    """
    block = ((entry.get("game_lines") or {}).get("team_totals")) or {}
    if not isinstance(block, dict):
        raise DriverRefusal("DRIVER_CAPTURE_MALFORMED",
                            f"{sched.game_id}: team_totals is not an object")
    by_code: dict[str, runner.PairedQuote] = {}
    for key, value in block.items():
        try:
            code = _resolve_code(key)
        except NflTeamAliasError:
            raise DriverRefusal(
                "DRIVER_TEAM_TOTAL_KEY_UNRESOLVED",
                f"{sched.game_id}: team_totals key {key!r}")
        if code not in (sched.home_team, sched.away_team) \
                or code in by_code:
            raise DriverRefusal(
                "DRIVER_TEAM_TOTAL_KEY_UNRESOLVED",
                f"{sched.game_id}: team_totals key {key!r} -> {code}")
        if not isinstance(value, dict):
            raise DriverRefusal(
                "DRIVER_CAPTURE_MALFORMED",
                f"{sched.game_id}: team_totals[{key!r}] is not an object")
        # The current capture contract is an atomic paired quote.  Never
        # overwrite explicitly supplied side clocks with the common clock:
        # doing so can turn a >150s pair into a manufactured zero-span pair.
        stamp = value.get("captured_at")
        # Missing/invalid common clocks pass through to the pinned runner,
        # which refuses that team's quote per row.  Refusing here would abort
        # settlement of unrelated, valid team rows in the same capture.
        atomic_time = _parse_ts(stamp)
        has_over = "over_captured_at" in value
        has_under = "under_captured_at" in value
        if has_over != has_under:
            raise DriverRefusal(
                "DRIVER_CAPTURE_MALFORMED",
                f"{sched.game_id}: team_totals[{key!r}] partial side clocks")
        if has_over:
            over_time = _parse_ts(value["over_captured_at"])
            under_time = _parse_ts(value["under_captured_at"])
            if (atomic_time is None or over_time is None
                    or under_time is None or over_time != atomic_time
                    or under_time != atomic_time):
                raise DriverRefusal(
                    "DRIVER_CAPTURE_MALFORMED",
                    f"{sched.game_id}: team_totals[{key!r}] side clocks "
                    "contradict atomic captured_at")
        by_code[code] = runner.PairedQuote(
            line=value.get("line"), over_price=value.get("over_price"),
            under_price=value.get("under_price"),
            over_captured_at=stamp, under_captured_at=stamp)
    return by_code


def build_slate_games(captures: dict,
                      schedules: Sequence[eng.GameRecord]):
    """Build (SlateGame list, driver refusal list, note list) from a
    capture mapping. Games that fail driver-level checks are refused
    per game with exactly one DRIVER_* code; they never abort the
    slate and are never priced under a guessed identity."""
    games, refusals, notes = [], [], []
    for event_id, entry in captures.items():
        if not isinstance(entry, dict):
            refusals.append({"event_id": event_id,
                             "reason": "DRIVER_CAPTURE_MALFORMED"})
            continue
        if entry.get("sport") != "NFL":
            notes.append({"event_id": event_id, "note": "NON_NFL_SKIPPED"})
            continue
        if entry.get("status") not in (None, "CAPTURED"):
            notes.append({"event_id": event_id,
                          "note": f"STATUS_{entry.get('status')}_SKIPPED"})
            continue
        try:
            games.append(_build_game(event_id, entry, schedules, notes))
        except DriverRefusal as refusal:
            refusals.append({"event_id": event_id, "reason": refusal.code,
                             "detail": str(refusal)})
    return games, refusals, notes


def _build_game(event_id, entry: dict,
                schedules: Sequence[eng.GameRecord], notes: list):
    event = entry.get("event") or ""
    away_name, sep, home_name = event.partition(" @ ")
    kickoff = entry.get("kickoff_ct")
    kickoff_ts = _parse_ts(kickoff)
    if not sep or kickoff_ts is None:
        raise DriverRefusal(
            "DRIVER_CAPTURE_MALFORMED",
            f"event {event_id}: unparseable event/kickoff")
    try:
        away_code = _resolve_code(away_name)
        home_code = _resolve_code(home_name)
    except NflTeamAliasError as err:
        raise DriverRefusal("DRIVER_TEAM_UNRESOLVED",
                            f"event {event_id}: {err}")
    sched = _match_schedule(schedules, kickoff_ts.date().isoformat(),
                            away_code, home_code)
    claimed = entry.get("game_id")
    if claimed and claimed != sched.game_id:
        notes.append({"event_id": event_id,
                      "note": "CAPTURE_GAME_ID_DIFFERS_FROM_SCHEDULES",
                      "capture_game_id": claimed,
                      "schedules_game_id": sched.game_id})
    total = (entry.get("game_lines") or {}).get("total") or {}
    return runner.SlateGame(
        game_id=sched.game_id, season=sched.season, week=sched.week,
        gameday=sched.gameday, home_team=sched.home_team,
        away_team=sched.away_team, home_name=home_name.strip(),
        away_name=away_name.strip(), kickoff=kickoff,
        entry_quotes=_team_total_quotes(entry, sched),
        total_line=total.get("line"),
        total_over_price=total.get("over_price"))


def close_quotes_for(captures: dict,
                     schedules_by_id: dict, record: dict) -> list:
    """The paired CLOSE quote candidates for one priced row, from a
    later capture file of the same shape (the game's final capture).
    Returns [] when the close capture carries no team-total pair for
    the record's team — evaluate_close then rules NO_CLOSE_ROW."""
    sched = schedules_by_id.get(record["game_id"])
    if sched is None:
        return []
    for entry in captures.values():
        if not isinstance(entry, dict) or entry.get("sport") != "NFL":
            continue
        event = entry.get("event") or ""
        kickoff_ts = _parse_ts(entry.get("kickoff_ct"))
        if kickoff_ts is None:
            continue
        try:
            codes = {_resolve_code(part) for part in event.split(" @ ")}
        except NflTeamAliasError:
            continue
        if codes != {sched.home_team, sched.away_team}:
            continue
        if kickoff_ts.date().isoformat() != sched.gameday:
            continue
        quotes = _team_total_quotes(entry, sched)
        quote = quotes.get(record["team"])
        return [quote] if quote is not None else []
    return []


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_price(args) -> int:
    captures = load_captures(args.captures)
    schedules = load_schedules(args.games)
    games, driver_refusals, notes = build_slate_games(captures, schedules)
    if not games:
        print(json.dumps({"driver": DRIVER_ID, "status": "NO_GAMES_BUILT",
                          "driver_refusals": driver_refusals,
                          "notes": notes}, indent=1))
        return 3
    slate_date = args.slate_date or min(g.gameday for g in games)
    earliest = min(g.gameday for g in games)
    history = history_before(schedules, earliest)
    now = _parse_ts(args.now) if args.now else datetime.now().astimezone()
    if now is None:
        raise DriverRefusal("DRIVER_CAPTURE_MALFORMED",
                            f"--now is not a tz-aware ISO timestamp: "
                            f"{args.now!r}")
    tt_runner = runner.TeamTotalRunner(history)
    if args.lane_a_mode == "manual":
        lane_a_provider, auto_context = None, False
    else:
        lane_a_provider, auto_context = "LIVE", True
    out = tt_runner.price_slate(slate_date, games, now=now,
                                lane_a_provider=lane_a_provider,
                                lane_a_auto_context=auto_context)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    records_path = out_dir / f"entry_{slate_date}.jsonl"
    report_path = out_dir / f"entry_{slate_date}.report.json"
    if records_path.exists() or report_path.exists():
        raise runner.RunnerRefusal("RECORD_FILE_EXISTS",
                                   str(records_path))
    if out["records"]:
        runner.write_entry_records(out["records"], records_path)
    report = {
        "driver": DRIVER_ID, "command": "price",
        "slate_date": slate_date, "priced_at": now.isoformat(),
        "lane_a_mode": args.lane_a_mode,
        "captures_sha256": _sha256_file(args.captures),
        "games_sha256": _sha256_file(args.games),
        "history_snapshot_sha256": tt_runner.history_sha256,
        "history_games": len(history),
        "games_built": len(games),
        "records_written": len(out["records"]),
        "records_file": str(records_path) if out["records"] else None,
        "runner_refusals": out["refusals"],
        "driver_refusals": driver_refusals,
        "notes": notes,
        "metrics_computed": False,
    }
    with report_path.open("x", encoding="utf-8") as fh:
        json.dump(report, fh, indent=1, sort_keys=True)
    print(json.dumps(report, indent=1, sort_keys=True))
    return 0 if out["records"] else 3


def cmd_settle(args) -> int:
    records = [json.loads(line) for line in
               Path(args.records).read_text(encoding="utf-8").splitlines()
               if line.strip()]
    captures = load_captures(args.captures)
    schedules = load_schedules(args.games)
    by_id = {g.game_id: g for g in schedules}
    void_games = set(args.void_game or [])
    settled = []
    for record in records:
        sched = by_id.get(record["game_id"])
        points = None
        if sched is not None and sched.is_final_regular:
            points = (sched.home_score if record["team"] == sched.home_team
                      else sched.away_score)
        settled.append(runner.evaluate_close(
            record, close_quotes_for(captures, by_id, record),
            void=record["game_id"] in void_games, final_team_points=points))
    out_path = Path(args.out)
    if out_path.exists():
        raise runner.RunnerRefusal("RECORD_FILE_EXISTS", str(out_path))
    runner.write_entry_records(settled, out_path)
    summary = {
        "driver": DRIVER_ID, "command": "settle",
        "records_file": args.records, "settlements_file": str(out_path),
        "rows": len(settled),
        "dispositions": sorted({row["close_status"] for row in settled}),
        "metrics_computed": False,
    }
    print(json.dumps(summary, indent=1, sort_keys=True))
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="nfl_team_total_driver",
        description="Operational driver for the frozen NFL team-totals "
                    "runner (NFL_TEAM_TOTAL_RUNNER_V1). Computes no "
                    "section 6 metrics.")
    sub = parser.add_subparsers(dest="command", required=True)

    price = sub.add_parser("price", help="price one slate from a capture "
                                         "file and write create-only "
                                         "entry records")
    price.add_argument("--captures", required=True,
                       help="captures_all.json (RUN-IT handoff shape)")
    price.add_argument("--games", required=True,
                       help="nflverse games file (.csv or .csv.gz): "
                            "identity, history, and settlement source")
    price.add_argument("--slate-date",
                       help="slate label (default: earliest game date)")
    price.add_argument("--out-dir", required=True,
                       help="directory for entry_<slate>.jsonl + report")
    price.add_argument("--now",
                       help="pricing moment, tz-aware ISO (default: now); "
                            "must be within 180 s after the entry quotes "
                            "and before kickoff, per the pinned runner")
    price.add_argument("--lane-a-mode", choices=("live", "manual"),
                       default="live",
                       help="live = Lane A public-context provider "
                            "(production); manual = Lane A's offline "
                            "no-fetch mode (replays, tests)")
    price.set_defaults(func=cmd_price)

    settle = sub.add_parser("settle", help="attach section 7 closes and "
                                           "final scores to written "
                                           "entry records")
    settle.add_argument("--records", required=True,
                        help="entry_<slate>.jsonl written by `price`")
    settle.add_argument("--captures", required=True,
                        help="final capture file (same shape) supplying "
                             "the closing team-total pairs")
    settle.add_argument("--games", required=True,
                        help="nflverse games file with final scores")
    settle.add_argument("--out", required=True,
                        help="settlement output .jsonl (create-only)")
    settle.add_argument("--void-game", action="append",
                        help="schedules game_id to settle VOID "
                             "(postponed/cancelled); repeatable")
    settle.set_defaults(func=cmd_settle)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (runner.RunnerRefusal, DriverRefusal) as refusal:
        print(json.dumps({"driver": DRIVER_ID, "status": "REFUSED",
                          "code": refusal.code, "detail": str(refusal)},
                         indent=1), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
