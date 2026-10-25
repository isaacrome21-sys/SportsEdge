#!/usr/bin/env python3
"""Persist NHL final scores into the repo so NHL ledgers can grade.

  capture --date 2026-10-24 [--score-json saved.json] --output-dir ledger/nhl_finals

Writes ledger/nhl_finals/<date>.json (schema NHL_FINAL_SCORES_V1): one row per
official NHL game whose gameState is completed (OFF / FINAL — the same
completed set scripts/collect_nhl_official_boxscores.py admits). Non-final
games are omitted, never guessed. Existing files are merged append-only: a
game already stored is never changed, and a conflicting score aborts the run.

NHL pick-ledger rows (scripts/render_nhl_myspari_card.py ledger_rows) start
with result=None because grading is a separate step; this file is the
persisted finals source that step consumes. Mirrors the CFB pattern from PR
#2588 (scripts/capture_cfb_final_scores.py): any ledger can consume the
finals uniformly via load_finals: {(game_id, away_norm, home_norm):
(away_goals, home_goals)} with official NHL game ids as game_id. Rows also
carry team abbreviations for joins against name-shortened ledger rows.

Source: the official NHL API score endpoint (api-web.nhle.com), the same
public source the program's NHL boxscore collector uses. No DK API, no paid
source. Research-only plumbing; nothing here is OFFICIAL, validated, or
promoted.
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

SCHEMA = "NHL_FINAL_SCORES_V1"
NHL_SCORE = "https://api-web.nhle.com/v1/score/{d}"
COMPLETED_STATES = {"OFF", "FINAL"}


def _norm(name: str) -> str:
    """Same normalization contract as cfb_probation_ledger._norm, minus the
    CFB-specific alias table (no NHL alias table is admitted yet)."""
    t = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode("ascii")
    t = " ".join(re.sub(r"[^a-z0-9() ]", " ", t.lower()).split())
    return t.replace("(", "").replace(")", "")


def _team_label(team: dict, game_id: str) -> str:
    name = team.get("name")
    if isinstance(name, dict) and name.get("default"):
        return str(name["default"])
    place = team.get("placeName")
    common = team.get("commonName")
    if isinstance(place, dict) and place.get("default") and isinstance(common, dict) and common.get("default"):
        return f"{place['default']} {common['default']}"
    if isinstance(common, dict) and common.get("default"):
        return str(common["default"])
    if team.get("abbrev"):
        return str(team["abbrev"])
    raise ValueError("NHL_FINALS_TEAM_INVALID:" + game_id)


def parse_scoreboard(payload: dict, *, date: str) -> list[dict]:
    out = []
    for g in payload.get("games") or []:
        state = str(g.get("gameState") or "").upper()
        if state not in COMPLETED_STATES:
            continue
        if g.get("gameDate") and str(g["gameDate"]) != date:
            continue
        game_id = str(g.get("id") or "")
        if not game_id:
            raise ValueError("NHL_FINALS_GAME_ID_MISSING")
        pts = {}
        labels = {}
        abbrevs = {}
        for side, key in (("away", "awayTeam"), ("home", "homeTeam")):
            team = g.get(key)
            if not isinstance(team, dict) or team.get("score") is None:
                raise ValueError("NHL_FINALS_TEAM_INVALID:" + game_id)
            v = float(team["score"])
            if not (math.isfinite(v) and v >= 0 and v.is_integer()):
                raise ValueError("NHL_FINALS_SCORE_INVALID:" + game_id)
            pts[side] = int(v)
            labels[side] = _team_label(team, game_id)
            abbrevs[side] = str(team.get("abbrev") or "")
        out.append({
            "game_id": game_id,
            "away_team": labels["away"], "home_team": labels["home"],
            "away_abbrev": abbrevs["away"], "home_abbrev": abbrevs["home"],
            "away_points": pts["away"], "home_points": pts["home"],
            "status": state, "start_ts": g.get("startTimeUTC"),
        })
    return out


def merge(existing: dict | None, rows: list[dict], *, date: str, captured_at: str) -> dict:
    doc = existing or {"schema": SCHEMA, "date": date, "source": "NHL_OFFICIAL_API",
                       "official": False, "games": []}
    if doc.get("schema") != SCHEMA:
        raise ValueError("NHL_FINALS_SCHEMA_INVALID")
    have = {g["game_id"]: g for g in doc["games"]}
    added = 0
    for r in rows:
        old = have.get(r["game_id"])
        if old is not None:
            if (old["away_points"], old["home_points"]) != (r["away_points"], r["home_points"]):
                raise ValueError("NHL_FINALS_CONFLICT:" + r["game_id"])
            continue
        doc["games"].append(dict(r, captured_at_utc=captured_at))
        have[r["game_id"]] = r
        added += 1
    doc["games"].sort(key=lambda g: g["game_id"])
    doc["last_captured_at_utc"] = captured_at
    return doc, added


def load_finals(path: Path) -> dict:
    """NHL_FINAL_SCORES_V1 -> {(game_id, away_norm, home_norm): (away_goals, home_goals)}."""
    doc = json.loads(Path(path).read_text())
    if doc.get("schema") != SCHEMA:
        raise ValueError("NHL_FINALS_SCHEMA_INVALID")
    out = {}
    for g in doc.get("games") or []:
        ap, hp = float(g["away_points"]), float(g["home_points"])
        if not all(math.isfinite(x) and x >= 0 and x.is_integer() for x in (ap, hp)):
            raise ValueError("NHL_FINALS_SCORE_INVALID:" + str(g.get("game_id")))
        key = (str(g["game_id"]), _norm(g["away_team"]), _norm(g["home_team"]))
        if key in out and out[key] != (ap, hp):
            raise ValueError("NHL_FINALS_CONFLICT:" + str(g.get("game_id")))
        out[key] = (ap, hp)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("capture")
    c.add_argument("--date", required=True, help="YYYY-MM-DD (NHL score date)")
    c.add_argument("--score-json", type=Path, help="Use a saved score payload instead of fetching")
    c.add_argument("--output-dir", type=Path, required=True)
    a = ap.parse_args(argv)
    if a.score_json:
        payload = json.loads(a.score_json.read_text())
    else:
        req = Request(NHL_SCORE.format(d=a.date), headers={"User-Agent": "SportsEdge/1.0"})
        with urlopen(req, timeout=45) as r:
            payload = json.load(r)
    out = a.output_dir / f"{a.date}.json"
    existing = json.loads(out.read_text()) if out.exists() else None
    doc, added = merge(existing, parse_scoreboard(payload, date=a.date), date=a.date,
                       captured_at=datetime.now(timezone.utc).isoformat())
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=2) + "\n")
    print(f"NHL_FINALS_CAPTURED added={added} total={len(doc['games'])} -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
