"""Market-baseline loaders for the backtest harness. Research only.

Fills the harness's ``market_baseline`` slot (see runner.run_backtest):
``lookup(fixture_id, market, selection, line) -> float | None`` — the
no-vig market-implied probability for the requested market/selection/line,
or None when the baseline is MISSING for that record. Prices are never
invented: any gap (no archived game, no two-sided quote, line mismatch,
unparseable row) returns None.

Fixture-id contract (the price-adapter author must use this format for the
baseline leg to join)::

    "sport:YYYY-MM-DD:away_full_name:home_full_name"

e.g. "nfl:2024-09-05:Baltimore Ravens:Kansas City Chiefs".
``sport`` in {nfl, cfb, mlb, nba}; the date is the LEAGUE-LOCAL date
(America/New_York — the reporting timezone for NFL odds, SBR listings,
and the archive's US-region captures), NOT the UTC date. US evening games
commence after midnight UTC; build the id with fixture_id_for_game() to
get this right. Names are the ESPN/StatsAPI display names. Each source
adapter normalizes to its own team tokens internally. The keys-backed
archive (the only UTC-dated source) dual-indexes games under the UTC date
and the previous day, which is collision-safe for its sports (NFL/CFB/UFC
never repeat a matchup on consecutive days).

Red-team guards (Isaac's standing "try to break it" directive): every
loader fails closed with an explicit BASELINE_* code —
- misaligned timestamps: archive rows must match their partition-file
  date (BASELINE_ARCHIVE_DATE_MISMATCH); MLB date keys must agree with
  startDate (BASELINE_MLB_DATE_MISMATCH); nflverse gameday must agree
  with the season column (BASELINE_NFLVERSE_SEASON_MISMATCH); NBA dates
  must agree with the season label (BASELINE_NBA_SEASON_MISMATCH);
- timezone confusion: naive/unparseable timestamps refused; archive rows
  must satisfy captured_at < commence_time and the capture lead must fit
  the claimed window (BASELINE_WINDOW_LEAD_MISMATCH), cross-checked
  against the row's own scheduled_lead_minutes field;
- book mislabeling: the archive accepts DraftKings rows only
  (BASELINE_BOOK_UNEXPECTED); the MLB median fallback synthesizes across
  books in decimal space and refuses violent cross-book disagreement
  (BASELINE_BOOK_DISPERSION_EXCEEDED) instead of returning fiction;
- duplicate rows: exact duplicates are harmless and counted; rows that
  contradict each other quarantine the game (BASELINE_*_CONTRADICTORY_
  DUPLICATE -> BASELINE_GAME_QUARANTINED) without nuking the file;
- wrong-season/truncated files: per-season counts are reported in
  coverage(); NflverseBaseline.assert_min_season_games() lets callers
  fail closed explicitly (BASELINE_SEASON_COVERAGE_SHORT); every
  individual gap still returns None (MISSING), never an invented price.
Skip reasons are counted per code in stats["skip_reasons"] and surfaced
via coverage() so validation reports can audit data quality.

Baseline sources, in composite precedence order:

1. ``ClosingLineArchive`` — PRIMARY, keys-backed, forward-only. Reads the
   data-branch archive written by .github/workflows/closing-line-archive.yml
   (CLOSING_LINE_ARCHIVE_V1, V3 transport):
   ``archive/closing-lines/{sport_key}/{date}.ndjson``. DraftKings only,
   US region, american odds, windows close (2-20 min pre-start) preferred,
   t0_prestart (0-5 min) fallback; "decision" window never used. Populated
   by GitHub Actions with ${{ secrets.SPORTSEDGE_ODDS_API_KEY* }}; EMPTY
   until dispatched -> MISSING. Rows are evidence_class NOT_EVIDENCE:
   that doctrine governs promotion/production authority, not research
   comparison — the archive's stated purpose is model-free closing-price
   archival, which is exactly what the baseline leg consumes.

2. ``NflverseBaseline`` — NFL historical. nflverse/nflverse-data schedules
   release, games.csv (CC-BY-4.0, attribution in README). Documented
   closing consensus lines (Pro-Football-Reference sourced) 1999-present;
   moneylines + closing juice 2010-present. Single consensus value per
   game (no per-book breakdown). Rows for not-yet-played games carry
   opener/current lines, NOT closes — the harness only queries completed
   fixtures, so the join handles this; do not use this file to price the
   future.

3. ``SbrMlbBaseline`` — MLB historical. ArnavSaraogi/mlb-odds-scraper
   release asset mlb_odds_dataset.json (SBR-derived, opening+current lines,
   6 books incl. DraftKings, 2021-04-01..2025-08-16). No explicit license
   file in that repo: used here as factual reference only, never
   redistributed; attribution documented. Book selection: DraftKings when
   present, else median across available books in DECIMAL space (never
   average American odds directly — the -100/+100 discontinuity corrupts
   means). "currentLine" is the closing line for historically scraped
   dates. Team-name quirk: the dataset uses current franchise names for
   all seasons ("Cleveland Guardians" even in 2021) — aliased internally.

4. ``NbaLinesBaseline`` — NBA historical. shawnmcgee/degenpredicts
   data/nba/lines.csv: compiler-aggregated closing lines, SBR-derived
   closing moneylines 2007-08 on (~96.5% coverage). Spreads/totals exist
   as lines only (no closing juice in the file) -> MISSING by design.
   No explicit license file: factual reference only, attribution
   documented. NBA outcomes are not yet wired in the harness; the loader
   is ready for when they are.

Book-selection and vig policy (documented per source above): probabilities
are no-vig normalized (each side's implied probability divided by the
two-sided overround). Spread/total baselines require the model's line to
EXACTLY equal the archived closing point — otherwise None (we only compare
against prices the market actually offered).

Market mapping: ML/MONEYLINE -> h2h (line must be None), SPREAD ->
spreads, TOTAL -> totals. Selections: HOME/AWAY for ML/SPREAD (from the
selection's perspective, matching outcomes.settle_game), OVER/UNDER for
TOTAL.

All timestamps are normalized to tz-aware UTC; naive or unparseable
timestamps fail closed (row skipped, counted). Captured rows must satisfy
captured_at < commence_time.

No secrets are read here: the archive is consumed from its data-branch
checkout; open datasets from local files. Nothing in this module touches
the network or any API key.
"""
from __future__ import annotations

import csv
import json
import math
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

UTC = timezone.utc
# Canonical "league date": US Eastern, the reporting timezone for NFL odds
# (nflverse gametime), SBR listings, and the archive's US-region captures.
# A fixture id's date component is ALWAYS this local date, never the UTC
# date — see fixture_id_for_game. (MLB/NBA sources natively use local
# dates; the archive natively uses UTC dates and is dual-indexed.)
LEAGUE_TZ = ZoneInfo("America/New_York")


class BaselineError(ValueError):
    pass


# ---------------------------------------------------------------------------
# Shared math
# ---------------------------------------------------------------------------

def american_to_decimal(american) -> float:
    """American odds -> decimal odds. Rejects non-numeric and the -100/+100 gap."""
    try:
        a = float(american)
    except (TypeError, ValueError) as exc:
        raise BaselineError("BASELINE_PRICE_UNVERIFIED:%r" % (american,)) from exc
    if not math.isfinite(a):
        raise BaselineError("BASELINE_PRICE_INVALID:%r" % (american,))
    # American odds have no values in [-100, 100); 0 is never valid.
    # (+100 is valid; -100 does not exist.)
    if a == 0 or -100 <= a < 100:
        raise BaselineError("BASELINE_PRICE_INVALID:%r" % (american,))
    if a > 0:
        return 1.0 + a / 100.0
    return 1.0 + 100.0 / abs(a)


def no_vig_probs(decimals: dict[str, float]) -> dict[str, float]:
    """Decimal odds -> no-vig probabilities (overround removed)."""
    implied = {}
    for side, dec in decimals.items():
        try:
            d = float(dec)
        except (TypeError, ValueError) as exc:
            raise BaselineError("BASELINE_DECIMAL_UNVERIFIED:%r" % (dec,)) from exc
        if not math.isfinite(d) or d <= 1.0:
            raise BaselineError("BASELINE_DECIMAL_INVALID:%r" % (dec,))
        implied[side] = 1.0 / d
    total = sum(implied.values())
    if total <= 0:
        raise BaselineError("BASELINE_OVERROUND_INVALID")
    return {side: p / total for side, p in implied.items()}


def american_pair_to_no_vig(home_american, away_american) -> tuple[float, float]:
    """(home_prob, away_prob) no-vig from a two-sided American quote."""
    dec = {
        "home": american_to_decimal(home_american),
        "away": american_to_decimal(away_american),
    }
    nv = no_vig_probs(dec)
    return nv["home"], nv["away"]


# ---------------------------------------------------------------------------
# Team normalization
# ---------------------------------------------------------------------------

def normalize_name(name) -> str:
    """Lowercase alphanumeric fold for team-name comparison."""
    return "".join(ch for ch in str(name or "").lower() if ch.isalnum())


NFL_ABBR_TO_FULL = {
    "ARI": "Arizona Cardinals", "ATL": "Atlanta Falcons",
    "BAL": "Baltimore Ravens", "BUF": "Buffalo Bills",
    "CAR": "Carolina Panthers", "CHI": "Chicago Bears",
    "CIN": "Cincinnati Bengals", "CLE": "Cleveland Browns",
    "DAL": "Dallas Cowboys", "DEN": "Denver Broncos",
    "DET": "Detroit Lions", "GB": "Green Bay Packers",
    "HOU": "Houston Texans", "IND": "Indianapolis Colts",
    "JAX": "Jacksonville Jaguars", "KC": "Kansas City Chiefs",
    "LA": "Los Angeles Rams", "LAC": "Los Angeles Chargers",
    "LV": "Las Vegas Raiders", "MIA": "Miami Dolphins",
    "MIN": "Minnesota Vikings", "NE": "New England Patriots",
    "NO": "New Orleans Saints", "NYG": "New York Giants",
    "NYJ": "New York Jets", "OAK": "Las Vegas Raiders",
    "PHI": "Philadelphia Eagles", "PIT": "Pittsburgh Steelers",
    "SD": "Los Angeles Chargers", "SEA": "Seattle Seahawks",
    "SF": "San Francisco 49ers", "STL": "Los Angeles Rams",
    "TB": "Tampa Bay Buccaneers", "TEN": "Tennessee Titans",
    "WAS": "Washington Commanders",
}
# LA = Rams (2016+; verified: co-occurs with LAC, Coliseum home games).

NBA_ABBR_TO_FULL = {
    "ATL": "Atlanta Hawks", "BKN": "Brooklyn Nets",
    "BOS": "Boston Celtics", "CHA": "Charlotte Hornets",
    "CHI": "Chicago Bulls", "CLE": "Cleveland Cavaliers",
    "DAL": "Dallas Mavericks", "DEN": "Denver Nuggets",
    "DET": "Detroit Pistons", "GSW": "Golden State Warriors",
    "HOU": "Houston Rockets", "IND": "Indiana Pacers",
    "LAC": "Los Angeles Clippers", "LAL": "Los Angeles Lakers",
    "MEM": "Memphis Grizzlies", "MIA": "Miami Heat",
    "MIL": "Milwaukee Bucks", "MIN": "Minnesota Timberwolves",
    "NOP": "New Orleans Pelicans", "NYK": "New York Knicks",
    "OKC": "Oklahoma City Thunder", "ORL": "Orlando Magic",
    "PHI": "Philadelphia 76ers", "PHX": "Phoenix Suns",
    "POR": "Portland Trail Blazers", "SAC": "Sacramento Kings",
    "SAS": "San Antonio Spurs", "TOR": "Toronto Raptors",
    "UTA": "Utah Jazz", "WAS": "Washington Wizards",
}

# Aliases applied AFTER normalize_name().
TEAM_ALIASES = {
    # MLB JSON uses current franchise names for all seasons.
    "clevelandindians": "clevelandguardians",
    # "Athletics Athletics" quirk + era names -> one canonical key.
    "athleticsathletics": "athletics",
    "oaklandathletics": "athletics",
    "sacramentoathletics": "athletics",
}


def canonical_team(name) -> str:
    key = normalize_name(name)
    return TEAM_ALIASES.get(key, key)


# ---------------------------------------------------------------------------
# Fixture-id contract
# ---------------------------------------------------------------------------

SPORT_TO_ARCHIVE_KEY = {
    "nfl": "americanfootball_nfl",
    "cfb": "americanfootball_ncaaf",
    "mlb": "baseball_mlb",
    "nba": "basketball_nba",
}

HARNESS_MARKET_TO_ARCHIVE = {
    "ML": "h2h", "MONEYLINE": "h2h",
    "SPREAD": "spreads", "TOTAL": "totals",
}


def parse_fixture_id(fixture_id: str) -> dict:
    """Parse "sport:YYYY-MM-DD:away_full_name:home_full_name"."""
    parts = str(fixture_id or "").split(":")
    if len(parts) != 4:
        raise BaselineError("BASELINE_FIXTURE_ID_MALFORMED:" + str(fixture_id))
    sport, date, away, home = (p.strip() for p in parts)
    if sport not in SPORT_TO_ARCHIVE_KEY:
        raise BaselineError("BASELINE_SPORT_UNSUPPORTED:" + sport)
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError as exc:
        raise BaselineError("BASELINE_FIXTURE_DATE_INVALID:" + date) from exc
    if not away or not home:
        raise BaselineError("BASELINE_FIXTURE_TEAMS_MISSING:" + str(fixture_id))
    return {
        "sport": sport,
        "date": date,
        "away": canonical_team(away),
        "home": canonical_team(home),
        "archive_key": SPORT_TO_ARCHIVE_KEY[sport],
    }


def parse_ts_utc(value) -> datetime:
    """ISO timestamp -> tz-aware UTC. Naive/unparseable fails closed."""
    text = str(value or "").strip()
    if not text:
        raise BaselineError("BASELINE_TIMESTAMP_MISSING")
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise BaselineError("BASELINE_TIMESTAMP_UNPARSEABLE:" + text) from exc
    if dt.tzinfo is None:
        raise BaselineError("BASELINE_TIMESTAMP_NAIVE:" + text)
    return dt.astimezone(UTC)


def fixture_id_for_game(sport: str, kickoff_iso: str, away_name: str,
                        home_name: str) -> str:
    """Build a fixture id from a kickoff timestamp.

    The date component is the America/New_York local date ("league date"),
    matching nflverse gameday, the SBR-derived MLB date keys, the NBA date
    column, and ESPN's displayed date. Pass the raw ESPN/StatsAPI
    display names; normalization is internal.
    """
    if sport not in SPORT_TO_ARCHIVE_KEY:
        raise BaselineError("BASELINE_SPORT_UNSUPPORTED:" + str(sport))
    kickoff = parse_ts_utc(kickoff_iso)
    local_date = kickoff.astimezone(LEAGUE_TZ).strftime("%Y-%m-%d")
    away = str(away_name or "").strip()
    home = str(home_name or "").strip()
    if not away or not home:
        raise BaselineError("BASELINE_FIXTURE_TEAMS_MISSING")
    return "%s:%s:%s:%s" % (sport, local_date, away, home)


# ---------------------------------------------------------------------------
# Base source
# ---------------------------------------------------------------------------

class BaselineSource:
    """One baseline source. Subclasses implement _lookup_or_raise."""

    name = "unknown"
    book_policy = "unknown"

    def lookup(self, fixture_id, market, selection, line=None):
        """No-vig baseline probability, or None when MISSING (never raises)."""
        try:
            return self._lookup_or_raise(fixture_id, market, selection, line)
        except BaselineError:
            return None

    def explain(self, fixture_id, market, selection, line=None) -> str:
        """Human reason for a None lookup (for validation reports)."""
        try:
            result = self._lookup_or_raise(fixture_id, market, selection, line)
        except BaselineError as exc:
            return "%s: %s" % (self.name, exc)
        if result is None:
            return "%s: MISSING (no archived quote)" % self.name
        return "%s: AVAILABLE p=%.4f" % (self.name, result)

    def coverage(self) -> dict:
        return {"source": self.name, "book_policy": self.book_policy}

    def _serializable_stats(self) -> dict:
        out = {}
        for key, value in self.stats.items():
            out[key] = dict(value) if isinstance(value, Counter) else value
        return out

    # -- helpers shared by subclasses ------------------------------------
    @staticmethod
    def _check_market_selection(market, selection):
        mkt = str(market or "").upper().strip()
        sel = str(selection or "").upper().strip()
        if mkt not in HARNESS_MARKET_TO_ARCHIVE:
            raise BaselineError("BASELINE_MARKET_UNSUPPORTED:" + str(market))
        if mkt in ("ML", "MONEYLINE"):
            if sel not in ("HOME", "AWAY"):
                raise BaselineError("BASELINE_SELECTION_INVALID:" + str(selection))
        elif mkt == "SPREAD":
            if sel not in ("HOME", "AWAY"):
                raise BaselineError("BASELINE_SELECTION_INVALID:" + str(selection))
        else:  # TOTAL
            if sel not in ("OVER", "UNDER"):
                raise BaselineError("BASELINE_SELECTION_INVALID:" + str(selection))
        return mkt, sel

    @staticmethod
    def _check_line_match(model_line, close_point, *, market):
        if model_line is None:
            raise BaselineError("BASELINE_LINE_REQUIRED:" + market)
        try:
            ml = float(model_line)
            cp = float(close_point)
        except (TypeError, ValueError) as exc:
            raise BaselineError("BASELINE_LINE_UNVERIFIED") from exc
        if not math.isfinite(ml) or not math.isfinite(cp):
            raise BaselineError("BASELINE_LINE_INVALID")
        # Exact match only: we compare against prices the market offered.
        if ml != cp:
            raise BaselineError(
                "BASELINE_LINE_MISMATCH:model=%r close=%r" % (model_line, close_point))
        return ml


# ---------------------------------------------------------------------------
# Red-team guards shared by loaders
# ---------------------------------------------------------------------------

class _Quarantine(BaselineError):
    """Raised during load when a game's rows contradict each other.

    Carries the quarantine code and the game's canonical identity. The
    loader quarantines that game (all its lookups -> None) and keeps
    loading the rest of the file: one corrupt game must not nuke the
    whole baseline, but it must never silently feed the harness.
    """

    def __init__(self, code: str, canonical):
        super().__init__(code)
        self.quarantine_code = code
        self.canonical = canonical


def _skip_reason(exc: BaselineError) -> str:
    return str(exc).split(":")[0]


# ---------------------------------------------------------------------------
# Source 1: keys-backed closing-line archive (PRIMARY, forward)
# ---------------------------------------------------------------------------

ARCHIVE_SCHEMA_VERSION = "CLOSING_LINE_ARCHIVE_ROW_V2"
# Window preference for the baseline: true closes first.
_ARCHIVE_WINDOW_PREFERENCE = ("close", "t0_prestart")
# Sanity bounds on (commence_time - captured_at) per window, in minutes.
# Catches gross timestamp misalignment (e.g. ET labeled as UTC). The policy
# windows are close=2-20min, t0_prestart=0-5min; bounds here are generous.
_ARCHIVE_WINDOW_LEAD_MAX = {"close": 25.0, "t0_prestart": 10.0}


class ClosingLineArchive(BaselineSource):
    """DraftKings closing lines from the data-branch archive.

    Reads ``archive/closing-lines/{sport_key}/{date}.ndjson`` under
    ``data_dir`` (a checkout of the repo's ``data`` branch, written by
    .github/workflows/closing-line-archive.yml). Empty/missing archive ->
    every lookup returns None (MISSING).
    """

    name = "closing_line_archive"
    book_policy = ("DraftKings only (policy books=[draftkings], US region, "
                   "american odds). No consensus; DK-absent games are MISSING.")

    def __init__(self, data_dir):
        self.data_dir = Path(data_dir)
        self._games: dict[tuple, dict] = {}
        self._quarantined: dict[tuple, str] = {}
        self._seen: dict[tuple, float] = {}
        self.stats = {"rows_read": 0, "rows_accepted": 0, "rows_skipped": 0,
                      "duplicate_rows": 0, "games": 0, "files": 0,
                      "quarantined_games": 0,
                      "skip_reasons": Counter()}

    def load(self) -> "ClosingLineArchive":
        root = self.data_dir / "archive" / "closing-lines"
        if not root.is_dir():
            return self  # nothing archived yet -> MISSING everywhere
        for path in sorted(root.rglob("*.ndjson")):
            self.stats["files"] += 1
            # Partition file is named for the UTC commence date; every row
            # inside must agree (attack: games stamped with the wrong date).
            expected_date = path.stem  # {date}.ndjson
            with path.open(encoding="utf-8") as handle:
                for text in handle:
                    text = text.strip()
                    if not text:
                        continue
                    self.stats["rows_read"] += 1
                    try:
                        row = json.loads(text)
                    except json.JSONDecodeError:
                        self._record_skip("BASELINE_ROW_NOT_JSON")
                        continue
                    try:
                        ingested = self._ingest_row(row, expected_date)
                    except _Quarantine as exc:
                        self._record_skip(exc.quarantine_code)
                        self._quarantine_game(exc.canonical, exc.quarantine_code)
                        continue
                    except BaselineError as exc:
                        self._record_skip(_skip_reason(exc))
                        continue
                    if ingested is None:  # exact duplicate row: harmless
                        self.stats["duplicate_rows"] += 1
                        continue
                    game_key, utc_date = ingested
                    self.stats["rows_accepted"] += 1
        # Collapse each game's rows to one closing quote per market.
        for game_key, bucket in self._games.items():
            bucket["quote"] = self._select_quote(bucket.pop("rows"))
        self.stats["games"] = len(self._games)
        return self

    def _record_skip(self, code: str):
        self.stats["rows_skipped"] += 1
        self.stats["skip_reasons"][code] += 1

    def _quarantine_game(self, canonical, code: str):
        if canonical not in self._quarantined:
            self._quarantined[canonical] = code
            self.stats["quarantined_games"] += 1
        # Buckets are KEPT for audit (rows remain inspectable in stats),
        # but every lookup for this game fails closed via the quarantine
        # check in _lookup_or_raise.

    # -- ingestion ------------------------------------------------------
    def _ingest_row(self, row, expected_date):
        """Return (index_key, utc_date); None for exact duplicates."""
        if not isinstance(row, dict):
            raise BaselineError("BASELINE_ROW_NOT_OBJECT")
        if row.get("schema_version") != ARCHIVE_SCHEMA_VERSION:
            raise BaselineError("BASELINE_ARCHIVE_SCHEMA_UNKNOWN:" +
                                str(row.get("schema_version")))
        commence = parse_ts_utc(row.get("commence_time"))
        captured = parse_ts_utc(row.get("captured_at"))
        utc_date = commence.strftime("%Y-%m-%d")
        if utc_date != expected_date:
            # Attack: row stamped with a date that does not match its
            # partition file (wrong-date/wrong-season data).
            raise BaselineError(
                "BASELINE_ARCHIVE_DATE_MISMATCH:row=%s file=%s"
                % (utc_date, expected_date))
        if not captured < commence:
            raise BaselineError("BASELINE_CAPTURED_AFTER_COMMENCE")
        window = str(row.get("window") or "").strip()
        if window not in _ARCHIVE_WINDOW_PREFERENCE:
            raise BaselineError("BASELINE_WINDOW_NOT_A_CLOSE:" + window)
        lead_minutes = (commence - captured).total_seconds() / 60.0
        if not 0 < lead_minutes <= _ARCHIVE_WINDOW_LEAD_MAX[window]:
            # Attack: timezone confusion (ET labeled as UTC) or a stale
            # capture masquerading as a close.
            raise BaselineError(
                "BASELINE_WINDOW_LEAD_MISMATCH:window=%s lead=%.1f"
                % (window, lead_minutes))
        field_lead = row.get("scheduled_lead_minutes")
        try:
            field_lead_f = float(field_lead)
        except (TypeError, ValueError):
            raise BaselineError("BASELINE_LEAD_FIELD_UNVERIFIED")
        if abs(field_lead_f - lead_minutes) > 1.0:
            raise BaselineError("BASELINE_LEAD_FIELD_MISMATCH")
        book = str(row.get("book") or "").strip().lower()
        if book != "draftkings":
            # Attack: book mislabeling — the policy archives DraftKings
            # only; anything else is refused, never blended in.
            raise BaselineError("BASELINE_BOOK_UNEXPECTED:" + book)
        market = str(row.get("market") or "").strip().lower()
        if market not in ("h2h", "spreads", "totals"):
            raise BaselineError("BASELINE_MARKET_UNSUPPORTED:" + market)
        try:
            price = float(row.get("price_american"))
        except (TypeError, ValueError):
            raise BaselineError("BASELINE_PRICE_UNVERIFIED")
        if not math.isfinite(price) or price == 0 or -100 <= price < 100:
            raise BaselineError("BASELINE_PRICE_INVALID")
        point = row.get("point")
        if point is not None:
            try:
                point = float(point)
            except (TypeError, ValueError):
                raise BaselineError("BASELINE_POINT_UNVERIFIED")
            if not math.isfinite(point):
                raise BaselineError("BASELINE_POINT_INVALID")
        outcome = str(row.get("outcome") or "").strip()
        if not outcome:
            raise BaselineError("BASELINE_OUTCOME_MISSING")
        home = canonical_team(row.get("home_team"))
        away = canonical_team(row.get("away_team"))
        if not home or not away:
            raise BaselineError("BASELINE_TEAMS_MISSING")
        sport_key = str(row.get("sport_key") or "").strip()
        if not sport_key:
            raise BaselineError("BASELINE_SPORT_KEY_MISSING")
        canonical = (sport_key, away, home, utc_date)
        if canonical in self._quarantined:
            raise BaselineError("BASELINE_GAME_QUARANTINED:" +
                                self._quarantined[canonical])
        # Attack: contradictory duplicates — same capture instant, same
        # outcome, different price. Exact duplicates are harmless.
        dup_key = (canonical, market, normalize_name(outcome), window,
                   captured.isoformat())
        prior = self._seen.get(dup_key)
        if prior is not None:
            if prior != price:
                raise _Quarantine("BASELINE_ARCHIVE_CONTRADICTORY_DUPLICATE",
                                  canonical)
            return None
        self._seen[dup_key] = price
        entry = {
            "market": market, "outcome": outcome, "point": point,
            "price": price, "window": window, "captured_at": captured,
            "book_last_update": row.get("book_last_update"),
        }
        # Dual-index under the UTC date AND the previous day: the fixture-id
        # date is the league-local date, and US evening games commence after
        # midnight UTC. Safe for this archive's sports (NFL/CFB/UFC): the
        # same matchup never occurs on consecutive days, so the two index
        # keys cannot collide with a different game.
        prev_date = (commence - timedelta(days=1)).strftime("%Y-%m-%d")
        index_keys = []
        for day in (utc_date, prev_date):
            index_key = (sport_key, day, away, home)
            bucket = self._games.setdefault(
                index_key, {"rows": [], "canonical": canonical,
                            "utc_date": utc_date})
            bucket["rows"].append(entry)
            index_keys.append(index_key)
        return index_keys[0], utc_date

    def _select_quote(self, rows):
        """One closing quote per market: preferred window, latest capture."""
        quote: dict[str, dict] = {}
        by_market: dict[str, list] = {}
        for row in rows:
            by_market.setdefault(row["market"], []).append(row)
        for market, mrows in by_market.items():
            chosen = None
            for window in _ARCHIVE_WINDOW_PREFERENCE:
                wrows = [r for r in mrows if r["window"] == window]
                if wrows:
                    chosen = max(wrows, key=lambda r: r["captured_at"])
                    break
            if chosen is None:
                continue
            # All rows sharing the chosen capture: the two-sided quote.
            capture_rows = [r for r in mrows
                            if r["window"] == chosen["window"]
                            and r["captured_at"] == chosen["captured_at"]]
            sides: dict[str, dict] = {}
            for r in capture_rows:
                key = normalize_name(r["outcome"])
                # totals outcomes are Over/Under; h2h/spreads are team names
                sides[key] = {"price": r["price"], "point": r["point"],
                              "outcome": r["outcome"]}
            if len(sides) < 2:
                continue  # one-sided quote is not imputed
            quote[market] = {
                "sides": sides,
                "window": chosen["window"],
                "captured_at": chosen["captured_at"].isoformat(),
                "book": "draftkings",
            }
        return quote

    # -- lookup ---------------------------------------------------------
    def _lookup_or_raise(self, fixture_id, market, selection, line=None):
        mkt, sel = self._check_market_selection(market, selection)
        fix = parse_fixture_id(fixture_id)
        game = self._games.get(
            (fix["archive_key"], fix["date"], fix["away"], fix["home"]))
        if game is None:
            raise BaselineError("BASELINE_GAME_NOT_ARCHIVED")
        canonical = game.get("canonical")
        if canonical in self._quarantined:
            raise BaselineError("BASELINE_GAME_QUARANTINED:" +
                                self._quarantined[canonical])
        quote = game["quote"].get(HARNESS_MARKET_TO_ARCHIVE[mkt])
        if quote is None:
            raise BaselineError("BASELINE_MARKET_NOT_ARCHIVED:" + mkt)
        sides = quote["sides"]
        if mkt in ("ML", "MONEYLINE"):
            if line is not None:
                raise BaselineError("BASELINE_ML_LINE_MUST_BE_NONE")
            home = sides.get(fix["home"])
            away = sides.get(fix["away"])
            if home is None or away is None:
                raise BaselineError("BASELINE_SIDES_INCOMPLETE")
            hp, ap = american_pair_to_no_vig(home["price"], away["price"])
            return hp if sel == "HOME" else ap
        if mkt == "SPREAD":
            side = sides.get(fix["home"] if sel == "HOME" else fix["away"])
            if side is None or side["point"] is None:
                raise BaselineError("BASELINE_SIDES_INCOMPLETE")
            self._check_line_match(line, side["point"], market=mkt)
            other = sides.get(fix["away"] if sel == "HOME" else fix["home"])
            if other is None:
                raise BaselineError("BASELINE_SIDES_INCOMPLETE")
            sp, op = american_pair_to_no_vig(side["price"], other["price"])
            return sp
        # TOTAL
        over = sides.get("over")
        under = sides.get("under")
        if over is None or under is None or over["point"] is None:
            raise BaselineError("BASELINE_SIDES_INCOMPLETE")
        self._check_line_match(line, over["point"], market=mkt)
        ovp, unp = american_pair_to_no_vig(over["price"], under["price"])
        return ovp if sel == "OVER" else unp

    def coverage(self) -> dict:
        cov = super().coverage()
        cov.update(self._serializable_stats())
        return cov


# ---------------------------------------------------------------------------
# Source 2: nflverse games.csv (NFL historical consensus)
# ---------------------------------------------------------------------------

class NflverseBaseline(BaselineSource):
    """NFL closing consensus lines from nflverse games.csv (CC-BY-4.0).

    spread_line/total_line: documented closing lines (PFR-sourced),
    1999-present. Moneylines + closing juice: 2010-present. Rows for
    not-yet-played games carry opener/current lines, not closes — only
    completed fixtures are ever queried by the harness.
    """

    name = "nflverse"
    book_policy = ("Consensus aggregate (Pro-Football-Reference sourced "
                   "closing consensus). No per-book breakdown.")

    def __init__(self, csv_path):
        self.csv_path = Path(csv_path)
        self._games: dict[tuple, dict] = {}
        self._quarantined: dict[tuple, str] = {}
        self.stats = {"rows_read": 0, "rows_accepted": 0, "rows_skipped": 0,
                      "duplicate_rows": 0, "quarantined_games": 0,
                      "seasons": Counter(), "skip_reasons": Counter()}

    def load(self) -> "NflverseBaseline":
        with self.csv_path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                self.stats["rows_read"] += 1
                try:
                    game = self._parse_row(row)
                except _Quarantine as exc:
                    self._record_skip(exc.quarantine_code)
                    self._quarantine_game(exc.canonical, exc.quarantine_code)
                    continue
                except BaselineError as exc:
                    self._record_skip(_skip_reason(exc))
                    continue
                if game is None:  # exact duplicate row: harmless
                    self.stats["duplicate_rows"] += 1
                    continue
                self._games[game["key"]] = game
                self.stats["rows_accepted"] += 1
                self.stats["seasons"][game["season"]] += 1
        return self

    def _record_skip(self, code: str):
        self.stats["rows_skipped"] += 1
        self.stats["skip_reasons"][code] += 1

    def _quarantine_game(self, canonical, code: str):
        if canonical not in self._quarantined:
            self._quarantined[canonical] = code
            self.stats["quarantined_games"] += 1
        self._games.pop(canonical, None)

    def assert_min_season_games(self, season, minimum: int):
        """Fail closed when a season's file coverage is suspiciously thin.

        Attack: a truncated/partial download that "looks clean" but is
        missing games. Callers that need a full season (e.g. the harness
        validation) assert this explicitly; individual missing games
        already fail closed per-lookup as BASELINE_GAME_NOT_ARCHIVED.
        """
        have = self.stats["seasons"].get(str(season), 0)
        if have < minimum:
            raise BaselineError(
                "BASELINE_SEASON_COVERAGE_SHORT:%s:have=%d minimum=%d"
                % (season, have, minimum))

    @staticmethod
    def _num(row, col):
        text = str(row.get(col) or "").strip()
        if not text:
            return None
        try:
            val = float(text)
        except ValueError as exc:
            raise BaselineError("BASELINE_NFLVERSE_BAD_VALUE:%s" % col) from exc
        if not math.isfinite(val):
            raise BaselineError("BASELINE_NFLVERSE_BAD_VALUE:%s" % col)
        return val

    def _parse_row(self, row):
        date = str(row.get("gameday") or "").strip()
        try:
            gameday = datetime.strptime(date, "%Y-%m-%d")
        except ValueError as exc:
            raise BaselineError("BASELINE_NFLVERSE_BAD_DATE") from exc
        season_txt = str(row.get("season") or "").strip()
        game_type = str(row.get("game_type") or "").strip()
        try:
            season = int(season_txt)
        except ValueError as exc:
            raise BaselineError("BASELINE_NFLVERSE_BAD_SEASON") from exc
        # Attack: games stamped with the wrong season. Regular-season games
        # carry the season year, except Week 17/18 spillover into January
        # (year == season+1, month == 1); postseason games fall in Jan/Feb
        # of season+1.
        if game_type == "REG":
            season_ok = (gameday.year == season or
                         (gameday.year == season + 1 and gameday.month == 1))
        elif game_type in ("WC", "DIV", "CON", "SB"):
            season_ok = gameday.year in (season, season + 1)
        else:
            season_ok = gameday.year == season
        if not season_ok:
            raise BaselineError(
                "BASELINE_NFLVERSE_SEASON_MISMATCH:season=%s gameday=%s"
                % (season_txt, date))
        home_abbr = str(row.get("home_team") or "").strip().upper()
        away_abbr = str(row.get("away_team") or "").strip().upper()
        if home_abbr not in NFL_ABBR_TO_FULL or away_abbr not in NFL_ABBR_TO_FULL:
            raise BaselineError("BASELINE_NFLVERSE_UNKNOWN_TEAM")
        home = canonical_team(NFL_ABBR_TO_FULL[home_abbr])
        away = canonical_team(NFL_ABBR_TO_FULL[away_abbr])
        game = {
            "key": ("nfl", date, away, home),
            "season": season_txt,
            "spread_line": self._num(row, "spread_line"),      # + = home favored
            "home_spread_odds": self._num(row, "home_spread_odds"),
            "away_spread_odds": self._num(row, "away_spread_odds"),
            "total_line": self._num(row, "total_line"),
            "over_odds": self._num(row, "over_odds"),
            "under_odds": self._num(row, "under_odds"),
            "home_moneyline": self._num(row, "home_moneyline"),
            "away_moneyline": self._num(row, "away_moneyline"),
        }
        # Attack: duplicate rows. Identical rows are harmless; rows that
        # disagree on the lines quarantine the game.
        prior = self._games.get(game["key"])
        if prior is not None:
            before = {k: v for k, v in prior.items() if k != "key"}
            after = {k: v for k, v in game.items() if k != "key"}
            if before != after:
                raise _Quarantine("BASELINE_NFLVERSE_CONTRADICTORY_DUPLICATE",
                                  game["key"])
            return None
        return game

    def _lookup_or_raise(self, fixture_id, market, selection, line=None):
        mkt, sel = self._check_market_selection(market, selection)
        fix = parse_fixture_id(fixture_id)
        if fix["sport"] != "nfl":
            raise BaselineError("BASELINE_NFLVERSE_SPORT_MISMATCH")
        key = ("nfl", fix["date"], fix["away"], fix["home"])
        if key in self._quarantined:
            raise BaselineError("BASELINE_GAME_QUARANTINED:" +
                                self._quarantined[key])
        game = self._games.get(key)
        if game is None:
            raise BaselineError("BASELINE_GAME_NOT_ARCHIVED")
        if mkt in ("ML", "MONEYLINE"):
            if line is not None:
                raise BaselineError("BASELINE_ML_LINE_MUST_BE_NONE")
            hm, am = game["home_moneyline"], game["away_moneyline"]
            if hm is None or am is None:
                raise BaselineError("BASELINE_MONEYLINE_UNAVAILABLE_PRE_2010")
            hp, ap = american_pair_to_no_vig(hm, am)
            return hp if sel == "HOME" else ap
        if mkt == "SPREAD":
            sl = game["spread_line"]
            ho, ao = game["home_spread_odds"], game["away_spread_odds"]
            if sl is None or ho is None or ao is None:
                raise BaselineError("BASELINE_SPREAD_QUOTE_INCOMPLETE")
            # spread_line > 0 means home favored; harness line is from the
            # selection's perspective: home_line = -spread_line.
            close_point = -sl if sel == "HOME" else sl
            self._check_line_match(line, close_point, market=mkt)
            hp, ap = american_pair_to_no_vig(ho, ao)
            return hp if sel == "HOME" else ap
        tl = game["total_line"]
        oo, uo = game["over_odds"], game["under_odds"]
        if tl is None or oo is None or uo is None:
            raise BaselineError("BASELINE_TOTAL_QUOTE_INCOMPLETE")
        self._check_line_match(line, tl, market=mkt)
        ovp, unp = american_pair_to_no_vig(oo, uo)
        return ovp if sel == "OVER" else unp

    def coverage(self) -> dict:
        cov = super().coverage()
        cov.update(self._serializable_stats())
        return cov


# ---------------------------------------------------------------------------
# Source 3: SBR-derived MLB JSON (historical, multi-book)
# ---------------------------------------------------------------------------

def _median(values: list[float]) -> float:
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    return ordered[mid] if n % 2 else (ordered[mid - 1] + ordered[mid]) / 2.0


# Maximum cross-book decimal-odds range tolerated when synthesizing a
# median fallback quote. Normal cross-book dispersion is a few cents;
# 0.25 (e.g. -110 vs roughly +130) means the rows disagree violently and
# the "consensus" would be fiction.
_MLB_BOOK_DISPERSION_MAX = 0.25


class SbrMlbBaseline(BaselineSource):
    """MLB closing lines from the ArnavSaraogi mlb-odds-scraper dataset.

    SBR-derived opening+current lines, 2021-04-01..2025-08-16, books:
    draftkings, fanduel, caesars, bet365, betmgm, bet_rivers_ny.
    Book selection: DraftKings when present, else median across available
    books computed in DECIMAL space. Factual reference only (no explicit
    license in the source repo); never redistributed.
    """

    name = "sbr_mlb"
    book_policy = ("DraftKings preferred; else median across available books "
                   "in decimal space. 6-book SBR-derived archive.")

    def __init__(self, json_path, preferred_book="draftkings"):
        self.json_path = Path(json_path)
        self.preferred_book = str(preferred_book or "").strip().lower()
        self._games: dict[tuple, dict] = {}
        self._quarantined: dict[tuple, str] = {}
        self.stats = {"rows_read": 0, "rows_accepted": 0, "rows_skipped": 0,
                      "duplicate_rows": 0, "quarantined_games": 0,
                      "book_used": Counter(), "skip_reasons": Counter()}

    def load(self) -> "SbrMlbBaseline":
        data = json.loads(self.json_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise BaselineError("BASELINE_MLB_JSON_MALFORMED")
        for date, games in data.items():
            try:
                key_date = datetime.strptime(str(date), "%Y-%m-%d")
            except ValueError:
                self._record_skip("BASELINE_MLB_BAD_DATE_KEY")
                continue
            if not isinstance(games, list):
                continue
            for entry in games:
                self.stats["rows_read"] += 1
                try:
                    game = self._parse_game(key_date, entry)
                except _Quarantine as exc:
                    self._record_skip(exc.quarantine_code)
                    self._quarantine_game(exc.canonical, exc.quarantine_code)
                    continue
                except BaselineError as exc:
                    self._record_skip(_skip_reason(exc))
                    continue
                if game is None:  # exact duplicate entry: harmless
                    self.stats["duplicate_rows"] += 1
                    continue
                self._games[game["key"]] = game
                self.stats["rows_accepted"] += 1
                used = game["book_used"]
                self.stats["book_used"][used] += 1
        return self

    def _record_skip(self, code: str):
        self.stats["rows_skipped"] += 1
        self.stats["skip_reasons"][code] += 1

    def _quarantine_game(self, canonical, code: str):
        if canonical not in self._quarantined:
            self._quarantined[canonical] = code
            self.stats["quarantined_games"] += 1
        self._games.pop(canonical, None)

    def _parse_game(self, key_date, entry):
        if not isinstance(entry, dict):
            raise BaselineError("BASELINE_MLB_ENTRY_MALFORMED")
        gv = entry.get("gameView") or {}
        odds = entry.get("odds") or {}
        try:
            start = parse_ts_utc((gv.get("startDate") or ""))
        except BaselineError as exc:
            raise BaselineError("BASELINE_MLB_START_UNVERIFIED") from exc
        # Attack: date key stamped with the wrong date/season. The key is a
        # local date and startDate is UTC; they must be within a day.
        start_utc_date = start.strftime("%Y-%m-%d")
        key_txt = key_date.strftime("%Y-%m-%d")
        if abs((datetime.strptime(start_utc_date, "%Y-%m-%d") -
                key_date).days) > 1:
            raise BaselineError(
                "BASELINE_MLB_DATE_MISMATCH:key=%s start=%s"
                % (key_txt, start_utc_date))
        home = canonical_team(((gv.get("homeTeam") or {}).get("fullName")))
        away = canonical_team(((gv.get("awayTeam") or {}).get("fullName")))
        if not home or not away:
            raise BaselineError("BASELINE_MLB_TEAMS_MISSING")
        key = ("mlb", key_txt, away, home)
        if key in self._quarantined:
            raise BaselineError("BASELINE_GAME_QUARANTINED:" +
                                self._quarantined[key])
        markets = {}
        for mkt_key, kind in (("moneyline", "h2h"), ("pointspread", "spreads"),
                              ("totals", "totals")):
            quote = self._pick_quote(odds.get(mkt_key), kind, key)
            if quote is not None:
                markets[kind] = quote
        if not markets:
            raise BaselineError("BASELINE_MLB_NO_MARKETS")
        game = {"key": key, "markets": markets,
                "book_used": markets["h2h"]["book"] if "h2h" in markets
                else next(iter(markets.values()))["book"],
                "start": start.isoformat()}
        # Attack: duplicate entries. Identical entries are harmless;
        # entries that disagree quarantine the game.
        prior = self._games.get(key)
        if prior is not None:
            before = {k: v for k, v in prior.items() if k != "key"}
            after = {k: v for k, v in game.items() if k != "key"}
            if before != after:
                raise _Quarantine("BASELINE_MLB_CONTRADICTORY_DUPLICATE", key)
            return None
        return game

    def _pick_quote(self, book_list, kind, game_key):
        """{book, home_american, away_american, home_point, away_point}."""
        if not isinstance(book_list, list) or not book_list:
            return None
        by_book = {}
        for b in book_list:
            if not isinstance(b, dict):
                continue
            book = str(b.get("sportsbook") or "").strip().lower()
            cur = b.get("currentLine") or {}
            try:
                if kind == "h2h":
                    ha = float(cur["homeOdds"]); aa = float(cur["awayOdds"])
                    hp = ap = None
                elif kind == "spreads":
                    ha = float(cur["homeOdds"]); aa = float(cur["awayOdds"])
                    hp = float(cur["homeSpread"]); ap = float(cur["awaySpread"])
                else:
                    ha = float(cur["overOdds"]); aa = float(cur["underOdds"])
                    hp = float(cur["total"]); ap = float(cur["total"])
            except (KeyError, TypeError, ValueError):
                continue
            if not all(math.isfinite(v) for v in (ha, aa)):
                continue
            if hp is not None and not all(math.isfinite(v) for v in (hp, ap)):
                continue
            # Attack: book mislabeling / corrupt rows. American odds outside
            # any plausible market range are refused, never blended in.
            if not all(-10000 <= v <= 10000 and (v == 0 or abs(v) >= 100)
                       for v in (ha, aa)):
                continue
            by_book[book] = (ha, aa, hp, ap)
        if not by_book:
            return None
        if self.preferred_book in by_book:
            ha, aa, hp, ap = by_book[self.preferred_book]
            return {"book": self.preferred_book, "home_american": ha,
                    "away_american": aa, "home_point": hp, "away_point": ap,
                    "n_books": 1}
        # Median across books in decimal space (American odds are
        # discontinuous at -100/+100; never average them directly).
        dec_h = [american_to_decimal(v[0]) for v in by_book.values()]
        dec_a = [american_to_decimal(v[1]) for v in by_book.values()]
        # Attack: a "consensus" synthesized from books that violently
        # disagree is worse than MISSING — refuse it outright.
        if max(dec_h) - min(dec_h) > _MLB_BOOK_DISPERSION_MAX or \
           max(dec_a) - min(dec_a) > _MLB_BOOK_DISPERSION_MAX:
            raise _Quarantine("BASELINE_BOOK_DISPERSION_EXCEEDED", game_key)
        quote = {"book": "median_of_%d_books" % len(by_book),
                 "home_american": None, "away_american": None,
                 "home_point": None, "away_point": None,
                 "n_books": len(by_book),
                 "_dec_h": _median(dec_h), "_dec_a": _median(dec_a)}
        if kind != "h2h":
            pts_h = [v[2] for v in by_book.values()]
            pts_a = [v[3] for v in by_book.values()]
            quote["home_point"] = _median(pts_h)
            quote["away_point"] = _median(pts_a)
        return quote

    def _probs(self, quote):
        if quote.get("_dec_h") is not None:
            nv = no_vig_probs({"home": quote["_dec_h"],
                               "away": quote["_dec_a"]})
            return nv["home"], nv["away"]
        return american_pair_to_no_vig(quote["home_american"],
                                       quote["away_american"])

    def _lookup_or_raise(self, fixture_id, market, selection, line=None):
        mkt, sel = self._check_market_selection(market, selection)
        fix = parse_fixture_id(fixture_id)
        if fix["sport"] != "mlb":
            raise BaselineError("BASELINE_MLB_SPORT_MISMATCH")
        key = ("mlb", fix["date"], fix["away"], fix["home"])
        if key in self._quarantined:
            raise BaselineError("BASELINE_GAME_QUARANTINED:" +
                                self._quarantined[key])
        game = self._games.get(key)
        if game is None:
            raise BaselineError("BASELINE_GAME_NOT_ARCHIVED")
        quote = game["markets"].get(HARNESS_MARKET_TO_ARCHIVE[mkt])
        if quote is None:
            raise BaselineError("BASELINE_MARKET_NOT_ARCHIVED:" + mkt)
        hp, ap = self._probs(quote)
        if mkt in ("ML", "MONEYLINE"):
            if line is not None:
                raise BaselineError("BASELINE_ML_LINE_MUST_BE_NONE")
            return hp if sel == "HOME" else ap
        if mkt == "SPREAD":
            point = quote["home_point"] if sel == "HOME" else quote["away_point"]
            if point is None:
                raise BaselineError("BASELINE_SPREAD_QUOTE_INCOMPLETE")
            self._check_line_match(line, point, market=mkt)
            return hp if sel == "HOME" else ap
        point = quote["home_point"]  # totals: single total value
        if point is None:
            raise BaselineError("BASELINE_TOTAL_QUOTE_INCOMPLETE")
        self._check_line_match(line, point, market=mkt)
        return hp if sel == "OVER" else ap

    def coverage(self) -> dict:
        cov = super().coverage()
        cov.update(self._serializable_stats())
        return cov


# ---------------------------------------------------------------------------
# Source 4: aggregated NBA closing lines (historical)
# ---------------------------------------------------------------------------

class NbaLinesBaseline(BaselineSource):
    """NBA closing lines from degenpredicts data/nba/lines.csv.

    Compiler-aggregated: SBR-derived closing moneylines 2007-08 on
    (ml_source=sbr_close, ~96.5% of games). Spreads/totals 2017-18 on are
    present as LINES ONLY (no closing juice anywhere in the file) and are
    therefore MISSING for baseline purposes — probabilities are never
    built on invented juice. Factual reference only (no explicit license
    in the source repo); never redistributed.
    """

    name = "nba_lines"
    book_policy = ("Compiler-aggregated closing consensus (up to 17 books "
                   "on priced rows; SBR close for moneylines).")

    def __init__(self, csv_path):
        self.csv_path = Path(csv_path)
        self._games: dict[tuple, dict] = {}
        self._quarantined: dict[tuple, str] = {}
        self.stats = {"rows_read": 0, "rows_accepted": 0, "rows_skipped": 0,
                      "duplicate_rows": 0, "quarantined_games": 0,
                      "seasons": Counter(), "skip_reasons": Counter()}

    def load(self) -> "NbaLinesBaseline":
        with self.csv_path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                self.stats["rows_read"] += 1
                try:
                    game = self._parse_row(row)
                except _Quarantine as exc:
                    self._record_skip(exc.quarantine_code)
                    self._quarantine_game(exc.canonical, exc.quarantine_code)
                    continue
                except BaselineError as exc:
                    self._record_skip(_skip_reason(exc))
                    continue
                if game is None:  # exact duplicate row: harmless
                    self.stats["duplicate_rows"] += 1
                    continue
                self._games[game["key"]] = game
                self.stats["rows_accepted"] += 1
                self.stats["seasons"][game["season"]] += 1
        return self

    def _record_skip(self, code: str):
        self.stats["rows_skipped"] += 1
        self.stats["skip_reasons"][code] += 1

    def _quarantine_game(self, canonical, code: str):
        if canonical not in self._quarantined:
            self._quarantined[canonical] = code
            self.stats["quarantined_games"] += 1
        self._games.pop(canonical, None)

    @staticmethod
    def _dec(row, col):
        text = str(row.get(col) or "").strip()
        if not text:
            return None
        try:
            val = float(text)
        except ValueError as exc:
            raise BaselineError("BASELINE_NBA_BAD_VALUE:%s" % col) from exc
        if not math.isfinite(val) or val <= 1.0:
            raise BaselineError("BASELINE_NBA_BAD_VALUE:%s" % col)
        return val

    def _parse_row(self, row):
        if str(row.get("is_closing") or "").strip().lower() != "true":
            raise BaselineError("BASELINE_NBA_NOT_CLOSING")
        date = str(row.get("date") or "").strip()
        try:
            day = datetime.strptime(date, "%Y-%m-%d")
        except ValueError as exc:
            raise BaselineError("BASELINE_NBA_BAD_DATE") from exc
        season_txt = str(row.get("season") or "").strip()
        try:
            season = int(season_txt)
        except ValueError as exc:
            raise BaselineError("BASELINE_NBA_BAD_SEASON") from exc
        # Attack: games stamped with the wrong season. Season S covers
        # Oct-Dec of year S and Jan-Jun of year S+1.
        if day.month >= 10:
            season_ok = day.year == season
        elif day.month <= 6:
            season_ok = day.year == season + 1
        else:
            season_ok = False
        if not season_ok:
            raise BaselineError(
                "BASELINE_NBA_SEASON_MISMATCH:season=%s date=%s"
                % (season_txt, date))
        home_abbr = str(row.get("home_team") or "").strip().upper()
        away_abbr = str(row.get("away_team") or "").strip().upper()
        if home_abbr not in NBA_ABBR_TO_FULL or away_abbr not in NBA_ABBR_TO_FULL:
            raise BaselineError("BASELINE_NBA_UNKNOWN_TEAM")
        spread_txt = str(row.get("spread_home") or "").strip()
        total_txt = str(row.get("total_line") or "").strip()
        try:
            spread_home = float(spread_txt) if spread_txt else None
            total_line = float(total_txt) if total_txt else None
        except ValueError as exc:
            raise BaselineError("BASELINE_NBA_BAD_LINE") from exc
        game = {
            "key": ("nba", date,
                    canonical_team(NBA_ABBR_TO_FULL[away_abbr]),
                    canonical_team(NBA_ABBR_TO_FULL[home_abbr])),
            "season": season_txt,
            "spread_home": spread_home,      # home perspective
            "spread_home_dec": self._dec(row, "spread_home_dec"),
            "spread_away_dec": self._dec(row, "spread_away_dec"),
            "total_line": total_line,
            "over_dec": self._dec(row, "over_dec"),
            "under_dec": self._dec(row, "under_dec"),
            "home_dec": self._dec(row, "home_dec"),
            "away_dec": self._dec(row, "away_dec"),
            "source": str(row.get("source") or "").strip(),
            "ml_source": str(row.get("ml_source") or "").strip(),
        }
        # Attack: duplicate rows. Identical rows are harmless; rows that
        # disagree quarantine the game.
        prior = self._games.get(game["key"])
        if prior is not None:
            before = {k: v for k, v in prior.items() if k != "key"}
            after = {k: v for k, v in game.items() if k != "key"}
            if before != after:
                raise _Quarantine("BASELINE_NBA_CONTRADICTORY_DUPLICATE",
                                  game["key"])
            return None
        return game

    def _lookup_or_raise(self, fixture_id, market, selection, line=None):
        mkt, sel = self._check_market_selection(market, selection)
        fix = parse_fixture_id(fixture_id)
        if fix["sport"] != "nba":
            raise BaselineError("BASELINE_NBA_SPORT_MISMATCH")
        key = ("nba", fix["date"], fix["away"], fix["home"])
        if key in self._quarantined:
            raise BaselineError("BASELINE_GAME_QUARANTINED:" +
                                self._quarantined[key])
        game = self._games.get(key)
        if game is None:
            raise BaselineError("BASELINE_GAME_NOT_ARCHIVED")
        if mkt in ("ML", "MONEYLINE"):
            if line is not None:
                raise BaselineError("BASELINE_ML_LINE_MUST_BE_NONE")
            hd, ad = game["home_dec"], game["away_dec"]
            if hd is None or ad is None:
                raise BaselineError("BASELINE_MONEYLINE_UNAVAILABLE")
            nv = no_vig_probs({"home": hd, "away": ad})
            return nv["home"] if sel == "HOME" else nv["away"]
        if mkt == "SPREAD":
            sh = game["spread_home"]
            hd, ad = game["spread_home_dec"], game["spread_away_dec"]
            if sh is None or hd is None or ad is None:
                raise BaselineError("BASELINE_SPREAD_QUOTE_INCOMPLETE")
            close_point = sh if sel == "HOME" else -sh
            self._check_line_match(line, close_point, market=mkt)
            nv = no_vig_probs({"home": hd, "away": ad})
            return nv["home"] if sel == "HOME" else nv["away"]
        tl = game["total_line"]
        od, ud = game["over_dec"], game["under_dec"]
        if tl is None or od is None or ud is None:
            raise BaselineError("BASELINE_TOTAL_QUOTE_INCOMPLETE")
        self._check_line_match(line, tl, market=mkt)
        nv = no_vig_probs({"over": od, "under": ud})
        return nv["over"] if sel == "OVER" else nv["under"]

    def coverage(self) -> dict:
        cov = super().coverage()
        cov.update(self._serializable_stats())
        return cov


# ---------------------------------------------------------------------------
# Composite: precedence-ordered baseline for the runner slot
# ---------------------------------------------------------------------------

class CompositeMarketBaseline:
    """First-available-wins across sources; fail-closed everywhere else.

    Precedence: keys-backed ClosingLineArchive (DraftKings close) first,
    then the open historical dataset for the sport. ``lookup`` matches the
    runner's ``market_baseline`` callable signature exactly.
    """

    def __init__(self, sources):
        self.sources = list(sources)

    def lookup(self, fixture_id, market, selection, line=None):
        for source in self.sources:
            prob = source.lookup(fixture_id, market, selection, line)
            if prob is not None:
                return prob
        return None

    def as_callable(self):
        return self.lookup

    def provenance(self, fixture_id, market, selection, line=None) -> dict:
        """Which source answered (or why none did). For validation reports."""
        for source in self.sources:
            prob = source.lookup(fixture_id, market, selection, line)
            if prob is not None:
                return {"source": source.name,
                        "book_policy": source.book_policy,
                        "probability": prob}
        return {"source": None,
                "reasons": [s.explain(fixture_id, market, selection, line)
                            for s in self.sources]}

    def coverage(self) -> list[dict]:
        return [s.coverage() for s in self.sources]


def build_default_baseline(*, archive_data_dir=None, nflverse_csv=None,
                           mlb_json=None, nba_csv=None) -> CompositeMarketBaseline:
    """Assemble the standard composite from whichever sources are provided.

    Any source left as None is simply absent (its leg stays MISSING).
    """
    sources: list[BaselineSource] = []
    if archive_data_dir is not None:
        sources.append(ClosingLineArchive(archive_data_dir).load())
    if nflverse_csv is not None:
        sources.append(NflverseBaseline(nflverse_csv).load())
    if mlb_json is not None:
        sources.append(SbrMlbBaseline(mlb_json).load())
    if nba_csv is not None:
        sources.append(NbaLinesBaseline(nba_csv).load())
    return CompositeMarketBaseline(sources)
