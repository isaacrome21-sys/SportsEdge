"""NFL anytime-TD engine v1 (PREREG_NFL_ATD_ENGINE_V1.md). RESEARCH_ONLY.

Prices P(player scores >= 1 rushing or receiving TD in a game) from the
hash-pinned nflverse weekly player-stats snapshot (the Part 1/Part 2 pins in
research/nfl_props_part2_20261018/SPEC_HASHES.txt). Construction is frozen in
the preregistration: recency-weighted player TD rate (8-game half-life, last
16 games, current + previous season), shrunk toward a point-in-time
position-group pool with K_A = 10, gated at MIN_GAMES = 4 prior appearances.
Fail closed: every row is priced or UNPRICED with exactly one named reason.

Board selections follow the LOCKED forward test
(docs/football/NFL_ANYTIME_TD_FORWARD_TEST_V1.md): YES iff model_p > raw
implied probability of the Yes price at entry (Rule 1); UNPRICED rows join
neither group (Rule 2); edge = model_p / raw implied - 1 is descriptive
only (Rule 9). Passing TDs never count for the thrower.
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import math
import re
from collections import defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path

HERE = Path(__file__).resolve().parent
PART2_HASHES = HERE.parent / "nfl_props_part2_20261018" / "SPEC_HASHES.txt"

K_A = 10.0                # shrinkage prior weight, in weighted games (frozen)
HALF_LIFE_GAMES = 8.0     # recency half-life, in player appearances (frozen)
MAX_EVIDENCE_GAMES = 16   # most recent prior appearances used (frozen)
MIN_GAMES = 4             # gate: minimum raw prior appearances (frozen)
POOL_MIN_GAMES = 200      # pool: minimum current-season prior-week appearances
POOL_GROUPS = ("QB", "RB", "WR", "TE")
REQUIRED_FILES = (
    "ps_2018.csv.gz", "ps_2019.csv.gz", "ps_2020.csv.gz", "ps_2021.csv.gz",
    "ps_2022.csv.gz", "ps_2023.csv.gz", "ps_2024.csv.gz", "sp_2025.csv.gz",
)

# Every UNPRICED reason the engine can emit (fail-closed contract). The
# prereg (PREREG_NFL_ATD_ENGINE_V1.md §2) names only INSUFFICIENT_GAMES,
# POSITION_GROUP_NOT_POOLED, NAME_UNRESOLVED and NOT_A_PLAYER_ROW; declaring
# the rest in the prereg is an OWNER ITEM (the prereg is hash-pinned and is
# not edited here).
DECLARED_UNPRICED_REASONS = (
    "UNPRICED_INSUFFICIENT_GAMES",
    "UNPRICED_POSITION_GROUP_NOT_POOLED",
    "UNPRICED_POOL_UNAVAILABLE",
    "UNPRICED_NAME_UNRESOLVED",
    "UNPRICED_NOT_A_PLAYER_ROW",
    "UNPRICED_PLAYER_ID_UNKNOWN",
    "UNPRICED_PLAYER_TEAM_MISMATCH",
    "UNPRICED_INVALID_PRICE",
    "UNPRICED_CAPTURED_AFTER_KICKOFF",
    "UNPRICED_TIMESTAMP_MISSING",
    "UNPRICED_TIMESTAMP_UNPARSEABLE",
)
MAX_ABS_AMERICAN = 100000  # sanity bound on a quoted American price

FAMILY = "anytime_td"
LABELS = {"status_label": "RESEARCH_ONLY", "validation_status": "NOT_VALIDATED",
          "estimate_label": "UNVALIDATED_ESTIMATE", "eligible": False,
          "promotable": False}


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def check_data_pins(data: Path) -> dict:
    """Verify the snapshot files against the Part 1/Part 2 SPEC_HASHES pins
    (fail closed on any missing or mismatched file)."""
    want = {}
    for line in PART2_HASHES.read_text().splitlines():
        h, name = line.split()
        want[name] = h
    pins = {}
    for name in REQUIRED_FILES:
        f = data / name
        if not f.exists():
            raise SystemExit(f"DATA_INPUT_MISSING: {name}")
        got = sha256_bytes(f.read_bytes())
        if got != want[name]:
            raise SystemExit(f"DATA_HASH_MISMATCH: {name}")
        pins[name] = got
    return pins


def _f(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def load_data(data: Path) -> dict:
    """Load the pinned snapshot.

    Returns {
      "by_player": {pid: [appearance, ...] sorted by (season, week)},
      "by_season": {season: [appearance, ...]},
      "meta": {pid: {"display_name", "team", "position_group",
                     "last_season", "last_week"}},
    }
    An appearance is one regular-season player-week row:
    {season, week, pid, position_group, team, opp, td, st_td} where td is
    1 iff rushing_tds + receiving_tds >= 1 (the priced quantity).
    """
    by_player: dict = defaultdict(list)
    by_season: dict = defaultdict(list)
    meta: dict = {}
    for name in REQUIRED_FILES:
        with gzip.open(data / name, "rt") as fh:
            for r in csv.DictReader(fh):
                if r.get("season_type") != "REG":
                    continue
                season, week = int(r["season"]), int(r["week"])
                pid = r["player_id"]
                team = r.get("recent_team") or r.get("team") or ""
                app = {
                    "season": season, "week": week, "pid": pid,
                    "position_group": r.get("position_group") or "",
                    "team": team, "opp": r.get("opponent_team") or "",
                    "td": 1 if _f(r.get("rushing_tds")) + _f(r.get("receiving_tds")) >= 1 else 0,
                    "st_td": 1 if _f(r.get("special_teams_tds")) >= 1 else 0,
                }
                by_player[pid].append(app)
                by_season[season].append(app)
                key = (season, week)
                cur = meta.get(pid)
                if cur is None or key >= (cur["last_season"], cur["last_week"]):
                    meta[pid] = {
                        "display_name": r.get("player_display_name") or "",
                        "team": team,
                        "position_group": app["position_group"],
                        "last_season": season, "last_week": week,
                    }
    for pid in by_player:
        by_player[pid].sort(key=lambda a: (a["season"], a["week"]))
    return {"by_player": dict(by_player), "by_season": dict(by_season),
            "meta": meta}


def pool_rate(data: dict, season: int, week: int, group: str, cache=None):
    """Point-in-time position-group pool rate for a game at (season, week).

    Returns (rate, n, source) or None if no pool can be formed. Current-season
    strictly-earlier weeks first; if they hold < POOL_MIN_GAMES appearances,
    the previous season's full-season rate is used instead (frozen rule).
    `cache` is an optional dict memoizing identical (season, week, group)
    lookups within one loaded dataset; it never changes the value."""
    key = (season, week, group)
    if cache is not None and key in cache:
        return cache[key]
    cur = [a for a in data["by_season"].get(season, [])
           if a["week"] < week and a["position_group"] == group]
    if len(cur) >= POOL_MIN_GAMES:
        out = (sum(a["td"] for a in cur) / len(cur), len(cur),
               "CURRENT_SEASON_PRIOR_WEEKS")
    else:
        prev = [a for a in data["by_season"].get(season - 1, [])
                if a["position_group"] == group]
        out = ((sum(a["td"] for a in prev) / len(prev), len(prev),
                "PREVIOUS_SEASON_FULL") if prev else None)
    if cache is not None:
        cache[key] = out
    return out


def evidence_games(data: dict, pid: str, season: int, week: int) -> list:
    """The player's appearances strictly before (season, week), from that
    season and the previous one, most recent first, capped at
    MAX_EVIDENCE_GAMES."""
    apps = [a for a in data["by_player"].get(pid, [])
            if a["season"] >= season - 1
            and (a["season"], a["week"]) < (season, week)]
    apps.sort(key=lambda a: (a["season"], a["week"]), reverse=True)
    return apps[:MAX_EVIDENCE_GAMES]


def recency_weights(n: int) -> list:
    """w_i = 0.5 ** (i / HALF_LIFE_GAMES), i = 0 is the most recent game."""
    return [0.5 ** (i / HALF_LIFE_GAMES) for i in range(n)]


def shrunk_rate(t_w: float, n_w: float, pool: float) -> float:
    """model_p = (T_w + K_A * pool) / (N_w + K_A)."""
    return (t_w + K_A * pool) / (n_w + K_A)


def price_player(data: dict, pid: str, season: int, week: int,
                 pool_cache=None) -> dict:
    """Price one player for a game at (season, week). Returns a dict with
    status PRICED (+ model_p and components) or UNPRICED (+ reason)."""
    ev = evidence_games(data, pid, season, week)
    if len(ev) < MIN_GAMES:
        return {"status": "UNPRICED", "reason": "UNPRICED_INSUFFICIENT_GAMES",
                "prior_games": len(ev)}
    group = ev[0]["position_group"]
    if group not in POOL_GROUPS:
        return {"status": "UNPRICED",
                "reason": "UNPRICED_POSITION_GROUP_NOT_POOLED",
                "prior_games": len(ev), "position_group": group}
    pool = pool_rate(data, season, week, group, cache=pool_cache)
    if pool is None:
        return {"status": "UNPRICED", "reason": "UNPRICED_POOL_UNAVAILABLE",
                "prior_games": len(ev), "position_group": group}
    rate, pool_n, pool_source = pool
    w = recency_weights(len(ev))
    t_w = sum(wi * a["td"] for wi, a in zip(w, ev))
    n_w = sum(w)
    p = shrunk_rate(t_w, n_w, rate)
    return {"status": "PRICED", "model_p": p,
            "prior_games": len(ev), "weighted_games": n_w,
            "weighted_td_games": t_w, "pool_rate": rate, "pool_n": pool_n,
            "pool_source": pool_source, "position_group": group,
            "raw_rate": sum(a["td"] for a in ev) / len(ev)}


# ---------------------------------------------------------------------------
# Board pricing (locked forward-test contract)

_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}


def normalize_name(name: str) -> str:
    s = re.sub(r"[^a-z0-9 ]", " ", (name or "").lower())
    toks = [t for t in s.split() if t not in _SUFFIXES]
    return " ".join(toks)


def build_name_index(data: dict) -> dict:
    """normalized display name -> [pid, ...] from each player's most recent
    appearance in the snapshot."""
    idx: dict = defaultdict(list)
    for pid, m in data["meta"].items():
        idx[normalize_name(m["display_name"])].append(pid)
    return dict(idx)


def resolve_name(data: dict, idx: dict, name: str, game_teams) -> str | None:
    """Resolve a board name to a player_id: unique normalized match whose
    most recent team in the data is one of the game's teams. Fail closed."""
    cands = idx.get(normalize_name(name), [])
    ok = [pid for pid in cands if data["meta"][pid]["team"] in game_teams]
    return ok[0] if len(ok) == 1 else None


def raw_implied(american_price: float) -> float:
    """Raw implied probability of an American price (cut included)."""
    price = float(american_price)
    if price > 0:
        return 100.0 / (price + 100.0)
    if price < 0:
        return abs(price) / (abs(price) + 100.0)
    raise ValueError("american price of 0 is not a price")


def parse_american(v):
    """A valid American price as float, else None. Valid: finite number (or
    numeric string such as "+600"), |price| in [100, MAX_ABS_AMERICAN].
    Booleans, 0, null, NaN/inf and the dead zone (-100, 100) are invalid."""
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, str):
        v = v.strip()
        if not re.fullmatch(r"[+-]?\d+(\.\d+)?", v):
            return None
    elif not isinstance(v, (int, float)):
        return None
    try:
        price = float(v)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(price) or not 100 <= abs(price) <= MAX_ABS_AMERICAN:
        return None
    return price


_ZONES = {"CT": "America/Chicago", "CDT": "America/Chicago",
          "CST": "America/Chicago", "ET": "America/New_York",
          "EDT": "America/New_York", "EST": "America/New_York",
          "UTC": "UTC", "Z": "UTC"}
_HOUSE_RE = re.compile(
    r"(\d{4}-\d{2}-\d{2}) +(\d{1,2}:\d{2}) *([AaPp][Mm]) +([A-Za-z]+)")


def parse_timestamp(v):
    """Timezone-aware datetime, or None if missing; raises ValueError if
    present but unparseable or zone-less (a naive time is never assumed).
    Accepts ISO 8601 with an offset/Z, or the capture house format
    'YYYY-MM-DD H:MM AM/PM CT'."""
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    if not isinstance(v, str):
        raise ValueError("timestamp is not a string")
    s = v.strip()
    m = _HOUSE_RE.fullmatch(s)
    if m:
        zone = _ZONES.get(m.group(4).upper())
        if zone is None:
            raise ValueError("unknown zone")
        dt = datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3).upper()}",
                               "%Y-%m-%d %I:%M %p")
        return dt.replace(tzinfo=ZoneInfo(zone))
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00") if s.endswith("Z") else s)
    except ValueError:
        raise ValueError("unparseable timestamp")
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("timestamp has no zone")
    return dt


def timing_refusal(captured_at, kickoff):
    """None if the row was captured strictly before kickoff, else the
    UNPRICED reason."""
    try:
        cap, ko = parse_timestamp(captured_at), parse_timestamp(kickoff)
    except ValueError:
        return "UNPRICED_TIMESTAMP_UNPARSEABLE"
    if cap is None or ko is None:
        return "UNPRICED_TIMESTAMP_MISSING"
    if cap >= ko:
        return "UNPRICED_CAPTURED_AFTER_KICKOFF"
    return None


def is_not_a_player_row(name: str) -> bool:
    n = (name or "").strip().lower()
    return n == "no touchdown scorer" or "d/st" in n


def price_board_row(data: dict, idx: dict, row: dict) -> dict:
    """Price one captured board row. `row` carries: game_id, player_name
    and/or player_id, game_teams (the game's two team abbreviations),
    yes_price (American), captured_at, kickoff."""
    out = {
        "family": FAMILY, **LABELS,
        "game_id": row.get("game_id"), "player_name": row.get("player_name"),
        "player_id": row.get("player_id"), "yes_price": row.get("yes_price"),
        "captured_at": row.get("captured_at"), "kickoff": row.get("kickoff"),
    }
    def refuse(reason, **extra):
        out.update(status="UNPRICED", reason=reason, **extra)
        return out

    # Order: timing, not-a-player, price, identity, engine. Exactly one
    # named reason per row; a bad row never raises.
    reason = timing_refusal(row.get("captured_at"), row.get("kickoff"))
    if reason:
        return refuse(reason)
    if is_not_a_player_row(row.get("player_name") or ""):
        return refuse("UNPRICED_NOT_A_PLAYER_ROW")
    price = parse_american(row.get("yes_price"))
    if price is None:
        return refuse("UNPRICED_INVALID_PRICE")
    game_teams = row.get("game_teams") or []
    pid = row.get("player_id")
    if pid:
        # Same team-in-game rule as name resolution: the player's most
        # recent team in the snapshot must be one of the game's teams.
        m = data["meta"].get(pid)
        if m is None:
            return refuse("UNPRICED_PLAYER_ID_UNKNOWN")
        if m["team"] not in game_teams:
            return refuse("UNPRICED_PLAYER_TEAM_MISMATCH",
                          data_team=m["team"])
    else:
        pid = resolve_name(data, idx, row.get("player_name") or "",
                           game_teams)
        if not pid:
            return refuse("UNPRICED_NAME_UNRESOLVED")
        out["player_id"] = pid
    season, week = int(row["season"]), int(row["week"])
    priced = price_player(data, pid, season, week)
    if priced["status"] != "PRICED":
        out.update(status="UNPRICED", reason=priced["reason"],
                   prior_games=priced.get("prior_games"))
        return out
    imp = raw_implied(price)
    p = priced["model_p"]
    out.update(status="PRICED", model_p=p, raw_implied=imp,
               edge=p / imp - 1.0,
               selection="YES" if p > imp else "PASS",
               prior_games=priced["prior_games"],
               weighted_games=priced["weighted_games"],
               pool_rate=priced["pool_rate"],
               pool_source=priced["pool_source"],
               position_group=priced["position_group"])
    return out
