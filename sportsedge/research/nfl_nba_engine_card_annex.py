"""Fail-closed, operator-pinned NFL/NBA engine research annex for RUN IT.

This readout never updates evaluated rows, registry state, watchlists, or plays.
History and fixtures must come from operator arguments, never issue/line payloads.
The separate SHA-256 pins must be supplied from an independent channel.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math

SCHEMA = "SPORTSEDGE_NFL_NBA_ENGINE_RESEARCH_ANNEX_V1"
NFL_FAMILIES = {
    "PASS_RUSH_YDS": "pass_plus_rush_yards",
    "PASS_PLUS_RUSH_YARDS": "pass_plus_rush_yards",
    "RUSH_REC_YDS": "rush_plus_rec_yards",
    "RUSH_PLUS_REC_YARDS": "rush_plus_rec_yards",
    "TARGETS": "targets",
    "PLAYER_TARGETS": "targets",
    "TWO_PLUS_TD": "two_plus_td",
    "FG_MADE": "fg_made",
    "FIELD_GOALS_MADE": "fg_made",
    "XP_MADE": "xp_made",
    "EXTRA_POINTS_MADE": "xp_made",
    "KICKING_POINTS": "kicking_points",
    "PLAYER_SACKS": "player_sacks",
    "TACKLES_ASSISTS": "tackles_assists",
    "DEFENSIVE_PLAYER_INTERCEPTIONS": "player_interceptions",
}
# PLAYER_INTERCEPTIONS denotes QB interceptions THROWN in RUN IT.
# The defensive family must never inherit that ambiguous legacy name.
NBA_FORMS = {
    "TEAM_TOTAL", "TEAM_TOTALS", "TEAM_QUARTER_TOTAL",
    "GAME_QUARTER_TOTAL", "QUARTER_TOTAL",
    "FIRST_QUARTER_TOTAL", "SECOND_QUARTER_TOTAL",
    "THIRD_QUARTER_TOTAL", "FOURTH_QUARTER_TOTAL",
    "TEAM_HALF_TOTAL", "GAME_HALF_TOTAL", "HALF_TOTAL",
    "FIRST_HALF_TOTAL", "SECOND_HALF_TOTAL",
}


def content_hash(value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                     ensure_ascii=True, allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _instant(value):
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("TIMESTAMP_TIMEZONE_REQUIRED")
    return dt.astimezone(timezone.utc)


def _name(row):
    return str(row.get("market") or "").strip().upper()


def _sport(row, default_sport):
    return str(row.get("sport") or default_sport or "").upper()


def _refused(index, sport, market, reason):
    return {"input_index": index, "sport": sport, "market": market,
            "status": "REFUSED", "reason": reason, "research_only": True,
            "eligible": False, "play_authority": False}


def _pins_ok(data, pins, key):
    if data is None or not isinstance(pins, dict) or not pins.get(key):
        return False
    try:
        return content_hash(data) == pins[key]
    except (TypeError, ValueError):
        return False


def _pair_ok(rows, row, *, at, event_id, sport, market, player_id, line):
    """Check a REAL two-sided DraftKings pair; never imply a missing side."""
    def side(r):
        return str(r.get("selection") or r.get("side") or "").upper()
    if side(row) not in {"OVER", "UNDER"}:
        return "TWO_SIDED_OU_REQUIRED"
    matching = []
    for other in rows:
        if not isinstance(other, dict):
            continue
        if _sport(other, None) != sport or _name(other) != market:
            continue
        if str(other.get("event_id") or other.get("book_event_id") or "") != event_id:
            continue
        if str(other.get("player_id") or "") != player_id:
            continue
        if str(other.get("line")) != str(line):
            continue
        book = str(other.get("book") or other.get("bookmaker") or "").upper()
        if book not in {"DRAFTKINGS", "DK"}:
            continue
        try:
            stamp = _instant(other.get("quote_captured_at"))
        except (TypeError, ValueError):
            continue
        age = (at - stamp).total_seconds()
        if age < 0 or age > 180:
            continue
        matching.append((side(other), stamp))
    overs = [s for side_name, s in matching if side_name == "OVER"]
    unders = [s for side_name, s in matching if side_name == "UNDER"]
    if not overs or not unders:
        return "DK_PAIR_MISSING_OR_STALE"
    if min(abs((o - u).total_seconds()) for o in overs for u in unders) > 120:
        return "DK_PAIR_CAPTURE_SPAN_EXCEEDED"
    return None


def build_annex(rows, evaluated, *, at, default_sport=None, history=None,
                fixtures=None, pins=None, nba_period_source=None):
    """Run *existing* engines from independently supplied evidence only.

    Explicit Python keyword arguments are required; issue payloads cannot
    supply history, fixture registry, SHA pins, or the frozen period-fit source.
    """
    if len(rows) != len(evaluated):
        raise ValueError("ANNEX_ROW_ALIGNMENT_REQUIRED")
    clock = _instant(at)
    history = history if isinstance(history, dict) else {}
    fixtures = fixtures if isinstance(fixtures, dict) else {}
    pins = pins if isinstance(pins, dict) else {}
    candidate = [(i, r, _sport(r, default_sport), _name(r))
                 for i, r in enumerate(rows) if isinstance(r, dict)
                 and ((_sport(r, default_sport) == "NFL" and _name(r) in NFL_FAMILIES)
                      or (_sport(r, default_sport) == "NBA" and _name(r) in NBA_FORMS))]
    if not candidate:
        return None
    result = {"schema": SCHEMA, "section_label": "RESEARCH_ONLY",
              "validation_state": "UNVALIDATED_ESTIMATE",
              "official_authority": False, "play_authority": False,
              "staking_authority": False, "eligible": False,
              "readouts": []}
    fixture_pin_ok = _pins_ok(fixtures, pins, "fixtures_sha256")
    history_pin_ok = {sport: _pins_ok(history.get(sport), pins,
                                  sport.lower() + "_history_sha256")
                      for sport in ("NFL", "NBA")}
    for index, row, sport, market in candidate:
        def refuse(reason):
            result["readouts"].append(_refused(index, sport, market, reason))
        if not fixture_pin_ok:
            refuse("OPERATOR_FIXTURE_PIN_MISSING_OR_MISMATCH")
            continue
        if not history_pin_ok[sport]:
            refuse("OPERATOR_HISTORY_PIN_MISSING_OR_MISMATCH")
            continue
        event_id = str(row.get("event_id") or row.get("book_event_id") or "")
        fixture = fixtures.get(event_id)
        if not event_id or not isinstance(fixture, dict):
            refuse("FIXTURE_ID_UNBOUND")
            continue
        if fixture.get("sport") != sport or str(fixture.get("event_id")) != event_id:
            refuse("FIXTURE_SPORT_OR_EVENT_MISMATCH")
            continue
        if str(fixture.get("venue_state") or "").upper() == "TN" or any(
                "TENNESSEE" in str(fixture.get(x) or "").upper()
                for x in ("venue", "home", "away")):
            refuse("TENNESSEE_FIXTURE_BLOCKED")
            continue
        try:
            if _instant(fixture["start_time"]) <= clock:
                refuse("FIXTURE_ALREADY_STARTED")
                continue
        except (ValueError, KeyError, TypeError):
            refuse("FIXTURE_START_TIME_UNVERIFIED")
            continue
        player_id = str(row.get("player_id") or "")
        try:
            line = float(row.get("line"))
            if not math.isfinite(line):
                raise ValueError("nonfinite")
        except (ValueError, TypeError):
            refuse("FINITE_LINE_REQUIRED")
            continue
        if market == "TWO_PLUS_TD":
            # Not a two-sided O/U: no market-set admission exists.
            refuse("ONE_SIDED_MARKET_NOT_ADMITTED")
            continue
        pair_reason = _pair_ok(rows, row, at=clock, event_id=event_id,
                               sport=sport, market=market,
                               player_id=player_id, line=row.get("line"))
        if pair_reason:
            refuse(pair_reason)
            continue
        if sport == "NFL":
            if not player_id:
                refuse("PLAYER_ID_UNBOUND")
                continue
            if not isinstance(fixture.get("season"), int) or not isinstance(
                    fixture.get("week"), int) or fixture["week"] < 1:
                refuse("NFL_PIT_SEASON_WEEK_UNVERIFIED")
                continue
            try:
                # The v1 engine excludes >= target week; earlier-season
                # pool fallback is already part of its frozen construction.
                from sportsedge.nfl_prop_engines_v1 import price_nfl_prop
                estimate = price_nfl_prop(
                    NFL_FAMILIES[market], player_id, line,
                    history["NFL"], fixture["season"], fixture["week"])
            except Exception as exc:
                refuse("NFL_ENGINE_FAILED:" + type(exc).__name__)
                continue
            if estimate.get("status") != "PRICED":
                refuse("NFL_ENGINE_" + str(estimate.get("reason") or estimate.get("status")))
                continue
            projection = {"engine": estimate.get("engine"),
                          "family": NFL_FAMILIES[market],
                          "mean": estimate.get("mu"),
                          "p_over": estimate.get("p_over"),
                          "p_under": estimate.get("p_under"),
                          "prior_games": estimate.get("games_logged")}
        else:
            home, away = fixture.get("home"), fixture.get("away")
            if not home or not away or home == away or not isinstance(
                    fixture.get("season"), int) or not fixture.get("target_date"):
                refuse("NBA_FIXTURE_IDENTITY_INCOMPLETE")
                continue
            try:
                if str(fixture["target_date"]) != _instant(
                        fixture["start_time"]).date().isoformat():
                    refuse("NBA_TARGET_DATE_MISMATCH")
                    continue
                from sportsedge.nba_team_period_engine import price_game
                estimate = price_game(
                    history["NBA"], home, away, season=fixture["season"],
                    target_date=fixture["target_date"],
                    period_source=nba_period_source)
            except Exception as exc:
                refuse("NBA_ENGINE_FAILED:" + type(exc).__name__)
                continue
            if estimate.get("status") != "PRICED":
                refuse("NBA_ENGINE_" + str(estimate.get("reason") or estimate.get("status")))
                continue
            if market not in {"TEAM_TOTAL", "TEAM_TOTALS"} and (
                    estimate.get("periods", {}).get("status") != "PRICED"):
                refuse("NBA_PERIOD_" + str(
                    estimate.get("periods", {}).get("reason") or "UNAVAILABLE"))
                continue
            projection = {"engine": estimate.get("engine_id"),
                          "team_totals": estimate.get("team_totals"),
                          "periods": estimate.get("periods") if market not in {
                              "TEAM_TOTAL", "TEAM_TOTALS"} else None,
                          "calibration_label": estimate.get("calibration_label"),
                          "market_test": estimate.get("market_test")}
        result["readouts"].append({
            "input_index": index, "sport": sport, "market": market,
            "status": "RESEARCH_ESTIMATE_UNVALIDATED",
            "event_id": event_id, "research_only": True,
            "eligible": False, "play_authority": False,
            "projection": projection,
        })
    return result
