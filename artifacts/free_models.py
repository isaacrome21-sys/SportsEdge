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
        if latitude is None or longitude is None:
            address = venue.get("address") or {}
            city = address.get("city")
            state = address.get("state")
            if not city:
                return 0.0, "VENUE_LOCATION_MISSING"
            # Open-Meteo geocodes CITIES or postal codes, not necessarily
            # stadium names. Always bind candidates back to ESPN's venue
            # city/state before accepting a forecast location. ESPN may use
            # 'AZ' while the geocoder returns 'Arizona'.
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
                    # Population breaks exact-city AND exact-state ties only.
                    # Missing or tied populations remain ambiguous.
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
                # Retry less restrictive city-only search but still require
                # exact ESPN state and US jurisdiction for every candidate.
                chosen = choose(geocode(city), city)
            if chosen is None:
                # A stadium name is not generally a valid city geocode query.
                # Accept this fallback ONLY for an exact venue name with a
                # state match, never by an unrelated city's prefix.
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
        if seconds > 3600:
            return 0.0, "FORECAST_KICKOFF_HOUR_UNAVAILABLE"
        try:
            wind = numeric(hourly["wind_speed_10m"][idx], "wind")
            rain = numeric(hourly["precipitation_probability"][idx], "rain")
        except (KeyError, TypeError, IndexError, ValueError):
            return 0.0, "FORECAST_VARIABLE_MISSING"
        # Deliberately small unvalidated weather prior, no claim of profit.
        impact = (0.8 if wind >= 18 else 0.4 if wind >= 13 else 0.0)
        impact += 0.4 if rain >= 70 else 0.0
        return -round(impact * (0.3 if sport == "MLB" else 1.0), 3), "HEURISTIC_FORECAST_NOT_CALIBRATED"


def context_for(sport, away, home, start, provider, row):
    out = {k: 0.0 for k in CONTEXT_KEYS[sport]}
    notes = []
    # Never fetch retrospective context without a verifiable future event.
    fixture = provider.fixture(sport, away, home, start)
    if fixture is None:
        notes.append("UNIQUE_FUTURE_ESPN_FIXTURE_MISSING")
        return out, None, notes
    kickoff, competition = fixture
    for prefix, name in (("home", home), ("away", away)):
        team = provider.identify(sport, name)
        if team is None:
            notes.append(prefix.upper() + "_TEAM_IDENTITY_UNMATCHED")
            continue
        sample = provider.schedule(sport, team, kickoff)
        if sample:
            days_rest = (kickoff - sample[0][0]).total_seconds() / 86400
            if 0 < days_rest < 40:
                # Context only until a rest coefficient is trained vs closes.
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
        weather, status = provider.weather(sport, competition, kickoff,
                            latitude=row.get("venue_latitude"), longitude=row.get("venue_longitude"))
        out["weather_total_adj"] = weather
        notes.append("WEATHER:" + status)
    return out, kickoff, notes


def score_means(sport, context):
    """Pregame expected scores from verified context.

    Single source of truth for the pregame score means, shared by
    ``calculate()`` and the live in-game repricing path
    (``sportsedge.live_reprice``), which reconstructs these means as of
    kickoff. Market anchoring is deliberately NOT part of this function:
    live Model_P must stay market-blind per LIVE_POLICY_V1.
    """
    base, _, _, hfa = PRIORS[sport]
    home_mean = base + hfa / 2 + context["home_rating"]
    away_mean = base - hfa / 2 + context["away_rating"]
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
    return home_mean, away_mean


def calculate(row, provider, now, *, auto_context=True, min_ev=0.02):
    sport = str(row.get("sport") or "").upper().strip()
    if sport not in PRIORS:
        raise ValueError("UNSUPPORTED_SPORT")
    market = str(row.get("market") or "").upper().strip()
    market = {"MONEYLINE": "ML", "H2H": "ML", "RUN_LINE": "SPREAD",
              "GAME_TOTAL": "TOTAL", "TOTALS": "TOTAL"}.get(market, market)
    if market not in {"ML", "SPREAD", "TOTAL"}:
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
    side = {"OVER": "OVER", "UNDER": "UNDER", "HOME": "HOME", "AWAY": "AWAY"}.get(side_raw.upper())
    if not side:
        # Must identify either exact team; substring similarity is unsafe.
        norm = PublicContext.key
        side = "HOME" if norm(side_raw) == norm(home) else "AWAY" if norm(side_raw) == norm(away) else None
    if side not in ({"OVER", "UNDER"} if market == "TOTAL" else {"HOME", "AWAY"}):
        raise ValueError("SIDE_MARKET_MISMATCH")
    line = None if market == "ML" else numeric(row.get("line"), "line")
    if market == "TOTAL" and line <= 0:
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
    home_mean, away_mean = score_means(sport, context)
    # A raw league-score baseline is NOT an executable fair price. Shrink
    # game-location departures toward the posted market threshold; 15% is an
    # unfitted RESEARCH prior, not a learned edge. Do not move an unknown line.
    raw_margin, raw_total = home_mean-away_mean, home_mean+away_mean
    # The model's own score means MUST be captured before sportsbook
    # anchoring. This is a simple unvalidated league/form/injury heuristic,
    # not a proven independent model or a validated wagering probability.
    raw_win, raw_push = model_probability(
        sport, market, side, line, home_mean, away_mean)
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
        "family": "FREE_TEAM_SCORE_HEURISTIC_UNVALIDATED",
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
    }
    anchor = {"status": "MARKET_ANCHORED_UNVALIDATED", "weight": 0.15}
    if market == "TOTAL":
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
    win, push = model_probability(sport, market, side, line, home_mean, away_mean)
    if market == "ML":
        win = bounded(anchor["market_no_vig_p"] + 0.15*(win-anchor["market_no_vig_p"]), 0, 1)
    loss = bounded(1 - win - push, 0, 1)
    ev = win * (dec - 1) - loss
    breakeven = (1 - push) / dec  # effective win-probability threshold with push refund
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
        return side.upper() if side.upper() in ("OVER", "UNDER") else None
    game = str(result.get("game") or "")
    if " @ " not in game:
        return None
    away, home = game.split(" @ ", 1)
    if side.upper() in ("HOME", "AWAY"):
        return side.upper()
    return "HOME" if key(side) == key(home) else "AWAY" if key(side) == key(away) else None


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
    if market == "ML":
        # Validate both quotations, not just this row. If an existing
        # opposite ticket row carries a contradictory opposite_odds field,
        # neither side gets a fabricated two-sided no-vig comparison.
        if len(compatible) == 1:
            partner = rows[compatible[0]["input_index"]]
            reverse = partner.get("opposite_odds")
            if reverse is not None:
                try:
                    reverse_dec = odds_decimal(reverse)
                    quoted_dec = odds_decimal(result["odds_american"])
                except (ValueError, TypeError):
                    projected["paired_market_status"] = "OPPOSITE_ML_INVALID"
                    return
                if abs(reverse_dec - quoted_dec) > 1e-12:
                    projected["paired_market_status"] = "OPPOSITE_ML_CONFLICT"
                    return
        opposite = row.get("opposite_odds")
        if opposite is not None:
            try:
                opposite = int(numeric(opposite,"opposite_odds"))
            except (ValueError,TypeError):
                projected["paired_market_status"] = "OPPOSITE_ML_INVALID"
                return
            if partner_price is not None and int(partner_price) != opposite:
                projected["paired_market_status"] = "OPPOSITE_ML_CONFLICT"
                return
            partner_price = opposite
    if partner_price is None:
        projected["paired_market_status"] = "MISSING_EXACT_OPPOSITE_DK_PRICE"
        return
    if book(row) != "draftkings":
        projected["paired_market_status"] = "NOT_DRAFTKINGS_PAIR"
        return
    # Optional quotes are assumed same screenshot unless an explicit
    # timestamp proves they differ; never compare known mismatched captures.
    input_time = row.get("quote_captured_at")
    matching_time = None
    if len(compatible) == 1:
        matching_time = rows[compatible[0]["input_index"]].get("quote_captured_at")
    if input_time and matching_time and str(input_time) != str(matching_time):
        projected["paired_market_status"] = "MISMATCHED_QUOTE_TIMESTAMPS"
        return
    try:
        p1 = 1.0 / odds_decimal(result["odds_american"])
        p2 = 1.0 / odds_decimal(partner_price)
    except (ValueError,TypeError,KeyError):
        projected["paired_market_status"] = "PAIRED_PRICE_INVALID"
        return
    fair = p1/(p1+p2)
    projected["market_no_vig_p"] = round(fair,6)
    projected["edge_vs_dk_no_vig_pp"] = round(100*(projected["estimate_p"]-fair),3)
    projected["paired_market_status"] = "EXACT_DK_TWO_SIDED_NO_VIG_RESEARCH"
    projected["reference_is_independent_sharp_market"] = False



def run(payload, *, now=None, getter=None, auto_context=True, min_ev=0.02):
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("AS_OF_TIMEZONE_REQUIRED")
    now = now.astimezone(timezone.utc)
    rows = payload if isinstance(payload, list) else payload.get("lines") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise ValueError("LINES_MUST_BE_LIST")
    provider = PublicContext(now, getter=getter)
    # A single-sport ticket may declare its sport once at the root.
    # Do not guess a sport from a team name or an ambiguous matchup.
    ticket_sport = payload.get("sport") if isinstance(payload, dict) else None
    all_rows = []
    for i, row in enumerate(rows):
        try:
            if not isinstance(row, dict):
                raise ValueError("LINE_MUST_BE_OBJECT")
            bound_row = dict(row)
            if not bound_row.get("sport") and ticket_sport is not None:
                bound_row["sport"] = ticket_sport
            result = calculate(bound_row, provider, now, auto_context=auto_context, min_ev=min_ev)
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            result = {"status": "BLOCKED_INVALID", "reason": str(exc)[:140]}
        result["input_index"] = i
        all_rows.append(result)
    # Keep independent projections available even when an optional 15%
    # book-anchored research view has zero qualifying candidates. Exact
    # paired DK no-vig is a benchmark, not a predictive feature.
    for i, result in enumerate(all_rows):
        if isinstance(rows[i], dict):
            _paired_book_context(rows, all_rows, i)
    independent = []
    watchlist = []
    for row in all_rows:
        projection = row.get("independent_projection")
        if not isinstance(projection, dict):
            continue
        if projection.get("paired_market_status") != "EXACT_DK_TWO_SIDED_NO_VIG_RESEARCH":
            watchlist.append(row)
            continue
        if row.get("odds_american", -999) < -165:
            watchlist.append(row)
            continue
        if projection.get("ev_per_dollar", -1) >= min_ev:
            independent.append(row)
        else:
            watchlist.append(row)
    independent.sort(key=lambda r: (-r["independent_projection"]["ev_per_dollar"],
                                    r["game"],r["selection"]))
    watchlist.sort(key=lambda r: (-r["independent_projection"]["ev_per_dollar"],
                                  r["game"],r["selection"]))
    edges = [r for r in all_rows if r["status"] == "RESEARCH_EDGE"]
    edges.sort(key=lambda r: (-r["ev_per_dollar"], r["game"], r["selection"]))
    return {"schema": "SPORTSEDGE_FREE_RESEARCH_CARD_V1", "as_of_utc": now.isoformat(),
            "authority": {"research_only": True, "official": False, "model_p": False,
                          "truth_gate": False, "staking": False},
            "min_ev": min_ev, "edges": edges,
            "independent_candidates": independent,
            "independent_watchlist": watchlist,
            "research_projection_note": "Unvalidated independent league-score heuristic; DK is a paired same-book no-vig benchmark, not sharp market verification.",
            # Keep the complete graded, source-annotated rows for reproducible
            # factor coverage and honest diagnostics even when below threshold.
            "evaluated_rows": all_rows,
            "summary": {"rows": len(rows), "edges": len(edges),
                        "status_counts": dict(sorted(Counter(r["status"] for r in all_rows).items()))},
            "diagnostics": [{"input_index": r["input_index"], "status": r["status"],
                             "reason": r.get("reason") or ",".join(r.get("context_notes") or [])}
                            for r in all_rows if r["status"] != "RESEARCH_EDGE"],
            "source_receipts": provider.receipts}


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
