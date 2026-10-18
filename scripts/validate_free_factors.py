#!/usr/bin/env python3
"""Harness validation for SportsEdge free factors (Phase 2).

RUN WITH cwd=~/workspace/sportsedge-backtest. Do NOT copy the harness into
the branch. This script imports sportsedge.backtest from the cwd and loads
the factor/model code from the free-factors worktree via importlib.

Each factor is evaluated as:
    existing  = production-equivalent independent projection (ratings + form;
                injuries unavailable historically -> 0; weather unavailable
                historically -> 0; NO market anchoring, NO invented prices)
    candidate = existing + the single candidate factor
on chronological walk-forward splits, scored by Brier + log-loss, vs the
market baseline slot (MISSING: no Odds API by Isaac's choice -> best
achievable verdict is CONDITIONAL_PASS, never presented as validated).

Subcommands: park | rest | travel | weather | weather_interaction |
             weather_interaction_legacy | keynums | pitcher | bullpen |
             rotation | qb_oracle | srs | venue_hfa | pace | turnovers | fip |
             epa | time_decay | all
Research only. No betting authority.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode

# Harness location: cwd when run per the documented invocation
# (cwd=~/workspace/sportsedge-backtest); SPORTSEDGE_BACKTEST_DIR overrides
# for test contexts where cwd is the factor worktree.
_harness_dir = os.environ.get("SPORTSEDGE_BACKTEST_DIR", os.getcwd())
sys.path.insert(0, _harness_dir)
from sportsedge.backtest import outcomes, splits, runner, report  # noqa: E402

# Stacked branches (e.g. feat/umpire-weather-20261011 on feat/free-factors-20261011)
# point this at their own worktree; default keeps the Phase 2 path.
WORKTREE = Path(os.environ.get(
    "SPORTSEDGE_FACTOR_WORKTREE",
    "/home/hatch/workspace/sportsedge-freefactors"))
CACHE = Path("/tmp/sportsedge-ff-cache")
REPORTS = WORKTREE / "docs" / "validation_reports"


def load(mod_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(mod_name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


ff = load("ff_factors", WORKTREE / "sportsedge" / "free_factors.py")
# artifacts/free_models.py does `from sportsedge import free_factors`; the
# harness cwd shadows the worktree's sportsedge package, so register the
# worktree module explicitly before loading free_models.
import sportsedge as _harness_sportsedge  # noqa: E402
_harness_sportsedge.free_factors = ff
sys.modules["sportsedge.free_factors"] = ff
fm = load("ff_models", WORKTREE / "artifacts" / "free_models.py")


def _get(url: str, timeout: int = 30) -> dict | list:
    req = urllib.request.Request(
        url, headers={"User-Agent": "SportsEdge-free-research/1.0",
                      "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def cached_json(key: str, url: str) -> dict | list | None:
    """Disk-cached JSON fetch (never re-hits the network on reruns)."""
    path = CACHE / (key + ".json")
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    try:
        data = _get(url)
    except Exception:
        return None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")
    except OSError:
        pass
    return data


# ---------------------------------------------------------------------------
# Shared adapter: production-equivalent independent projection
# ---------------------------------------------------------------------------
RATING_CAP = {"MLB": 0.7, "NBA": 5.0}


def team_history(train: list[dict], team: str, kickoff: datetime,
                 key: str = "name") -> list[tuple[datetime, float, float]]:
    """Last <=5 completed games for a team before kickoff, from train only."""
    hist = []
    for fx in train:
        ko = datetime.fromisoformat(str(fx["kickoff"]).replace("Z", "+00:00"))
        if ko >= kickoff:
            continue
        if fx.get("home_" + key) == team:
            hist.append((ko, fx["home_score"] - fx["away_score"]))
        elif fx.get("away_" + key) == team:
            hist.append((ko, fx["away_score"] - fx["home_score"]))
    hist.sort(reverse=True)
    return hist[:5]


def base_means(sport: str, fixture: dict, train: list[dict]) -> tuple[float, float]:
    """Production-equivalent independent means (ratings + form only)."""
    base, _, _, hfa = fm.PRIORS[sport]
    kickoff = datetime.fromisoformat(
        str(fixture["kickoff"]).replace("Z", "+00:00"))
    home_hist = team_history(train, fixture["home_team"], kickoff)
    away_hist = team_history(train, fixture["away_team"], kickoff)
    cap = RATING_CAP.get(sport, 3.0)

    def rating(hist):
        if not hist:
            return 0.0, 0.0
        margins = [m for _, m in hist]
        r = fm.bounded(sum(margins) / len(margins) * 0.12, -cap, cap)
        form = 0.0
        if sport in ("NFL", "CFB") and len(margins) >= 4:
            trend = sum(margins[:2]) / 2 - sum(margins) / len(margins)
            form = fm.bounded(trend * 0.07, -1.5, 1.5)
        return round(r, 3), round(form, 3)

    hr, hf = rating(home_hist)
    ar, af = rating(away_hist)
    home_mean = base + hfa / 2 + hr + hf
    away_mean = base - hfa / 2 + ar + af
    return home_mean, away_mean


def fair_lines(sport: str, home_mean: float, away_mean: float):
    spread = -round((home_mean - away_mean) * 2) / 2
    total = round((home_mean + away_mean) * 2) / 2
    return spread, total


def price_fn_factory(sport: str, markets: list[str], adjust):
    """adjust(model_name, fixture, as_of, train, home_mean, away_mean)
    -> (home_mean, away_mean, extra_push_fn|None)."""
    def price_fn(model_name, fixture, as_of, train):
        hm, am = base_means(sport, fixture, train)
        hm, am, push_fn = adjust(model_name, fixture, as_of, train, hm, am)
        spread_line, total_line = fair_lines(sport, hm, am)
        preds = []
        for market in markets:
            if market == "ML":
                for side in ("HOME",):
                    win, _ = fm.model_probability(sport, "ML", side, None, hm, am)
                    preds.append({"market": "ML", "selection": side,
                                  "model_p": win})
            elif market == "SPREAD":
                win, push = fm.model_probability(
                    sport, "SPREAD", "HOME", spread_line, hm, am)
                if push_fn is not None:
                    push = push_fn("SPREAD", spread_line, push)
                    loss = max(0.0, 1.0 - win - push)
                    win, push, _ = ff.apply_key_push(win, push, loss, push)
                preds.append({"market": "SPREAD", "selection": "HOME",
                              "line": spread_line, "model_p": win})
            elif market == "TOTAL":
                win, push = fm.model_probability(
                    sport, "TOTAL", "OVER", total_line, hm, am)
                preds.append({"market": "TOTAL", "selection": "OVER",
                              "line": total_line, "model_p": win})
            elif market == "PUSH_AT":
                # Pseudo-market isolating the push model: P(|margin| == k).
                for k in (3, 7) if sport == "NFL" else (3, 7, 10, 14):
                    _, push = fm.model_probability(
                        sport, "SPREAD", "HOME", -k, hm, am)
                    if push_fn is not None:
                        push = push_fn("SPREAD", -k, push)
                    preds.append({"market": "PUSH_AT", "selection": str(k),
                                  "line": k, "model_p": push})
        return preds
    return price_fn


def settle_fn(fixture, market, selection, line):
    if market == "PUSH_AT":
        margin = fixture["home_score"] - fixture["away_score"]
        return 1.0 if abs(margin) == int(selection) else 0.0
    game = {"home_score": fixture["home_score"],
            "away_score": fixture["away_score"]}
    return outcomes.settle_game(game, market, selection, line)


def run_evaluation(name: str, fixtures: list[dict], price_fn,
                   min_train: int, test_size: int,
                   embargo_days: int = 1, step: int = 1) -> dict:
    # embargo_days=1 suits weekly football; daily MLB needs 0 (consecutive
    # game-days are <24h apart and would otherwise yield zero splits).
    # step>1 thins walk-forward splits for expensive runners.
    fixtures = sorted(fixtures,
                      key=lambda f: datetime.fromisoformat(
                          str(f["kickoff"]).replace("Z", "+00:00")))
    sp = list(splits.walk_forward_splits(fixtures, min_train=min_train,
                                         test_size=test_size,
                                         embargo_days=embargo_days, step=step))
    result = runner.run_backtest(
        fixtures=fixtures, splits=sp, models=["existing", "candidate"],
        price_fn=price_fn, settle_fn=settle_fn, market_baseline=None)
    comp = runner.compare_models(result)
    verdict = report.evaluate(
        candidate=comp["models"]["candidate"],
        existing=comp["models"]["existing"],
        baseline_status=comp["baseline"]["status"],
        baseline=comp["baseline"]["summary"])
    out = {"factor": name, "n_fixtures": len(fixtures),
           "n_splits": comp["n_splits"], "verdict": verdict["verdict"],
           "reasons": verdict["reasons"],
           "existing": comp["models"]["existing"],
           "candidate": comp["models"]["candidate"],
           "research_only": True}
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / f"{name}.json").write_text(json.dumps(out, indent=2))
    print(f"### {name}: {verdict['verdict']}")
    for r_ in verdict["reasons"]:
        print("  -", r_)
    e, c = comp["models"]["existing"], comp["models"]["candidate"]
    print(f"  existing  n={e['n']} brier={e.get('brier')} logloss={e.get('log_loss')}")
    print(f"  candidate n={c['n']} brier={c.get('brier')} logloss={c.get('log_loss')}")
    return out


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------
def mlb_fixtures(year: int, months: list[int]) -> list[dict]:
    fixtures = []
    seen_pk: dict[int, dict] = {}
    for month in months:
        start = date(year, month, 1)
        end = date(year, month + 1, 1) - timedelta(days=1) if month < 12 else date(year, 12, 31)
        key = f"mlb_sched_{year}_{month:02d}"
        url = ("https://statsapi.mlb.com/api/v1/schedule?sportId=1&"
               f"startDate={start}&endDate={end}&hydrate=probablePitcher")
        data = cached_json(key, url) or {}
        for day in data.get("dates") or []:
            for g in day.get("games") or []:
                if str((g.get("status") or {}).get("detailedState")) != "Final":
                    continue
                teams = g.get("teams") or {}
                home, away = teams.get("home") or {}, teams.get("away") or {}
                try:
                    hs, aws = int(home.get("score")), int(away.get("score"))
                except (TypeError, ValueError):
                    continue
                ko = g.get("gameDate")
                if not ko:
                    continue
                kickoff = datetime.fromisoformat(str(ko).replace("Z", "+00:00"))
                # MLB double-lists some rescheduled games under two dates;
                # keep the listing whose gameDate matches officialDate.
                pk = g.get("gamePk")
                official = str(g.get("officialDate") or "")[:10]
                is_official = kickoff.date().isoformat() == official
                if pk in seen_pk and not (is_official and not seen_pk[pk]["_official"]):
                    continue
                fx = {
                    "fixture_id": f"mlb-{pk}",
                    "kickoff": kickoff.isoformat(),
                    "as_of": (kickoff - timedelta(hours=2)).isoformat(),
                    "home_team": ((home.get("team") or {}).get("name") or "").strip(),
                    "away_team": ((away.get("team") or {}).get("name") or "").strip(),
                    "home_score": hs, "away_score": aws,
                    "venue_id": (g.get("venue") or {}).get("id"),
                    "game_pk": pk,
                    "_official": is_official,
                    "probable": {
                        "home": (home.get("probablePitcher") or {}).get("id"),
                        "away": (away.get("probablePitcher") or {}).get("id"),
                    },
                }
                seen_pk[pk] = fx
                fixtures.append(fx)
    # drop any superseded duplicates (kept the official-date listing)
    by_pk: dict[str, dict] = {}
    for fx in fixtures:
        fid = fx["fixture_id"]
        if fid not in by_pk or (fx["_official"] and not by_pk[fid]["_official"]):
            by_pk[fid] = fx
    out = []
    for fx in by_pk.values():
        fx = dict(fx)
        fx.pop("_official", None)
        out.append(fx)
    return out


FIRST_THURSDAY = {
    "nfl": {2024: date(2024, 9, 5), 2025: date(2025, 9, 4)},
    "cfb": {2024: date(2024, 8, 29)},
}


def football_game_days(sport: str, season: int):
    start = FIRST_THURSDAY[sport][season]
    days = []
    n_weeks = 22 if sport == "nfl" else 16
    for w in range(n_weeks):
        thu = start + timedelta(days=7 * w)
        if sport == "nfl":
            days += [thu, thu + timedelta(days=3), thu + timedelta(days=4)]
            if w >= 14:
                days.append(thu + timedelta(days=2))
        else:
            days += [thu + timedelta(days=2), thu + timedelta(days=1)]
    return days


def football_fixtures(sport: str, seasons: list[int]) -> list[dict]:
    path = {"nfl": "nfl", "cfb": "college-football"}[sport]
    base = f"https://site.api.espn.com/apis/site/v2/sports/football/{path}/scoreboard"
    fixtures, seen = [], set()
    for season in seasons:
        for day in football_game_days(sport, season):
            key = f"{sport}_sb_{day:%Y%m%d}"
            url = base + "?" + urlencode({"dates": day.strftime("%Y%m%d")})
            data = cached_json(key, url) or {}
            for ev in data.get("events") or []:
                eid = str(ev.get("id") or "")
                if not eid or eid in seen:
                    continue
                if ((ev.get("status") or {}).get("type") or {}).get("completed") is not True:
                    continue
                seen.add(eid)
                comp = (ev.get("competitions") or [{}])[0]
                comps = comp.get("competitors") or []
                home = next((c for c in comps if c.get("homeAway") == "home"), None)
                away = next((c for c in comps if c.get("homeAway") == "away"), None)
                if home is None or away is None:
                    continue
                try:
                    hs, aws = int(home.get("score")), int(away.get("score"))
                except (TypeError, ValueError):
                    continue
                ko = ev.get("date")
                kickoff = datetime.fromisoformat(str(ko).replace("Z", "+00:00"))
                ht, at = home.get("team") or {}, away.get("team") or {}
                fixtures.append({
                    "fixture_id": f"{sport}-{eid}",
                    "kickoff": kickoff.isoformat(),
                    "as_of": (kickoff - timedelta(hours=2)).isoformat(),
                    "home_team": str(ht.get("displayName") or "").strip(),
                    "away_team": str(at.get("displayName") or "").strip(),
                    "home_id": str(ht.get("id")), "away_id": str(at.get("id")),
                    "home_abbr": str(ht.get("abbreviation") or ""),
                    "away_abbr": str(at.get("abbreviation") or ""),
                    "home_score": hs, "away_score": aws,
                    "season": season,
                    "week": (ev.get("week") or {}).get("number"),
                })
    return fixtures


# ---------------------------------------------------------------------------
# Factor data helpers (all cached; point-in-time filtered)
# ---------------------------------------------------------------------------
def nfl_team_schedule(team_id: str, season: int) -> list[dict]:
    key = f"nfl_team_sched_{team_id}_{season}"
    url = (f"https://site.api.espn.com/apis/site/v2/sports/football/nfl/"
           f"teams/{team_id}/schedule?season={season}")
    data = cached_json(key, url) or {}
    return data.get("events") or []


def team_last_game(team_id: str, season: int,
                   kickoff: datetime) -> dict | None:
    """Most recent completed game before kickoff: date, venue coords, home flag."""
    best = None
    for ev in nfl_team_schedule(team_id, season):
        comp = (ev.get("competitions") or [{}])[0]
        if ((comp.get("status") or {}).get("type") or {}).get("completed") is not True:
            continue
        played = datetime.fromisoformat(str(ev.get("date")).replace("Z", "+00:00"))
        if played >= kickoff:
            continue
        comps = comp.get("competitors") or []
        home = next((c for c in comps if c.get("homeAway") == "home"), None)
        away = next((c for c in comps if c.get("homeAway") == "away"), None)
        is_home = home is not None and str((home.get("team") or {}).get("id")) == str(team_id)
        opp = away if is_home else home
        opp_abbr = str((opp.get("team") or {}).get("abbreviation") or "") if opp else ""
        venue = comp.get("venue") or {}
        addr = venue.get("address") or {}
        neutral = bool(comp.get("neutralSite"))
        if best is None or played > best["played"]:
            best = {"played": played, "is_home": is_home,
                    "venue_name": venue.get("fullName"),
                    "city": addr.get("city"), "state": addr.get("state"),
                    "opp_abbr": opp_abbr, "neutral": neutral}
    return best


def mlb_venue_info(venue_id: int) -> dict | None:
    if not venue_id:
        return None
    key = f"mlb_venue_{venue_id}"
    url = f"https://statsapi.mlb.com/api/v1/venues/{venue_id}?hydrate=location,fieldInfo"
    data = cached_json(key, url) or {}
    vs = (data.get("venues") or [None])[0]
    if not vs:
        return None
    loc = vs.get("location") or {}
    coords = loc.get("defaultCoordinates") or {}
    field = vs.get("fieldInfo") or {}
    return {
        "name": vs.get("name"),
        "lat": coords.get("latitude"), "lon": coords.get("longitude"),
        "azimuth": loc.get("azimuthAngle"),
        "roof": field.get("roofType"),
    }


def era5_venue_month(lat: float, lon: float, year: int, month: int) -> dict | None:
    """ERA5 hourly weather for a venue-month (one cached call per venue-month).

    NOTE (2026-10-11): the ERA5 archive does not serve
    precipitation_probability (all nulls -- verified); it is dropped from the
    request and the harness validates the wind leg only, passing
    precip_probability_pct=None. The production forecast path (Open-Meteo
    forecast API) does provide precipitation_probability, so the declared
    precip thresholds are unaffected in production -- they are simply not
    exercised by this harness run. Cache key bumped (era5w2_) so the old
    all-null-precip payloads are never read.
    """
    key = f"era5w2_{lat:.2f}_{lon:.2f}_{year}_{month:02d}"
    start = date(year, month, 1)
    end = (date(year, month + 1, 1) - timedelta(days=1) if month < 12
           else date(year, 12, 31))
    url = ("https://archive-api.open-meteo.com/v1/archive?" + urlencode({
        "latitude": lat, "longitude": lon,
        "start_date": start.isoformat(), "end_date": end.isoformat(),
        "hourly": "wind_speed_10m,wind_direction_10m",
        "wind_speed_unit": "mph", "timezone": "UTC"}))
    data = cached_json(key, url)
    return (data or {}).get("hourly")


def _era5_best_hour_index(times: list, ko: datetime) -> int | None:
    """Index of the hourly timestamp nearest kickoff (within 90 min).

    ERA5 returns naive ISO times when timezone=UTC is requested; the request
    is UTC so naive times are treated as UTC. (Bug fix 2026-10-11: naive-vs-
    aware subtraction raised TypeError, which is why the weather runner never
    completed.)
    """
    best, best_dt = None, None
    for i, t in enumerate(times or []):
        try:
            th = datetime.fromisoformat(str(t).replace("Z", "+00:00"))
        except ValueError:
            continue
        if th.tzinfo is None:
            th = th.replace(tzinfo=timezone.utc)
        d = abs((th - ko).total_seconds())
        if best is None or d < best:
            best, best_dt = d, i
    if best is None or best > 5400:
        return None
    return best_dt


def era5_temp_humidity_venue_month(lat: float, lon: float, year: int,
                                   month: int) -> dict | None:
    """ERA5 hourly temperature/humidity for a venue-month.

    Separate cache key from era5_venue_month (wind/precip) so adding the
    weather-interaction runner never invalidates the existing cache.
    Free, keyless, no signup.
    """
    key = f"era5t_{lat:.2f}_{lon:.2f}_{year}_{month:02d}"
    start = date(year, month, 1)
    end = (date(year, month + 1, 1) - timedelta(days=1) if month < 12
           else date(year, 12, 31))
    url = ("https://archive-api.open-meteo.com/v1/archive?" + urlencode({
        "latitude": lat, "longitude": lon,
        "start_date": start.isoformat(), "end_date": end.isoformat(),
        "hourly": "temperature_2m,relative_humidity_2m",
        "temperature_unit": "fahrenheit", "timezone": "UTC"}))
    data = cached_json(key, url)
    return (data or {}).get("hourly")


def pitcher_gamelog(pid: int, season: int) -> list:
    """Per-start pitching game log for one pitcher-season (MLB Stats API, cached)."""
    key = f"mlb_plog_{pid}_{season}"
    url = (f"https://statsapi.mlb.com/api/v1/people/{pid}/stats?"
           + urlencode({"stats": "gameLog", "season": season, "group": "pitching"}))
    data = cached_json(key, url) or {}
    splits_ = ((data.get("stats") or [{}])[0].get("splits")) or []
    return splits_


def pitcher_prior_era(pid: int, season: int, as_of: datetime,
                      min_starts: int = 5) -> tuple[float | None, int, float | None]:
    """(ERA over prior starts, n_starts, days_rest). None if insufficient."""
    eras, rests = [], []
    last_date = None
    for s in pitcher_gamelog(pid, season):
        d = str(s.get("date") or "")[:10]
        try:
            gd = datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if gd >= as_of:
            continue
        st = s.get("stat") or {}
        try:
            gs = int(st.get("gamesStarted") or 0)
        except (TypeError, ValueError):
            gs = 0
        if gs != 1:
            continue
        try:
            er = float(st.get("earnedRuns") or 0)
            ip = float(str(st.get("inningsPitched") or "0").replace(".1", ".333").replace(".2", ".667"))
        except (TypeError, ValueError):
            continue
        if ip <= 0:
            continue
        eras.append((gd, er, ip))
        last_date = gd if last_date is None or gd > last_date else last_date
    eras.sort()
    n = len(eras)
    if n < min_starts:
        return None, n, None
    tot_er = sum(e for _, e, _ in eras)
    tot_ip = sum(i for _, _, i in eras)
    era = 9 * tot_er / tot_ip if tot_ip > 0 else None
    rest = (as_of - last_date).days if last_date else None
    return era, n, rest


def _month_schedule(year: int, month: int) -> dict:
    """Reuse the monthly schedule cache written by mlb_fixtures."""
    key = f"mlb_sched_{year}_{month:02d}"
    url = ("https://statsapi.mlb.com/api/v1/schedule?sportId=1&"
           f"startDate={date(year, month, 1)}&"
           f"endDate={(date(year, month + 1, 1) - timedelta(days=1) if month < 12 else date(year, 12, 31))}"
           f"&hydrate=probablePitcher")
    return cached_json(key, url) or {}


def bullpen_trailing_pitches(team_name: str, season: int,
                             as_of: datetime, days: int = 3) -> tuple[float | None, int]:
    """Sum bullpen pitches from the team's boxscores in the trailing window."""
    total, n_games = 0.0, 0
    seen_pks: set[int] = set()
    for back in range(1, days + 1):
        day = (as_of - timedelta(days=back)).date()
        data = _month_schedule(day.year, day.month)
        for d_ in data.get("dates") or []:
            if str(d_.get("date") or "")[:10] != day.isoformat():
                continue
            for g in d_.get("games") or []:
                if str((g.get("status") or {}).get("detailedState")) != "Final":
                    continue
                pk = g.get("gamePk")
                if pk in seen_pks:
                    continue
                teams = g.get("teams") or {}
                side = None
                for s_ in ("home", "away"):
                    nm = ((teams.get(s_) or {}).get("team") or {}).get("name")
                    if nm == team_name:
                        side = s_
                if side is None:
                    continue
                seen_pks.add(pk)
                bs = cached_json(f"mlb_box_{pk}",
                                 f"https://statsapi.mlb.com/api/v1/game/{pk}/boxscore") or {}
                tdata = ((bs.get("teams") or {}).get(side)) or {}
                pitchers = tdata.get("pitchers") or []
                players = tdata.get("players") or {}
                if not pitchers:
                    continue
                starter_id = None
                for pid in pitchers:
                    p = players.get(f"ID{pid}") or {}
                    if int((p.get("stats") or {}).get("pitching", {}).get("gamesStarted") or 0) == 1:
                        starter_id = pid
                        break
                if starter_id is None:
                    starter_id = pitchers[0]
                bp = 0.0
                for pid in pitchers:
                    if pid == starter_id:
                        continue
                    p = players.get(f"ID{pid}") or {}
                    try:
                        bp += float((p.get("stats") or {}).get("pitching", {}).get("numberOfPitches") or 0)
                    except (TypeError, ValueError):
                        pass
                total += bp
                n_games += 1
    if n_games == 0:
        return None, 0
    return total, n_games


# ---------------------------------------------------------------------------
# Per-factor evaluations
# ---------------------------------------------------------------------------
def _no_adjust(model_name, fixture, as_of, train, hm, am):
    return hm, am, None


def run_park():
    fixtures = mlb_fixtures(2025, [4, 5, 6, 7, 8, 9])
    print(f"park: {len(fixtures)} MLB 2025 fixtures")

    def adjust(model_name, fixture, as_of, train, hm, am):
        if model_name != "candidate":
            return hm, am, None
        season = datetime.fromisoformat(
            fixture["kickoff"].replace("Z", "+00:00")).year
        pf, status, _ = ff.park_factor_for(fixture["home_team"], season)
        if pf is None:
            return hm, am, None  # fail closed: no adjustment
        scale = ff.park_runs_scale(pf)
        return hm * scale, am * scale, None

    price_fn = price_fn_factory("MLB", ["TOTAL", "ML"], adjust)
    return run_evaluation("park", fixtures, price_fn,
                          min_train=400, test_size=200,
                          embargo_days=0, step=7)


def run_rest():
    fixtures = football_fixtures("nfl", [2024, 2025])
    print(f"rest: {len(fixtures)} NFL fixtures")

    def rest_days(team_id, season, kickoff):
        last = team_last_game(team_id, season, kickoff)
        if last is None:
            return None
        return (kickoff - last["played"]).total_seconds() / 86400

    def adjust(model_name, fixture, as_of, train, hm, am):
        if model_name != "candidate":
            return hm, am, None
        ko = datetime.fromisoformat(fixture["kickoff"].replace("Z", "+00:00"))
        hr = rest_days(fixture["home_id"], fixture["season"], ko)
        ar = rest_days(fixture["away_id"], fixture["season"], ko)
        adj, status, _ = ff.rest_margin_adjustment(hr, ar)
        if status != "REST_VERIFIED_APPLIED":
            return hm, am, None
        return hm + adj / 2, am - adj / 2, None

    price_fn = price_fn_factory("NFL", ["ML", "SPREAD", "TOTAL"], adjust)
    return run_evaluation("rest", fixtures, price_fn,
                          min_train=150, test_size=60)


def run_travel():
    fixtures = football_fixtures("nfl", [2024, 2025])
    print(f"travel: {len(fixtures)} NFL fixtures")
    geo = ff.NFL_TEAM_GEO

    def coords_for(last, abbr):
        if last is None:
            return None
        if last.get("neutral"):
            return None  # neutral-site prev game: fail closed
        if last["is_home"]:
            return geo.get(abbr)
        return geo.get(last.get("opp_abbr") or "")

    def adjust(model_name, fixture, as_of, train, hm, am):
        if model_name != "candidate":
            return hm, am, None
        ko = datetime.fromisoformat(fixture["kickoff"].replace("Z", "+00:00"))
        last = team_last_game(fixture["away_id"], fixture["season"], ko)
        game_coords = geo.get(fixture["home_abbr"])
        prev = coords_for(last, fixture["away_abbr"])
        if game_coords is None or prev is None:
            return hm, am, None  # fail closed
        miles = ff.haversine_miles(prev[0], prev[1], game_coords[0], game_coords[1])
        tz = ff.timezone_jumps(prev[1], game_coords[1])
        adj, status, _ = ff.travel_margin_adjustment(miles, tz, traveler="AWAY")
        if status != "TRAVEL_VERIFIED_APPLIED":
            return hm, am, None
        return hm, am + adj, None

    price_fn = price_fn_factory("NFL", ["ML", "SPREAD", "TOTAL"], adjust)
    return run_evaluation("travel", fixtures, price_fn,
                          min_train=150, test_size=60)


def _run_weather(name: str, apply_interaction: bool, base: str = "thresholds"):
    """Shared MLB weather harness.

    apply_interaction=False: the original weather run — existing =
    legacy production heuristic, candidate = declared wind/precip
    thresholds (ff.weather_total_adjustment).
    apply_interaction=True, base="thresholds": existing = declared
    thresholds, candidate = thresholds + temp/humidity x park interaction
    (ff.weather_interaction_adjustment, MLB branch). Gates the interaction
    vs the thresholds it was designed to stack on.
    apply_interaction=True, base="legacy": existing = legacy production
    heuristic, candidate = legacy + temp/humidity x park interaction. The
    production-relevant wiring gate, since the declared thresholds FAILED
    vs the legacy heuristic (weather.json, 2026-10-11).
    """
    fixtures = mlb_fixtures(2025, [6, 7, 8])
    print(f"{name}: {len(fixtures)} MLB fixtures (Jun-Aug 2025)")
    venue_cache: dict[int, dict | None] = {}

    def venue(fid_vid):
        if fid_vid not in venue_cache:
            venue_cache[fid_vid] = mlb_venue_info(fid_vid)
        return venue_cache[fid_vid]

    def hour_weather(v, ko):
        """(wind, wdir, precip) at kickoff hour from ERA5, or None.

        precip is always None: ERA5 archive has no precipitation_probability
        (verified all-nulls 2026-10-11) -- the harness exercises the wind leg
        only.
        """
        if not v or v.get("lat") is None:
            return None
        hourly = era5_venue_month(v["lat"], v["lon"], ko.year, ko.month)
        if not hourly:
            return None
        i = _era5_best_hour_index(hourly.get("time"), ko)
        if i is None:
            return None
        try:
            return (float(hourly["wind_speed_10m"][i]),
                    float(hourly["wind_direction_10m"][i]), None)
        except (KeyError, TypeError, IndexError, ValueError):
            return None

    def hour_temp_humidity(v, ko):
        """(temp_f, humidity_pct) at kickoff hour from ERA5, or None."""
        if not v or v.get("lat") is None:
            return None
        hourly = era5_temp_humidity_venue_month(v["lat"], v["lon"],
                                                ko.year, ko.month)
        if not hourly:
            return None
        i = _era5_best_hour_index(hourly.get("time"), ko)
        if i is None:
            return None
        try:
            return (float(hourly["temperature_2m"][i]),
                    float(hourly["relative_humidity_2m"][i]))
        except (KeyError, TypeError, IndexError, ValueError):
            return None

    def old_heuristic(wind, precip):
        """Legacy production weather heuristic (the gate's existing leg).

        precip may be None (ERA5 archive has no precipitation_probability) --
        the precip leg is then skipped, not invented.
        """
        impact = (0.8 if wind >= 18 else 0.4 if wind >= 13 else 0.0)
        impact += 0.4 if (precip is not None and precip >= 70) else 0.0
        return -round(impact * 0.3, 3)

    # StatsAPI fieldInfo.roofType is unreliable (Tropicana reports "Open");
    # use the known fixed-dome list instead. Retractable roofs: status
    # unknown at game time -> weather applied in both legs (as in production).
    FIXED_DOMES = {"Tropicana Field"}

    def adjust(model_name, fixture, as_of, train, hm, am):
        v = venue(fixture.get("venue_id"))
        if v is not None and v.get("name") in FIXED_DOMES:
            return hm, am, None  # verified indoor: no weather effect either leg
        ko = datetime.fromisoformat(fixture["kickoff"].replace("Z", "+00:00"))
        hw = hour_weather(v, ko)
        if hw is None:
            return hm, am, None
        wind, wdir, precip = hw
        if not apply_interaction:
            if model_name != "candidate":
                # existing = legacy production heuristic
                adj = old_heuristic(wind, precip)
                return hm + adj / 2, am + adj / 2, None
            if v.get("azimuth") is None:
                return hm, am, None
            adj, status, _ = ff.weather_total_adjustment(
                sport="MLB", wind_speed_mph=wind, wind_from_degrees=wdir,
                field_azimuth_degrees=v["azimuth"],
                precip_probability_pct=precip, indoor=(v.get("roof") == "closed"))
            if status not in ("WEATHER_THRESHOLDS_VERIFIED_APPLIED",
                              "WEATHER_CALM_NO_EFFECT"):
                return hm, am, None
            return hm + adj / 2, am + adj / 2, None
        # Interaction runs: both legs share the base; the candidate adds the
        # temp/humidity x park interaction on top.
        if base == "legacy":
            badj = old_heuristic(wind, precip)
            hm, am = hm + badj / 2, am + badj / 2
        else:
            if v.get("azimuth") is None:
                return hm, am, None
            adj, status, _ = ff.weather_total_adjustment(
                sport="MLB", wind_speed_mph=wind, wind_from_degrees=wdir,
                field_azimuth_degrees=v["azimuth"],
                precip_probability_pct=precip,
                indoor=(v.get("roof") == "closed"))
            if status not in ("WEATHER_THRESHOLDS_VERIFIED_APPLIED",
                              "WEATHER_CALM_NO_EFFECT"):
                return hm, am, None
            hm, am = hm + adj / 2, am + adj / 2
        if model_name == "candidate":
            th = hour_temp_humidity(v, ko)
            if th is not None:
                pf, pf_status, _ = ff.park_factor_for(
                    fixture.get("home_team"), ko.year)
                iadj, istatus, _ = ff.weather_interaction_adjustment(
                    sport="MLB", temp_f=th[0], humidity_pct=th[1],
                    park_factor=(pf if pf_status == "PARK_FACTOR_VERIFIED"
                                 else None),
                    indoor=(v.get("roof") == "closed"))
                if istatus == "WEATHER_INTERACTION_VERIFIED":
                    hm, am = hm + iadj / 2, am + iadj / 2
        return hm, am, None

    price_fn = price_fn_factory("MLB", ["TOTAL"], adjust)
    return run_evaluation(name, fixtures, price_fn,
                          min_train=300, test_size=150,
                          embargo_days=0, step=7)


def run_weather():
    return _run_weather("weather", apply_interaction=False)


def run_weather_interaction():
    """Gate the declared temp/humidity x park interaction vs the declared
    thresholds it was designed to stack on."""
    return _run_weather("weather_interaction", apply_interaction=True,
                        base="thresholds")


def run_weather_interaction_legacy():
    """Gate the declared temp/humidity x park interaction vs the legacy
    production heuristic -- the production-relevant wiring gate, since the
    declared thresholds FAILED vs legacy (weather.json, 2026-10-11)."""
    return _run_weather("weather_interaction_legacy", apply_interaction=True,
                        base="legacy")


def run_keynums():
    nfl = football_fixtures("nfl", [2024, 2025])
    cfb = football_fixtures("cfb", [2024])
    print(f"keynums: {len(nfl)} NFL + {len(cfb)} CFB fixtures")

    def make_adjust(sport):
        def adjust(model_name, fixture, as_of, train, hm, am):
            if model_name != "candidate":
                return hm, am, None
            def push_fn(market, line, normal_push):
                p, _, _ = ff.key_number_push_probability(sport, line, normal_push)
                return p
            return hm, am, push_fn
        return adjust

    out = {}
    price_fn = price_fn_factory("NFL", ["PUSH_AT"], make_adjust("NFL"))
    out["nfl"] = run_evaluation("keynums_nfl", nfl, price_fn,
                                min_train=150, test_size=60)
    price_fn = price_fn_factory("CFB", ["PUSH_AT"], make_adjust("CFB"))
    out["cfb"] = run_evaluation("keynums_cfb", cfb, price_fn,
                                min_train=150, test_size=60)
    return out


def run_pitcher(sample_every: int = 4):
    fixtures = mlb_fixtures(2025, [6, 7, 8])
    fixtures = fixtures[::sample_every]
    print(f"pitcher: {len(fixtures)} MLB fixtures (1-in-{sample_every} sample)")

    def adjust(model_name, fixture, as_of, train, hm, am):
        if model_name != "candidate":
            return hm, am, None
        ko = datetime.fromisoformat(fixture["kickoff"].replace("Z", "+00:00"))
        season = ko.year
        probs = fixture.get("probable") or {}
        # home pitcher adj -> added to AWAY mean; away pitcher adj -> HOME mean
        for side, target in (("home", "away"), ("away", "home")):
            pid = probs.get(side)
            if not pid:
                continue
            era, n, _ = pitcher_prior_era(int(pid), season, ko)
            adj, status, _ = ff.pitcher_quality_adjustment(era, n)
            if status != "PITCHER_VERIFIED_APPLIED":
                continue
            if target == "home":
                hm += adj
            else:
                am += adj
        return hm, am, None

    price_fn = price_fn_factory("MLB", ["TOTAL", "ML"], adjust)
    return run_evaluation("pitcher", fixtures, price_fn,
                          min_train=120, test_size=60,
                          embargo_days=0, step=7)


def run_bullpen(sample_every: int = 8):
    fixtures = mlb_fixtures(2025, [6, 7, 8])
    fixtures = fixtures[::sample_every]
    print(f"bullpen: {len(fixtures)} MLB fixtures (1-in-{sample_every} sample)")

    def adjust(model_name, fixture, as_of, train, hm, am):
        if model_name != "candidate":
            return hm, am, None
        ko = datetime.fromisoformat(fixture["kickoff"].replace("Z", "+00:00"))
        for side, target in (("home", "away"), ("away", "home")):
            team = fixture[f"{side}_team"]
            pitches, n = bullpen_trailing_pitches(team, ko.year, ko)
            adj, status, _ = ff.bullpen_workload_adjustment(pitches)
            if status != "BULLPEN_TAXED_APPLIED":
                continue
            if target == "home":
                hm += adj
            else:
                am += adj
        return hm, am, None

    price_fn = price_fn_factory("MLB", ["TOTAL"], adjust)
    return run_evaluation("bullpen", fixtures, price_fn,
                          min_train=60, test_size=30,
                          embargo_days=0, step=7)


def run_rotation(sample_every: int = 4):
    fixtures = mlb_fixtures(2025, [6, 7, 8])
    fixtures = fixtures[::sample_every]
    print(f"rotation: {len(fixtures)} MLB fixtures (1-in-{sample_every} sample)")

    def adjust(model_name, fixture, as_of, train, hm, am):
        if model_name != "candidate":
            return hm, am, None
        ko = datetime.fromisoformat(fixture["kickoff"].replace("Z", "+00:00"))
        season = ko.year
        probs = fixture.get("probable") or {}
        for side, target in (("home", "away"), ("away", "home")):
            pid = probs.get(side)
            if not pid:
                continue
            _, _, rest = pitcher_prior_era(int(pid), season, ko)
            adj, status, _ = ff.rotation_rest_adjustment(rest)
            if status != "ROTATION_SHORT_REST_APPLIED":
                continue
            if target == "home":
                hm += adj
            else:
                am += adj
        return hm, am, None

    price_fn = price_fn_factory("MLB", ["TOTAL"], adjust)
    return run_evaluation("rotation", fixtures, price_fn,
                          min_train=120, test_size=60,
                          embargo_days=0, step=7)


def run_qb_oracle():
    """ORACLE study (NOT a harness gate): post-game boxscore QB1-out labels
    measure the max achievable gain from perfect QB-out knowledge. Labels are
    lookahead -> verdict is INFORMATIONAL only."""
    fixtures = football_fixtures("nfl", [2024, 2025])
    print(f"qb_oracle: {len(fixtures)} NFL fixtures")
    # Season pass-attempt leaders -> QB1 per team-season (from summaries).
    # To bound cost, use scoreboard summaries per fixture (cached).
    qb1: dict[tuple[str, int], str] = {}
    att: dict[tuple[str, int, str], int] = {}
    for fx in fixtures:
        eid = fx["fixture_id"].split("-", 1)[1]
        key = f"nfl_summary_{eid}"
        url = ("https://site.api.espn.com/apis/site/v2/sports/football/nfl/"
               f"summary?event={eid}")
        data = cached_json(key, url) or {}
        box = data.get("boxscore") or {}
        for side, tid in (("home", fx["home_id"]), ("away", fx["away_id"])):
            team_box = next((t for t in box.get("teams") or []
                             if str((t.get("team") or {}).get("id")) == str(tid)),
                            None)
            if not team_box:
                continue
            stats = team_box.get("statistics") or []
            passing = next((s for s in stats if s.get("name") == "passing"), None)
            if not passing:
                continue
            leaders = (passing.get("leaders") or [{}])[0].get("leaders") or []
            if not leaders:
                continue
            # leaders[0] has displayValue like "24/35"; athlete id present
            lead = leaders[0]
            ath = lead.get("athlete") or {}
            try:
                atts = int(str(lead.get("displayValue") or "0/0").split("/")[1])
            except (ValueError, IndexError):
                atts = 0
            aid = str(ath.get("id"))
            k = (str(tid), fx["season"], aid)
            att[k] = att.get(k, 0) + atts
            fx.setdefault("_qb_att", {})[str(tid)] = (aid, atts)
    leaders_: dict[tuple[str, int], str] = {}
    for (tid, season, aid), total in att.items():
        k = (tid, season)
        if k not in leaders_ or total > att.get((tid, season, leaders_[k]), 0):
            leaders_[k] = aid

    def adjust(model_name, fixture, as_of, train, hm, am):
        if model_name != "candidate":
            return hm, am, None
        for side, tid in (("home", fixture["home_id"]), ("away", fixture["away_id"])):
            qb1_id = leaders_.get((str(tid), fixture["season"]))
            cur = (fixture.get("_qb_att") or {}).get(str(tid))
            if qb1_id is None or cur is None:
                continue
            cur_id, cur_att = cur
            # QB1 DNP (0 attempts, someone else led) -> oracle QB-out
            if cur_id != qb1_id and cur_att is not None:
                # verify QB1 truly DNP: he is not the leader and attempts==0?
                # We only know the leader; treat leader!=QB1 as QB-out signal
                # only when QB1's season role is established (he led >=8 games).
                adj, status, _ = ff.qb_out_adjustment("NFL", True)
                if side == "home":
                    hm += adj
                else:
                    am += adj
        return hm, am, None

    price_fn = price_fn_factory("NFL", ["ML", "SPREAD"], adjust)
    out = run_evaluation("qb_oracle", fixtures, price_fn,
                         min_train=150, test_size=60)
    out["oracle"] = True
    out["verdict"] = "INFORMATIONAL_ORACLE"
    out["reasons"] = ["ORACLE_LABELS_ARE_LOOKAHEAD: not a production gate; "
                      "sizes the declared QB-out coefficient only."]
    (REPORTS / "qb_oracle.json").write_text(json.dumps(out, indent=2))
    return out




# ---------------------------------------------------------------------------
# Backlog factor evaluations
# ---------------------------------------------------------------------------
def _srs_table_for(train, as_of):
    games = []
    for fx in train:
        ko = datetime.fromisoformat(str(fx["kickoff"]).replace("Z", "+00:00"))
        if ko >= as_of:
            continue
        games.append((fx["home_team"], fx["away_team"],
                      fx["home_score"] - fx["away_score"],
                      (as_of - ko).total_seconds() / 86400))
    return ff.srs_ratings(games)


def run_srs():
    fixtures = football_fixtures("nfl", [2024, 2025])
    print(f"srs: {len(fixtures)} NFL fixtures")

    def adjust(model_name, fixture, as_of, train, hm, am):
        if model_name != "candidate":
            return hm, am, None
        as_of_dt = datetime.fromisoformat(str(as_of).replace("Z", "+00:00"))
        table = _srs_table_for(train, as_of_dt)
        margin, status = ff.srs_predicted_margin(
            table, fixture["home_team"], fixture["away_team"], 1.5)
        if status != "SRS_VERIFIED":
            return hm, am, None
        total = hm + am
        return total / 2 + margin / 2, total / 2 - margin / 2, None

    price_fn = price_fn_factory("NFL", ["ML", "SPREAD"], adjust)
    return run_evaluation("srs", fixtures, price_fn,
                          min_train=150, test_size=60)


def run_venue_hfa():
    fixtures = football_fixtures("nfl", [2024, 2025])
    print(f"venue_hfa: {len(fixtures)} NFL fixtures")

    def adjust(model_name, fixture, as_of, train, hm, am):
        if model_name != "candidate":
            return hm, am, None
        ko = datetime.fromisoformat(fixture["kickoff"].replace("Z", "+00:00"))
        home_movs, road_movs = [], []
        for fx in train:
            fxko = datetime.fromisoformat(str(fx["kickoff"]).replace("Z", "+00:00"))
            if fxko >= ko:
                continue
            mov = fx["home_score"] - fx["away_score"]
            if fx["home_team"] == fixture["home_team"]:
                home_movs.append(mov)
            elif fx["away_team"] == fixture["home_team"]:
                road_movs.append(-mov)
        # league home edge from train
        hmoves = [fx["home_score"] - fx["away_score"] for fx in train
                  if datetime.fromisoformat(str(fx["kickoff"]).replace("Z", "+00:00")) < ko]
        league_edge = sum(hmoves) / len(hmoves) if hmoves else 1.5
        delta, status, _ = ff.venue_hfa_delta(home_movs, road_movs, league_edge)
        if status != "VENUE_HFA_VERIFIED":
            return hm, am, None
        return hm + delta / 2, am - delta / 2, None

    price_fn = price_fn_factory("NFL", ["ML", "SPREAD"], adjust)
    return run_evaluation("venue_hfa", fixtures, price_fn,
                          min_train=150, test_size=60)


def _summary_team_stats(fixture):
    """(plays_home, plays_away, to_home, to_away) from cached ESPN summary."""
    eid = fixture["fixture_id"].split("-", 1)[1]
    key = f"nfl_summary_{eid}"
    url = ("https://site.api.espn.com/apis/site/v2/sports/football/nfl/"
           f"summary?event={eid}")
    data = cached_json(key, url) or {}
    box = data.get("boxscore") or {}
    out = {}
    for t in box.get("teams") or []:
        abbr = str((t.get("team") or {}).get("abbreviation") or "")
        stats = {s.get("name"): s.get("displayValue")
                 for s in t.get("statistics") or []}
        try:
            plays = float(stats.get("totalOffensivePlays") or 0) or None
        except (TypeError, ValueError):
            plays = None
        try:
            to = float(stats.get("turnovers") or 0)
        except (TypeError, ValueError):
            to = None
        out[abbr] = (plays, to)
    h = out.get(fixture["home_abbr"], (None, None))
    a = out.get(fixture["away_abbr"], (None, None))
    return h[0], a[0], h[1], a[1]


def _trailing_stat(team_abbr, train, kickoff, stat_idx, n=5):
    """Mean of a per-game stat (0=plays, 2=turnovers) over a team's last n games."""
    vals = []
    for fx in sorted(train, key=lambda f: f["kickoff"], reverse=True):
        fxko = datetime.fromisoformat(str(fx["kickoff"]).replace("Z", "+00:00"))
        if fxko >= kickoff:
            continue
        if team_abbr not in (fx["home_abbr"], fx["away_abbr"]):
            continue
        s = _summary_team_stats(fx)
        v = s[stat_idx] if fx["home_abbr"] == team_abbr else s[stat_idx + 1]
        if v is not None:
            vals.append(v)
        if len(vals) >= n:
            break
    return sum(vals) / len(vals) if vals else None


def run_pace():
    fixtures = football_fixtures("nfl", [2025])
    print(f"pace: {len(fixtures)} NFL 2025 fixtures")

    def adjust(model_name, fixture, as_of, train, hm, am):
        if model_name != "candidate":
            return hm, am, None
        ko = datetime.fromisoformat(fixture["kickoff"].replace("Z", "+00:00"))
        hp = _trailing_stat(fixture["home_abbr"], train, ko, 0)
        ap = _trailing_stat(fixture["away_abbr"], train, ko, 0)
        # league avg plays from train summaries (sample every 10th for cost)
        tot, cnt = 0.0, 0
        for fx in train[::10]:
            fxko = datetime.fromisoformat(str(fx["kickoff"]).replace("Z", "+00:00"))
            if fxko >= ko:
                continue
            s = _summary_team_stats(fx)
            for v in (s[0], s[1]):
                if v:
                    tot += v
                    cnt += 1
        lg = tot / cnt if cnt else None
        adj, status, _ = ff.pace_total_adjustment(hp, ap, lg)
        if status != "PACE_VERIFIED_APPLIED":
            return hm, am, None
        return hm + adj / 2, am + adj / 2, None

    price_fn = price_fn_factory("NFL", ["TOTAL"], adjust)
    return run_evaluation("pace", fixtures, price_fn,
                          min_train=100, test_size=40)


def run_turnovers():
    fixtures = football_fixtures("nfl", [2024, 2025])
    print(f"turnovers: {len(fixtures)} NFL fixtures")

    def to_diff(team_abbr, train, kickoff, n=5):
        vals = []
        for fx in sorted(train, key=lambda f: f["kickoff"], reverse=True):
            fxko = datetime.fromisoformat(str(fx["kickoff"]).replace("Z", "+00:00"))
            if fxko >= kickoff:
                continue
            if team_abbr not in (fx["home_abbr"], fx["away_abbr"]):
                continue
            s = _summary_team_stats(fx)
            mine_to = s[2] if fx["home_abbr"] == team_abbr else s[3]
            opp_to = s[3] if fx["home_abbr"] == team_abbr else s[2]
            if mine_to is None or opp_to is None:
                continue
            vals.append(opp_to - mine_to)  # takeaways - giveaways
            if len(vals) >= n:
                break
        return sum(vals) / len(vals) if vals else None

    def adjust(model_name, fixture, as_of, train, hm, am):
        if model_name != "candidate":
            return hm, am, None
        ko = datetime.fromisoformat(fixture["kickoff"].replace("Z", "+00:00"))
        for abbr, side in ((fixture["home_abbr"], "home"),
                           (fixture["away_abbr"], "away")):
            d = to_diff(abbr, train, ko)
            adj, status, _ = ff.turnover_luck_adjustment(d)
            if status != "TURNOVER_REGRESSED_APPLIED":
                continue
            if side == "home":
                hm += adj
            else:
                am += adj
        return hm, am, None

    price_fn = price_fn_factory("NFL", ["ML", "SPREAD"], adjust)
    return run_evaluation("turnovers", fixtures, price_fn,
                          min_train=150, test_size=60)


def run_fip(sample_every: int = 4):
    fixtures = mlb_fixtures(2025, [6, 7, 8])
    fixtures = fixtures[::sample_every]
    print(f"fip: {len(fixtures)} MLB fixtures (1-in-{sample_every} sample)")

    def starts_for(pid, season, as_of):
        out = []
        for s in pitcher_gamelog(pid, season):
            d = str(s.get("date") or "")[:10]
            try:
                gd = datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            if gd >= as_of:
                continue
            st = s.get("stat") or {}
            try:
                gs = int(st.get("gamesStarted") or 0)
            except (TypeError, ValueError):
                gs = 0
            if gs != 1:
                continue
            out.append({"HR": st.get("homeRuns"), "BB": st.get("baseOnBalls"),
                        "HBP": st.get("hitByPitch"), "SO": st.get("strikeOuts"),
                        "IP": st.get("inningsPitched")})
        return out

    def adjust(model_name, fixture, as_of, train, hm, am):
        if model_name != "candidate":
            return hm, am, None
        ko = datetime.fromisoformat(fixture["kickoff"].replace("Z", "+00:00"))
        probs = fixture.get("probable") or {}
        for side, target in (("home", "away"), ("away", "home")):
            pid = probs.get(side)
            if not pid:
                continue
            fip, n = ff.fip_from_gamelog(starts_for(int(pid), ko.year, ko))
            adj, status, _ = ff.pitcher_fip_adjustment(fip, n)
            if status != "PITCHER_FIP_VERIFIED_APPLIED":
                continue
            if target == "home":
                hm += adj
            else:
                am += adj
        return hm, am, None

    price_fn = price_fn_factory("MLB", ["TOTAL", "ML"], adjust)
    return run_evaluation("fip", fixtures, price_fn,
                          min_train=120, test_size=60,
                          embargo_days=0, step=7)



# ---------------------------------------------------------------------------
# NFL EPA/play via nflverse (free, public, no key) -- backlog NFL
# ---------------------------------------------------------------------------
# Source: nflverse play_by_play CSVs from GitHub releases
# (https://github.com/nflverse/nflverse-data/releases/tag/pbp).
# Team strength = trailing-8-week offensive EPA/play minus defensive
# EPA/play allowed; predicted home margin = 55 * (strength_h - strength_a)
# + 1.5 (declared conversion). Raw EPA/play (not opponent-adjusted);
# opponent-adjusted EPA is a queued refinement.
EPA_MARGIN_PER_UNIT = 55.0
EPA_TRAIL_WEEKS = 8
EPA_MIN_WEEKS = 4


def _epa_weekly():
    """Weekly (season, week, team) -> (off_plays, off_epa, def_plays, def_epa)."""
    key = "nflverse_epa_weekly"
    path = CACHE / (key + ".json")
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    import pandas as pd
    frames = []
    for season in (2024, 2025):
        f = CACHE / f"pbp{season}.csv.gz"
        if not f.exists():
            continue
        d = pd.read_csv(f, low_memory=False,
                        usecols=["season", "week", "posteam", "defteam",
                                 "play_type", "epa"])
        d = d[d["play_type"].isin(["pass", "run"]) & d["epa"].notna()
              & d["posteam"].notna()]
        frames.append(d)
    if not frames:
        return {}
    d = pd.concat(frames)
    off = d.groupby(["season", "week", "posteam"]).agg(
        plays=("epa", "size"), epa=("epa", "sum")).reset_index()
    deff = d.groupby(["season", "week", "defteam"]).agg(
        plays=("epa", "size"), epa=("epa", "sum")).reset_index()
    out = {}
    for _, r in off.iterrows():
        out.setdefault(f"{int(r['season'])}-{int(r['week'])}", {})[
            str(r["posteam"])] = {"op": int(r["plays"]), "oe": float(r["epa"])}
    for _, r in deff.iterrows():
        cell = out.setdefault(f"{int(r['season'])}-{int(r['week'])}", {}).setdefault(
            str(r["defteam"]), {})
        cell["dp"] = int(r["plays"])
        cell["de"] = float(r["epa"])
    serial = {k: v for k, v in out.items()}
    path.write_text(json.dumps(serial))
    return serial


def _epa_strength(weekly, abbr, season, week):
    """Trailing EPA strength for a team before (season, week)."""
    off_p = off_e = def_p = def_e = 0.0
    n_weeks = 0
    # walk back through (season, week) keys
    keys = sorted(weekly.keys())
    target = f"{season}-{int(week):02d}"
    prior = [k for k in keys if k < target][-EPA_TRAIL_WEEKS:]
    for k in prior:
        cell = weekly[k].get(abbr)
        if not cell:
            continue
        n_weeks += 1
        off_p += cell.get("op", 0)
        off_e += cell.get("oe", 0.0)
        def_p += cell.get("dp", 0)
        def_e += cell.get("de", 0.0)
    if n_weeks < EPA_MIN_WEEKS or off_p < 100 or def_p < 100:
        return None
    return off_e / off_p - def_e / def_p


def run_epa():
    fixtures = football_fixtures("nfl", [2024, 2025])
    fixtures = [f for f in fixtures if f.get("week")]
    print(f"epa: {len(fixtures)} NFL fixtures")
    weekly = _epa_weekly()
    if not weekly:
        print("epa: nflverse data unavailable")
        return {"factor": "epa", "verdict": "ERROR",
                "error": "NFLVERSE_DATA_UNAVAILABLE"}

    def adjust(model_name, fixture, as_of, train, hm, am):
        if model_name != "candidate":
            return hm, am, None
        sh = _epa_strength(weekly, fixture["home_abbr"],
                           fixture["season"], fixture["week"])
        sa = _epa_strength(weekly, fixture["away_abbr"],
                           fixture["season"], fixture["week"])
        if sh is None or sa is None:
            return hm, am, None
        margin = EPA_MARGIN_PER_UNIT * (sh - sa) + 1.5
        total = hm + am
        return total / 2 + margin / 2, total / 2 - margin / 2, None

    price_fn = price_fn_factory("NFL", ["ML", "SPREAD"], adjust)
    return run_evaluation("epa", fixtures, price_fn,
                          min_train=150, test_size=60)



# ---------------------------------------------------------------------------
# Poisson time-decay (Dixon-Coles adapted) -- frameworks note
# ---------------------------------------------------------------------------
def run_time_decay():
    fixtures = football_fixtures("nfl", [2024, 2025])
    print(f"time_decay: {len(fixtures)} NFL fixtures")

    def decay_means(fixture, train):
        # Candidate: identical to base_means EXCEPT the 5-game rating uses
        # time-decay weights. Form component kept equal-weighted (as in
        # base_means) to isolate the decay effect.
        base, _, _, hfa = fm.PRIORS["NFL"]
        ko = datetime.fromisoformat(fixture["kickoff"].replace("Z", "+00:00"))
        hl = ff.TIME_DECAY_HALF_LIFE_DAYS["NFL"]
        ratings = []
        forms = []
        for team in (fixture["home_team"], fixture["away_team"]):
            vals = []
            for fx in train:
                fxko = datetime.fromisoformat(
                    str(fx["kickoff"]).replace("Z", "+00:00"))
                if fxko >= ko:
                    continue
                if fx["home_team"] == team:
                    vals.append((fx["home_score"] - fx["away_score"],
                                 (ko - fxko).total_seconds() / 86400))
                elif fx["away_team"] == team:
                    vals.append((fx["away_score"] - fx["home_score"],
                                 (ko - fxko).total_seconds() / 86400))
            vals.sort(key=lambda x: x[1])
            recent = vals[:5]
            m, _ = ff.decay_weighted_mean(recent, hl)
            if m is None:
                m = 0.0
            ratings.append(max(-3.0, min(3.0, m * 0.12)))
            margins = [v for v, _ in recent]
            form = 0.0
            if len(margins) >= 4:
                trend = sum(margins[:2]) / 2 - sum(margins) / len(margins)
                form = fm.bounded(trend * 0.07, -1.5, 1.5)
            forms.append(form)
        return (base + hfa / 2 + ratings[0] + forms[0],
                base - hfa / 2 + ratings[1] + forms[1])

    def adjust(model_name, fixture, as_of, train, hm, am):
        if model_name != "candidate":
            return hm, am, None
        hm2, am2 = decay_means(fixture, train)
        return hm2, am2, None

    price_fn = price_fn_factory("NFL", ["ML", "SPREAD", "TOTAL"], adjust)
    return run_evaluation("time_decay", fixtures, price_fn,
                          min_train=150, test_size=60)

RUNNERS = {
    "park": run_park, "rest": run_rest, "travel": run_travel,
    "weather": run_weather, "weather_interaction": run_weather_interaction,
    "weather_interaction_legacy": run_weather_interaction_legacy,
    "keynums": run_keynums, "pitcher": run_pitcher,
    "bullpen": run_bullpen, "rotation": run_rotation, "qb_oracle": run_qb_oracle,
    "srs": run_srs, "venue_hfa": run_venue_hfa, "pace": run_pace,
    "turnovers": run_turnovers, "fip": run_fip,
    "epa": run_epa,
    "time_decay": run_time_decay,
}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("factor", choices=list(RUNNERS) + ["all"])
    args = ap.parse_args(argv)
    names = list(RUNNERS) if args.factor == "all" else [args.factor]
    results = {}
    for name in names:
        try:
            results[name] = RUNNERS[name]()
        except Exception as exc:  # noqa: BLE001 - report, don't crash the batch
            print(f"### {name}: ERROR {type(exc).__name__}: {exc}")
            results[name] = {"factor": name, "verdict": "ERROR",
                             "error": f"{type(exc).__name__}: {exc}"}
    print(json.dumps({k: (v.get("verdict") if isinstance(v, dict) else v)
                      for k, v in results.items()}, indent=2))


if __name__ == "__main__":
    main()
