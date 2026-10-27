#!/usr/bin/env python3
"""Persist NFL final scores into the repo so NFL ledgers can grade.

  capture --date 2026-10-25 [--scoreboard-json saved.json] --output-dir ledger/nfl_finals

Writes ledger/nfl_finals/<date>.json (schema NFL_FINAL_SCORES_V1): one row per
ESPN event whose status is completed (STATUS_FINAL*). Non-final games are
omitted, never guessed. Existing files are merged append-only: a game already
stored is never changed, and a conflicting score aborts the run.

This mirrors scripts/capture_cfb_final_scores.py (the CFB pattern from PR
#2588) so every sport's finals land in the same shape and any ledger can
consume them uniformly via load_finals: {(game_id, away_norm, home_norm):
(away_pts, home_pts)} with ESPN event ids as game_id.
Research-only plumbing; nothing here is OFFICIAL, validated, or promoted.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

SCHEMA = "NFL_FINAL_SCORES_V1"
ESPN = ("https://site.api.espn.com/apis/site/v2/sports/football/nfl/"
        "scoreboard?dates={d}&limit=100")


def _norm(name: str) -> str:
    """Same normalization contract as cfb_probation_ledger._norm, minus the
    CFB-specific alias table (no NFL alias table is admitted yet)."""
    t = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode("ascii")
    t = " ".join(re.sub(r"[^a-z0-9() ]", " ", t.lower()).split())
    return t.replace("(", "").replace(")", "")


def parse_scoreboard(payload: dict) -> list[dict]:
    out = []
    for ev in payload.get("events") or []:
        comp = (ev.get("competitions") or [{}])[0]
        st = ((comp.get("status") or ev.get("status") or {}).get("type") or {})
        if not st.get("completed") or not str(st.get("name", "")).startswith("STATUS_FINAL"):
            continue
        teams = {c.get("homeAway"): c for c in comp.get("competitors") or []}
        if set(teams) != {"home", "away"}:
            raise ValueError("NFL_FINALS_COMPETITORS_INVALID:" + str(ev.get("id")))
        pts = {}
        for side, c in teams.items():
            v = float(c.get("score"))
            if not (math.isfinite(v) and v >= 0 and v.is_integer()):
                raise ValueError("NFL_FINALS_SCORE_INVALID:" + str(ev.get("id")))
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
        raise ValueError("NFL_FINALS_SCHEMA_INVALID")
    have = {g["game_id"]: g for g in doc["games"]}
    added = 0
    for r in rows:
        old = have.get(r["game_id"])
        if old is not None:
            if (old["away_points"], old["home_points"]) != (r["away_points"], r["home_points"]):
                raise ValueError("NFL_FINALS_CONFLICT:" + r["game_id"])
            continue
        doc["games"].append(dict(r, captured_at_utc=captured_at))
        have[r["game_id"]] = r
        added += 1
    doc["games"].sort(key=lambda g: g["game_id"])
    doc["last_captured_at_utc"] = captured_at
    return doc, added


def load_finals(path: Path) -> dict:
    """NFL_FINAL_SCORES_V1 -> {(game_id, away_norm, home_norm): (away_pts, home_pts)}."""
    doc = json.loads(Path(path).read_text())
    if doc.get("schema") != SCHEMA:
        raise ValueError("NFL_FINALS_SCHEMA_INVALID")
    out = {}
    for g in doc.get("games") or []:
        ap, hp = float(g["away_points"]), float(g["home_points"])
        if not all(math.isfinite(x) and x >= 0 and x.is_integer() for x in (ap, hp)):
            raise ValueError("NFL_FINALS_SCORE_INVALID:" + str(g.get("game_id")))
        key = (str(g["game_id"]), _norm(g["away_team"]), _norm(g["home_team"]))
        if key in out and out[key] != (ap, hp):
            raise ValueError("NFL_FINALS_CONFLICT:" + str(g.get("game_id")))
        out[key] = (ap, hp)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("capture")
    c.add_argument("--date", required=True, help="YYYY-MM-DD (ESPN scoreboard date)")
    c.add_argument("--scoreboard-json", type=Path, help="Use a saved scoreboard payload instead of fetching")
    c.add_argument("--output-dir", type=Path, required=True)
    a = ap.parse_args(argv)
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
    print(f"NFL_FINALS_CAPTURED added={added} total={len(doc['games'])} -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
