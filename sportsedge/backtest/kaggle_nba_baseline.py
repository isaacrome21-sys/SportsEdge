"""Kaggle NBA historical-odds baseline loader — drop-in for the backtest harness.

Reads the NORMALIZED archive written by scripts/archive_kaggle_nba_odds.py
(Actions-side, keyed) from a data-branch checkout:

  {data_dir}/archive/nba-kaggle-odds/{season_label}/games.csv

Kaggle odds are BASELINE-EVALUATION data only — never pricing features.
Market-blind stands.

INTEGRATION (for feat/market-baseline-20261011, sportsedge/backtest/):
  This module is intentionally self-contained: it does not import from
  market_baseline.py (which lives on another branch). On merge, unify the
  shared helpers (BaselineError, american_to_decimal, no_vig_probs,
  normalize_name/canonical_team, fixture-id parsing, _Quarantine) with
  market_baseline.py and make KaggleNbaBaseline subclass its
  BaselineSource. Register in build_default_baseline:

      def build_default_baseline(*, archive_data_dir=None, nflverse_csv=None,
                                 mlb_json=None, nba_csv=None,
                                 kaggle_nba_dir=None):
          ...
          if kaggle_nba_dir is not None:
              sources.append(KaggleNbaBaseline(kaggle_nba_dir).load())

  Precedence decision (document, don't guess): KaggleNbaBaseline carries
  the same 2007+ window as the existing NbaLinesBaseline (degenpredicts).
  Put the Kaggle source AFTER NbaLinesBaseline in precedence unless the
  harness validation proves it prices more games correctly — both are soft
  consensus-close, so the harness verdict stays CONDITIONAL per spec
  either way.

Contract (mirrors market_baseline.BaselineSource):
  lookup(fixture_id, market, selection, line=None) -> float | None
  — the no-vig market-implied probability, or None when MISSING.
  explain(...) -> human reason. coverage() -> audit dict.
  load() -> self, classmethod-friendly.

Fail-closed codes: BASELINE_KAGGLE_NBA_* — schema mismatch, season/date
mismatch, contradictory duplicates (-> quarantine), missing juice
(-> MISSING for that leg, never invented), line mismatch on spreads/totals.

No network. No secrets. The archive is consumed from its data-branch
checkout; nothing here touches the Kaggle API or any credential.
"""

from __future__ import annotations

import csv
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

UTC = timezone.utc
LEAGUE_TZ = ZoneInfo("America/New_York")

SCHEMA_VERSION = "KAGGLE_NBA_BASELINE_V1"
ARCHIVE_SUBDIR = Path("archive") / "nba-kaggle-odds"

EXPECTED_COLUMNS = (
    "game_date", "season_label", "home_team", "away_team",
    "home_score", "away_score",
    "closing_spread_home", "spread_home_juice", "spread_away_juice",
    "closing_total", "over_juice", "under_juice",
    "closing_ml_home", "closing_ml_away",
)


class BaselineError(ValueError):
    pass


class _Quarantine(BaselineError):
    def __init__(self, code: str, canonical):
        super().__init__(code)
        self.quarantine_code = code
        self.canonical = canonical


def _skip_reason(exc: BaselineError) -> str:
    return str(exc).split(":")[0]


def normalize_name(name) -> str:
    return "".join(ch for ch in str(name or "").lower() if ch.isalnum())


def canonical_team(name) -> str:
    return normalize_name(name)


def american_to_decimal(american) -> float:
    try:
        a = float(american)
    except (TypeError, ValueError) as exc:
        raise BaselineError("BASELINE_PRICE_UNVERIFIED:%r" % (american,)) from exc
    if not math.isfinite(a):
        raise BaselineError("BASELINE_PRICE_INVALID:%r" % (american,))
    if a == 0 or -100 <= a < 100:
        raise BaselineError("BASELINE_PRICE_INVALID:%r" % (american,))
    if a > 0:
        return 1.0 + a / 100.0
    return 1.0 + 100.0 / abs(a)


def no_vig_probs(decimals: dict) -> dict:
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


def american_pair_to_no_vig(home_american, away_american):
    dec = {"home": american_to_decimal(home_american),
           "away": american_to_decimal(away_american)}
    nv = no_vig_probs(dec)
    return nv["home"], nv["away"]


def parse_fixture_id(fixture_id: str) -> dict:
    parts = str(fixture_id or "").split(":")
    if len(parts) != 4:
        raise BaselineError("BASELINE_FIXTURE_ID_MALFORMED:" + str(fixture_id))
    sport, date, away, home = (p.strip() for p in parts)
    if sport != "nba":
        raise BaselineError("BASELINE_SPORT_UNSUPPORTED:" + sport)
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError as exc:
        raise BaselineError("BASELINE_FIXTURE_DATE_INVALID:" + date) from exc
    if not away or not home:
        raise BaselineError("BASELINE_FIXTURE_TEAMS_MISSING:" + str(fixture_id))
    return {"sport": sport, "date": date,
            "away": canonical_team(away), "home": canonical_team(home)}


class KaggleNbaBaseline:
    """NBA closing lines from the Kaggle cviaxmiwnptr/nba-betting-data archive.

    CC0, 2007-2026, SportsbookReviewsOnline consensus close. Soft
    consensus-close ceiling — harness verdict stays CONDITIONAL per spec.
    """

    name = "kaggle_nba"
    book_policy = ("Consensus close (SportsbookReviewsOnline aggregate). "
                   "Soft consensus-close ceiling; CONDITIONAL baseline.")

    def __init__(self, archive_path):
        self.archive_path = Path(archive_path)
        self._games: dict[tuple, dict] = {}
        self._quarantined: dict[tuple, str] = {}
        self.stats = {"rows_read": 0, "rows_accepted": 0, "rows_skipped": 0,
                      "duplicate_rows": 0, "quarantined_games": 0,
                      "seasons": Counter(), "skip_reasons": Counter()}

    # -- loading ------------------------------------------------------
    def load(self) -> "KaggleNbaBaseline":
        root = self.archive_path
        if root.is_file():
            files = [root]
        else:
            root = root / ARCHIVE_SUBDIR if (root / ARCHIVE_SUBDIR).is_dir() else root
            files = sorted(root.rglob("games.csv"))
        for path in files:
            season_dir = path.parent.name
            with path.open(newline="", encoding="utf-8") as handle:
                reader = csv.DictReader(handle)
                header = reader.fieldnames or []
                missing = [c for c in EXPECTED_COLUMNS if c not in header]
                if missing:
                    # One corrupt season file must not nuke the baseline,
                    # but it is counted loudly.
                    self.stats["skip_reasons"][
                        "BASELINE_KAGGLE_NBA_SCHEMA_MISMATCH"] += 1
                    continue
                for row in reader:
                    self.stats["rows_read"] += 1
                    try:
                        game = self._parse_row(row, season_dir)
                    except _Quarantine as exc:
                        self._record_skip(exc.quarantine_code)
                        self._quarantine_game(exc.canonical,
                                             exc.quarantine_code)
                        continue
                    except BaselineError as exc:
                        self._record_skip(_skip_reason(exc))
                        continue
                    if game is None:
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
    def _num(row, col):
        text = str(row.get(col) or "").strip()
        if not text:
            return None
        try:
            val = float(text)
        except ValueError as exc:
            raise BaselineError(
                "BASELINE_KAGGLE_NBA_BAD_VALUE:%s" % col) from exc
        if not math.isfinite(val):
            raise BaselineError("BASELINE_KAGGLE_NBA_BAD_VALUE:%s" % col)
        return val

    def _parse_row(self, row, season_dir):
        date = str(row.get("game_date") or "").strip()
        try:
            day = datetime.strptime(date, "%Y-%m-%d")
        except ValueError as exc:
            raise BaselineError("BASELINE_KAGGLE_NBA_BAD_DATE") from exc
        season_txt = str(row.get("season_label") or "").strip()
        try:
            season = int(season_txt)
        except ValueError as exc:
            raise BaselineError("BASELINE_KAGGLE_NBA_BAD_SEASON") from exc
        # Season S covers Oct-Dec of year S and Jan-Jun of year S+1.
        if day.month >= 10:
            season_ok = day.year == season
        elif day.month <= 6:
            season_ok = day.year == season + 1
        else:
            season_ok = False
        if not season_ok:
            raise BaselineError(
                "BASELINE_KAGGLE_NBA_SEASON_MISMATCH:season=%s date=%s"
                % (season_txt, date))
        # Partition-file guard: the games.csv must live under the season
        # directory matching its season_label.
        if season_dir != season_txt:
            raise BaselineError(
                "BASELINE_KAGGLE_NBA_PARTITION_MISMATCH:dir=%s label=%s"
                % (season_dir, season_txt))
        home = canonical_team(row.get("home_team"))
        away = canonical_team(row.get("away_team"))
        if not home or not away:
            raise BaselineError("BASELINE_KAGGLE_NBA_TEAMS_MISSING")
        game = {
            "key": ("nba", date, away, home),
            "season": season_txt,
            "spread_home": self._num(row, "closing_spread_home"),
            "spread_home_juice": self._num(row, "spread_home_juice"),
            "spread_away_juice": self._num(row, "spread_away_juice"),
            "total_line": self._num(row, "closing_total"),
            "over_juice": self._num(row, "over_juice"),
            "under_juice": self._num(row, "under_juice"),
            "home_ml": self._num(row, "closing_ml_home"),
            "away_ml": self._num(row, "closing_ml_away"),
        }
        prior = self._games.get(game["key"])
        if prior is not None:
            before = {k: v for k, v in prior.items() if k != "key"}
            after = {k: v for k, v in game.items() if k != "key"}
            if before != after:
                raise _Quarantine(
                    "BASELINE_KAGGLE_NBA_CONTRADICTORY_DUPLICATE",
                    game["key"])
            return None
        return game

    # -- BaselineSource contract --------------------------------------
    def lookup(self, fixture_id, market, selection, line=None):
        try:
            return self._lookup_or_raise(fixture_id, market, selection, line)
        except BaselineError:
            return None

    def explain(self, fixture_id, market, selection, line=None) -> str:
        try:
            result = self._lookup_or_raise(fixture_id, market, selection, line)
        except BaselineError as exc:
            return "%s: %s" % (self.name, exc)
        if result is None:
            return "%s: MISSING (no archived quote)" % self.name
        return "%s: AVAILABLE p=%.4f" % (self.name, result)

    def coverage(self) -> dict:
        cov = {"source": self.name, "book_policy": self.book_policy}
        for key, value in self.stats.items():
            cov[key] = dict(value) if isinstance(value, Counter) else value
        return cov

    @staticmethod
    def _check_market_selection(market, selection):
        mkt = str(market or "").upper().strip()
        sel = str(selection or "").upper().strip()
        if mkt not in ("ML", "MONEYLINE", "SPREAD", "TOTAL"):
            raise BaselineError("BASELINE_MARKET_UNSUPPORTED:" + str(market))
        if mkt in ("ML", "MONEYLINE"):
            if sel not in ("HOME", "AWAY"):
                raise BaselineError("BASELINE_SELECTION_INVALID:" + str(selection))
        elif mkt == "SPREAD":
            if sel not in ("HOME", "AWAY"):
                raise BaselineError("BASELINE_SELECTION_INVALID:" + str(selection))
        else:
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
        if ml != cp:
            raise BaselineError(
                "BASELINE_LINE_MISMATCH:model=%r close=%r"
                % (model_line, close_point))
        return ml

    def _lookup_or_raise(self, fixture_id, market, selection, line=None):
        mkt, sel = self._check_market_selection(market, selection)
        fix = parse_fixture_id(fixture_id)
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
            hm, am = game["home_ml"], game["away_ml"]
            if hm is None or am is None:
                raise BaselineError("BASELINE_MONEYLINE_UNAVAILABLE")
            hp, ap = american_pair_to_no_vig(hm, am)
            return hp if sel == "HOME" else ap
        if mkt == "SPREAD":
            sh = game["spread_home"]
            hj, aj = game["spread_home_juice"], game["spread_away_juice"]
            if sh is None or hj is None or aj is None:
                # No juice in the archive -> MISSING. Probabilities are
                # never built on invented juice.
                raise BaselineError("BASELINE_SPREAD_QUOTE_INCOMPLETE")
            close_point = sh if sel == "HOME" else -sh
            self._check_line_match(line, close_point, market=mkt)
            hp, ap = american_pair_to_no_vig(hj, aj)
            return hp if sel == "HOME" else ap
        tl = game["total_line"]
        oj, uj = game["over_juice"], game["under_juice"]
        if tl is None or oj is None or uj is None:
            raise BaselineError("BASELINE_TOTAL_QUOTE_INCOMPLETE")
        self._check_line_match(line, tl, market=mkt)
        ovp, unp = american_pair_to_no_vig(oj, uj)
        return ovp if sel == "OVER" else unp
