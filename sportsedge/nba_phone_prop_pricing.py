"""Phone-only NBA player-prop intake: user odds, independently held history.

The user's JSON supplies quotes and player display names, never a
probability or history. Pricing comes solely from
``sportsedge.nba_prop_empirical`` (the Oct 17/18 calibration
construction: a player's point-in-time prior same-season game logs,
smoothed k=5 toward the per-position league pool) over a game-log
store the operator supplies locally — the verified sportsdataverse
box-score pull shape (``scripts/pull_nba_results.py``), joined with
game dates and roster positions from sidecar files. Nothing is
fetched at pricing time and nothing is read from the intake row
beyond the quote and the player's display name.

Store directory contract (``SPORTSEDGE_NBA_PROP_STORE_DIR`` or the
``store_dir`` argument):

* ``nba_player_games_*.csv`` — one or more pull-output files
  (PLAYER_ID / PLAYER_NAME / GAME_ID / MIN / PTS / REB / AST).
* ``game_dates.csv`` — GAME_ID,GAME_DATE for every game in the pull
  (the asset carries no dates; a row whose game has no date cannot
  be point-in-time ordered and is dropped by the engine's store).
* ``positions.csv`` — PLAYER_ID,POSITION roster abbreviations
  (G / F / C, compounds like G-F resolve by first character, exactly
  as in the calibration programs). A player with no verified
  position is outside the construction's universe and cannot price.

With no store available, every row in the four registered families
fails closed with NBA_PROP_HISTORY_STORE_UNAVAILABLE. Research only:
the families are REGISTERED_RESEARCH_ONLY / NOT_VALIDATED, no market
test exists, and no row here can become a PLAY.
"""
from __future__ import annotations

import csv
import glob
import math
import os
import re
import unicodedata
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .family_market_registry import (
    NBA_RESEARCH_REGISTERED_FAMILIES, family_market_decision)
from .nba_prop_empirical import (
    ENGINE_ID, GameLogStore, records_from_boxscore_rows)

FAMILY_TO_STAT = {"player_points": "points", "player_rebounds": "rebounds",
                  "player_assists": "assists", "player_pra": "pra"}
STORE_ENV_VAR = "SPORTSEDGE_NBA_PROP_STORE_DIR"
QUOTE_FRESH_SECONDS = 180

# The capture pipeline's slate timezone: the DK archive and slate
# dates are CT-anchored, so a UTC tipoff instant is reduced to its
# Chicago calendar date (see _target_date).
_SLATE_TZ = ZoneInfo("America/Chicago")
_BARE_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DATE_KEYS = ("kickoff", "commence_time", "start_time", "game_start",
              "tipoff", "game_date", "date")

STORE_UNAVAILABLE = "NBA_PROP_HISTORY_STORE_UNAVAILABLE"
IDENTITY_MISSING = "NBA_PROP_PLAYER_IDENTITY_MISSING"
PLAYER_NOT_IN_STORE = "NBA_PROP_PLAYER_NOT_IN_STORE"
IDENTITY_AMBIGUOUS = "NBA_PROP_PLAYER_IDENTITY_AMBIGUOUS"
TARGET_DATE_UNVERIFIED = "NBA_PROP_TARGET_DATE_UNVERIFIED"
LINE_MISSING = "NBA_PROP_LINE_MISSING"
SIDE_UNVERIFIED = "NBA_PROP_SIDE_UNVERIFIED"
QUOTE_PRICE_MISSING = "NBA_PROP_QUOTE_PRICE_MISSING"
QUOTE_PRICE_INVALID = "NBA_PROP_QUOTE_PRICE_INVALID"
QUOTE_TIMESTAMP_MISSING = "NBA_PROP_QUOTE_TIMESTAMP_MISSING"
QUOTE_TIMESTAMP_INVALID = "NBA_PROP_QUOTE_TIMESTAMP_INVALID"
QUOTE_TIMESTAMP_CONFLICT = "NBA_PROP_QUOTE_TIMESTAMP_CONFLICT"
BOOK_UNVERIFIED = "NBA_PROP_BOOK_UNVERIFIED"
QUOTE_NOT_PRE_EVENT = "NBA_PROP_QUOTE_NOT_PRE_EVENT"
TARGET_START_INVALID = "NBA_PROP_TARGET_START_INVALID"
TARGET_START_CONFLICT = "NBA_PROP_TARGET_START_CONFLICT"
TARGET_DATE_CONFLICT = "NBA_PROP_TARGET_DATE_CONFLICT"


def nba_prop_family_for_market(market):
    """Canonical registered NBA prop family for an intake spelling,
    or None. Single source of truth: the family registry."""
    decision = family_market_decision("NBA", market)
    if decision is None:
        return None
    family = decision.get("market")
    return family if family in NBA_RESEARCH_REGISTERED_FAMILIES else None


def _norm_name(name) -> str:
    text = unicodedata.normalize("NFKD", str(name or ""))
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join("".join(c.lower() if c.isalnum() else " "
                            for c in text).split())


def _parse_instant(value):
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str) and value.strip():
        try:
            dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if dt.tzinfo is None or dt.utcoffset() is None:
        return None
    return dt.astimezone(timezone.utc)


def _parse_aware(value):
    """``value`` as an aware datetime in its OWN offset, or None.

    Same acceptance rules as ``_parse_instant`` (datetime objects and
    ISO strings; a value carrying no offset is not an instant), but the
    stated offset is preserved instead of normalized to UTC.
    """
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str) and value.strip():
        try:
            dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if dt.tzinfo is None or dt.utcoffset() is None:
        return None
    return dt


def _target_date(row):
    """The target game's LOCAL calendar date for the PIT slices.

    ``GameLogStore.price``'s contract: ``target_date`` is the target
    game's calendar date, and every slice admits only games with
    ``game_date < target_date`` — where the store's game dates are
    local calendar dates (``game_dates.csv``). An instant tipoff must
    therefore be reduced to a calendar date in the timezone the
    instant is anchored to, never in UTC: taking the UTC date (the
    pre-fix behavior) rolls every tip at/after 19:00 CT to the next
    day and admits same-day finals into the player, pool, and league
    prior slices.

    Preference order over the row's date-bearing keys:

    (a) a bare date (``YYYY-MM-DD``) on any key is already the game's
        local calendar date — return it unchanged;
    (b) an instant carrying a non-UTC offset — the calendar date in
        that offset;
    (c) a UTC instant — convert it to America/Chicago (the capture
        pipeline's slate timezone; the DK archive and slate dates
        are CT-anchored) and take that date.
    """
    values = [row.get(key) for key in _DATE_KEYS]
    for value in values:
        if isinstance(value, str) and _BARE_DATE_RE.match(value.strip()):
            try:
                return date.fromisoformat(value.strip())
            except ValueError:
                continue
    for value in values:
        if value is None:
            continue
        aware = _parse_aware(value)
        if aware is not None:
            if aware.utcoffset() == timedelta(0):
                return aware.astimezone(_SLATE_TZ).date()
            return aware.date()
        if isinstance(value, str) and len(value.strip()) >= 10:
            try:
                return datetime.fromisoformat(value.strip()[:10]).date()
            except ValueError:
                continue
    return None


def _american_to_decimal(odds):
    """Parse integer American odds only; never coerce NaN, inf, bool or decimals.

    This is syntax validation, NOT an authenticated DraftKings quote.
    """
    if isinstance(odds, bool) or odds is None:
        return None
    if isinstance(odds, int):
        value = odds
    elif isinstance(odds, str) and re.fullmatch(r"[+-]?[0-9]+", odds.strip()):
        try:
            value = int(odds.strip())
        except ValueError:
            return None
    else:
        return None
    if abs(value) < 100:
        return None
    try:
        decimal = 1.0 + (value / 100.0 if value > 0 else 100.0 / abs(value))
    except OverflowError:
        return None
    return decimal if math.isfinite(decimal) and decimal > 1.0 else None


def _fair_american(p_win: float, p_lose: float):
    denom = p_win + p_lose
    if denom <= 0:
        return None
    p = p_win / denom
    if p <= 0.0 or p >= 1.0:
        return None
    if p >= 0.5:
        return -round(100.0 * p / (1.0 - p))
    return round(100.0 * (1.0 - p) / p)


# ---------- store loading -----------------------------------------------------

def load_store_from_dir(store_dir):
    """Read the operator's current local NBA store, or fail closed.

    The old process-global cache retained a negative load forever after an
    initially empty/incomplete directory and also retained SUCCESS after
    the same path received new games. Both violate the declared PIT source
    snapshot used for prospective pricing. A pricing batch calls this once,
    so reload per batch rather than trusting the previous invocation's
    directory contents. No synthetic data or cross-season fallback.
    """
    if not store_dir:
        return None, STORE_UNAVAILABLE
    return _load_store_uncached(os.path.abspath(str(store_dir)))


def _load_store_uncached(key):
    try:
        pull_files = sorted(glob.glob(os.path.join(key, "nba_player_games_*.csv")))
        dates_path = os.path.join(key, "game_dates.csv")
        positions_path = os.path.join(key, "positions.csv")
        if not pull_files or not os.path.exists(dates_path) \
                or not os.path.exists(positions_path):
            return None, STORE_UNAVAILABLE
        rows = []
        for path in pull_files:
            with open(path, newline="", encoding="utf-8") as fh:
                rows.extend(dict(r) for r in csv.DictReader(fh))
        game_dates = {}
        with open(dates_path, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                rr = {str(k).strip().upper(): v for k, v in r.items()}
                gid = str(rr.get("GAME_ID") or "").strip()
                gdate = str(rr.get("GAME_DATE") or rr.get("DATE") or "").strip()
                if gid and gdate:
                    game_dates[gid] = gdate
        positions = {}
        with open(positions_path, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                rr = {str(k).strip().upper(): v for k, v in r.items()}
                pid = str(rr.get("PLAYER_ID") or "").strip()
                pos = str(rr.get("POSITION") or rr.get("POS") or "").strip()
                if pid and pos:
                    positions[pid] = pos
        if not rows or not game_dates or not positions:
            return None, STORE_UNAVAILABLE
        records = records_from_boxscore_rows(rows, game_dates, positions)
        store = GameLogStore(records)
        if not store.player_ids():
            return None, STORE_UNAVAILABLE
        receipt = {
            "source": "SPORTSEDGE_NBA_PROP_STORE_DIR",
            "status": "NBA_PROP_STORE_LOADED",
            "store_dir": key,
            "pull_files": [os.path.basename(p) for p in pull_files],
            "players": len(store.player_ids()),
            "records_kept": store.counters["records_kept"],
            "store_counters": dict(store.counters),
            "engine_id": ENGINE_ID,
        }
        return store, receipt
    except (OSError, UnicodeDecodeError, csv.Error, TypeError, ValueError):
        return None, STORE_UNAVAILABLE


def _resolve_store(store, store_dir):
    if store is not None:
        return store, {"source": "SPORTSEDGE_NBA_PROP_STORE_OBJECT",
                       "status": "NBA_PROP_STORE_SUPPLIED",
                       "players": len(store.player_ids()),
                       "records_kept": store.counters["records_kept"],
                       "engine_id": ENGINE_ID}
    directory = store_dir or os.environ.get(STORE_ENV_VAR)
    loaded, receipt_or_reason = load_store_from_dir(directory)
    if loaded is None:
        return None, receipt_or_reason
    return loaded, receipt_or_reason


# ---------- row pricing ---------------------------------------------------------

def _blocked(row, family, reason):
    return {"status": "NO_MODEL_OR_MARKET", "reason": str(reason)[:180],
            "blocker": str(reason),
            "sport": "NBA", "market": row.get("market"),
            "coverage_market": family,
            "selection": row.get("side") or row.get("selection"),
            "player_name": row.get("player_name") or row.get("label"),
            "research_only": True, "official_authority": False,
            "model_p_authority": False, "staking_authority": False,
            "registry_enforced": True,
            "registry_module": "sportsedge.registry_gate",
            "family_decision": family_market_decision(
                "NBA", row.get("market"))}


def phone_nba_prop_rows(rows, *, now=None, store=None, store_dir=None,
                        min_ev=0.02):
    """Price NBA PTS/REB/AST/PRA rows through the empirical engine.

    Returns (outputs, receipts), one output per input row, in order.
    Every output is either a priced research row (registration +
    engine stamps, INDEPENDENT provenance) or a fail-closed blocked
    row naming its reason.
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("NOW_TIMEZONE_REQUIRED")
    resolved_store, receipt = _resolve_store(store, store_dir)
    receipts = [receipt] if isinstance(receipt, dict) else [{
        "source": "SPORTSEDGE_NBA_PROP_STORE_DIR",
        "status": "NBA_PROP_STORE_UNAVAILABLE",
        "reason": receipt}]
    name_index = {}
    if resolved_store is not None:
        for pid in resolved_store.player_ids():
            name_index.setdefault(
                _norm_name(resolved_store.player_name(pid)), set()).add(pid)
    outputs = []
    for row in rows:
        family = nba_prop_family_for_market(row.get("market"))
        if family is None:
            outputs.append(_blocked(row, None, "NBA_PROP_MARKET_NOT_SUPPORTED"))
            continue
        if resolved_store is None:
            outputs.append(_blocked(row, family, STORE_UNAVAILABLE))
            continue
        name = str(row.get("player_name") or row.get("label") or "").strip()
        if not name:
            outputs.append(_blocked(row, family, IDENTITY_MISSING))
            continue
        candidates = name_index.get(_norm_name(name), set())
        if not candidates:
            outputs.append(_blocked(row, family, PLAYER_NOT_IN_STORE))
            continue
        if len(candidates) > 1:
            outputs.append(_blocked(row, family, IDENTITY_AMBIGUOUS))
            continue
        player_id = next(iter(candidates))
        target = _target_date(row)
        if target is None:
            outputs.append(_blocked(row, family, TARGET_DATE_UNVERIFIED))
            continue
        try:
            raw_line = row["line"]
            if isinstance(raw_line, bool):
                raise ValueError("boolean line")
            line = float(raw_line)
            if not math.isfinite(line) or line < 0:
                raise ValueError("nonfinite or negative stat line")
        except (KeyError, TypeError, ValueError, OverflowError):
            outputs.append(_blocked(row, family, LINE_MISSING))
            continue
        side = str(row.get("side") or row.get("selection") or "").upper()
        if side not in {"OVER", "UNDER"}:
            outputs.append(_blocked(row, family, SIDE_UNVERIFIED))
            continue
        raw_odds = row.get("odds", row.get("price"))
        decimal = _american_to_decimal(raw_odds)
        if decimal is None:
            reason = (QUOTE_PRICE_MISSING if raw_odds is None or raw_odds == ""
                      else QUOTE_PRICE_INVALID)
            outputs.append(_blocked(row, family, reason))
            continue
        # Both aliases may be present in archived/phone rows. Refuse a
        # disagreement rather than silently selecting one clock for EV.
        quote_values = [row[key] for key in ("quote_captured_at", "captured_at")
                        if key in row and row[key] is not None
                        and row[key] != ""]
        if not quote_values:
            outputs.append(_blocked(row, family, QUOTE_TIMESTAMP_MISSING))
            continue
        parsed_quotes = [_parse_instant(value) for value in quote_values]
        if any(value is None for value in parsed_quotes):
            outputs.append(_blocked(row, family, QUOTE_TIMESTAMP_INVALID))
            continue
        if any(value != parsed_quotes[0] for value in parsed_quotes[1:]):
            outputs.append(_blocked(row, family, QUOTE_TIMESTAMP_CONFLICT))
            continue
        quote_ts = parsed_quotes[0]
        # A syntactically fresh quote can still be post-tip. Compare against
        # the asserted aware fixture start before any empirical model call.
        # This does not authenticate the fixture or the quote source.
        start_keys = ("kickoff", "commence_time", "start_time",
                      "game_start", "tipoff")
        supplied_starts = [row[key] for key in start_keys
                           if key in row and row[key] is not None
                           and row[key] != ""]
        if supplied_starts:
            parsed_starts = [_parse_instant(value) for value in supplied_starts]
            if any(start is None for start in parsed_starts):
                outputs.append(_blocked(row, family, TARGET_START_INVALID))
                continue
            if any(start != parsed_starts[0] for start in parsed_starts[1:]):
                outputs.append(_blocked(row, family, TARGET_START_CONFLICT))
                continue
            if quote_ts >= parsed_starts[0]:
                outputs.append(_blocked(row, family, QUOTE_NOT_PRE_EVENT))
                continue
            # The model's history slice must use the SAME local date as the
            # asserted start. A conflicting date silently changes the PIT
            # sample even when both clock values are individually pre-tip.
            start_local_date = parsed_starts[0].astimezone(_SLATE_TZ).date()
            if target != start_local_date:
                outputs.append(_blocked(row, family, TARGET_DATE_CONFLICT))
                continue
            for date_key in ("game_date", "date"):
                raw_date = row.get(date_key)
                if raw_date is None or raw_date == "":
                    continue
                if isinstance(raw_date, str) and _BARE_DATE_RE.fullmatch(raw_date.strip()):
                    try:
                        stated_date = date.fromisoformat(raw_date.strip())
                    except ValueError:
                        stated_date = None
                else:
                    stated_instant = _parse_instant(raw_date)
                    stated_date = (stated_instant.astimezone(_SLATE_TZ).date()
                                   if stated_instant is not None else None)
                if stated_date != start_local_date:
                    outputs.append(_blocked(row, family, TARGET_DATE_CONFLICT))
                    break
            else:
                pass
            if outputs and outputs[-1].get("blocker") == TARGET_DATE_CONFLICT:
                continue
        # A caller-supplied book is only a research assertion, never provider
        # authentication. Never manufacture DraftKings attribution from absence.
        raw_book = row.get("book")
        if not isinstance(raw_book, str) or not raw_book.strip():
            outputs.append(_blocked(row, family, BOOK_UNVERIFIED))
            continue
        book = raw_book.strip()
        priced = resolved_store.price(
            player_id, FAMILY_TO_STAT[family], line, target)
        if priced.get("status") != "PRICED":
            outputs.append(_blocked(row, family, priced.get("reason")))
            continue
        p_win = priced["p_over"] if side == "OVER" else priced["p_under"]
        p_lose = priced["p_under"] if side == "OVER" else priced["p_over"]
        ev = p_win * (decimal - 1.0) - p_lose
        age = (now - quote_ts).total_seconds()
        stale = age > QUOTE_FRESH_SECONDS or age < 0
        freshness = "STALE_OR_FUTURE" if stale else "CURRENT"
        if stale:
            status = "WATCH_QUOTE_NOT_CURRENT"
        elif ev >= min_ev:
            status = "RESEARCH_CANDIDATE_NOT_VALIDATED"
        else:
            status = "PRICED_RESEARCH"
        decision = family_market_decision("NBA", row.get("market"))
        outputs.append({
            "status": status,
            "sport": "NBA",
            "market": row.get("market"),
            "coverage_market": family,
            "selection": side,
            "side": side,
            "player_name": priced["player_name"],
            "player_id": player_id,
            "line": line,
            "odds": row.get("odds", row.get("price")),
            "book": book,
            "book_provenance": "CALLER_ASSERTED_NOT_AUTHENTICATED",
            "quote_captured_at": row.get("quote_captured_at")
                                 or row.get("captured_at"),
            "quote_freshness": freshness,
            "model_p": p_win,
            "model_probability": p_win,
            "model_source": ENGINE_ID,
            "p_over": priced["p_over"], "p_under": priced["p_under"],
            "p_push": priced["p_push"],
            "fair_american": _fair_american(p_win, p_lose),
            "ev_per_dollar": ev,
            "lean_label": "UNVALIDATED_ESTIMATE",
            "pricing_provenance": {
                "lane": "INDEPENDENT", "mechanism": None,
                "source": "NBA_PROP_EMPIRICAL_V1_MARKET_BLIND",
                "engine_lane": None, "play_eligible": False},
            "nba_prop_engine": {
                "engine_id": ENGINE_ID,
                "sufficiency_met": True,
                "n_prior": priced["n_prior"],
                "pool_n": priced["pool_n"],
                "pool_source": priced["pool_source"],
                "b1_fallback_to_b2": priced["b1_fallback_to_b2"],
                "weight_player": priced["weight_player"],
                "weight_pool": priced["weight_pool"],
                "k_smooth": priced["k_smooth"],
                "model_mean": priced["model_mean"],
                "position_group": priced["position_group"],
                "history_basis": priced["history_basis"],
                "participation_feed": priced["participation_feed"],
                "limitation": priced["limitation"],
                "construction": priced["construction"],
            },
            "family_decision": decision,
            "registration_state": decision["registration_state"],
            "validation_status": decision["validation_status"],
            "eligible": False, "promotable": False,
            "research_only": True, "official_authority": False,
            "model_p_authority": False, "staking_authority": False,
            "registry_enforced": True,
            "registry_module": "sportsedge.registry_gate",
            "registry_disposition":
                "RESEARCH_PRICING_ALLOWED_ENGINE_SUFFICIENCY_MET",
        })
    return outputs, receipts
