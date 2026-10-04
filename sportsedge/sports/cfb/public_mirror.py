"""CFB history from public GitHub mirrors -- no CFBD API calls.

Why: the CFBD free tier is out of quota (429) until it resets, which blocked
the 10-season residual backtest (#1471, #1476). The same history is public:

  * closing + opening spreads, 2006-2025, many books:
      sportsdataverse/cfbfastR-data  betting/csv/cfb_line_odds.csv.gz
  * scores, week, neutral site, CFBD team names (game_id = CFBD id):
      sportsdataverse/cfbfastR-data  schedules/csv/cfb_schedules_<season>.csv
  * 247 team talent composite (CFBD /talent), pinned to commits:
      2015-2023 aserban13/SIADS593-MilestoneI data/team_talent.csv
      2024      blaizerlahman/CFB-Model tests/fixtures/talent_2024.json
      2025      BowmanStephen/Script_Ohio_2.0 model_pack/2025_talent.csv
      2026      gmalbert/college-football-predictions data_files/raw/talent_2026.json

Every URL is pinned to a commit SHA so reruns see identical bytes.
Closing spread = median across books of the home line; opening = median of
the books' opening lines. Regular season only.
"""
from __future__ import annotations

import csv
import gzip
import io
import json
import re
import statistics
from collections import defaultdict
from typing import Callable, Iterable

RAW = "https://raw.githubusercontent.com"
CFBFASTR = f"{RAW}/sportsdataverse/cfbfastR-data/88554e2698c8b0dc1fe006418bbeabde819e4c11"
LINES_URL = f"{CFBFASTR}/betting/csv/cfb_line_odds.csv.gz"
SCHEDULE_URL = CFBFASTR + "/schedules/csv/cfb_schedules_{season}.csv"
TALENT_SOURCES = (
    (f"{RAW}/aserban13/SIADS593-MilestoneI/e67e3dd270aa79f069646e97199e5154302ef864/data/team_talent.csv", "csv_year_school"),
    (f"{RAW}/blaizerlahman/CFB-Model/f55a4548f77707c665cbb10087f1b5d9680a63f3/tests/fixtures/talent_2024.json", "json_list"),
    (f"{RAW}/BowmanStephen/Script_Ohio_2.0/b20fc553d61b1bddab895a0ebde6e36a0151ce53/model_pack/2025_talent.csv", "csv_team_season"),
    (f"{RAW}/gmalbert/college-football-predictions/c0d575fb9e1f9d2ca2b73271e5731e1878d48bb4/data_files/raw/talent_2026.json", "json_list"),
)

# CFBD renamed several schools over time; map every spelling to one key.
ALIAS = {
    "ut san antonio": "utsa", "connecticut": "uconn", "umass": "massachusetts",
    "louisiana monroe": "ul monroe", "southern mississippi": "southern miss",
    "appalachian state": "app state", "sam houston state": "sam houston",
    "hawaii": "hawai i", "miami oh": "miami (oh)",
}


def canon(name) -> str:
    t = str(name or "").lower().replace("é", "e").replace("'", " ")
    t = re.sub(r"[^a-z0-9() ]", " ", t)
    t = " ".join(t.split())
    return ALIAS.get(t, t)


def _f(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


def http_get(url: str, timeout: int = 120) -> bytes:
    from urllib.request import Request, urlopen
    with urlopen(Request(url, headers={"User-Agent": "SportsEdge"}), timeout=timeout) as r:
        return r.read()


# ---------- parsers (pure; unit-tested) ----------

def parse_talent(text: str, kind: str) -> dict:
    """-> {season: {canon team: talent}}; zero talent (service academies some years) = missing."""
    out: dict = defaultdict(dict)
    if kind == "json_list":
        recs = [(r.get("year"), r.get("team") or r.get("school"), r.get("talent")) for r in json.loads(text)]
    elif kind == "csv_year_school":
        recs = [(r["year"], r["school"], r["talent"]) for r in csv.DictReader(io.StringIO(text))]
    elif kind == "csv_team_season":
        recs = [(r["season"], r["team"], r["talent"]) for r in csv.DictReader(io.StringIO(text))]
    else:
        raise ValueError(kind)
    for year, team, val in recs:
        v = _f(val)
        if year is None or not team or v is None or v <= 0:
            continue
        out[int(float(year))][canon(team)] = v
    return {k: dict(v) for k, v in out.items()}


def parse_schedule(text: str) -> dict:
    """-> {game_id: game} for completed regular-season games."""
    out = {}
    for r in csv.DictReader(io.StringIO(text)):
        hp, ap = _f(r.get("home_points")), _f(r.get("away_points"))
        if r.get("season_type") != "regular" or hp is None or ap is None:
            continue
        out[str(r["game_id"])] = {
            "season": int(float(r["season"])), "week": int(float(r["week"])),
            "home": r["home_team"], "away": r["away_team"],
            "home_id": str(r["home_id"]), "away_id": str(r["away_id"]),
            "neutral": str(r.get("neutral_site")).upper() == "TRUE",
            "home_pts": hp, "away_pts": ap,
            "home_div": r.get("home_division"), "away_div": r.get("away_division"),
        }
    return out


def consensus_spreads(line_rows: Iterable[dict], sched: dict) -> dict:
    """Median home closing/opening spread per game.

    Book rows carry a team abbreviation, not a team id. An abbreviation's team
    is the one id present in every game it appears in, so intersect.
    """
    by_game: dict = defaultdict(list)
    abbr_ids: dict = {}
    for r in line_rows:
        if r.get("market_type") != "spread":
            continue
        gid = str(r.get("game_id"))
        g = sched.get(gid)
        if g is None:
            continue
        ids = {g["home_id"], g["away_id"]}
        a = r.get("abbr")
        abbr_ids[a] = abbr_ids[a] & ids if a in abbr_ids else set(ids)
        by_game[gid].append(r)
    out = {}
    for gid, rows in by_game.items():
        g = sched[gid]
        abbrs = {r.get("abbr") for r in rows}
        home_abbr = next((a for a in abbrs if abbr_ids.get(a) == {g["home_id"]}), None)
        if home_abbr is None and len(abbrs) == 2:
            away = next((a for a in abbrs if abbr_ids.get(a) == {g["away_id"]}), None)
            home_abbr = next((a for a in abbrs if a != away), None) if away is not None else None
        if home_abbr is None:
            continue
        close, opn = [], []
        for r in rows:
            sgn = 1.0 if r.get("abbr") == home_abbr else -1.0
            c, o = _f(r.get("lines")), _f(r.get("opening_lines"))
            if c is not None and abs(c) < 80:
                close.append(sgn * c)
            if o is not None and abs(o) < 80:
                opn.append(sgn * o)
        if close:
            out[gid] = {"spread": statistics.median(close),
                        "spread_open": statistics.median(opn) if opn else None,
                        "n_books": len({r.get("book") for r in rows})}
    return out


def build_games(sched: dict, spreads: dict) -> list:
    games = []
    for gid, s in spreads.items():
        g = dict(sched[gid])
        g.update(s)
        g["game_id"] = gid
        games.append(g)
    return games


# ---------- leave-one-season-out residual test ----------

def design(games: list, talent: dict, *, line: str = "spread", max_week: int = 99, fbs_only: bool = True):
    """Rows [1, talent diff/100, (talent diff/100)/week, neutral]; target = home margin + home spread."""
    X, y, seasons = [], [], []
    for g in games:
        if fbs_only and (g.get("home_div") != "fbs" or g.get("away_div") != "fbs"):
            continue
        if g["week"] > max_week or g.get(line) is None:
            continue
        T = talent.get(g["season"]) or {}
        th, ta = T.get(canon(g["home"])), T.get(canon(g["away"]))
        if th is None or ta is None:
            continue
        td = (th - ta) / 100.0
        X.append([1.0, td, td / max(g["week"], 1), 1.0 if g.get("neutral") else 0.0])
        y.append(g["home_pts"] - g["away_pts"] + g[line])
        seasons.append(g["season"])
    return X, y, seasons


def loso_ats(X, y, seasons, cols, threshold: float):
    """Fit OLS on other seasons, bet held-out games with |pred| >= threshold. -> (pooled [w,l], {season: [w,l]})."""
    import numpy as np
    X, y, seasons = np.asarray(X, float), np.asarray(y, float), np.asarray(seasons)
    pooled, per = [0, 0], {}
    for s in sorted(set(seasons.tolist())):
        te = seasons == s
        tr = ~te
        if tr.sum() < len(cols) + 1:
            continue
        beta, *_ = np.linalg.lstsq(X[tr][:, cols], y[tr], rcond=None)
        pred = X[te][:, cols] @ beta
        w = l = 0
        for p, r in zip(pred, y[te]):
            if abs(p) < threshold or r == 0:
                continue
            if (p > 0) == (r > 0):
                w += 1
            else:
                l += 1
        per[int(s)] = [w, l]
        pooled[0] += w
        pooled[1] += l
    return pooled, per


def pct(w, l) -> float:
    return 100.0 * w / (w + l) if (w + l) else float("nan")


# Pre-registered before the first run (Oct 4 2026, #1476):
PRIMARY_COLS = [0, 1, 2, 3]
PRIMARY_THRESHOLD = 0.5
PASS_POOLED = 53.0
PASS_SEASON = 52.4
PASS_MIN_SEASONS = 7


def verdict(pooled, per) -> bool:
    good = sum(1 for wl in per.values() if pct(*wl) >= PASS_SEASON)
    return pct(*pooled) >= PASS_POOLED and good >= PASS_MIN_SEASONS


def to_cache_lines(games: list, season: int) -> dict:
    """Same shape as cfbd_issue_cache lines_<season> items (FBS vs FBS only, to stay under the comment cap)."""
    out = {}
    for g in games:
        if g["season"] != season or g.get("home_div") != "fbs" or g.get("away_div") != "fbs":
            continue
        out[g["game_id"]] = {
            "spread": g["spread"], "total": None, "spread_open": g.get("spread_open"), "total_open": None,
            "provider": "mirror_median", "home": g["home"], "away": g["away"], "week": g["week"],
            "home_pts": g["home_pts"], "away_pts": g["away_pts"],
        }
    return out


def load_all(seasons: Iterable[int], get: Callable[[str], bytes] = http_get):
    seasons = list(seasons)
    sched = {}
    for s in seasons:
        sched.update(parse_schedule(get(SCHEDULE_URL.format(season=s)).decode("utf-8")))
    text = gzip.decompress(get(LINES_URL)).decode("utf-8")
    spreads = consensus_spreads(csv.DictReader(io.StringIO(text)), sched)
    talent: dict = {}
    for url, kind in TALENT_SOURCES:
        for yr, tbl in parse_talent(get(url).decode("utf-8"), kind).items():
            talent.setdefault(yr, {}).update(tbl)
    return build_games(sched, spreads), talent
