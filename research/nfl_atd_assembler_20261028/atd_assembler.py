#!/usr/bin/env python3
"""NFL anytime-TD v1.1 capture -> records assembler (NON-COUNTED tooling).

The frozen ATD v1.1 engine (branch grok/t227-nfl-atd-engine-fixes-20261022,
freeze commit c2fd86dc) consumes two record bodies per game:

  * a BOARD record  nfl_atd_v1_1/boards/<season>-W<week>/<sha256>.json
    {season, week, game_id (book event id), game_teams, captured_at, kickoff,
     slate_id, rows: [{player_name, yes_price, player_id?}]}
  * a CLOSE record  nfl_atd_v1_1/closes/<season>-W<week>/<sha256>.json
    {game_id (nflverse), kickoff, captured_at,
     captures: [{player_id, yes_price, captured_at}]}

Nothing converted a lane capture into those records; Rocky's Oct 28, 2026
pre-flight (~/workspace/atd-preflight-20261028/FINDINGS.md, gap 1) found the
pipeline NOT-READY for that reason. This module is that missing path. It is
additive tooling only: it does not modify the frozen engine, the records
branch, or main's v1 ATD engine, and it never pushes anything itself — it
writes record bodies to a local records-layout directory for the operator
to push under the records branch's single-commit discipline.

Input sources (per the build spec):
  (a) a lane detailed capture file — the canonical capture JSON contract
      below, or the verbatim detailed-read TEXT a single-game rendered
      DraftKings capture returns (TD Scorers tab section);
  (b) the same capture JSON produced by a fresh single-game capture.
The GitHub issue-comment form is NOT a source: the shared intake strips
HTML comments by design (a comment-form anytime-TD table extracts 0 rows),
comment tables carry no nflverse ids, and one issue body can hold two
snapshots with no authoritative designation. This assembler never opens
an issue body.

Identity: player names resolve to nflverse player_ids through the same
pinned data path the frozen engine uses — the eight pinned player-data
files (sha256-verified against the freeze's SPEC_HASHES values) plus, when
supplied, the current-season stats file merged point-in-time (appearances
count only from games completed before the capture, mirroring
atd_refresh.load_current_season). Name normalization, ambiguity and
team-match rules mirror atd_engine.normalize_name / resolve_name exactly.
Unresolved players are NAMED REFUSALS in the assembly report — never
guessed, never silently dropped, and kept out of the emitted record (a
board row the engine cannot resolve would fail the whole slate closed;
the Oct 25 operating record treats unresolvable names as a declared,
systematic exclusion). D/ST rows and the "No Touchdown Scorer" row are
out of scope for this player-keyed engine and are excluded by name.

Snapshot rules (frozen terms, PREREG_NFL_ATD_ENGINE_V1_1 Rules 4-6 as
frozen — ATD section 6's own Oct 22 rulings; Part 2/2B's LINE_MOVED /
sign-test machinery does not exist in this family and is NOT imported):
  * board: built from the entry capture (lane T-1H mark). A capture inside
    the FINAL close window (<=20 min before kickoff) is refused as a board
    source; a capture outside the nominal T-1H band (45-75 min before
    kickoff) is accepted only with a stamped warning (owner-ordered entry
    captures outside the band are on the record, e.g. Oct 26, 2026).
  * close: built from the LATEST capture strictly before kickoff; refused
    when that capture is more than 60 minutes before kickoff (the frozen
    Rule 4 staleness rule: kickoff - t > 60 min is CLOSE_STALE).

Provenance: every emitted record carries an "assembler_provenance" block
(assembler name/version, source kind + name, source read timestamp,
nflverse game identity, window classification). The frozen loader ignores
unknown keys; the run record the pricer emits remains the counting record.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ASSEMBLER_NAME = "nfl_atd_assembler"
ASSEMBLER_VERSION = "NFL_ATD_ASSEMBLER_V1_20261028"

ET = ZoneInfo("America/New_York")
CT = ZoneInfo("America/Chicago")

# Frozen Rule 4: kickoff - captured_at > 60 minutes -> CLOSE_STALE.
STALE_CLOSE = timedelta(minutes=60)
# Lane cadence marks (operating procedure, not frozen terms): the T-1H
# window is kickoff-75m..kickoff-45m; the FINAL window opens at kickoff-20m.
T1H_BAND = (timedelta(minutes=45), timedelta(minutes=75))
FINAL_WINDOW = timedelta(minutes=20)

# The eight pinned player-data files and their sha256 pins, verbatim from
# research/nfl_props_part2_20261018/SPEC_HASHES.txt at freeze commit
# c2fd86dc. The frozen pricer re-verifies the same pins independently.
REQUIRED_FILES = (
    "ps_2018.csv.gz", "ps_2019.csv.gz", "ps_2020.csv.gz", "ps_2021.csv.gz",
    "ps_2022.csv.gz", "ps_2023.csv.gz", "ps_2024.csv.gz", "sp_2025.csv.gz",
)
PINNED_SHA256 = {
    "ps_2018.csv.gz": "15730d75271ec10affc412b50b22fc8e3d6ce8f442d377936f65bc0044ef15bf",
    "ps_2019.csv.gz": "d143b91c62380bed1587fe390e594d0e5555e8ebac81fcc7212ad7224115caf2",
    "ps_2020.csv.gz": "e23a81d6ed3c94bd2dd14a5ee3ed94584a69e67fdb985c1ba0de4ccbc5a2bdcc",
    "ps_2021.csv.gz": "a2fb266576a1bde5d7978005a5f6ccf83e3c023234da500d38cf6a14f40a01c8",
    "ps_2022.csv.gz": "2b7dca6814993b9fd6ad3d4fdc56131663311bbe83281126e1ac441620d824ba",
    "ps_2023.csv.gz": "b7590543f3c81dceb17d7577a1dce7b8ff1a9aacf0f562e3d7bbc7e60f37bc9b",
    "ps_2024.csv.gz": "629b77e0c88d361f8b5c4a850e7866013aa670b7a5a94b7f1d0c591adf18f971",
    "sp_2025.csv.gz": "c7401e321bdb369443f3280b9acd74ba6e16d82e710383bf1c01acabfebeac0b",
}

# DraftKings display name -> nflverse team abbreviation (schedule identity).
DK_TEAM_ABBR = {
    "Arizona Cardinals": "ARI", "Atlanta Falcons": "ATL",
    "Baltimore Ravens": "BAL", "Buffalo Bills": "BUF",
    "Carolina Panthers": "CAR", "Chicago Bears": "CHI",
    "Cincinnati Bengals": "CIN", "Cleveland Browns": "CLE",
    "Dallas Cowboys": "DAL", "Denver Broncos": "DEN",
    "Detroit Lions": "DET", "Green Bay Packers": "GB",
    "Houston Texans": "HOU", "Indianapolis Colts": "IND",
    "Jacksonville Jaguars": "JAX", "Kansas City Chiefs": "KC",
    "Las Vegas Raiders": "LV", "Los Angeles Chargers": "LAC",
    "Los Angeles Rams": "LA", "Miami Dolphins": "MIA",
    "Minnesota Vikings": "MIN", "New England Patriots": "NE",
    "New Orleans Saints": "NO", "New York Giants": "NYG",
    "New York Jets": "NYJ", "Philadelphia Eagles": "PHI",
    "Pittsburgh Steelers": "PIT", "San Francisco 49ers": "SF",
    "Seattle Seahawks": "SEA", "Tampa Bay Buccaneers": "TB",
    "Tennessee Titans": "TEN", "Washington Commanders": "WAS",
}


class AssemblyRefusal(Exception):
    """Fail-closed refusal of a whole assembly (code + detail)."""

    def __init__(self, code, detail=""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


# ---------------------------------------------------------------------------
# Scalar parsers — mirrored from the frozen atd_engine.py (same semantics).
# ---------------------------------------------------------------------------

def parse_american(value):
    """American odds -> int, or None when invalid (frozen rules: finite
    number or numeric string, 100 <= |price| <= 100000)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        num = float(value)
    elif isinstance(value, str):
        s = value.strip().replace("−", "-").replace("+", "")
        if not s:
            return None
        try:
            num = float(s)
        except ValueError:
            return None
    else:
        return None
    if num != num or num in (float("inf"), float("-inf")):
        return None
    if num != int(num):
        return None
    price = int(num)
    return price if 100 <= abs(price) <= 100000 else None


_HOUSE_ZONES = {
    "CT": CT, "CDT": CT, "CST": CT,
    "ET": ET, "EDT": ET, "EST": ET,
    "UTC": timezone.utc, "Z": timezone.utc,
}
_HOUSE_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})\s+(\d{1,2}):(\d{2})\s*([AaPp])[Mm]\s+([A-Za-z]{1,4})$")


def parse_timestamp(value):
    """ISO 8601 with offset/Z, or the house 'YYYY-MM-DD H:MM AM/PM CT'
    format. Naive timestamps are refused (frozen discipline)."""
    if isinstance(value, datetime):
        dt = value
    else:
        s = str(value).strip()
        dt = None
        try:
            cand = datetime.fromisoformat(s.replace("Z", "+00:00"))
            if cand.tzinfo is not None:
                dt = cand
        except ValueError:
            pass
        if dt is None:
            m = _HOUSE_RE.match(s)
            if not m:
                raise AssemblyRefusal("TIMESTAMP_INVALID", repr(value))
            year, mon, day, hh, mm, ap, zone = m.groups()
            if zone.upper() not in _HOUSE_ZONES:
                raise AssemblyRefusal("TIMESTAMP_INVALID", repr(value))
            hour = int(hh) % 12 + (12 if ap.upper() == "P" else 0)
            dt = datetime(int(year), int(mon), int(day), hour, int(mm),
                          tzinfo=_HOUSE_ZONES[zone.upper()])
    if dt.tzinfo is None:
        raise AssemblyRefusal("TIMESTAMP_INVALID", "naive timestamp refused")
    return dt


def zulu(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}


def normalize_name(name):
    """Mirror of atd_engine.normalize_name."""
    toks = re.sub(r"[^a-z0-9 ]", " ", str(name).lower()).split()
    while toks and toks[-1] in _SUFFIXES:
        toks.pop()
    return " ".join(toks)


def is_not_a_player_row(name):
    """Mirror of atd_engine.is_not_a_player_row."""
    low = str(name).strip().lower()
    return low == "no touchdown scorer" or "d/st" in low


# ---------------------------------------------------------------------------
# Identity — the pinned data path the frozen engine uses.
# ---------------------------------------------------------------------------

def _appearances(path):
    """Yield (player_id, display_name, season, week, team, game_id) for
    REG rows of one player-week stats file (mirrors
    atd_engine.load_data / atd_refresh.load_current_season row rules)."""
    with gzip.open(path, "rt", newline="") as fh:
        for row in csv.DictReader(fh):
            pid = (row.get("player_id") or "").strip()
            wk = row.get("week")
            if not pid or row.get("season_type") != "REG" or wk in (None, ""):
                continue
            try:
                week = int(float(wk))
                season = int(row["season"])
            except (TypeError, ValueError, KeyError):
                continue
            yield (pid, (row.get("player_display_name") or "").strip(),
                   season, week, (row.get("recent_team") or "").strip(),
                   (row.get("game_id") or "").strip())


class IdentityIndex:
    """Name -> player_id resolution with the frozen engine's discipline:
    a name resolves only when exactly one pinned-snapshot player with that
    normalized name has his most recent appearance for one of the game's
    teams. `meta[pid]` is the (season, week, team) of the latest
    appearance, exactly as atd_engine.build_name_index computes it."""

    def __init__(self):
        self.names = {}
        self.meta = {}
        self.by_norm = {}

    def _add(self, pid, name, season, week, team):
        if name and pid not in self.names:
            self.names[pid] = name
        cur = self.meta.get(pid)
        if cur is None or (season, week) >= (cur[0], cur[1]):
            self.meta[pid] = (season, week, team)

    def _rebuild_norm(self):
        self.by_norm = {}
        for pid, name in self.names.items():
            if name:
                self.by_norm.setdefault(normalize_name(name), set()).add(pid)

    def clone(self):
        other = IdentityIndex()
        other.names = dict(self.names)
        other.meta = dict(self.meta)
        other.by_norm = {k: set(v) for k, v in self.by_norm.items()}
        return other

    def resolve(self, name, game_teams):
        """-> (player_id, None) or (None, reason) with reason in
        {NO_MATCH, TEAM_MISMATCH, AMBIGUOUS} (mirrors resolve_name, with
        the refusal reason named instead of collapsed to None)."""
        pids = self.by_norm.get(normalize_name(name), set())
        cands = [p for p in pids
                 if self.meta.get(p, (0, 0, ""))[2] in game_teams]
        if len(cands) == 1:
            return cands[0], None
        if len(cands) > 1:
            return None, "AMBIGUOUS"
        if pids:
            return None, "TEAM_MISMATCH"
        return None, "NO_MATCH"


def load_pinned_index(data_dir, pins=None):
    """Verify the eight pinned files' sha256 and build the base index.
    Returns (IdentityIndex, {filename: sha256})."""
    pins = PINNED_SHA256 if pins is None else pins
    data_dir = Path(data_dir)
    index = IdentityIndex()
    shas = {}
    for fname in REQUIRED_FILES:
        path = data_dir / fname
        if not path.is_file():
            raise AssemblyRefusal("PLAYER_DATA_MISSING", str(path))
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if pins.get(fname) != digest:
            raise AssemblyRefusal(
                "PLAYER_DATA_PIN_MISMATCH",
                f"{fname}: expected {pins.get(fname)}, got {digest}")
        shas[fname] = digest
        for pid, name, season, week, team, _gid in _appearances(path):
            index._add(pid, name, season, week, team)
    index._rebuild_norm()
    return index, shas


def merge_current_season(index, stats_path, schedule_rows, captured_at):
    """Point-in-time merge of the current-season stats file, mirroring
    atd_refresh.load_current_season: every game_id in the stats file must
    exist on the schedule, and appearances count only from games
    completed before the capture (schedule result present AND
    kickoff + 4h <= captured_at). Mutates `index`; returns merge stats."""
    stats_path = Path(stats_path)
    rows = list(_appearances(stats_path))
    seasons = {r[2] for r in rows}
    if len(seasons) != 1:
        raise AssemblyRefusal("STATS_SEASON_AMBIGUOUS", str(sorted(seasons)))
    season = seasons.pop()
    sched = {r["game_id"]: r for r in schedule_rows if r["season"] == season}
    done = set()
    for gid, row in sched.items():
        if row["game_type"] != "REG" or not row.get("result"):
            continue
        if row["kickoff"] + timedelta(hours=4) <= captured_at:
            done.add(gid)
    seen = set()
    merged = 0
    for pid, name, rseason, week, team, gid in rows:
        if gid not in seen:
            seen.add(gid)
            if gid not in sched:
                raise AssemblyRefusal("STATS_GAME_NOT_IN_SCHEDULE", gid)
        if gid not in done:
            continue
        index._add(pid, name, rseason, week, team)
        merged += 1
    index._rebuild_norm()
    return {"stats_season": season, "completed_games": len(done),
            "appearances_merged": merged}


# ---------------------------------------------------------------------------
# Schedule — mirror of atd_refresh.load_schedule / schedule_kickoff.
# ---------------------------------------------------------------------------

def load_schedule_rows(text):
    """Parse nflverse games.csv text into row dicts (mirror of
    atd_refresh.parse_schedule_csv, restricted to the fields used)."""
    rows = []
    for row in csv.DictReader(text.splitlines()):
        try:
            gameday = datetime.strptime(row["gameday"], "%Y-%m-%d").date()
            hh, mm = (row["gametime"] or "13:00").split(":")[:2]
            kickoff = datetime(gameday.year, gameday.month, gameday.day,
                               int(hh), int(mm), tzinfo=ET)
            rows.append({
                "game_id": row["game_id"], "season": int(row["season"]),
                "game_type": row["game_type"], "week": int(row["week"]),
                "away_team": row["away_team"], "home_team": row["home_team"],
                "kickoff": kickoff, "result": (row.get("result") or ""),
            })
        except (KeyError, TypeError, ValueError):
            continue
    return rows


def resolve_game(schedule_rows, season, game_teams, kickoff):
    """Mirror of atd_refresh.schedule_kickoff: exactly one REG game of the
    season with these teams within a day of the claimed kickoff, and its
    schedule instant must equal the claimed kickoff instant."""
    cands = []
    for row in schedule_rows:
        if row["season"] != season or row["game_type"] != "REG":
            continue
        if {row["away_team"], row["home_team"]} != set(game_teams):
            continue
        if abs((row["kickoff"] - kickoff).total_seconds()) > 86400:
            continue
        cands.append(row)
    if len(cands) != 1 or cands[0]["kickoff"] != kickoff:
        raise AssemblyRefusal(
            "KICKOFF_SCHEDULE_MISMATCH",
            f"teams={sorted(game_teams)} kickoff={zulu(kickoff)} "
            f"candidates={len(cands)}")
    row = cands[0]
    return {"game_id": row["game_id"], "week": row["week"],
            "season": row["season"], "kickoff": row["kickoff"]}


# ---------------------------------------------------------------------------
# Captures.
#
# Canonical capture JSON contract (what a lane detailed capture or a fresh
# single-game capture writes for this assembler):
#   {game: "Away @ Home"  (or away_team / home_team),
#    dk_event_id: int, kickoff: <timestamp>, captured_at: <timestamp>,
#    td_scorers: [{player_name: str, yes_price: number}, ...],
#    source: {...} (optional, carried into provenance)}
# ---------------------------------------------------------------------------

class Capture:
    def __init__(self, away_name, home_name, dk_event_id, kickoff,
                 captured_at, td_rows, source_kind, source_name,
                 section_note=None):
        self.away_name = away_name
        self.home_name = home_name
        self.dk_event_id = dk_event_id
        self.kickoff = kickoff
        self.captured_at = captured_at
        self.td_rows = td_rows  # [{player_name, yes_price|None}]
        self.source_kind = source_kind
        self.source_name = source_name
        self.section_note = section_note


def load_capture_json(path):
    path = Path(path)
    try:
        raw = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise AssemblyRefusal("CAPTURE_UNREADABLE", f"{path}: {exc}")
    if not isinstance(raw, dict):
        raise AssemblyRefusal("CAPTURE_MALFORMED", f"{path}: not an object")
    away = raw.get("away_team")
    home = raw.get("home_team")
    if not (away and home) and raw.get("game"):
        parts = str(raw["game"]).split(" @ ")
        if len(parts) == 2:
            away, home = parts[0].strip(), parts[1].strip()
    if not (away and home):
        raise AssemblyRefusal("CAPTURE_MALFORMED", f"{path}: teams missing")
    for field in ("dk_event_id", "kickoff", "captured_at", "td_scorers"):
        if field not in raw:
            raise AssemblyRefusal("CAPTURE_MALFORMED", f"{path}: {field} missing")
    rows = []
    for entry in raw["td_scorers"]:
        if not isinstance(entry, dict) or "player_name" not in entry:
            raise AssemblyRefusal("CAPTURE_MALFORMED",
                                  f"{path}: td_scorers entry lacks player_name")
        price = entry.get("yes_price", entry.get("anytime_yes"))
        rows.append({"player_name": str(entry["player_name"]),
                     "yes_price": price})
    return Capture(str(away), str(home), raw["dk_event_id"],
                   parse_timestamp(raw["kickoff"]),
                   parse_timestamp(raw["captured_at"]), rows,
                   "capture_json", str(path),
                   section_note=(raw.get("source") or {}).get("note")
                   if isinstance(raw.get("source"), dict) else None)


_PRICE = r"([+−\-]\d{2,6})"
# Entry form: "Name P1 / P2 / P3" — the name may itself contain "/"
# (e.g. "DAL Cowboys D/ST"), so the name group excludes only the ";"
# entry separator and the price columns are anchored by " / ".
_TRIPLE_RE = re.compile(
    r"([^;]+?)\s+" + _PRICE + r"\s*/\s*" + _PRICE + r"\s*/\s*" + _PRICE)
_EVENT_RE = re.compile(r"^Event:\s*(.+?)\s*@\s*(.+?),\s*DK event\s+(\d+)\s*$", re.M)
_WINDOW_RE = re.compile(
    r"Capture window:\s*\w+,\s*(\w+ \d{1,2}, \d{4}),\s*"
    r"(\d{1,2}:\d{2}\s*[AP]M)\s*[–\-]\s*(\d{1,2}:\d{2}\s*[AP]M)\s*CT")
_KICKOFF_RE = re.compile(r"Kickoff:\s*Today\s+(\d{1,2}:\d{2}\s*[AP]M)\s*CT")
_DESIGNATED_RE = re.compile(r"The table above is the .*?TD Scorers tab snapshot")


def _ct_on(date_text, time_text):
    day = datetime.strptime(date_text, "%B %d, %Y").date()
    tod = datetime.strptime(re.sub(r"\s+", " ", time_text.strip()),
                            "%I:%M %p").time()
    return datetime(day.year, day.month, day.day, tod.hour, tod.minute,
                    tzinfo=CT)


def parse_detailed_read_text(text, source_name):
    """Parse the verbatim detailed-read text a single-game rendered DK
    capture returns. Only the TD Scorers TAB snapshot is taken (the
    section the read itself designates as the table); the Popular-tab
    drift snapshots are never blended in. Refuses when the read does not
    designate its TD table snapshot."""
    ev = _EVENT_RE.search(text)
    win = _WINDOW_RE.search(text)
    ko = _KICKOFF_RE.search(text)
    if not (ev and win and ko):
        raise AssemblyRefusal(
            "CAPTURE_MALFORMED",
            f"{source_name}: detailed read lacks event/window/kickoff header")
    away, home, event_id = ev.group(1), ev.group(2), int(ev.group(3))
    date_text = win.group(1)
    captured_at = _ct_on(date_text, win.group(3))
    kickoff = _ct_on(date_text, ko.group(1))
    lines = text.splitlines()
    head_idx = next((i for i, ln in enumerate(lines)
                     if "TOUCHDOWN SCORERS" in ln and "TD Scorers tab" in ln),
                    None)
    if head_idx is None:
        raise AssemblyRefusal("CAPTURE_TD_TABLE_MISSING", source_name)
    section_lines = []
    for ln in lines[head_idx + 1:]:
        if ln.startswith("Drift note:") or re.match(r"^\d+\)\s", ln):
            break
        section_lines.append(ln)
    if not _DESIGNATED_RE.search(text):
        raise AssemblyRefusal(
            "TEXT_SNAPSHOT_NOT_DESIGNATED",
            f"{source_name}: read does not designate the TD Scorers tab "
            "snapshot as its table; refusing to guess between snapshots")
    section = "\n".join(section_lines)
    rows = []
    for m in _TRIPLE_RE.finditer(section):
        rows.append({"player_name": m.group(1).strip(),
                     "yes_price": m.group(2).replace("−", "-")})
    if not rows:
        raise AssemblyRefusal("CAPTURE_TD_TABLE_MISSING",
                              f"{source_name}: TD section held no priced rows")
    if re.search(r"No Touchdown Scorer", section):
        rows.append({"player_name": "No Touchdown Scorer", "yes_price": None})
    note = None
    m = re.search(r"TD Scorers tab at (\d{1,2}:\d{2}\s*[AP]M)", lines[head_idx])
    if m:
        note = f"TD Scorers tab snapshot at {m.group(1)} CT (designated)"
    return Capture(away, home, event_id, kickoff, captured_at, rows,
                   "detailed_read_text", source_name, section_note=note)


def load_capture(path):
    """Load a capture from a .json (canonical contract) or .txt/.md
    (verbatim detailed-read text) file."""
    path = Path(path)
    if not path.is_file():
        raise AssemblyRefusal("CAPTURE_MISSING", str(path))
    if path.suffix.lower() == ".json":
        return load_capture_json(path)
    return parse_detailed_read_text(path.read_text(), str(path))


# ---------------------------------------------------------------------------
# Assembly.
# ---------------------------------------------------------------------------

def _team_abbrs(capture):
    try:
        return [DK_TEAM_ABBR[capture.away_name], DK_TEAM_ABBR[capture.home_name]]
    except KeyError as exc:
        raise AssemblyRefusal("TEAM_NAME_UNKNOWN", str(exc))


def _provenance(capture, game, extra=None):
    prov = {
        "assembler": ASSEMBLER_NAME,
        "assembler_version": ASSEMBLER_VERSION,
        "source_kind": capture.source_kind,
        "source_name": capture.source_name,
        "source_captured_at": zulu(capture.captured_at),
        "source_kickoff": zulu(capture.kickoff),
        "dk_event_id": capture.dk_event_id,
        "nflverse_game_id": game["game_id"],
    }
    if capture.section_note:
        prov["source_section"] = capture.section_note
    if extra:
        prov.update(extra)
    return prov


def _resolve_rows(capture, index, game_teams):
    """Resolve a capture's TD rows. Returns (resolved, refusals,
    exclusions): resolved = [{player_name, player_id, yes_price}];
    refusals/exclusions are named per-row dispositions."""
    resolved, refusals, exclusions = [], [], []
    seen_names, seen_pids = set(), set()
    for row in capture.td_rows:
        name = str(row["player_name"]).strip()
        if is_not_a_player_row(name):
            exclusions.append({"player_name": name,
                               "code": "NOT_A_PLAYER_ROW"})
            continue
        if row.get("yes_price") is None:
            exclusions.append({"player_name": name, "code": "NO_ANYTIME_PRICE"})
            continue
        price = parse_american(row["yes_price"])
        if price is None:
            refusals.append({"player_name": name, "code": "PRICE_INVALID",
                             "yes_price": row["yes_price"]})
            continue
        norm = normalize_name(name)
        if norm in seen_names:
            raise AssemblyRefusal("DUPLICATE_CAPTURE_ROW", name)
        seen_names.add(norm)
        pid, reason = index.resolve(name, game_teams)
        if pid is None:
            refusals.append({"player_name": name,
                             "code": "NAME_UNRESOLVED", "reason": reason})
            continue
        if pid in seen_pids:
            raise AssemblyRefusal("DUPLICATE_CAPTURE_ROW", name)
        seen_pids.add(pid)
        resolved.append({"player_name": name, "player_id": pid,
                         "yes_price": price})
    return resolved, refusals, exclusions


def _index_at(base_index, stats_path, schedule_rows, captured_at):
    """The identity index as of a capture: pinned snapshot plus the
    point-in-time current-season merge when a stats file is supplied."""
    if stats_path is None:
        return base_index, None
    if schedule_rows is None:
        raise AssemblyRefusal("SCHEDULE_REQUIRED_FOR_STATS_MERGE")
    merged = base_index.clone()
    info = merge_current_season(merged, stats_path, schedule_rows, captured_at)
    return merged, info


def _record_bytes(body):
    return json.dumps(body, sort_keys=True).encode()


def board_record_path(body_sha, season, week):
    """Records-branch layout (mirrors atd_provenance.board_record_path)."""
    return f"nfl_atd_v1_1/boards/{season}-W{week}/{body_sha}.json"


def close_record_path(body_sha, season, week):
    """Records-branch layout (mirrors atd_provenance.close_record_path)."""
    return f"nfl_atd_v1_1/closes/{season}-W{week}/{body_sha}.json"


def default_slate_id(season, week, away_abbr, home_abbr):
    return f"ASM-{season}W{week:02d}-{away_abbr}-{home_abbr}"


def assemble_board(capture, base_index, schedule_rows, stats_path=None,
                   slate_id=None, season=None):
    """Build the ATD board record from an entry capture. Returns
    {body, bytes, sha256, path, report}. Whole-assembly problems raise
    AssemblyRefusal; per-player problems are named in the report."""
    teams = _team_abbrs(capture)
    season = capture.kickoff.year if season is None else season
    game = resolve_game(schedule_rows, season, teams, capture.kickoff)
    kickoff = game["kickoff"]
    if capture.captured_at >= kickoff:
        raise AssemblyRefusal(
            "CAPTURED_AFTER_KICKOFF",
            f"captured_at={zulu(capture.captured_at)} kickoff={zulu(kickoff)}")
    before = kickoff - capture.captured_at
    warnings = []
    if before <= FINAL_WINDOW:
        raise AssemblyRefusal(
            "CAPTURE_IN_CLOSE_WINDOW",
            f"capture is {before} before kickoff — that is a close "
            "capture, not an entry/board capture")
    if not (T1H_BAND[0] <= before <= T1H_BAND[1]):
        warnings.append({
            "code": "CAPTURE_OUTSIDE_T1H_BAND",
            "minutes_before_kickoff": round(before.total_seconds() / 60, 1),
            "detail": "entry capture outside the nominal T-1H band "
                      "(45-75 min); accepted as an owner-ordered entry "
                      "and stamped, per the Oct 26, 2026 precedent"})
    index, merge_info = _index_at(base_index, stats_path, schedule_rows,
                                  capture.captured_at)
    resolved, refusals, exclusions = _resolve_rows(capture, index, teams)
    if not resolved:
        raise AssemblyRefusal(
            "NO_RESOLVED_ROWS",
            "every TD row was refused or excluded; no board emitted")
    slate_id = slate_id or default_slate_id(game["season"], game["week"],
                                            teams[0], teams[1])
    prov = _provenance(capture, game, {
        "role": "board",
        "minutes_before_kickoff": round(before.total_seconds() / 60, 1),
        "warnings": warnings,
        "stats_merge": merge_info,
        "rows_extracted": len(capture.td_rows),
        "rows_resolved": len(resolved),
        "rows_refused": len(refusals),
        "rows_excluded": len(exclusions),
    })
    body = {
        "season": game["season"],
        "week": game["week"],
        "game_id": str(capture.dk_event_id),
        "game_teams": teams,
        "captured_at": zulu(capture.captured_at),
        "kickoff": zulu(kickoff),
        "slate_id": slate_id,
        "rows": resolved,
        "assembler_provenance": prov,
    }
    raw = _record_bytes(body)
    sha = hashlib.sha256(raw).hexdigest()
    report = {
        "record": "board", "slate_id": slate_id,
        "nflverse_game_id": game["game_id"],
        "rows_extracted": len(capture.td_rows),
        "resolved": resolved, "refusals": refusals,
        "exclusions": exclusions, "warnings": warnings,
        "sha256": sha, "path": board_record_path(sha, game["season"],
                                                 game["week"]),
    }
    return {"body": body, "bytes": raw, "sha256": sha,
            "path": report["path"], "report": report}


def assemble_close(captures, base_index, schedule_rows, stats_path=None,
                   season=None):
    """Build the ATD close record from the latest capture strictly before
    kickoff, under the frozen Rule 4 staleness rule (refused when the
    latest pre-kickoff capture is more than 60 minutes before kickoff).
    Returns {body, bytes, sha256, path, report}."""
    if not captures:
        raise AssemblyRefusal("CLOSE_NO_CAPTURE", "no captures supplied")
    first = captures[0]
    teams = _team_abbrs(first)
    for other in captures[1:]:
        if (other.away_name, other.home_name, other.dk_event_id) != \
                (first.away_name, first.home_name, first.dk_event_id):
            raise AssemblyRefusal("CLOSE_CAPTURE_GAME_MISMATCH",
                                  other.source_name)
    season = first.kickoff.year if season is None else season
    game = resolve_game(schedule_rows, season, teams, first.kickoff)
    kickoff = game["kickoff"]
    pre = [c for c in captures if c.captured_at < kickoff]
    if not pre:
        raise AssemblyRefusal(
            "CLOSE_NO_CAPTURE_BEFORE_KICKOFF",
            f"{len(captures)} capture(s), none strictly before kickoff")
    latest = max(pre, key=lambda c: c.captured_at)
    gap = kickoff - latest.captured_at
    if gap > STALE_CLOSE:
        raise AssemblyRefusal(
            "CLOSE_STALE",
            f"latest pre-kickoff capture is {gap} before kickoff "
            f"({latest.source_name}); frozen Rule 4 refuses closes "
            "more than 60 minutes old")
    index, merge_info = _index_at(base_index, stats_path, schedule_rows,
                                  latest.captured_at)
    resolved, refusals, exclusions = _resolve_rows(latest, index, teams)
    entries = [{"player_id": r["player_id"], "yes_price": r["yes_price"],
                "captured_at": zulu(latest.captured_at)} for r in resolved]
    prov = _provenance(latest, game, {
        "role": "close",
        "minutes_before_kickoff": round(gap.total_seconds() / 60, 1),
        "captures_considered": len(captures),
        "captures_before_kickoff": len(pre),
        "stats_merge": merge_info,
        "rows_extracted": len(latest.td_rows),
        "rows_resolved": len(resolved),
        "rows_refused": len(refusals),
        "rows_excluded": len(exclusions),
    })
    body = {
        "game_id": game["game_id"],
        "kickoff": zulu(kickoff),
        "captured_at": zulu(latest.captured_at),
        "captures": entries,
        "assembler_provenance": prov,
    }
    raw = _record_bytes(body)
    sha = hashlib.sha256(raw).hexdigest()
    report = {
        "record": "close", "nflverse_game_id": game["game_id"],
        "source_capture": latest.source_name,
        "minutes_before_kickoff": round(gap.total_seconds() / 60, 1),
        "rows_extracted": len(latest.td_rows),
        "resolved": resolved, "refusals": refusals,
        "exclusions": exclusions,
        "sha256": sha, "path": close_record_path(sha, game["season"],
                                                 game["week"]),
    }
    return {"body": body, "bytes": raw, "sha256": sha,
            "path": report["path"], "report": report}


def write_record(result, out_dir):
    """Write an assembled record into a local records-layout directory.
    The assembler never pushes; the operator pushes the file to the
    records branch under its single-commit discipline."""
    dest = Path(out_dir) / result["path"]
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(result["bytes"])
    return dest


# ---------------------------------------------------------------------------
# CLI.
# ---------------------------------------------------------------------------

def _load_schedule_arg(path):
    if path is None:
        raise AssemblyRefusal("SCHEDULE_REQUIRED",
                              "a nflverse games.csv schedule is required")
    return load_schedule_rows(Path(path).read_text())


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="NFL anytime-TD v1.1 capture -> records assembler "
                    "(non-counted tooling; writes record bodies locally)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("board", "close"):
        sp = sub.add_parser(name)
        sp.add_argument("--capture", action="append", required=True,
                        help="capture file (.json canonical contract or "
                             ".txt detailed-read text); repeat for close")
        sp.add_argument("--player-data-dir", required=True,
                        help="dir holding the eight pinned player-data files")
        sp.add_argument("--schedule", required=True,
                        help="nflverse games.csv")
        sp.add_argument("--stats", default=None,
                        help="current-season stats_player_week_<season>.csv.gz "
                             "for the point-in-time identity merge")
        sp.add_argument("--slate-id", default=None)
        sp.add_argument("--season", type=int, default=None)
        sp.add_argument("--out-dir", default=None,
                        help="write the record into this records-layout dir")
        sp.add_argument("--report", default=None,
                        help="write the assembly report JSON here")
    args = ap.parse_args(argv)
    try:
        schedule_rows = _load_schedule_arg(args.schedule)
        base_index, _shas = load_pinned_index(args.player_data_dir)
        captures = [load_capture(p) for p in args.capture]
        if args.cmd == "board":
            if len(captures) != 1:
                raise AssemblyRefusal("BOARD_SINGLE_CAPTURE",
                                      "board assembly takes exactly one capture")
            result = assemble_board(captures[0], base_index, schedule_rows,
                                    stats_path=args.stats,
                                    slate_id=args.slate_id,
                                    season=args.season)
        else:
            result = assemble_close(captures, base_index, schedule_rows,
                                    stats_path=args.stats, season=args.season)
    except AssemblyRefusal as exc:
        report = {"status": "REFUSED", "code": exc.code, "detail": exc.detail,
                  "assembler_version": ASSEMBLER_VERSION}
        print(json.dumps(report, indent=1), file=sys.stderr)
        if args.report:
            Path(args.report).write_text(json.dumps(report, indent=1))
        return 2
    if args.out_dir:
        dest = write_record(result, args.out_dir)
        result["report"]["written_to"] = str(dest)
    print(json.dumps(result["report"], indent=1))
    if args.report:
        Path(args.report).write_text(json.dumps(result["report"], indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
