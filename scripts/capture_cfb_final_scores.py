#!/usr/bin/env python3
"""Persist CFB final scores into the repo so the probation ledger can grade.

  capture --date 2026-10-10 [--scoreboard-json saved.json] --output-dir ledger/cfb_finals
  grade   --ledger ledger/cfb_probation/<date>.json --finals ledger/cfb_finals/<date>.json
          --output ledger/cfb_probation_graded/<date>.json [--closing close_board.json]

Writes ledger/cfb_finals/<date>.json (schema CFB_FINAL_SCORES_V1): one row per
ESPN event whose status is completed (STATUS_FINAL*). Non-final games are
omitted, never guessed. Existing files are merged append-only: a game already
stored is never changed, and a conflicting score aborts the run.

The probation ledger stores ESPN event ids as game_id, so the join in
cfb_probation_ledger.grade stays exact (game_id + both team names).
Research-only plumbing; nothing here is OFFICIAL, validated, or promoted.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

SCHEMA = "CFB_FINAL_SCORES_V1"
ESPN = ("https://site.api.espn.com/apis/site/v2/sports/football/college-football/"
        "scoreboard?dates={d}&groups=80&limit=400")


def parse_scoreboard(payload: dict) -> list[dict]:
    out = []
    for ev in payload.get("events") or []:
        comp = (ev.get("competitions") or [{}])[0]
        st = ((comp.get("status") or ev.get("status") or {}).get("type") or {})
        if not st.get("completed") or not str(st.get("name", "")).startswith("STATUS_FINAL"):
            continue
        teams = {c.get("homeAway"): c for c in comp.get("competitors") or []}
        if set(teams) != {"home", "away"}:
            raise ValueError("CFB_FINALS_COMPETITORS_INVALID:" + str(ev.get("id")))
        pts = {}
        for side, c in teams.items():
            v = float(c.get("score"))
            if not (math.isfinite(v) and v >= 0 and v.is_integer()):
                raise ValueError("CFB_FINALS_SCORE_INVALID:" + str(ev.get("id")))
            pts[side] = int(v)
        out.append({
            "game_id": str(ev["id"]),
            "away_team": teams["away"]["team"].get("location") or teams["away"]["team"]["displayName"],
            "home_team": teams["home"]["team"].get("location") or teams["home"]["team"]["displayName"],
            "away_points": pts["away"], "home_points": pts["home"],
            "status": st.get("name"), "start_ts": ev.get("date"),
        })
    return out


def merge(existing: dict | None, rows: list[dict], *, date: str, captured_at: str) -> dict:
    doc = existing or {"schema": SCHEMA, "date": date, "source": "ESPN_SCOREBOARD",
                       "official": False, "games": []}
    if doc.get("schema") != SCHEMA:
        raise ValueError("CFB_FINALS_SCHEMA_INVALID")
    have = {g["game_id"]: g for g in doc["games"]}
    added = 0
    for r in rows:
        old = have.get(r["game_id"])
        if old is not None:
            if (old["away_points"], old["home_points"]) != (r["away_points"], r["home_points"]):
                raise ValueError("CFB_FINALS_CONFLICT:" + r["game_id"])
            continue
        doc["games"].append(dict(r, captured_at_utc=captured_at))
        have[r["game_id"]] = r
        added += 1
    doc["games"].sort(key=lambda g: g["game_id"])
    doc["last_captured_at_utc"] = captured_at
    return doc, added


def _ledger_module():
    path = Path(__file__).resolve().parent / "cfb_probation_ledger.py"
    spec = importlib.util.spec_from_file_location("cfb_probation_ledger", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_finals(path: Path) -> dict:
    """CFB_FINAL_SCORES_V1 -> {(game_id, away_norm, home_norm): (away_pts, home_pts)} for ledger.grade."""
    norm = _ledger_module()._norm
    doc = json.loads(Path(path).read_text())
    if doc.get("schema") != SCHEMA:
        raise ValueError("CFB_FINALS_SCHEMA_INVALID")
    out = {}
    for g in doc.get("games") or []:
        ap, hp = float(g["away_points"]), float(g["home_points"])
        if not all(math.isfinite(x) and x >= 0 and x.is_integer() for x in (ap, hp)):
            raise ValueError("CFB_FINALS_SCORE_INVALID:" + str(g.get("game_id")))
        key = (str(g["game_id"]), norm(g["away_team"]), norm(g["home_team"]))
        if key in out and out[key] != (ap, hp):
            raise ValueError("CFB_FINALS_CONFLICT:" + str(g.get("game_id")))
        out[key] = (ap, hp)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("capture")
    c.add_argument("--date", required=True, help="YYYY-MM-DD (ESPN scoreboard date)")
    c.add_argument("--scoreboard-json", type=Path, help="Use a saved scoreboard payload instead of fetching")
    c.add_argument("--output-dir", type=Path, required=True)
    g = sub.add_parser("grade")
    g.add_argument("--ledger", type=Path, required=True)
    g.add_argument("--finals", type=Path, required=True)
    g.add_argument("--closing", type=Path)
    g.add_argument("--output", type=Path, required=True)
    a = ap.parse_args(argv)
    if a.cmd == "grade":
        if a.output.resolve() == a.ledger.resolve() or a.output.exists():
            raise SystemExit("CFB_LEDGER_IMMUTABLE_OUTPUT_REQUIRED:" + str(a.output))
        led = json.loads(a.ledger.read_text())
        closing = json.loads(a.closing.read_text()) if a.closing else None
        _ledger_module().grade(led, load_finals(a.finals), closing)
        a.output.parent.mkdir(parents=True, exist_ok=True)
        a.output.write_text(json.dumps(led, indent=2) + "\n")
        done = sum(p["result"] is not None for p in led["plays"])
        print(f"CFB_LEDGER_GRADED {done}/{len(led['plays'])} -> {a.output}")
        return 0
    if a.scoreboard_json:
        payload = json.loads(a.scoreboard_json.read_text())
    else:
        req = Request(ESPN.format(d=a.date.replace("-", "")), headers={"User-Agent": "SportsEdge/1.0"})
        with urlopen(req, timeout=45) as r:
            payload = json.load(r)
    out = a.output_dir / f"{a.date}.json"
    existing = json.loads(out.read_text()) if out.exists() else None
    doc, added = merge(existing, parse_scoreboard(payload), date=a.date,
                       captured_at=datetime.now(timezone.utc).isoformat())
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=2) + "\n")
    print(f"CFB_FINALS_CAPTURED added={added} total={len(doc['games'])} -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
