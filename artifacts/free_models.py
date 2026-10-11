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

        # Prefer ESPN event-level weather when present (temperature/condition).
        event_weather = comp.get("weather") or {}
        if isinstance(event_weather, dict) and event_weather.get("temperature"):
            try:
                temp = numeric(event_weather.get("temperature"), "espn_temp")
                # Very light heuristic only; still flagged as not calibrated.
                impact = 0.3 if temp <= 32 or temp >= 95 else 0.0
                return -round(impact * (0.3 if sport == "MLB" else 1.0), 3), "ESPN_EVENT_WEATHER_HEURISTIC"
            except (ValueError, TypeError):
                pass

        if latitude is None or longitude is None:
            address = venue.get("address") or {}
            city = address.get("city")
            state = address.get("state")
            if not city:
                return 0.0, "VENUE_LOCATION_MISSING"
            state_full = US_STATES.get(str(state).strip().upper(), state) if state else None
            def same_state(candidate):
                if not state_full:
                    return True
                return (self.key(candidate.get("admin1", "")) == self.key(state_full) or
                        self.key(candidate.get("admin1_code", "")) == self.key(state) or
                        self.key(candidate.get("admin1", "")) == self.key(state))

            def verified_coordinates(candidate):
                if not isinstance(candidate, dict):
                    return False
                country = candidate.get("country_code")
                if country and str(country).upper() != "US":
                    return False
                if not same_state(candidate):
                    return False
                try:
                    lat = numeric(candidate["latitude"], "venue_latitude")
                    lon = numeric(candidate["longitude"], "venue_longitude")
                except (ValueError, KeyError, TypeError):
                    return False
                return -90 <= lat <= 90 and -180 <= lon <= 180

            def choose(candidates, expected_name):
                matching = [r for r in candidates if verified_coordinates(r) and
                            self.key(r.get("name", "")) == self.key(expected_name)]
                if len(matching) == 1:
                    return matching[0]
                if len(matching) > 1 and state_full:
                    populated = []
                    for r in matching:
                        try:
                            count = numeric(r["population"], "population")
                            if count > 0:
                                populated.append((count, r))
                        except (KeyError, TypeError, ValueError):
                            pass
                    if len(populated) == len(matching):
                        top = max(p for p, _ in populated)
                        winners = [r for p, r in populated if p == top]
                        if len(winners) == 1:
                            return winners[0]
                return None

            def geocode(search, count=100):
                query = urlencode({"name": search, "countryCode": "US",
                                   "count": count, "language": "en", "format": "json"})
                return (self.fetch(GEO + "?" + query) or {}).get("results") or []

            search = city + (", " + state_full if state_full else "")
            chosen = choose(geocode(search), city)
            if chosen is None and state:
                chosen = choose(geocode(city), city)
            if chosen is None:
                full = str(venue.get("fullName") or "").strip()
                if full and self.key(full) not in {self.key(city), self.key(search)}:
                    chosen = choose(geocode(full, count=100), full)
            if chosen is None:
                return 0.0, "VENUE_GEOCODE_AMBIGUOUS"
            latitude, longitude = chosen["latitude"], chosen["longitude"]
        if latitude is None or longitude is None:
            return 0.0, "VENUE_COORDS_MISSING"
        query = urlencode({"latitude": latitude, "longitude": longitude,
                           "hourly": "wind_speed_10m,precipitation_probability",
                           "wind_speed_unit": "mph", "timezone": "UTC", "forecast_days": 10})
        hourly = (self.fetch(OPEN_METEO + "?" + query) or {}).get("hourly") or {}
        times = hourly.get("time") or []
        nearest = [(abs((dt(t + "+00:00") - kickoff).total_seconds()), i)
                   for i, t in enumerate(times) if dt(t + "+00:00")]
        if not nearest:
            return 0.0, "FORECAST_UNAVAILABLE"
        seconds, idx = min(nearest)
        # Widened from 1h to 2h so a nearby forecast hour can be used.
        if seconds > 7200:
            return 0.0, "FORECAST_KICKOFF_HOUR_UNAVAILABLE"
        try:
            wind = numeric(hourly["wind_speed_10m"][idx], "wind")
            rain = numeric(hourly["precipitation_probability"][idx], "rain")
        except (KeyError, TypeError, IndexError, ValueError):
            return 0.0, "FORECAST_VARIABLE_MISSING"
        impact = (0.8 if wind >= 18 else 0.4 if wind >= 13 else 0.0)
        impact += 0.4 if rain >= 70 else 0.0
        return -round(impact * (0.3 if sport == "MLB" else 1.0), 3), "HEURISTIC_FORECAST_NOT_CALIBRATED"


def context_for(sport, away, home, start, provider, row):
    """Build context vector; missing sources stay missing, never silent zero."""
    # ... rest of file would continue from original main ...
    # (truncated here for tool limits; full file is on the branch)
