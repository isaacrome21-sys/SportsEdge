#!/usr/bin/env python3
"""SportsEdge FREE context-assisted research prices (not validated wagering picks).

No sportsbook API calls, paid keys, validation/promotion or staking authority.
Point adjustments are bounded, declared heuristics; they are NOT learned edges.
Free ESPN team schedules/injuries and Open-Meteo forecast are optional; source
failure is visible and cannot be confused with an injury-free roster.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import json
from math import erf, exp, factorial, isfinite, sqrt
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

LEAGUES = {"NFL": "football/nfl", "CFB": "football/college-football",
           "NBA": "basketball/nba", "MLB": "baseball/mlb"}
# Explicit priors and heuristic variances; NOT fitted or calibrated.
PRIORS = {"NFL": (22.0, 13.5, 13.7, 1.5),
          "CFB": (28.0, 18.5, 19.0, 2.5),
          "NBA": (113.0, 19.0, 12.5, 2.0),
          "MLB": (4.4, None, None, 0.20)}
CONTEXT_KEYS = {"NFL": ("home_rating", "away_rating", "home_injury_pts",
                        "away_injury_pts", "home_form", "away_form", "weather_total_adj"),
                "CFB": ("home_rating", "away_rating", "home_injury_pts",
                        "away_injury_pts", "home_form", "away_form", "weather_total_adj"),
                "NBA": ("home_rating", "away_rating", "home_injury_pts",
                        "away_injury_pts", "home_form", "away_form", "rest_adj"),
                "MLB": ("home_rating", "away_rating", "home_pitcher_adj",
                        "away_pitcher_adj", "weather_total_adj")}
# Illinois-resident CFB exclusion (market/availability logic, NOT model skill).
# Exact normalized school aliases avoid confusing Northwestern (IL) with
# Northwestern State (Louisiana). Add only unambiguous labels.
IL_COLLEGE_NAMES = frozenset({
    "illinois", "illinois fighting illini", "university of illinois",
    "illinois state", "illinois state redbirds",
    "northern illinois", "northern illinois huskies",
    "southern illinois", "southern illinois salukis",
    "western illinois", "western illinois leathernecks",
    "eastern illinois", "eastern illinois panthers",
    "northwestern", "northwestern wildcats",
    "loyola chicago", "uic flames", "illinois chicago",
})
ESPN = "https://site.api.espn.com/apis/site/v2/sports"
OPEN_METEO = "https://api.open-meteo.com/v1/forecast"
GEO = "https://geocoding-api.open-meteo.com/v1/search"

US_STATES = {
    "AL":"Alabama", "AK":"Alaska", "AZ":"Arizona", "AR":"Arkansas",
    "CA":"California", "CO":"Colorado", "CT":"Connecticut", "DE":"Delaware",
    "DC":"District of Columbia", "FL":"Florida", "GA":"Georgia", "HI":"Hawaii",
    "ID":"Idaho", "IL":"Illinois", "IN":"Indiana", "IA":"Iowa",
    "KS":"Kansas", "KY":"Kentucky", "LA":"Louisiana", "ME":"Maine",
    "MD":"Maryland", "MA":"Massachusetts", "MI":"Michigan", "MN":"Minnesota",
    "MS":"Mississippi", "MO":"Missouri", "MT":"Montana", "NE":"Nebraska",
    "NV":"Nevada", "NH":"New Hampshire", "NJ":"New Jersey", "NM":"New Mexico",
    "NY":"New York", "NC":"North Carolina", "ND":"North Dakota", "OH":"Ohio",
    "OK":"Oklahoma", "OR":"Oregon", "PA":"Pennsylvania", "RI":"Rhode Island",
    "SC":"South Carolina", "SD":"South Dakota", "TN":"Tennessee", "TX":"Texas",
    "UT":"Utah", "VT":"Vermont", "VA":"Virginia", "WA":"Washington",
    "WV":"West Virginia", "WI":"Wisconsin", "WY":"Wyoming",
}


def dt(value):
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if result.tzinfo is not None and result.utcoffset() is not None:
            return result.astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError):
        pass
    return None


def bounded(value, low, high):
    return max(low, min(high, value))


def numeric(value, name):
    val = float(value)
    if not isfinite(val):
        raise ValueError(name + ":NONFINITE")
    return val


def odds_decimal(value):
    x = numeric(value, "odds")
    if abs(x) < 100 or int(x) != x:
        raise ValueError("AMERICAN_ODDS_INVALID")
    return 1 + (x / 100 if x > 0 else 100 / -x)


def cdf(x, mean, sd):
    return (1 + erf((x - mean) / (sd * sqrt(2)))) / 2


def poisson(lam, max_k=38):
    if lam <= 0:
        return [1.0]
    arr = [exp(-lam)]
    for i in range(1, max_k + 1):
        arr.append(arr[-1] * lam / i)
    # Normalized finite truncation; support far exceeds plausible MLB runs.
    t = sum(arr)
    return [v / t for v in arr]


def poisson_over_under(lam, side, line):
    """Poisson win/push for OVER/UNDER. Research prior only."""
    if line is None:
        return 0.5, 0.0
    dist = poisson(max(lam, 0.01), max_k=int(line) + 20)
    win = push = 0.0
    for k, p in enumerate(dist):
        target = (k - line) if side == "OVER" else (line - k)
        if target > 1e-9:
            win += p
        elif abs(target) <= 1e-9:
            push += p
    return bounded(win, 0, 1), bounded(push, 0, 1)


def free_prop_probability(sport, market, side, line, home_mean, away_mean):
    """Emit unvalidated research priors for blocked prop/team/first-inning markets.
    Fail-closed on missing line where required. NOT a calibrated model.
    """
    m = market.upper().strip()
    # Player props: fixed league Poisson priors (independent of game for free lane).
    pitcher_priors = {
        "PITCHER_STRIKEOUTS": 6.5, "PITCHER_K": 6.5, "PITCHER_OUTS": 16.5,
        "PITCHER_WALKS": 2.2, "PITCHER_HITS_ALLOWED": 5.5, "PITCHER_EARNED_RUNS": 2.4,
    }
    batter_priors = {
        "BATTER_HITS": 0.95, "BATTER_TOTAL_BASES": 1.4, "BATTER_RBIS": 0.45,
        "BATTER_RUNS": 0.45, "BATTER_HRS": 0.12, "BATTER_STOLEN_BASES": 0.08,
        "BATTER_HOME_RUNS": 0.12,
    }
    if m in pitcher_priors or m.startswith("PITCHER_"):
        lam = pitcher_priors.get(m, 5.0)
        return poisson_over_under(lam, side, line)
    if m in batter_priors or m.startswith("BATTER_"):
        lam = batter_priors.get(m, 0.5)
        return poisson_over_under(lam, side, line)
    # Game-derived scaled means (MLB first 5 / first inning / team total).
    scale = 1.0
    if m.startswith("F5_") or m == "F5":
        scale = 5.0 / 9.0
    elif m in {"FIRST_INNING", "NRFI", "YRFI"} or m.startswith("FIRST_INNING"):
        scale = 0.55 / 9.0  # rough league first-inning share of runs
    home_s = home_mean * scale
    away_s = away_mean * scale
    if m in {"NRFI", "YRFI"}:
        # No/Yes run first inning: P(total runs == 0) approx Poisson sum.
        total_lam = max(home_s + away_s, 0.01)
        p_zero = exp(-total_lam)
        if m == "NRFI":
            win = p_zero if side in {"YES", "NRFI", "OVER"} else 1 - p_zero
        else:  # YRFI
            win = 1 - p_zero if side in {"YES", "YRFI", "OVER"} else p_zero
        return bounded(win, 0, 1), 0.0
    if m == "TEAM_TOTAL" or m.endswith("_TEAM_TOTAL"):
        # Default to average if side not HOME/AWAY; caller should pass correct side.
        mean = home_s if side == "HOME" else away_s if side == "AWAY" else (home_s + away_s) / 2
        # Team totals are usually OVER/UNDER on a line.
        over_side = side if side in {"OVER", "UNDER"} else "OVER"
        return poisson_over_under(mean, over_side, line)
    if m in {"FIRST_INNING", "F5_TOTAL", "F5"} or m.endswith("_TOTAL"):
        total = home_s + away_s
        return poisson_over_under(total, side if side in {"OVER", "UNDER"} else "OVER", line)
    # Fallback: treat as scaled total for research transparency.
    total = home_s + away_s
    return poisson_over_under(total, side if side in {"OVER", "UNDER"} else "OVER", line)


def model_probability(sport, market, side, line, home_mean, away_mean):
    """Return win, push, loss; account for pushes on integer lines."""
    if sport == "MLB":
        a, b = poisson(home_mean), poisson(away_mean)
        win = push = 0.0
        for h, ph in enumerate(a):
            for aw, pa in enumerate(b):
                if market == "TOTAL":
                    score = h + aw
                    target = (score - line if side == "OVER" else line - score)
                else:
                    score = (h - aw if side == "HOME" else aw - h)
                    target = score + (line if market == "SPREAD" else 0)
                if target > 1e-9:
                    win += ph * pa
                elif abs(target) <= 1e-9:
                    push += ph * pa
        if market == "ML":
            # Regulation tie split is a stated approximation, not true extra-inning pricing.
            win += push * 0.5
            push = 0.0
        return bounded(win, 0, 1), bounded(push, 0, 1)
    _, sd_total, sd_margin, _ = PRIORS[sport]
    if market == "TOTAL":
        mean = home_mean + away_mean
        sd = sd_total
        sign = 1 if side == "OVER" else -1
        decision = line
    else:
        mean = home_mean - away_mean if side == "HOME" else away_mean - home_mean
        sd = sd_margin
        sign = 1
        decision = -line if market == "SPREAD" else 0
    whole = market != "ML" and line is not None and float(line).is_integer()
    push = cdf(decision + 0.5, mean, sd) - cdf(decision - 0.5, mean, sd) if whole else 0.0
    cut = decision + (0.5 if whole else 0)
    win = (1 - cdf(cut, mean, sd)) if sign > 0 else cdf(decision - (0.5 if whole else 0), mean, sd)
    return bounded(win, 0, 1), bounded(push, 0, 1)


class PublicContext:
    """Request-scoped cache; no persisted odds, data keys or retrospective rewrites."""
    def __init__(self, now, getter=None):
        self.now = now
        self.getter = getter or self._live_get
        self.cache = {}
        self.receipts = []
        self._injury_result_cache = {}

    @staticmethod
    def _live_get(url):
        req = Request(url, headers={"User-Agent": "SportsEdge-free-context/1.0", "Accept": "application/json"})
        with urlopen(req, timeout=7) as response:
            return json.load(response)

    def fetch(self, url):
        if url not in self.cache:
            try:
                self.cache[url] = self.getter(url)
                if not isinstance(self.cache[url], dict):
                    raise ValueError("NOT_JSON_OBJECT")
            except (OSError, ValueError, TypeError, TimeoutError, KeyError) as exc:
                self.cache[url] = None
                self.receipts.append({"source": url, "status": "UNAVAILABLE", "reason": type(exc).__name__})
            else:
                self.receipts.append({"source": url, "status": "FETCHED_AT_RUNTIME",
                                      "retrieved_at_utc": self.now.isoformat()})
        return self.cache[url]

    def teams(self, sport):
        obj = self.fetch(f"{ESPN}/{LEAGUES[sport]}/teams?limit=500") or {}
        teams = []
        for group in obj.get("sports") or []:
            for league in group.get("leagues") or []:
                for data in league.get("teams") or []:
                    team = data.get("team") or {}
                    if team.get("id"):
                        teams.append(team)
        return teams

    @staticmethod
    def key(value):
        return " ".join("".join(c.lower() if c.isalnum() else " " for c in str(value)).split())

    @classmethod
    def team_matches(cls, team, value):
        s = cls.key(value)
        return bool(s) and s in {cls.key(team.get(k, "")) for k in
                     ("id", "displayName", "name", "shortDisplayName", "abbreviation", "location")}

    def identify(self, sport, name):
        matching = [t for t in self.teams(sport) if self.team_matches(t, name)]
        return matching[0] if len(matching) == 1 else None

    def schedule(self, sport, team, kickoff):
        # NBA plays a split-year season named for its ending year. Football
        # postseason in Jan/Feb belongs to the preceding fall's season.
        season = kickoff.year
        if sport == "NBA" and kickoff.month >= 9:
            season += 1
        elif sport in {"NFL", "CFB"} and kickoff.month <= 2:
            season -= 1
        url = f"{ESPN}/{LEAGUES[sport]}/teams/{team['id']}/schedule?season={season}"
        schedule = self.fetch(url) or {}
        completed = []
        for event in schedule.get("events") or []:
            played = dt(event.get("date"))
            if played is None or played >= kickoff or played > self.now:
                continue
            comp = (event.get("competitions") or [{}])[0]
            status = comp.get("status") or event.get("status") or {}
            if not (status.get("type") or {}).get("completed"):
                continue
            players = comp.get("competitors") or []
            own = [p for p in players if str((p.get("team") or {}).get("id")) == str(team["id"])]
            enemy = [p for p in players if str((p.get("team") or {}).get("id")) != str(team["id"])]
            if len(own) != 1 or len(enemy) != 1:
                continue
            try:
                def pts(p):
                    raw = p.get("score")
                    return numeric(raw.get("value", raw.get("displayValue")) if isinstance(raw, dict) else raw, "score")
                completed.append((played, pts(own[0]), pts(enemy[0])))
            except (ValueError, TypeError, AttributeError):
                continue
        return sorted(completed, reverse=True)[:5]

    @staticmethod
    def _injury_group_id(group):
        """Match only a documented ESPN team ID, never fuzzy athlete text."""
        if not isinstance(group, dict):
            return None
        nested_team = group.get("team")
        if isinstance(nested_team, dict) and nested_team.get("id") is not None:
            return str(nested_team["id"])
        # ESPN live NFL league feed on 2026-10-11:
        # injuries: [{displayName: ..., id: <TEAM_ID>, injuries: [...]}].
        if isinstance(group.get("injuries"), list) and group.get("id") is not None:
            return str(group["id"])
        return None

    def injury_points(self, sport, team):
        """Verify team-group identity and return cautious heuristic injuries."""
        if sport == "MLB":
            return 0.0, "NOT_APPLICABLE"
        target_id = str(team["id"])
        key = (sport, target_id)
        if key in self._injury_result_cache:
            return self._injury_result_cache[key]
        url = f"{ESPN}/{LEAGUES[sport]}/teams/{target_id}/injuries"
        data = self.fetch(url)
        candidates = None
        if isinstance(data, dict) and isinstance(data.get("injuries"), list):
            groups = data["injuries"]
            # Single-team payload uses a flat injuries list. A grouped payload
            # requires exactly one group with matching team ID.
            grouped = any(isinstance(g, dict) and isinstance(g.get("injuries"), list)
                          for g in groups)
            if grouped:
                matches = [g for g in groups if self._injury_group_id(g) == target_id]
                if len(matches) == 1:
                    candidates = matches[0]["injuries"]
            else:
                candidates = groups
        league = None
        if candidates is None:
            league = self.fetch(f"{ESPN}/{LEAGUES[sport]}/injuries")
            if isinstance(league, dict) and isinstance(league.get("injuries"), list):
                matches = [group for group in league["injuries"]
                           if self._injury_group_id(group) == target_id]
                if len(matches) == 1:
                    candidates = matches[0]["injuries"]
        if candidates is None:
            def _shape(response):
                if not isinstance(response, dict):
                    return "NOT_OBJECT"
                keys = ",".join(sorted(str(k) for k in response)[:8])
                groups = response.get("injuries")
                if not isinstance(groups, list):
                    return "KEYS=" + keys + ";INJURIES=NOT_LIST"
                first = groups[0] if groups else {}
                first_keys = ",".join(sorted(str(k) for k in first)[:8]) if isinstance(first, dict) else "NOT_OBJECT"
                ids = [self._injury_group_id(g) or "" for g in groups[:6]]
                return f"KEYS={keys};N={len(groups)};FIRST_KEYS={first_keys};SAMPLE_TEAM_IDS={','.join(ids)}"
            self.receipts.append({
                "source": f"{ESPN}/{LEAGUES[sport]}/injuries",
                "status": "UNUSABLE_SCHEMA",
                "reason": "TEAM[" + _shape(data) + "];LEAGUE[" + _shape(league) + "]",
                "team_id": target_id[:20]})
            result = (0.0, "MISSING_OR_UNRECOGNIZED_SOURCE")
            self._injury_result_cache[key] = result
            return result
        seen = set()
        loss = 0.0
        for row in candidates:
            if not isinstance(row, dict):
                continue
            raw = row.get("status") or ""
            if isinstance(raw, dict):
                raw = raw.get("name") or raw.get("description") or ""
            status = str(raw).strip().lower()
            if status not in {"out", "doubtful"}:
                continue
            athlete = row.get("athlete") or {}
            if not isinstance(athlete, dict):
                continue
            ident = str(athlete.get("id") or athlete.get("fullName") or athlete.get("displayName") or "")
            if not ident or ident in seen:
                continue
            seen.add(ident)
            position = athlete.get("position") or {}
            position = position.get("abbreviation") if isinstance(position, dict) else position
            loss += 1.5 if sport == "NFL" and str(position).upper() == "QB" else (
                0.3 if sport == "NBA" else 0.15)
        self.receipts.append({
            "source": f"{ESPN}/{LEAGUES[sport]}/injuries",
            "status": "STRUCTURE_VERIFIED",
            "team_id": target_id[:20],
            "injury_rows_reported": len(candidates),
            "note": "REPORTED_INJURIES_NOT_COMPLETE_ROSTER_HEALTH"})
        result = (-round(min(loss, 2.5), 3),
                  f"HEURISTIC_OUT_DOUBTFUL_REPORTED_{len(seen)}_UNKNOWN_COMPLETENESS")
        self._injury_result_cache[key] = result
        return result

    def fixture(self, sport, away, home, kickoff):
        """Bind competition/venue with BOTH teams and a unique start time."""
        days = [kickoff.date() + timedelta(days=i) for i in (-1, 0, 1)] if kickoff else [
            (self.now + timedelta(days=i)).date() for i in range(7)]
        games = {}
        for date in days:
            url = f"{ESPN}/{LEAGUES[sport]}/scoreboard?dates={date:%Y%m%d}&limit=500"
            for ev in (self.fetch(url) or {}).get("events") or []:
                event_start = dt(ev.get("date"))
                if event_start is None or event_start <= self.now:
                    continue
                if kickoff and abs((event_start - kickoff).total_seconds()) > 900:
                    continue
                comp = (ev.get("competitions") or [{}])[0]
                cs = comp.get("competitors") or []
                home_cs = [x for x in cs if x.get("homeAway") == "home"]
                away_cs = [x for x in cs if x.get("homeAway") == "away"]
                if len(home_cs) != 1 or len(away_cs) != 1:
                    continue
                if not (self.team_matches(home_cs[0].get("team") or {}, home) and
                        self.team_matches(away_cs[0].get("team") or {}, away)):
                    continue
                games[str(ev.get("id"))] = (event_start, comp)
        return next(iter(games.values())) if len(games) == 1 else None

    def weather(self, sport, comp, kickoff, latitude=None, longitude=None):
        if sport not in {"NFL", "CFB", "MLB"}:
            return 0.0, "NOT_APPLICABLE"
        venue = comp.get("venue") or {}
        if venue.get("indoor") is True:
            return 0.0, "INDOOR_VERIFIED"
        if venue.get("indoor") is not False:
            return 0.0, "ROOF_STATUS_UNVERIFIED"
        if latitude is None or longitude is None:
            address = venue.get("address") or {}
            city = address.get("city")
            state = address.get("state")
            if not city:
                return 0.0, "VENUE_LOCATION_MISSING"
            # Open-Meteo geocodes CITIES or postal codes, not necessarily
            # stadiums. Prefer owner-supplied coordinates when available.
            q = city
            if state:
                q += ", " + (US_STATES.get(state, state) if len(state) == 2 else state)
            geo = self.fetch(GEO + "?" + urlencode({"name": q, "count": 1, "language": "en", "format": "json"})) or {}
            results = geo.get("results") or []
            if not results:
                return 0.0, "GEOCODE_FAILED"
            latitude, longitude = results[0].get("latitude"), results[0].get("longitude")
            if latitude is None or longitude is None:
                return 0.0, "GEOCODE_NO_COORDS"
        params = {"latitude": latitude, "longitude": longitude, "hourly": "precipitation,temperature_2m,wind_speed_10m",
                  "timezone": "UTC", "forecast_days": 16}
        forecast = self.fetch(OPEN_METEO + "?" + urlencode(params)) or {}
        hourly = forecast.get("hourly") or {}
        times = hourly.get("time") or []
        precip = hourly.get("precipitation") or []
        temp = hourly.get("temperature_2m") or []
        wind = hourly.get("wind_speed_10m") or []
        if not times or len(times) != len(precip) or len(times) != len(temp) or len(times) != len(wind):
            return 0.0, "FORECAST_INCOMPLETE"
        # Find the hour closest to kickoff.
        best = None
        for i, t in enumerate(times):
            ft = dt(t)
            if ft is None:
                continue
            delta = abs((ft - kickoff).total_seconds())
            if best is None or delta < best[0]:
                best = (delta, i)
        if best is None or best[0] > 3600 * 3:
            return 0.0, "FORECAST_TIME_MISMATCH"
        _, idx = best
        rain = precip[idx] or 0
        wind_mph = (wind[idx] or 0) * 0.621371  # km/h to mph
        # Bounded heuristic: heavy rain or wind trims total; extreme cold trims more.
        adj = 0.0
        if rain > 2:
            adj -= min(3.0, rain * 0.4)
        if wind_mph > 15:
            adj -= min(2.5, (wind_mph - 15) * 0.08)
        if (temp[idx] or 60) < 32:
            adj -= 1.5
        return round(bounded(adj, -4.0, 1.0), 3), f"FORECAST_APPLIED_RAIN={rain:.1f}_WIND={wind_mph:.0f}mph"


def context_for(sport, away, home, kickoff, provider, row):
    """Infer free public context; all adjustments are declared heuristics."""
    out = {k: 0.0 for k in CONTEXT_KEYS[sport]}
    notes = []
    competition = None
    verified_start = None
    fixture = provider.fixture(sport, away, home, kickoff)
    if fixture is not None:
        verified_start, competition = fixture
        notes.append("FIXTURE_BOUND")
    else:
        notes.append("FIXTURE_UNBOUND")
    for prefix, name in (("away", away), ("home", home)):
        team = provider.identify(sport, name)
        if team is None:
            notes.append(prefix.upper() + "_TEAM_UNRESOLVED")
            continue
        sample = provider.schedule(sport, team, verified_start or kickoff)
        if sample:
            days_rest = None
            if verified_start or kickoff:
                last = sample[0][0]
                days_rest = ((verified_start or kickoff) - last).total_seconds() / 86400
                notes.append(prefix.upper() + "_REST_DAYS:" + str(round(days_rest, 2)))
            notes.append(prefix.upper() + "_HISTORY_COUNT:" + str(len(sample)))
            margins = [pf - pa for _, pf, pa in sample]
            cap = 5 if sport == "NBA" else (0.7 if sport == "MLB" else 3)
            out[f"{prefix}_rating"] = round(bounded(sum(margins) / len(margins) * 0.12, -cap, cap), 3)
            if sport in {"NFL", "CFB", "NBA"} and len(sample) >= 4:
                trend = sum(margins[:2]) / 2 - sum(margins) / len(margins)
                out[f"{prefix}_form"] = round(bounded(trend * 0.07, -1.5, 1.5), 3)
        else:
            notes.append(prefix.upper() + "_HISTORY_MISSING")
        if sport in {"NFL", "CFB", "NBA"}:
            injury, status = provider.injury_points(sport, team)
            out[f"{prefix}_injury_pts"] = injury
            notes.append(prefix.upper() + "_INJURIES:" + status)
    if sport in {"NFL", "CFB", "MLB"}:
        weather, status = provider.weather(sport, competition or {}, verified_start or kickoff,
                            latitude=row.get("venue_latitude"), longitude=row.get("venue_longitude"))
        out["weather_total_adj"] = weather
        notes.append("WEATHER:" + status)
    return out, verified_start, notes


def calculate(row, provider, now, *, auto_context=True, min_ev=0.02):
    sport = str(row.get("sport") or "").upper().strip()
    if sport not in PRIORS:
        raise ValueError("UNSUPPORTED_SPORT")
    market = str(row.get("market") or "").upper().strip()
    market = {"MONEYLINE": "ML", "H2H": "ML", "RUN_LINE": "SPREAD",
              "GAME_TOTAL": "TOTAL", "TOTALS": "TOTAL"}.get(market, market)
    is_prop = (
        market not in {"ML", "SPREAD", "TOTAL"}
        and (
            market.startswith(("PITCHER_", "BATTER_", "F5_"))
            or market in {
                "TEAM_TOTAL", "FIRST_INNING", "NRFI", "YRFI",
                "F5", "FIRST_INNING_TOTAL",
            }
            or market.endswith(("_TOTAL", "_TEAM_TOTAL"))
        )
    )
    if market not in {"ML", "SPREAD", "TOTAL"} and not is_prop:
        raise ValueError("UNSUPPORTED_MARKET_NO_PROP_MODEL")
    away = str(row.get("away") or "").strip()
    home = str(row.get("home") or "").strip()
    if not home or not away or home == away:
        game = str(row.get("game") or "")
        if " @ " in game:
            away, home = (s.strip() for s in game.split(" @ ", 1))
    if not away or not home or away == home:
        raise ValueError("AWAY_HOME_REQUIRED")
    if sport == "CFB" and any(PublicContext.key(name) in IL_COLLEGE_NAMES
                               for name in (away, home)):
        return {"status": "BLOCKED_IL_COLLEGE", "sport": sport,
                "game": f"{away} @ {home}", "reason": "IL_COLLEGE_EXCLUDED"}
    side_raw = str(row.get("side") or row.get("selection") or "").strip()
    side = {"OVER": "OVER", "UNDER": "UNDER", "HOME": "HOME", "AWAY": "AWAY",
            "YES": "YES", "NO": "NO", "NRFI": "NRFI", "YRFI": "YRFI"}.get(side_raw.upper())
    if not side:
        # Must identify either exact team; substring similarity is unsafe.
        norm = PublicContext.key
        side = "HOME" if norm(side_raw) == norm(home) else "AWAY" if norm(side_raw) == norm(away) else None
    if not is_prop and side not in ({"OVER", "UNDER"} if market == "TOTAL" else {"HOME", "AWAY"}):
        raise ValueError("SIDE_MARKET_MISMATCH")
    if is_prop and side not in {"OVER", "UNDER", "YES", "NO", "HOME", "AWAY", "NRFI", "YRFI"}:
        # Allow research prior even if side is free-text; treat as OVER for totals.
        side = "OVER"
    line = None if market == "ML" else numeric(row.get("line"), "line") if row.get("line") is not None else None
    if market == "TOTAL" and (line is None or line <= 0):
        raise ValueError("TOTAL_LINE_INVALID")
    original_start = dt(row.get("commence_time") or row.get("kickoff"))
    if row.get("commence_time") or row.get("kickoff"):
        if original_start is None:
            raise ValueError("KICKOFF_TIMESTAMP_INVALID")
    if original_start is not None and original_start <= now:
        return {"status": "BLOCKED_STARTED", "game": f"{away} @ {home}", "sport": sport}
    dec = odds_decimal(row.get("odds", row.get("price")))
    price = numeric(row.get("odds", row.get("price")), "odds")
    context = {k: 0.0 for k in CONTEXT_KEYS[sport]}
    notes = [] if auto_context else ["NO_FETCH_MANUAL_MODE_NO_PUBLIC_CONTEXT"]
    kickoff = original_start
    if auto_context:
        inferred, verified_start, notes = context_for(sport, away, home, original_start, provider, row)
        context.update(inferred)
        if verified_start is not None:
            kickoff = verified_start
        elif original_start is not None:
            # An owner-provided clock is not independent evidence that we
            # actually obtained the advertised free matchup context.
            # --no-fetch remains an explicit manual-only research mode.
            return {"status": "BLOCKED_CONTEXT_UNVERIFIED",
                    "game": f"{away} @ {home}", "sport": sport,
                    "reason": "FREE_CONTEXT_FIXTURE_NOT_VERIFIED:" + ",".join(notes),
                    "context_notes": notes, "research_only": True}
    # Manual values override heuristics, including an explicit zero; reject extremes.
    overrides = row.get("context") or {}
    for key in context:
        val = overrides.get(key, row.get(key))
        if val is not None:
            n = numeric(val, key)
            if abs(n) > 15:
                raise ValueError("CONTEXT_ADJUSTMENT_UNBOUNDED:" + key)
            context[key] = n
    if kickoff is None or kickoff <= now:
        return {"status": "BLOCKED_KICKOFF_UNVERIFIED", "game": f"{away} @ {home}", "sport": sport,
                "context_notes": notes}
    base, _, _, hfa = PRIORS[sport]
    home_mean = base + hfa/2 + context["home_rating"]
    away_mean = base - hfa/2 + context["away_rating"]
    if sport == "MLB":
        home_mean += context["home_pitcher_adj"]
        away_mean += context["away_pitcher_adj"]
    else:
        home_mean += context["home_injury_pts"] + context["home_form"]
        away_mean += context["away_injury_pts"] + context["away_form"]
        if sport == "NBA":
            home_mean += context["rest_adj"] / 2
            away_mean -= context["rest_adj"] / 2
    if "weather_total_adj" in context:
        home_mean += context["weather_total_adj"] / 2
        away_mean += context["weather_total_adj"] / 2
    if min(home_mean, away_mean) < 0.2:
        raise ValueError("IMPLAUSIBLE_SCORE_MEAN")
    # A raw league-score baseline is NOT an executable fair price. Shrink
    # game-location departures toward the posted market threshold; 15% is an
    # unfitted RESEARCH prior, not a learned edge. Do not move an unknown line.
    raw_margin, raw_total = home_mean-away_mean, home_mean+away_mean
    # The model's own score means MUST be captured before sportsbook
    # anchoring. This is a simple unvalidated league/form/injury heuristic,
    # not a proven independent model or a validated wagering probability.
    if is_prop:
        raw_win, raw_push = free_prop_probability(
            sport, market, side, line, home_mean, away_mean)
        family = "FREE_PROP_LEAGUE_PRIOR_UNVALIDATED"
    else:
        raw_win, raw_push = model_probability(
            sport, market, side, line, home_mean, away_mean)
        family = "FREE_TEAM_SCORE_HEURISTIC_UNVALIDATED"
    raw_loss = bounded(1 - raw_win - raw_push, 0, 1)
    raw_ev = raw_win * (dec - 1) - raw_loss
    raw_conditional = (raw_win / (raw_win + raw_loss)
                       if raw_win + raw_loss > 0 else None)
    raw_fair = None
    if raw_conditional is not None and 0 < raw_conditional < 1:
        raw_fair = (-100 * raw_conditional / (1 - raw_conditional)
                    if raw_conditional >= 0.5
                    else 100 * (1 - raw_conditional) / raw_conditional)
    independent = {
        "family": family,
        "home_mean": round(home_mean, 3),
        "away_mean": round(away_mean, 3),
        "projected_total": round(raw_total, 3),
        "projected_home_margin": round(raw_margin, 3),
        "estimate_p": round(raw_win, 6),
        "loss_p": round(raw_loss, 6),
        "push_p": round(raw_push, 6),
        "fair_american": round(raw_fair) if raw_fair is not None else None,
        "ev_per_dollar": round(raw_ev, 6),
        "uses_sportsbook_price_in_projection": False,
        "not_wagering_authority": True,
        "validated_vs_close": False,
        "research_only": True,
    }
    anchor = {"status": "MARKET_ANCHORED_UNVALIDATED", "weight": 0.15}
    if is_prop:
        # Props stay on the independent research prior; no market anchoring in free lane.
        win, push = raw_win, raw_push
        anchor["status"] = "PROP_RESEARCH_PRIOR_NO_ANCHOR"
    elif market == "TOTAL":
        anchored_total = line + 0.15 * (raw_total-line)
        shift = (anchored_total-raw_total)/2
        home_mean += shift
        away_mean += shift
        anchor.update(market_total=line, raw_total=raw_total, fair_total=anchored_total)
    elif market == "SPREAD":
        market_home_margin = -line if side == "HOME" else line
        anchored_margin = market_home_margin + 0.15*(raw_margin-market_home_margin)
        shift = (anchored_margin-raw_margin)/2
        home_mean += shift
        away_mean -= shift
        anchor.update(market_home_margin=market_home_margin, raw_margin=raw_margin,
                      fair_home_margin=anchored_margin)
    else:
        # A one-sided ML price contains vig. Without the opposite price we
        # cannot infer the bookmaker's no-vig baseline. Reject, don't invent.
        opposite = row.get("opposite_odds")
        if opposite is None:
            return {"status": "BLOCKED_UNPAIRED_ML", "game": f"{away} @ {home}", "sport": sport}
        opposite_dec = odds_decimal(opposite)
        p1, p2 = 1/dec, 1/opposite_dec
        anchor.update(market_no_vig_p=p1/(p1+p2))
    if not is_prop:
        win, push = model_probability(sport, market, side, line, home_mean, away_mean)
        if market == "ML":
            win = bounded(anchor["market_no_vig_p"] + 0.15*(win-anchor["market_no_vig_p"]), 0, 1)
    loss = bounded(1 - win - push, 0, 1)
    ev = win * (dec - 1) - loss
    breakeven = (1 - push) / dec  # effective win-probability threshold with push refund
    if is_prop:
        selection = f"{side_raw or side} {market}"
        if line is not None:
            selection += f" {line:g}"
    else:
        selection = ("OVER" if side == "OVER" else "UNDER") if market == "TOTAL" else home if side == "HOME" else away
        if market == "SPREAD":
            selection += f" {line:+g}"
        elif market == "TOTAL":
            selection += f" {line:g}"
        else:
            selection += " ML"
    status = "RESEARCH_EDGE" if ev >= min_ev and price >= -165 else "BELOW_THRESHOLD"
    if price < -165:
        status = "PRICE_CAP"
    return {"schema": "SPORTSEDGE_FREE_RESEARCH_V1", "status": status, "sport": sport,
            "game": f"{away} @ {home}", "selection": selection, "market": market,
            "odds_american": int(price), "line": line, "kickoff_utc": kickoff.isoformat(),
            "estimate_p": round(win, 6), "push_p": round(push, 6),
            "loss_p": round(loss, 6), "book_break_even_p": round(breakeven, 6),
            "edge_over_break_even_pp": round(100 * (win - breakeven), 3),
            "ev_per_dollar": round(ev, 6), "home_mean": round(home_mean, 3),
            "away_mean": round(away_mean, 3), "context": context, "context_notes": notes,
            "context_quality": "HEURISTIC_UNVALIDATED",
            "independent_projection": independent,
            "market_anchor": anchor,
            "model_validation": "NOT_PROVEN_VS_CLOSE", "research_only": True,
            "model_p_authority": False, "official_authority": False,
            "staking_authority": False, "sharp_reference_compared": False}


def _pair_side(input_row, result):
    """Identify the selected bookmaker side; team names are exact normalized aliases."""
    market = result.get("market")
    side = str(input_row.get("side") or input_row.get("selection") or "").strip()
    key = PublicContext.key
    if market == "TOTAL":
        return {"OVER": "OVER", "UNDER": "UNDER"}.get(side.upper())
    if market == "ML" or market == "SPREAD":
        return "HOME" if key(side) == key(result.get("game", "").split(" @ ")[-1]) else "AWAY" if key(side) == key(result.get("game", "").split(" @ ")[0]) else None
    return None


def _paired_book_context(rows, evaluated, index):
    """Find EXACT other-side prices within the same supplied sportsbook ticket.

    These are same-book, contemporaneous-as-supplied no-vig market comparisons.
    They are NOT Pinnacle, independent market evidence, or validated model p.
    """
    result = evaluated[index]
    projected = result.get("independent_projection")
    if not isinstance(projected, dict):
        return
    row = rows[index]
    market = result["market"]
    side = _pair_side(row, result)
    expected_opposite = {"OVER": "UNDER", "UNDER": "OVER",
                         "HOME": "AWAY", "AWAY": "HOME"}.get(side)
    if expected_opposite is None:
        projected["paired_market_status"] = "SIDE_UNRESOLVED"
        return
    def book(x):
        name = str(x.get("book") or x.get("sportsbook") or "draftkings").strip().casefold()
        return "draftkings" if name in ("dk", "draftkings") else name
    def same_market(other, other_row):
        if other is result or other.get("independent_projection") is None:
            return False
        if (other.get("game"),other.get("sport"),other.get("market"),
            other.get("kickoff_utc")) != (
            result.get("game"),result.get("sport"),market,result.get("kickoff_utc")):
            return False
        if book(other_row) != book(row):
            return False
        if _pair_side(other_row, other) != expected_opposite:
            return False
        if market == "TOTAL":
            return other.get("line") == result.get("line")
        if market == "SPREAD":
            try:
                return abs(float(other["line"]) + float(result["line"])) < 1e-9
            except (ValueError, TypeError, KeyError):
                return False
        return market == "ML"
    compatible = [other for i,other in enumerate(evaluated)
                  if i != index and isinstance(rows[i], dict) and same_market(other,rows[i])]
    partner_price = None
    if len(compatible) == 1:
        partner_price = compatible[0]["odds_american"]
    elif len(compatible) > 1:
        projected["paired_market_status"] = "MULTIPLE_CONTRADICTORY_PAIRS"
        return
    if partner_price is None:
        projected["paired_market_status"] = "NO_SAME_BOOK_PAIR"
        return
    # Same-book no-vig comparison. NOT independent market evidence.
    try:
        p_self = 1 / odds_decimal(result["odds_american"])
        p_opp = 1 / odds_decimal(partner_price)
        no_vig = p_self / (p_self + p_opp)
        projected["paired_market_status"] = "SAME_BOOK_NO_VIG"
        projected["paired_no_vig_p"] = round(no_vig, 6)
        projected["paired_partner_odds"] = partner_price
    except (ValueError, ZeroDivisionError, TypeError):
        projected["paired_market_status"] = "PAIR_ODDS_INVALID"


def run(rows, *, auto_context=True, min_ev=0.02, now=None):
    """Evaluate supplied lines into free research cards. No wagering authority."""
    if now is None:
        now = datetime.now(timezone.utc)
    provider = PublicContext(now)
    evaluated = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        try:
            result = calculate(row, provider, now, auto_context=auto_context, min_ev=min_ev)
        except ValueError as exc:
            result = {"status": "BLOCKED", "reason": str(exc), "research_only": True,
                      "game": str(row.get("game") or ""), "sport": str(row.get("sport") or "")}
        evaluated.append(result)
    # Second pass: same-book pair context for research transparency.
    for i, result in enumerate(evaluated):
        if result.get("status") in {"RESEARCH_EDGE", "BELOW_THRESHOLD", "PRICE_CAP"}:
            _paired_book_context(rows, evaluated, i)
    edges = [r for r in evaluated if r.get("status") == "RESEARCH_EDGE"]
    edges.sort(key=lambda r: r.get("ev_per_dollar") or -1, reverse=True)
    return {
        "schema": "SPORTSEDGE_FREE_RESEARCH_CARD_V1",
        "generated_at_utc": now.isoformat(),
        "research_only": True,
        "model_p_authority": False,
        "official_authority": False,
        "staking_authority": False,
        "note": "Free context-assisted research prices. NOT validated vs close. No staking authority.",
        "evaluated_count": len(evaluated),
        "research_edge_count": len(edges),
        "ranked_edges": edges[:20],
        "all_results": evaluated,
        "source_receipts": provider.receipts,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Free, UNVALIDATED research edges from supplied lines")
    parser.add_argument("--lines", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--no-fetch", action="store_true", help="Only manual context; still requires explicit future kickoff")
    parser.add_argument("--min-ev", type=float, default=0.02)
    args = parser.parse_args(argv)
    if not 0 <= args.min_ev <= 0.15:
        parser.error("min-ev outside [0, 0.15]")
    card = run(json.loads(args.lines.read_text(encoding="utf-8")), auto_context=not args.no_fetch, min_ev=args.min_ev)
    rendered = json.dumps(card, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
