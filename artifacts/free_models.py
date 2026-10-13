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
import hashlib
import json
from math import erf, exp, factorial, isfinite, sqrt
from pathlib import Path
import sys
from urllib.parse import urlencode
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sportsedge.quote_freshness import (
    MAX_QUOTE_AGE_SECONDS,
    check_quote_freshness,
    is_fresh as quote_is_fresh,
)
from sportsedge.pricing_provenance import (
    ANCHORED_PLAY_BLOCK,
    ANCHORED_WATCH_STATUS,
    LANE_MARKET_ANCHORED as PROVENANCE_MARKET_ANCHORED,
    apply_play_gate,
    is_play_eligible,
    provenance_for_game_result,
)

LEAGUES = {"NFL": "football/nfl", "CFB": "football/college-football",
           "NBA": "basketball/nba", "MLB": "baseball/mlb"}
# Explicit priors and heuristic variances; NOT fitted or calibrated.
PRIORS = {"NFL": (22.0, 13.5, 13.7, 1.5),
          "CFB": (28.0, 18.5, 19.0, 2.5),
          "NBA": (113.0, 19.0, 12.5, 2.0),
          "MLB": (4.4, None, None, 0.20)}
CONTEXT_KEYS = {"NFL": ("home_rating", "away_rating", "home_injury_pts",
                        "away_injury_pts", "home_form", "away_form", "weather_total_adj",
                        "rest_diff_adj"),
                "CFB": ("home_rating", "away_rating", "home_injury_pts",
                        "away_injury_pts", "home_form", "away_form", "weather_total_adj",
                        "rest_diff_adj"),
                "NBA": ("home_rating", "away_rating", "home_injury_pts",
                        "away_injury_pts", "home_form", "away_form", "rest_adj"),
                "MLB": ("home_rating", "away_rating", "home_pitcher_adj",
                        "away_pitcher_adj", "weather_total_adj", "rest_diff_adj")}
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
    "chicago state", "chicago state cougars", "chicago st",
})
# Frozen ESPN-ID registry for the same exclusion (owner rule: no Illinois
# college teams on user-facing CFB/CBB cards). The name list above is
# form-dependent: it missed Chicago State (ESPN id 2130) in every attested
# name form, so the canonical intake enforces THIS registry on the verified
# ESPN team-directory binding (PublicContext.identify) -- see
# sportsedge/prepricing/factor_ingestion.py and
# sportsedge/team_half_pricing.py. The name list remains a secondary
# signal for provider-less paths (direct calculate calls, the research
# bridge). Provenance: ESPN teams registry cross-checked in the CBB
# foundation probe (workspace/sportsedge/cbb_foundation_probe/FINDINGS.md)
# and the CFB participation design verification (2026-10-13). Re-derive
# each season: conference realignment and D1 membership change (Chicago
# State's conference status in particular has been unstable). Eight
# schools field CFB teams in 2026 (ids 356, 77, 2287, 2459, 79, 2197,
# 2710, 2130); the other five have no football program, so their ids
# cannot appear in the CFB directory -- they are carried so this stays
# the single 13-school record shared with the CBB exclusion.
IL_COLLEGE_ESPN_IDS = {
    "356": "Illinois", "77": "Northwestern", "305": "DePaul",
    "2350": "Loyola Chicago", "82": "UIC", "71": "Bradley",
    "2287": "Illinois State", "79": "Southern Illinois",
    "2565": "SIU Edwardsville", "2197": "Eastern Illinois",
    "2710": "Western Illinois", "2459": "Northern Illinois",
    "2130": "Chicago State",
}
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


def declared_weather_total_adj(wind_mph, precip_prob, sport):
    """Declared uncalibrated weather scoring impact on the game total.

    Research prior, NOT a learned edge: wind >= 18 mph -> -0.8, >= 13 ->
    -0.4; precipitation probability >= 70% -> -0.4; MLB scaled 0.3.
    Shared by the live provider.weather path and archived weather evidence
    so the declared table cannot diverge between sources.
    """
    impact = (0.8 if wind_mph >= 18 else 0.4 if wind_mph >= 13 else 0.0)
    impact += 0.4 if precip_prob >= 70 else 0.0
    return -round(impact * (0.3 if sport == "MLB" else 1.0), 3)


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


def model_probability(sport, market, side, line, home_mean, away_mean, team_totals_team=None):
    """Return win, push, loss; account for pushes on integer lines."""
    if sport == "MLB":
        a, b = poisson(home_mean), poisson(away_mean)
        win = push = 0.0
        for h, ph in enumerate(a):
            for aw, pa in enumerate(b):
                if market == "TOTAL":
                    score = h + aw
                    target = (score - line if side == "OVER" else line - score)
                elif market == "TEAM_TOTALS":
                    # Same verified team means as ML/total, but select one
                    # team's count rather than the game count.
                    if team_totals_team not in {"HOME", "AWAY"}:
                        raise ValueError("TEAM_TOTALS_TEAM_UNVERIFIED")
                    score = h if team_totals_team == "HOME" else aw
                    target = score - line if side == "OVER" else line - score
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


# Injury-binding currency window (days before the as-of clock). CFB only.
# NFL shared-binding consequence: injury_rows() is the single binding path
# for NFL/CFB/NBA. The live NFL league feed legitimately carries season-long
# IR/PUP rows dated weeks earlier (oldest row 2026-09-23 on 2026-10-13), so
# a universal window would mark NFL teams STALE_UNKNOWN and block NFL games.
# NFL/NBA behavior is therefore UNCHANGED pending owner review.
INJURY_CURRENCY_DAYS = {"CFB": 21}
INJURY_STALE_UNKNOWN = "STALE_INJURY_ENTRIES_UNKNOWN"


class PublicContext:
    """Request-scoped cache; no persisted odds, data keys or retrospective rewrites.

    ``now`` is the as-of clock: every time comparison in this provider uses it,
    so passing a historical as-of reprices a fixture point-in-time. When
    ``historical=True`` the provider additionally refuses "current state"
    sources (injury reports, weather forecasts) that free endpoints only serve
    as-of today — using them for a past kickoff would leak the present into
    the backtest. Those factors are excluded with explicit AS_OF_* codes.
    """
    def __init__(self, now, getter=None, *, historical=False):
        self.now = now
        self.getter = getter or self._live_get
        # Live ESPN directory floor (see team_directory). Injected fixture
        # getters are exempt from the absolute floor only; pagination and
        # short-page completeness apply to every getter.
        self.enforce_directory_floor = getter is None
        self.cache = {}
        self.receipts = []
        self._injury_result_cache = {}
        self.historical = bool(historical)

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

    # Directory completeness (Grok reimplementation, 2026-10-13). ESPN's
    # site teams endpoint silently truncates at ``limit`` and publishes no
    # count/pageCount metadata. The CFB directory is 762 teams (all
    # divisions), so the old single ``?limit=500`` fetch saw only the first
    # 500 and any school past that cut failed identity resolution. Pages are
    # now walked (``&page=N``) until a short page; the directory fails CLOSED
    # (empty -> identify() returns None) when a page is unavailable/malformed,
    # a page repeats team IDs, the page cap is hit, or the total is below the
    # sport's declared floor. Page 1 keeps the historical URL.
    TEAM_PAGE_SIZE = 500
    TEAM_MAX_PAGES = 10
    TEAM_DIRECTORY_FLOOR = {"NFL": 32, "NBA": 30, "MLB": 30, "CFB": 700}

    @staticmethod
    def _team_page(obj):
        if not isinstance(obj, dict) or not isinstance(obj.get("sports"), list):
            return None
        teams = []
        for group in obj.get("sports") or []:
            if not isinstance(group, dict):
                return None
            for league in group.get("leagues") or []:
                if not isinstance(league, dict) or not isinstance(league.get("teams", []), list):
                    return None
                for data in league.get("teams") or []:
                    team = (data or {}).get("team") if isinstance(data, dict) else None
                    if isinstance(team, dict) and team.get("id"):
                        teams.append(team)
        return teams

    def team_directory(self, sport):
        """Return (teams, status). status COMPLETE or DIRECTORY_INCOMPLETE:<why>."""
        cache_key = ("team_directory", sport)
        if cache_key in self._injury_result_cache:
            return self._injury_result_cache[cache_key]
        base = f"{ESPN}/{LEAGUES[sport]}/teams?limit={self.TEAM_PAGE_SIZE}"
        teams, seen, status = [], set(), None
        for page in range(1, self.TEAM_MAX_PAGES + 1):
            url = base if page == 1 else f"{base}&page={page}"
            batch = self._team_page(self.fetch(url))
            if batch is None:
                status = f"DIRECTORY_INCOMPLETE:PAGE_{page}_UNAVAILABLE_OR_MALFORMED"
                break
            ids = [str(t["id"]) for t in batch]
            if len(set(ids)) != len(ids) or seen.intersection(ids):
                status = f"DIRECTORY_INCOMPLETE:PAGE_{page}_REPEATS_TEAM_IDS"
                break
            seen.update(ids)
            teams.extend(batch)
            if len(batch) < self.TEAM_PAGE_SIZE:
                status = "COMPLETE"
                break
        else:
            status = f"DIRECTORY_INCOMPLETE:PAGE_CAP_{self.TEAM_MAX_PAGES}_REACHED"
        floor = self.TEAM_DIRECTORY_FLOOR.get(sport, 1) if self.enforce_directory_floor else 1
        if status == "COMPLETE" and len(teams) < floor:
            status = f"DIRECTORY_INCOMPLETE:{len(teams)}_BELOW_FLOOR_{floor}"
        if status != "COMPLETE":
            self.receipts.append({"source": base, "status": "DIRECTORY_INCOMPLETE",
                                  "reason": status, "teams_seen": len(teams)})
            teams = []
        else:
            self.receipts.append({"source": base, "status": "DIRECTORY_COMPLETE",
                                  "teams": len(teams)})
        result = (teams, status)
        self._injury_result_cache[cache_key] = result
        return result

    def teams(self, sport):
        return self.team_directory(sport)[0]

    @staticmethod
    def key(value):
        return " ".join("".join(c.lower() if c.isalnum() else " " for c in str(value)).split())

    @classmethod
    def team_matches(cls, team, value):
        s = cls.key(value)
        return bool(s) and s in {cls.key(team.get(k, "")) for k in
                     ("id", "displayName", "name", "shortDisplayName", "abbreviation", "location",
                      "teamName", "clubName", "fileCode")}

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
        events = schedule.get("events")
        if not isinstance(events, list):
            return []  # fail closed: unverified schedule is no schedule
        for event in events:
            if not isinstance(event, dict):
                continue
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

    def _injury_currency(self, sport, rows):
        """Currency gate (Grok reimplementation, 2026-10-13).

        ESPN's CFB injuries feed serves entries dated 2020-2022 (e.g. a 2020
        Florida WR 'Out') that were being bound as the CURRENT report. For
        sports in INJURY_CURRENCY_DAYS, every row must carry a parseable,
        timezone-aware ``date`` within the window before the as-of clock
        (``self.now``) and not after it. Any stale, undated, or future row
        makes the WHOLE team binding STALE_UNKNOWN: a dropped row could be a
        QB, so partial binding would imply health. Returns None when current.
        NFL/NBA are deliberately NOT gated here (shared-binding consequence;
        see INJURY_CURRENCY_DAYS).
        """
        window = INJURY_CURRENCY_DAYS.get(sport)
        if window is None:
            return None
        oldest = self.now - timedelta(days=window)
        for i, row in enumerate(rows):
            stamp = dt(row.get("date")) if isinstance(row, dict) else None
            if stamp is None:
                return f"ROW_{i}_UNDATED"
            if stamp > self.now:
                return f"ROW_{i}_DATED_AFTER_AS_OF"
            if stamp < oldest:
                return f"ROW_{i}_DATED_{stamp.date().isoformat()}_OLDER_THAN_{window}D"
        return None

    def injury_rows(self, sport, team):
        """Return verified team-scoped injury rows, or (None, status).

        ("rows", "STRUCTURE_VERIFIED") when the ESPN injury payload binds to
        exactly one team group; (None, "UNUSABLE_SCHEMA") when neither the
        team nor league payload resolves; ([], "NOT_APPLICABLE") for MLB.
        Same fetch path and receipts as injury_points; the pre-pricing
        QB/participation check consumes these rows instead of a second,
        divergent fetch path.
        """
        if sport == "MLB":
            return [], "NOT_APPLICABLE"
        if self.historical:
            # ESPN serves the CURRENT injury report only. There is no free
            # as-of historical injury endpoint, so a historical repricing
            # must not silently apply today's report to a past kickoff.
            return [], "AS_OF_HISTORICAL_INJURIES_UNAVAILABLE"
        target_id = str(team["id"])
        key = ("injury_rows", sport, target_id)
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
            result = (None, "UNUSABLE_SCHEMA")
            self._injury_result_cache[key] = result
            return result
        currency = self._injury_currency(sport, candidates)
        if currency is not None:
            self.receipts.append({
                "source": f"{ESPN}/{LEAGUES[sport]}/injuries",
                "status": INJURY_STALE_UNKNOWN,
                "reason": currency,
                "team_id": target_id[:20],
                "note": "STALE_ENTRIES_ARE_UNKNOWN_NOT_HEALTHY"})
            result = (None, INJURY_STALE_UNKNOWN)
            self._injury_result_cache[key] = result
            return result
        self.receipts.append({
            "source": f"{ESPN}/{LEAGUES[sport]}/injuries",
            "status": "STRUCTURE_VERIFIED",
            "team_id": target_id[:20],
            "injury_rows_reported": len(candidates),
            "note": "REPORTED_INJURIES_NOT_COMPLETE_ROSTER_HEALTH"})
        result = (candidates, "STRUCTURE_VERIFIED")
        self._injury_result_cache[key] = result
        return result

    def injury_points(self, sport, team):
        """Verify team-group identity and return cautious heuristic injuries.

        Contract: (points, status); MLB -> (0.0, "NOT_APPLICABLE");
        verified payload -> (-loss, "HEURISTIC_OUT_DOUBTFUL_REPORTED_{n}_UNKNOWN_COMPLETENESS");
        unusable payload -> (0.0, "MISSING_OR_UNRECOGNIZED_SOURCE").
        QB out/doubtful costs 1.5 (NFL), NBA 0.3 each, others 0.15, capped 2.5.
        """
        if sport == "MLB":
            return 0.0, "NOT_APPLICABLE"
        rows, status = self.injury_rows(sport, team)
        if rows is None and status == INJURY_STALE_UNKNOWN:
            return 0.0, INJURY_STALE_UNKNOWN
        if rows is None:
            return 0.0, "MISSING_OR_UNRECOGNIZED_SOURCE"
        # Preserve historical unavailability: do not report a zero-injury
        # heuristic when the injury feed itself is unavailable for as-of.
        if status == "AS_OF_HISTORICAL_INJURIES_UNAVAILABLE":
            return 0.0, "AS_OF_HISTORICAL_INJURIES_UNAVAILABLE"
        candidates = rows
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
        # Receipt already recorded by injury_rows (STRUCTURE_VERIFIED); the
        # points heuristic keeps its original return contract.
        return (-round(min(loss, 2.5), 3),
                f"HEURISTIC_OUT_DOUBTFUL_REPORTED_{len(seen)}_UNKNOWN_COMPLETENESS")

    def _nfl_team_schedule_fixture(self, away, home, kickoff):
        """Second public source path when ESPN's date scoreboard omits NFL.

        Only an independently fetched HOME team schedule with a unique event,
        both exact ESPN team IDs in the correct roles, a pregame time within
        fifteen minutes, and a start later than the as-of clock can qualify.
        No intake event IDs or odds are trusted as verification.
        """
        if kickoff is None:
            return None
        h = self.identify("NFL", home)
        a = self.identify("NFL", away)
        if h is None or a is None or str(h["id"]) == str(a["id"]):
            return None
        season = kickoff.year - (1 if kickoff.month <= 2 else 0)
        url = f"{ESPN}/football/nfl/teams/{h['id']}/schedule?season={season}"
        response = self.fetch(url) or {}
        matched = {}
        for ev in response.get("events") or []:
            if not isinstance(ev, dict) or not ev.get("id"):
                continue
            start = dt(ev.get("date"))
            if (start is None or start <= self.now or
                    abs((start - kickoff).total_seconds()) > 900):
                continue
            competitions = ev.get("competitions") or []
            if len(competitions) != 1 or not isinstance(competitions[0], dict):
                continue
            comp = competitions[0]
            cs = comp.get("competitors") or []
            hc = [x for x in cs if isinstance(x, dict) and x.get("homeAway") == "home"]
            ac = [x for x in cs if isinstance(x, dict) and x.get("homeAway") == "away"]
            if len(hc) != 1 or len(ac) != 1:
                continue
            if (str((hc[0].get("team") or {}).get("id")) != str(h["id"]) or
                    str((ac[0].get("team") or {}).get("id")) != str(a["id"])):
                continue
            status = comp.get("status") or ev.get("status") or {}
            state = (status.get("type") or {}) if isinstance(status, dict) else {}
            if state.get("completed") is True or state.get("state") in {"in", "post"}:
                continue
            matched[str(ev["id"])] = (start, comp)
        return next(iter(matched.values())) if len(matched) == 1 else None

    def _mlb_statsapi_fixture(self, away, home, kickoff):
        """MLB-only independent schedule fallback when ESPN omits a fixture.

        The source must contain exactly one future gamePk matching both teams,
        the provided kickoff within 15 minutes, and a pregame status. An odds
        board or claimed ESPN event ID is never treated as source evidence.
        A minimal venue intentionally leaves weather unknown, not verified.
        """
        if kickoff is None:
            return None
        found = {}
        for offset in (-1, 0, 1):
            game_date = (kickoff + timedelta(days=offset)).date().isoformat()
            url = ("https://statsapi.mlb.com/api/v1/schedule?" +
                   urlencode({"sportId": "1", "date": game_date,
                              "hydrate": "team,probablePitcher"}))
            response = self.fetch(url) or {}
            for day in response.get("dates") or []:
                if not isinstance(day, dict):
                    continue
                for game in day.get("games") or []:
                    if not isinstance(game, dict):
                        continue
                    teams = game.get("teams") or {}
                    home_team = (teams.get("home") or {}).get("team") or {}
                    away_team = (teams.get("away") or {}).get("team") or {}
                    if not (self.team_matches(home_team, home)
                            and self.team_matches(away_team, away)):
                        continue
                    game_pk = game.get("gamePk")
                    start = dt(game.get("gameDate"))
                    if not game_pk or start is None or start <= self.now:
                        continue
                    if abs((start - kickoff).total_seconds()) > 900:
                        continue
                    status = (game.get("status") or {}).get("detailedState")
                    if status not in {"Scheduled", "Pre-Game", "Warmup"}:
                        continue
                    # The MLB schedule establishes fixture identity only;
                    # it does not attest a roof state or weather forecast.
                    found[str(game_pk)] = (
                        start, {"venue": {},
                                "source": "MLB_STATSAPI_SCHEDULE_VERIFIED",
                                "game_pk": game_pk})
        return next(iter(found.values())) if len(found) == 1 else None

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
        if len(games) == 1:
            return next(iter(games.values()))
        if sport == "MLB" and kickoff is not None and not games:
            return self._mlb_statsapi_fixture(away, home, kickoff)
        if sport == "NFL" and kickoff is not None and not games:
            return self._nfl_team_schedule_fixture(away, home, kickoff)
        return None

    def weather(self, sport, comp, kickoff, latitude=None, longitude=None):
        if sport not in {"NFL", "CFB", "MLB"}:
            return 0.0, "NOT_APPLICABLE"
        if self.historical:
            # The forecast endpoint serves a forward window only; the pre-game
            # forecast for a historical kickoff is not reconstructible, and
            # realized weather would be lookahead. Excluded, explicitly.
            return 0.0, "AS_OF_HISTORICAL_WEATHER_UNAVAILABLE"
        venue = comp.get("venue") or {}
        # A static ESPN indoor flag is NOT evidence that a retractable roof
        # is closed for this particular game. American Family Field has a
        # retractable roof; its state requires independent game-day evidence.
        venue_key = self.key(venue.get("fullName") or venue.get("name") or "")
        if sport == "MLB" and venue_key in {
            "american family field", "miller park", "chase field",
            "globe life field", "loandepot park", "marlins park",
            "minute maid park", "daikin park", "rogers centre",
            "t mobile park",
        }:
            return 0.0, "RETRACTABLE_ROOF_STATE_UNVERIFIED"
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
        # Shared declared table: see declared_weather_total_adj.
        return declared_weather_total_adj(wind, rain, sport), "HEURISTIC_FORECAST_NOT_CALIBRATED"


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
    """Market-blind pregame means for live repricing.

    Keep this calculation in parity with calculate()'s Lane A base model.
    No quoted market price enters here. Owner-disabled MLB pitcher ERA,
    recent form and rest differential factors must contribute exactly zero
    even when their unvalidated research values are present in context.
    The NBA rest adjustment (context key rest_adj) is disabled by the
    same Oct 13 ruling, extended on PR #2120 regardless of key name: it
    stays in context for research and contributes exactly zero here, so
    live repricing remains in parity with calculate().
    This helper restores the live_run_it import omitted by composition.
    """
    base, _, _, hfa = PRIORS[sport]
    home_mean = base + hfa / 2 + context["home_rating"]
    away_mean = base - hfa / 2 + context["away_rating"]
    if sport != "MLB":
        home_mean += context["home_injury_pts"]
        away_mean += context["away_injury_pts"]
    if "weather_total_adj" in context:
        home_mean += context["weather_total_adj"] / 2
        away_mean += context["weather_total_adj"] / 2
    if min(home_mean, away_mean) < 0.2:
        raise ValueError("IMPLAUSIBLE_SCORE_MEAN")
    return home_mean, away_mean


# Pricing-lane contract (Priority 1 repair, Oct 11 2026).
# Every probability the engine emits says which lane produced it:
#   LANE_A_INDEPENDENT - truly market-blind; the default everywhere. The
#                        win probability never sees a market price.
#   LANE_B_ANCHORED    - Lane A shrunk ANCHOR_WEIGHT toward the posted market
#                        line/total (MARKET_ANCHORED_UNVALIDATED). The 15% weight
#                        is an unfitted research hypothesis: it earns its keep
#                        in chronological out-of-sample backtesting or it goes.
# Both lanes are always computed and always labeled; the harness backtests
# them as two separate models.
LANE_A = "LANE_A_INDEPENDENT"
LANE_B = "LANE_B_ANCHORED"
ANCHOR_WEIGHT = 0.15
POSITIVE_EV_STATUS = "RESEARCH_POSITIVE_EV_UNVALIDATED"


def _lane_view(lane, win, push, home_mean, away_mean, dec, raw_total,
               raw_margin, extra=None):
    """One fully-labeled pricing-lane view. Three quantities kept distinct:

    - edge_over_break_even_pp / edge_vs_dk_no_vig_pp: MODEL EDGE estimates
      (P_model vs quoted breakeven / vs DK no-vig). Unvalidated.
    - ev_per_dollar: expected value AT THE AVAILABLE quoted price. Unvalidated.
    - validated_profitability: always False here. Nothing in this engine is a
      validated profitable edge; that verdict belongs to the backtest harness.
    """
    loss = bounded(1 - win - push, 0, 1)
    ev = win * (dec - 1) - loss
    breakeven = (1 - push) / dec  # win-probability threshold with push refund
    conditional = (win / (win + loss) if win + loss > 0 else None)
    fair = None
    if conditional is not None and 0 < conditional < 1:
        fair = (-100 * conditional / (1 - conditional)
                if conditional >= 0.5
                else 100 * (1 - conditional) / conditional)
    view = {
        "lane": lane,
        "estimate_p": round(win, 6),
        "push_p": round(push, 6),
        "loss_p": round(loss, 6),
        "ev_per_dollar": round(ev, 6),
        "fair_american": round(fair) if fair is not None else None,
        "book_break_even_p": round(breakeven, 6),
        "edge_over_break_even_pp": round(100 * (win - breakeven), 3),
        "home_mean": round(home_mean, 3),
        "away_mean": round(away_mean, 3),
        "projected_total": round(raw_total, 3),
        "projected_home_margin": round(raw_margin, 3),
        "validated_vs_close": False,
        "validated_profitability": False,
    }
    if extra:
        view.update(extra)
    return view


def calculate(row, provider, now, *, auto_context=True, min_ev=0.02,
              lane="A", allow_manual_context=False, prepricing_adjustments=None):
    """Price one game row in two labeled lanes.

    lane="A" (default): the primary top-level view is LANE_A_INDEPENDENT.
    lane="B": explicitly request the anchored primary view (Lane B).

    allow_manual_context=False (default): any manual context override in the
    untrusted intake row fails closed with BLOCKED_MANUAL_CONTEXT_UNDECLARED.
    allow_manual_context=True: overrides apply but each is labeled
    USER_SUPPLIED_MANUAL in context_provenance and context_notes.
    """
    lane = str(lane or "A").upper().strip()
    if lane not in ("A", "B"):
        raise ValueError("LANE_MUST_BE_A_OR_B")
    sport = str(row.get("sport") or "").upper().strip()
    if sport not in PRIORS:
        raise ValueError("UNSUPPORTED_SPORT")
    market = str(row.get("market") or "").upper().strip()
    market = {"MONEYLINE": "ML", "H2H": "ML", "RUN_LINE": "SPREAD",
              "GAME_TOTAL": "TOTAL", "TOTALS": "TOTAL",
              "TEAM_TOTAL": "TEAM_TOTALS"}.get(market, market)
    if market not in {"ML", "SPREAD", "TOTAL", "TEAM_TOTALS"}:
        raise ValueError("UNSUPPORTED_MARKET_NO_PROP_MODEL")
    if market == "TEAM_TOTALS" and sport != "MLB":
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
    team_totals_team = None
    if market == "TEAM_TOTALS":
        # The quote determines a SIDE and a TEAM; neither can be guessed.
        # Support either "Milwaukee Brewers Over" as selection, or an
        # explicit team with side="OVER". Team identity is exact only.
        normalized = PublicContext.key
        source_team = str(row.get("team") or "").strip()
        tokenized = side_raw.rsplit(" ", 1)
        if len(tokenized) == 2 and tokenized[-1].upper() in {"OVER", "UNDER"}:
            if source_team and normalized(source_team) != normalized(tokenized[0]):
                raise ValueError("TEAM_TOTALS_CONFLICTING_TEAM_IDENTITY")
            source_team = tokenized[0]
            side = tokenized[-1].upper()
        if not source_team:
            raise ValueError("TEAM_TOTALS_TEAM_REQUIRED")
        if normalized(source_team) in {"home", normalized(home)}:
            team_totals_team = "HOME"
        elif normalized(source_team) in {"away", normalized(away)}:
            team_totals_team = "AWAY"
        if team_totals_team is None or side not in {"OVER", "UNDER"}:
            raise ValueError("TEAM_TOTALS_TEAM_OR_SIDE_UNVERIFIED")
    else:
        if not side:
            normalized = PublicContext.key
            side = ("HOME" if normalized(side_raw) == normalized(home)
                    else "AWAY" if normalized(side_raw) == normalized(away) else None)
        if side not in ({"OVER", "UNDER"} if market == "TOTAL" else {"HOME", "AWAY"}):
            raise ValueError("SIDE_MARKET_MISMATCH")
    line = None if market == "ML" else numeric(row.get("line"), "line")
    if market in {"TOTAL", "TEAM_TOTALS"} and line <= 0:
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
    # Repair 1 (Oct 11 2026): untrusted intake must NEVER silently replace
    # verified factors. Any manual override attempt without the explicit
    # allow_manual_context flag fails closed; with the flag, every overridden
    # factor is labeled USER_SUPPLIED_MANUAL in the audit. Verified factors
    # always win on conflict because unflagged overrides never apply.
    attempted_overrides = []
    overrides = row.get("context") or {}
    if not isinstance(overrides, dict):
        raise ValueError("CONTEXT_MUST_BE_OBJECT")
    for key in context:
        if key in overrides and overrides[key] is not None:
            attempted_overrides.append("context." + key)
        elif row.get(key) is not None:
            attempted_overrides.append(key)
    context_provenance = {key: "VERIFIED_PUBLIC" for key in context}
    if attempted_overrides and not allow_manual_context:
        return {"status": "BLOCKED_MANUAL_CONTEXT_UNDECLARED",
                "game": f"{away} @ {home}", "sport": sport,
                "reason": "MANUAL_CONTEXT_OVERRIDES_REQUIRE_EXPLICIT_FLAG:"
                          + ",".join(sorted(attempted_overrides)),
                "attempted_override_keys": sorted(attempted_overrides),
                "context_notes": notes, "research_only": True}
    for key in context:
        val = overrides.get(key, row.get(key))
        if val is not None:
            # Reachable only when attempted_overrides was non-empty (and the
            # flag was set); every other path returned or left val None.
            n = numeric(val, key)
            if abs(n) > 15:
                raise ValueError("CONTEXT_ADJUSTMENT_UNBOUNDED:" + key)
            context[key] = n
            context_provenance[key] = "USER_SUPPLIED_MANUAL"
            notes.append("OVERRIDE_USER_SUPPLIED:" + key)
    # Option 3: System-verified prepricing adjustments, separate from user context.
    # Applied after user context; verified prepricing wins on overlap (no double-count).
    # A user-supplied "prepricing_adjustments" field is never trusted (stripped in run()).
    if prepricing_adjustments:
        pp_data = prepricing_adjustments.get("adjustments") or {}
        pp_source = prepricing_adjustments.get("source", "UNKNOWN")
        pp_status = prepricing_adjustments.get("verification_status", "UNVERIFIED")
        if pp_status != "VERIFIED":
            # Do not silently label unverified adjustments as verified
            notes.append("PREPRICING_UNVERIFIED_SKIPPED:" + pp_source)
        else:
            for key, val in pp_data.items():
                if key in context:
                    # Overlap: verified prepricing wins, log the override
                    if context_provenance.get(key) == "USER_SUPPLIED_MANUAL":
                        notes.append("PREPRICING_OVERRIDE_MANUAL:" + key)
                    n = numeric(val, "prepricing." + key)
                    if abs(n) > 15:
                        raise ValueError("PREPRICING_ADJUSTMENT_UNBOUNDED:" + key)
                    context[key] = n
                    context_provenance[key] = "VERIFIED_PREPRICING"
                    notes.append("PREPRICING_VERIFIED:" + key + ":" + pp_source)
    if kickoff is None or kickoff <= now:
        return {"status": "BLOCKED_KICKOFF_UNVERIFIED", "game": f"{away} @ {home}", "sport": sport,
                "context_notes": notes}
    # Fixture binding alone is NOT proof of two team-specific NFL inputs.
    # The league default (22 points/team) can otherwise masquerade as a huge
    # game-specific total edge when both history feeds are empty. A reported
    # empty/inaccessible injury feed is likewise not verified QB context.
    # Manual-only (--no-fetch) runs remain diagnostic and are separately
    # prevented from becoming card candidates below.
    if sport == "NFL" and auto_context:
        required = (
            "HOME_HISTORY_COUNT:", "AWAY_HISTORY_COUNT:",
            "HOME_INJURIES:HEURISTIC_OUT_DOUBTFUL_REPORTED_",
            "AWAY_INJURIES:HEURISTIC_OUT_DOUBTFUL_REPORTED_",
        )
        missing = [marker.split(":", 1)[0] for marker in required
                   if not any(str(note).startswith(marker) for note in notes)]
        if missing:
            return {
                "status": "BLOCKED_NFL_CRITICAL_CONTEXT_UNVERIFIED",
                "game": f"{away} @ {home}", "sport": sport,
                "reason": "NFL_TWO_TEAM_HISTORY_AND_INJURY_RECEIPTS_REQUIRED:" + ",".join(missing),
                "context_notes": notes, "context_provenance": context_provenance,
                "research_only": True,
                "model_p_authority": False, "official_authority": False,
                "staking_authority": False,
            }
    base, _, _, hfa = PRIORS[sport]
    home_mean = base + hfa/2 + context["home_rating"]
    away_mean = base - hfa/2 + context["away_rating"]
    # Owner ruling (Oct 13, 2026): three unvalidated adjustments are
    # DISABLED_PENDING_INCREMENTAL_VALUE in canonical pricing until each
    # demonstrates incremental value in the harness against the retained
    # baseline (team-strength ratings + static HFA, above) and the
    # market: the ERA-based starting-pitcher adjustment
    # (home/away_pitcher_adj), recent form (home/away_form), and the
    # rest differential (rest_diff_adj). Their values remain in context
    # and in the factor audit for research; the pricing contribution
    # here is exactly zero. The prepricing stage already hands these
    # keys over as 0.0; this gate keeps the contribution zero even if a
    # nonzero value reaches the engine by another path. The NBA rest
    # adjustment (key name rest_adj, not rest_diff_adj) is governed by
    # the same ruling — the owner extended it on PR #2120 with no
    # carve-out: the disable applies across all supported sports
    # regardless of the adjustment's key name.
    if sport == "MLB":
        notes.append("PITCHER_ADJ_DISABLED_PENDING_INCREMENTAL_VALUE")
    else:
        home_mean += context["home_injury_pts"]
        away_mean += context["away_injury_pts"]
        notes.append("RECENT_FORM_DISABLED_PENDING_INCREMENTAL_VALUE")
        if sport == "NBA":
            # rest_adj is NOT applied: contribution exactly zero. The
            # value stays in context for research (schedule/rest data
            # remains available for future point-in-time validation);
            # this gate holds however the value arrived — verified
            # prepricing, top-level intake key, or manual override.
            notes.append("REST_ADJ_DISABLED_PENDING_INCREMENTAL_VALUE")
    if "weather_total_adj" in context:
        home_mean += context["weather_total_adj"] / 2
        away_mean += context["weather_total_adj"] / 2
    if "rest_diff_adj" in context:
        notes.append("REST_DIFF_ADJ_DISABLED_PENDING_INCREMENTAL_VALUE")
    if min(home_mean, away_mean) < 0.2:
        raise ValueError("IMPLAUSIBLE_SCORE_MEAN")
    # Repair 3 (Oct 11 2026): quote freshness is checked centrally on every
    # pricing path. Only a verified-fresh capture can support a positive-EV
    # status; everything else is watch-only with an explicit code.
    quote_freshness = check_quote_freshness(row.get("quote_captured_at"), now=now)
    raw_margin, raw_total = home_mean-away_mean, home_mean+away_mean
    # ---- Lane A (independent): the model's own score means, no market input
    # in the probability. This is a simple unvalidated league/form/injury
    # heuristic, not a proven independent model or validated probability. ----
    a_win, a_push = model_probability(
        sport, market, side, line, home_mean, away_mean,
        team_totals_team=team_totals_team)
    lane_a = _lane_view(
        LANE_A, a_win, a_push, home_mean, away_mean, dec,
        raw_total, raw_margin,
        extra={
            "family": "FREE_TEAM_SCORE_HEURISTIC_UNVALIDATED",
            # The Lane A PROBABILITY never sees a market price. EV necessarily
            # compares that probability against the quoted price afterwards.
            "uses_sportsbook_price_in_projection": False,
            "not_wagering_authority": True,
        })
    # ---- Lane B (anchored): Lane A means shrunk ANCHOR_WEIGHT toward the
    # posted market line/total. 15% is an unfitted RESEARCH prior, not a
    # learned edge; it must prove itself out-of-sample or be removed. ----
    anchor = {"status": "MARKET_ANCHORED_UNVALIDATED", "weight": ANCHOR_WEIGHT,
              "hypothesis": "UNVALIDATED_OUT_OF_SAMPLE_REQUIRED"}
    b_home_mean, b_away_mean = home_mean, away_mean
    lane_b_blocked = None
    if market == "TOTAL":
        anchored_total = line + ANCHOR_WEIGHT * (raw_total - line)
        shift = (anchored_total - raw_total) / 2
        b_home_mean += shift
        b_away_mean += shift
        anchor.update(market_total=line, raw_total=raw_total,
                      fair_total=anchored_total)
    elif market == "TEAM_TOTALS":
        # No trained market-anchor relationship for a team total. Leave
        # independent pricing available, but do not misread team-total odds
        # as full-game moneyline odds in Lane B.
        lane_b_blocked = "LANE_B_TEAM_TOTALS_UNVALIDATED"
    elif market == "SPREAD":
        market_home_margin = -line if side == "HOME" else line
        anchored_margin = (market_home_margin
                           + ANCHOR_WEIGHT * (raw_margin - market_home_margin))
        shift = (anchored_margin - raw_margin) / 2
        b_home_mean += shift
        b_away_mean -= shift
        anchor.update(market_home_margin=market_home_margin,
                      raw_margin=raw_margin, fair_home_margin=anchored_margin)
    else:
        # A one-sided ML price contains vig. Without the opposite price we
        # cannot infer the bookmaker's no-vig baseline. Lane B is unavailable;
        # Lane A (market-blind) still prices. Reject, don't invent.
        opposite = row.get("opposite_odds")
        if opposite is None:
            lane_b_blocked = "BLOCKED_UNPAIRED_ML"
        else:
            opposite_dec = odds_decimal(opposite)
            p1, p2 = 1 / dec, 1 / opposite_dec
            anchor.update(market_no_vig_p=p1 / (p1 + p2))
    if lane_b_blocked is None:
        b_win, b_push = model_probability(
            sport, market, side, line, b_home_mean, b_away_mean,
        team_totals_team=team_totals_team)
        if market == "ML":
            b_win = bounded(anchor["market_no_vig_p"]
                            + ANCHOR_WEIGHT * (b_win - anchor["market_no_vig_p"]),
                            0, 1)
        lane_b = _lane_view(
            LANE_B, b_win, b_push, b_home_mean, b_away_mean, dec,
            raw_total, raw_margin,
            extra={
                "anchor": anchor,
                "uses_sportsbook_price_in_projection": True,
            })
    else:
        lane_b = {"lane": LANE_B, "status": "LANE_B_UNAVAILABLE",
                  "reason": lane_b_blocked, "anchor": anchor,
                  "validated_vs_close": False, "validated_profitability": False}
    if lane == "B" and lane_b.get("status") == "LANE_B_UNAVAILABLE":
        return {"status": lane_b["reason"], "game": f"{away} @ {home}",
                "sport": sport, "pricing_lane": LANE_B,
                "pricing_provenance": provenance_for_game_result(
                    {"pricing_lane": LANE_B, "market": market}),
                "pricing_lanes": {"lane_a_independent": lane_a,
                                  "lane_b_anchored": lane_b},
                "quote_freshness": quote_freshness,
                "context": context, "context_notes": notes,
                "context_provenance": context_provenance,
                "research_only": True}
    primary = lane_a if lane == "A" else lane_b
    pricing_lane = primary["lane"]
    if market == "TEAM_TOTALS":
        team_name = home if team_totals_team == "HOME" else away
        selection = f"{team_name} {side} {line:g}"
    else:
        selection = (("OVER" if side == "OVER" else "UNDER")
                     if market == "TOTAL" else home if side == "HOME" else away)
        if market == "SPREAD":
            selection += f" {line:+g}"
        elif market == "TOTAL":
            selection += f" {line:g}"
        else:
            selection += " ML"
    reason = None
    if not quote_is_fresh(quote_freshness):
        # Preserve specific quote-freshness diagnosis ahead of the
        # lower-priority no-fetch model-coverage blocker. Both prevent picks.
        status = "WATCH_QUOTE_NOT_CURRENT"
        reason = "QUOTE_NOT_FRESH:" + quote_freshness["code"]
    elif not auto_context and sport == "NFL":
        # The opt-in, no-fetch analysis mode may display a hypothetical
        # projection for diagnostics. It MUST NOT elevate a league-prior
        # estimate to a ranked current-game candidate.
        status = "WATCH_NFL_NO_VERIFIED_CONTEXT"
        reason = "NFL_MANUAL_ONLY_MODE_HAS_NO_VERIFIED_TEAM_FACTORS"
    elif sport == "NFL" and market == "TOTAL":
        # This heuristic starts each NFL club at 22 points and incorporates
        # previous games only through bounded point DIFFERENTIALS and form.
        # A four-game ESPN history count does not prove an absolute offense /
        # opponent-defense total scoring expectation. Bills/Rams 54.5 exposed
        # the failure: a 44.15 prior-driven mean generated a fake +54% EV.
        # Both independent and anchored totals remain diagnostic until an
        # exact-production, PIT-safe NFL total model is tested vs closes.
        status = "WATCH_NFL_TOTAL_PRIOR_ONLY"
        reason = "NFL_ABSOLUTE_SCORING_RATE_MODEL_MISSING:22_PTS_PER_TEAM_PLUS_MARGIN_FORM_ONLY"
    elif price < -165:
        status = "PRICE_CAP"
    elif primary["ev_per_dollar"] >= min_ev:
        # Repair 5: this is an UNVALIDATED positive-EV estimate, never a
        # validated edge. Validated profitability is tracked separately and is
        # always False in this engine; only the harness can change that.
        status = POSITIVE_EV_STATUS
    else:
        status = "BELOW_THRESHOLD"
    # Architecture-conflict ruling (Oct 12 2026): a PLAY requires an
    # INDEPENDENT probability that does not borrow the sportsbook price.
    # When the anchored Lane B view is the primary view, its +EV is
    # anchored research only -- it can never take the positive-EV play
    # status. Demote to a named WATCH status with the mechanism visible.
    if pricing_lane == LANE_B and status == POSITIVE_EV_STATUS:
        status = ANCHORED_WATCH_STATUS
        reason = (ANCHORED_PLAY_BLOCK + ":"
                  + ("NO_VIG_BLEND_15PCT" if market == "ML"
                     else "MARKET_SHRINK_15PCT"))
    result = {"schema": "SPORTSEDGE_FREE_RESEARCH_V1", "status": status, "sport": sport,
            "game": f"{away} @ {home}", "selection": selection, "market": market,
            "odds_american": int(price), "line": line, "kickoff_utc": kickoff.isoformat(),
            "team_totals_team": team_totals_team if market == "TEAM_TOTALS" else None,
            "pricing_lane": pricing_lane,
            "pricing_provenance": provenance_for_game_result(
                {"pricing_lane": pricing_lane, "market": market}),
            "pricing_lanes": {"lane_a_independent": lane_a,
                              "lane_b_anchored": lane_b},
            "quote_freshness": quote_freshness,
            "estimate_p": primary["estimate_p"], "push_p": primary["push_p"],
            "loss_p": primary["loss_p"],
            "book_break_even_p": primary["book_break_even_p"],
            "edge_over_break_even_pp": primary["edge_over_break_even_pp"],
            "ev_per_dollar": primary["ev_per_dollar"],
            "fair_american": primary["fair_american"],
            "home_mean": primary["home_mean"],
            "away_mean": primary["away_mean"], "context": context,
            "context_notes": notes, "context_provenance": context_provenance,
            "context_quality": "HEURISTIC_UNVALIDATED",
            "independent_projection": lane_a,
            "market_anchor": anchor,
            "model_validation": "NOT_PROVEN_VS_CLOSE",
            "validated_profitability": False,
            "research_only": True,
            "model_p_authority": False, "official_authority": False,
            "staking_authority": False, "sharp_reference_compared": False}
    if reason is not None:
        result["reason"] = reason
    return result



def _pair_side(input_row, result):
    """Identify the selected bookmaker side; team names are exact normalized aliases."""
    market = result.get("market")
    side = str(input_row.get("side") or input_row.get("selection") or "").strip()
    key = PublicContext.key
    if market in {"TOTAL", "TEAM_TOTALS"}:
        # Calculate has already verified the associated team identity.
        return side.upper() if side.upper() in ("OVER", "UNDER") else (
            side.rsplit(" ", 1)[-1].upper()
            if market == "TEAM_TOTALS" and side.rsplit(" ", 1)[-1].upper() in {"OVER", "UNDER"}
            else None)
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
        # A matching game/line is not sufficient across period or settlement
        # contracts, or conflicting supplied sportsbook event identities.
        for field in ("period", "phase", "alternate", "settlement_type", "event_id", "dk_event_id"):
            if str(other_row.get(field) or "").strip().upper() != str(row.get(field) or "").strip().upper():
                return False
        if _pair_side(other_row, other) != expected_opposite:
            return False
        if market == "TEAM_TOTALS":
            return (other.get("line") == result.get("line")
                    and other.get("team_totals_team") == result.get("team_totals_team"))
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
    # Pairing requires contemporaneous, independently timestamped quotes.
    # A counterpart quote without a parseable capture time is NOT assumed
    # to be from the same screenshot: the pair is refused. When both
    # timestamps parse, the captures must be within 120 seconds of each
    # other, not merely unequal as strings.
    input_time = dt(row.get("quote_captured_at"))
    if len(compatible) == 1:
        counterpart_raw_time = rows[compatible[0]["input_index"]].get("quote_captured_at")
        matching_time = dt(counterpart_raw_time)
        if matching_time is None:
            projected["paired_market_status"] = (
                "COUNTERPART_QUOTE_TIMESTAMP_MISSING"
                if counterpart_raw_time in (None, "") else "INVALID_PAIR_QUOTE_TIMESTAMP"
            )
            return
        if input_time is None:
            projected["paired_market_status"] = (
                "QUOTE_TIMESTAMP_MISSING"
                if row.get("quote_captured_at") in (None, "") else "INVALID_PAIR_QUOTE_TIMESTAMP"
            )
            return
        skew = abs((input_time - matching_time).total_seconds())
        if skew > 120:
            projected["paired_market_status"] = "MISMATCHED_QUOTE_TIMESTAMPS"
            return
        projected["paired_quote_skew_seconds"] = skew
        projected["paired_quote_captured_at"] = [input_time.isoformat(), matching_time.isoformat()]
    else:
        # No compatible partner row exists: the partner price came solely
        # from this row's own opposite_odds field. An asserted field on the
        # same row is NOT a separately timestamped quote — there is no
        # counterpart observation, no event/period/settlement identity
        # check on a second quote, and no timestamp pair. It must not be
        # labeled an exact two-sided quote or yield a no-vig comparison,
        # regardless of this row's own capture time: timestamping the
        # assertion does not cure the missing counterpart, and the refusal
        # names that defect (not QUOTE_TIMESTAMP_MISSING, which would
        # falsely imply this quote itself lacked a timestamp).
        projected["paired_market_status"] = "OPPOSITE_PRICE_NOT_A_TIMESTAMPED_QUOTE"
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



def run(payload, *, now=None, as_of=None, historical=False, getter=None,
        auto_context=True, min_ev=0.02, lane="A", allow_manual_context=False,
        prepricing_adjustments=None):
    """Build a research card. ``now`` is wall-clock execution time; ``as_of``
    is the point-in-time clock the pricing must respect (defaults to ``now``).

    Set as_of + historical=True when repricing history: the provider then
    refuses current-state sources (injuries, forecasts) that free endpoints
    cannot snapshot as-of, instead of leaking today's values into the past.
    """
    lane = str(lane or "A").upper().strip()
    if lane not in ("A", "B"):
        raise ValueError("LANE_MUST_BE_A_OR_B")
    wall = now or datetime.now(timezone.utc)
    if wall.tzinfo is None or wall.utcoffset() is None:
        raise ValueError("AS_OF_TIMEZONE_REQUIRED")
    wall = wall.astimezone(timezone.utc)
    as_of = as_of if as_of is not None else wall
    if isinstance(as_of, str):
        as_of = dt(as_of)
    if as_of is None or as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("AS_OF_TIMEZONE_REQUIRED")
    as_of = as_of.astimezone(timezone.utc)
    rows = payload if isinstance(payload, list) else payload.get("lines") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise ValueError("LINES_MUST_BE_LIST")
    # Repair 4: snapshot the inputs as-of run time for reproducibility.
    canonical = json.dumps(rows, sort_keys=True, default=str)
    input_snapshot = {
        "n_rows": len(rows),
        "rows_sha1": hashlib.sha1(canonical.encode("utf-8")).hexdigest(),
        "as_of_utc": as_of.isoformat(),
        "wall_utc": wall.isoformat(),
        "historical_repriced": bool(historical),
    }
    provider = PublicContext(as_of, getter=getter, historical=historical)
    # A single-sport ticket may declare its sport once at the root.
    # Do not guess a sport from a team name or an ambiguous matchup.
    ticket_sport = payload.get("sport") if isinstance(payload, dict) else None
    all_rows = []
    # Prepricing adjustments are system-verified, separate from user context.
    # A user-supplied "prepricing_adjustments" field in the row is NEVER trusted;
    # only the explicitly passed prepricing_adjustments parameter is used.
    prepricing_list = prepricing_adjustments or []
    for i, row in enumerate(rows):
        try:
            if not isinstance(row, dict):
                raise ValueError("LINE_MUST_BE_OBJECT")
            bound_row = dict(row)
            # Strip any spoofed prepricing_adjustments from user intake
            bound_row.pop("prepricing_adjustments", None)
            if not bound_row.get("sport") and ticket_sport is not None:
                bound_row["sport"] = ticket_sport
            # Get system-verified prepricing for this row (if any)
            pp_adj = prepricing_list[i] if i < len(prepricing_list) else None
            result = calculate(bound_row, provider, as_of, auto_context=auto_context,
                               min_ev=min_ev, lane=lane,
                               allow_manual_context=allow_manual_context,
                               prepricing_adjustments=pp_adj)
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            result = {"status": "BLOCKED_INVALID", "reason": str(exc)[:140]}
        result["input_index"] = i
        all_rows.append(result)
    # Provenance gate (Oct 12 2026 ruling): stamp every priced row and
    # refuse MARKET_ANCHORED rows any play status before surfaces are
    # built. Anchored rows may surface at most as WATCH.
    apply_play_gate(all_rows)
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
        if (row.get("pricing_provenance") or {}).get(
                "lane") == PROVENANCE_MARKET_ANCHORED:
            # The row's primary probability borrowed the sportsbook price.
            # Even if its independent side-view clears the EV floor, the
            # row itself is anchored research: watch surface only.
            watchlist.append(row)
            continue
        if row.get("status") in {"WATCH_NFL_NO_VERIFIED_CONTEXT",
                                 "WATCH_NFL_TOTAL_PRIOR_ONLY"}:
            watchlist.append(row)
            continue
        # Repair 3: a stale quote cannot support a research candidate, even
        # when the model probability is strong. Watch-only, explicitly.
        if not quote_is_fresh(row.get("quote_freshness") or {}):
            watchlist.append(row)
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
    # Repair 2: Lane B is always computed and labeled, so the harness (and the
    # card) can evaluate the anchored hypothesis separately from Lane A.
    # Oct 12 2026 ruling: anchored EV is suppressed from every +EV / edges
    # presentation. Qualifying Lane B rows surface ONLY on the watchlist
    # below, with the anchored view labeled inside each row. The legacy
    # lane_b_edges field is retained, always empty, so downstream consumers
    # fail safe instead of rendering anchored "edges".
    lane_b_watchlist = []
    for r in all_rows:
        if r.get("status") in {"WATCH_NFL_NO_VERIFIED_CONTEXT",
                              "WATCH_NFL_TOTAL_PRIOR_ONLY"}:
            continue
        lanes = r.get("pricing_lanes") or {}
        lane_b = lanes.get("lane_b_anchored") or {}
        if lane_b.get("status") == "LANE_B_UNAVAILABLE":
            continue
        if not quote_is_fresh(r.get("quote_freshness") or {}):
            continue
        if r.get("odds_american", -999) < -165:
            continue
        if lane_b.get("ev_per_dollar", -1) >= min_ev:
            lane_b_watchlist.append(r)
    lane_b_watchlist.sort(key=lambda r: (-r["pricing_lanes"]["lane_b_anchored"]["ev_per_dollar"],
                                         r["game"], r["selection"]))
    lane_b_edges = []
    edges = [r for r in all_rows
             if r["status"] == POSITIVE_EV_STATUS and is_play_eligible(r)]
    edges.sort(key=lambda r: (-r["ev_per_dollar"], r["game"], r["selection"]))
    primary_lane = LANE_A if lane == "A" else LANE_B
    return {"schema": "SPORTSEDGE_FREE_RESEARCH_CARD_V1",
            "as_of_utc": as_of.isoformat(),
            "wall_utc": wall.isoformat(),
            "primary_lane": primary_lane,
            "input_snapshot": input_snapshot,
            "quote_freshness_policy": {
                "max_age_seconds": MAX_QUOTE_AGE_SECONDS,
                "stale_quotes_are_watch_only": True,
            },
            "authority": {"research_only": True, "official": False, "model_p": False,
                          "truth_gate": False, "staking": False,
                          "validated_profitability": False},
            "min_ev": min_ev, "edges": edges,
            "lane_b_edges": lane_b_edges,
            "lane_b_watchlist": lane_b_watchlist,
            "play_gate": {
                "rule": "INDEPENDENT_PROBABILITY_REQUIRED_FOR_PLAY",
                "anchored_max_surface": "WATCH",
                "anchored_ev_in_edges_lists": "SUPPRESSED",
                "undetermined_provenance": "FAIL_CLOSED",
            },
            "independent_candidates": independent,
            "independent_watchlist": watchlist,
            "research_projection_note": "Unvalidated independent league-score heuristic; DK is a paired same-book no-vig benchmark, not sharp market verification.",
            # Keep the complete graded, source-annotated rows for reproducible
            # factor coverage and honest diagnostics even when below threshold.
            "evaluated_rows": all_rows,
            "summary": {"rows": len(rows), "edges": len(edges),
                        "lane_b_edges": len(lane_b_edges),
                        "lane_b_watchlist": len(lane_b_watchlist),
                        "status_counts": dict(sorted(Counter(r["status"] for r in all_rows).items()))},
            "diagnostics": [{"input_index": r["input_index"], "status": r["status"],
                             "reason": r.get("reason") or ",".join(r.get("context_notes") or [])}
                            for r in all_rows if r["status"] != POSITIVE_EV_STATUS],
            "source_receipts": provider.receipts}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Free, UNVALIDATED research edges from supplied lines")
    parser.add_argument("--lines", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--no-fetch", action="store_true", help="Only manual context; still requires explicit future kickoff")
    parser.add_argument("--min-ev", type=float, default=0.02)
    parser.add_argument("--lane", choices=["A", "B"], default="A",
                        help="Primary pricing lane: A=independent (default, market-blind), "
                             "B=anchored (explicit 15%% shrink toward posted line, unvalidated)")
    parser.add_argument("--allow-manual-context", action="store_true",
                        help="Allow untrusted intake rows to override verified context factors; "
                             "every override is labeled USER_SUPPLIED_MANUAL in the audit")
    parser.add_argument("--as-of",
                        help="Point-in-time clock (ISO-8601) the pricing must respect; defaults to now")
    parser.add_argument("--historical", action="store_true",
                        help="Repricing history: refuse current-state sources (injuries, forecasts) "
                             "that cannot be snapshotted as-of instead of leaking today's values")
    args = parser.parse_args(argv)
    if not 0 <= args.min_ev <= 0.15:
        parser.error("min-ev outside [0, 0.15]")
    card = run(json.loads(args.lines.read_text(encoding="utf-8")),
               auto_context=not args.no_fetch, min_ev=args.min_ev, lane=args.lane,
               allow_manual_context=args.allow_manual_context,
               as_of=args.as_of, historical=args.historical)
    rendered = json.dumps(card, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
