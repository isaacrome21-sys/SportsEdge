"""Independent MLB game-total mean challenger (RESEARCH ONLY).

Repairs the *hypothesis* behind margin-proxy totals: run production depends on
each offense and its opposing run prevention, not predicted victory margin.

Inputs are retrospective final-score rows with caller-declared observation times.
Times are screened point-in-time, but this code DOES NOT authenticate those
times, prove capture provenance, validate a predictive distribution, or grant
pricing/PLAY/OFFICIAL authority. No bookmaker data enter the mean formula.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import hashlib
import json
from math import isfinite, sqrt
from pathlib import Path
from typing import Any, Iterable, Mapping


class MLBTotalCandidateError(ValueError):
    pass


@dataclass(frozen=True)
class CandidateSpec:
    # Development defaults. Changing these requires a NEW candidate identity;
    # do not tune against the reserved evaluation period.
    recent_games: int = 30
    prior_equivalent_games: float = 25.0
    lookback_days: int = 370
    min_team_games: int = 10
    min_league_games: int = 150

    def __post_init__(self):
        if (type(self.recent_games) is not int or self.recent_games <= 0
                or type(self.lookback_days) is not int or self.lookback_days <= 0
                or type(self.min_team_games) is not int
                or not 1 <= self.min_team_games <= self.recent_games
                or type(self.min_league_games) is not int or self.min_league_games < 1
                or isinstance(self.prior_equivalent_games, bool)
                or not isinstance(self.prior_equivalent_games, (int, float))
                or not isfinite(float(self.prior_equivalent_games))
                or self.prior_equivalent_games <= 0):
            raise MLBTotalCandidateError("CANDIDATE_SPEC_INVALID")


def _timestamp(value: Any, name: str) -> datetime:
    if isinstance(value, datetime):
        stamp = value
    elif isinstance(value, str):
        try:
            stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise MLBTotalCandidateError(f"{name}:INVALID") from exc
    else:
        raise MLBTotalCandidateError(f"{name}:INVALID")
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise MLBTotalCandidateError(f"{name}:TIMEZONE_REQUIRED")
    return stamp.astimezone(timezone.utc)


def _id(value: Any, name: str) -> str:
    if not isinstance(value, (str, int)) or isinstance(value, bool):
        raise MLBTotalCandidateError(f"{name}:IDENTITY_REQUIRED")
    out = str(value).strip()
    if not out:
        raise MLBTotalCandidateError(f"{name}:IDENTITY_REQUIRED")
    return out


# Canonical MLB club ids (t212): one club under two spellings must compare
# equal for fixture identity.  Ids outside this table (e.g. numeric MLBAM ids
# or synthetic fixtures) compare by their casefolded, space-collapsed form.
_TEAM_ALIASES = {
    "ARI": ('AZ', 'ARIZONA', 'DIAMONDBACKS', 'DBACKS', 'ARIZONA DIAMONDBACKS'),
    "ATL": ('ATLANTA', 'BRAVES', 'ATLANTA BRAVES'),
    "BAL": ('BALTIMORE', 'ORIOLES', 'BALTIMORE ORIOLES'),
    "BOS": ('BOSTON', 'RED SOX', 'BOSTON RED SOX'),
    "CHC": ('CHI CUBS', 'CUBS', 'CHICAGO CUBS', 'CHN'),
    "CWS": ('CHI WHITE SOX', 'CHW', 'CHA', 'WHITE SOX', 'CHICAGO WHITE SOX'),
    "CIN": ('CINCINNATI', 'REDS', 'CINCINNATI REDS'),
    "CLE": ('CLEVELAND', 'GUARDIANS', 'CLEVELAND GUARDIANS'),
    "COL": ('COLORADO', 'ROCKIES', 'COLORADO ROCKIES'),
    "DET": ('DETROIT', 'TIGERS', 'DETROIT TIGERS'),
    "HOU": ('HOUSTON', 'ASTROS', 'HOUSTON ASTROS'),
    "KC": ('KC ROYALS', 'KCR', 'KCA', 'KANSAS CITY', 'ROYALS', 'KANSAS CITY ROYALS'),
    "LAA": ('ANA', 'ANGELS', 'LOS ANGELES ANGELS', 'LA ANGELS'),
    "LAD": ('LOS ANGELES DODGERS', 'LAN', 'DODGERS', 'LOS ANGELES DODGERS', 'LA DODGERS'),
    "MIA": ('FLA', 'MIAMI', 'MARLINS', 'MIAMI MARLINS'),
    "MIL": ('MILWAUKEE', 'BREWERS', 'MILWAUKEE BREWERS'),
    "MIN": ('MINNESOTA', 'TWINS', 'MINNESOTA TWINS'),
    "NYM": ('NY METS', 'NYN', 'METS', 'NEW YORK METS'),
    "NYY": ('NY YANKEES', 'NYA', 'YANKEES', 'NEW YORK YANKEES'),
    "ATH": ('OAK', 'ATHLETICS', 'OAKLAND ATHLETICS', 'AS', "A'S", 'SACRAMENTO ATHLETICS'),
    "PHI": ('PHILADELPHIA', 'PHILLIES', 'PHILADELPHIA PHILLIES'),
    "PIT": ('PITTSBURGH', 'PIRATES', 'PITTSBURGH PIRATES'),
    "SD": ('SD PADRES', 'SDP', 'SDN', 'SAN DIEGO', 'PADRES', 'SAN DIEGO PADRES'),
    "SF": ('SF GIANTS', 'SFG', 'SFN', 'SAN FRANCISCO', 'GIANTS', 'SAN FRANCISCO GIANTS'),
    "SEA": ('SEATTLE', 'MARINERS', 'SEATTLE MARINERS'),
    "STL": ('STL CARDINALS', 'SLN', 'ST LOUIS', 'CARDINALS', 'ST LOUIS CARDINALS', 'ST. LOUIS CARDINALS'),
    "TB": ('TB RAYS', 'TBR', 'TBA', 'TAMPA BAY', 'RAYS', 'TAMPA BAY RAYS'),
    "TEX": ('TEXAS', 'RANGERS', 'TEXAS RANGERS'),
    "TOR": ('TORONTO', 'BLUE JAYS', 'TORONTO BLUE JAYS'),
    "WSH": ('WSN', 'WAS', 'WASHINGTON', 'NATIONALS', 'WASHINGTON NATIONALS'),
}


def _alias_key(value: str) -> str:
    return " ".join("".join(ch for ch in str(value).upper() if ch.isalnum() or ch.isspace()).split())


_CANONICAL = {}
for _club, _names in _TEAM_ALIASES.items():
    for _name in (_club, *_names):
        _CANONICAL[_alias_key(_name)] = _club


def canonical_team_id(value: Any) -> str:
    key = _alias_key(value)
    return _CANONICAL.get(key, key.casefold())


# Same-club fixture identity (t212).  final_observed is an ingest time and is
# never used as a game end.  For two consecutive games of one club:
#   * starts under DOUBLEHEADER_MIN_GAP apart can never both be real;
#   * a recorded game end (end ts / duration) of the earlier game is always
#     binding: the later start must not precede it;
#   * grounded doubleheader: same away/home pair, gameNumber exactly 1 then 2,
#     doubleHeader Y or S and identical on both games, within a day;
#   * a different opponent always needs the 180-minute window;
#   * else (same pair) a recorded end that precedes the later start suffices;
#   * else (no grounded field) the later start must be >= 180 minutes after.
DOUBLEHEADER_MIN_GAP = timedelta(minutes=90)
MIN_SAME_TEAM_START_GAP = timedelta(minutes=180)


def _same_club_games_ok(earlier: "FinalScore", later: "FinalScore") -> bool:
    gap = later.event_start - earlier.event_start
    if gap < DOUBLEHEADER_MIN_GAP:
        return False
    # A recorded end is binding in every case (t212 audit).
    if earlier.game_end is not None and later.event_start < earlier.game_end:
        return False
    same_pair = (canonical_team_id(earlier.away_id), canonical_team_id(earlier.home_id)) == \
        (canonical_team_id(later.away_id), canonical_team_id(later.home_id))
    if not same_pair:
        # Different opponent: 180 minutes regardless of any recorded end.
        return gap >= MIN_SAME_TEAM_START_GAP
    if (same_pair and (earlier.game_number, later.game_number) == (1, 2)
            and earlier.double_header in {"Y", "S"}
            and earlier.double_header == later.double_header
            and gap < timedelta(hours=24)):
        return True
    if earlier.game_end is not None:
        return True  # end recorded and already proven before the later start
    return gap >= MIN_SAME_TEAM_START_GAP


def _runs(value: Any, name: str) -> int:
    if type(value) is not int or not 0 <= value <= 100:
        raise MLBTotalCandidateError(f"{name}:NONNEGATIVE_INTEGER_REQUIRED")
    return value


def _first(raw: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if raw.get(key) is not None:
            return raw.get(key)
    return None


def _game_number(raw: Mapping[str, Any]) -> int | None:
    value = _first(raw, "gameNumber", "game_number")
    if value is None:
        return None
    if type(value) is not int or not 1 <= value <= 3:
        raise MLBTotalCandidateError("GAME_NUMBER_INVALID")
    return value


def _double_header(raw: Mapping[str, Any]) -> str | None:
    value = _first(raw, "doubleHeader", "double_header")
    if value is None:
        return None
    out = str(value).strip().upper()
    if out not in {"Y", "S", "N"}:
        raise MLBTotalCandidateError("DOUBLE_HEADER_FLAG_INVALID")
    return out


def _game_end(raw: Mapping[str, Any], start: datetime) -> datetime | None:
    end_raw = _first(raw, "game_end_ts", "gameEndDateTime")
    if end_raw is not None:
        end = _timestamp(end_raw, "game_end_ts")
        if end <= start:
            raise MLBTotalCandidateError("GAME_END_BEFORE_START")
        return end
    minutes = _first(raw, "game_duration_minutes", "gameDurationMinutes")
    if minutes is None:
        return None
    if isinstance(minutes, bool) or not isinstance(minutes, (int, float)) or \
            not isfinite(float(minutes)) or not 0 < float(minutes) <= 600:
        raise MLBTotalCandidateError("GAME_DURATION_INVALID")
    return start + timedelta(minutes=float(minutes))


@dataclass(frozen=True)
class FinalScore:
    event_id: str
    away_id: str
    home_id: str
    event_start: datetime
    final_observed: datetime
    away_runs: int
    home_runs: int
    # Grounded fixture identity (t212): statsapi gameNumber / doubleHeader and
    # a recorded game end (end timestamp or duration).  Optional; absent
    # fields fall back to the 180-minute same-club window.
    game_number: int | None = None
    double_header: str | None = None
    game_end: datetime | None = None

    @classmethod
    def parse(cls, raw: Mapping[str, Any]) -> "FinalScore":
        # Do not admit a pregame feature contaminated with a market quote.
        if not isinstance(raw, Mapping) or any(k in raw for k in (
            "american_odds", "model_p", "price", "market_total",
            "closing_total", "closing_spread", "spread_line",
        )):
            raise MLBTotalCandidateError("FINAL_SCORE_INPUT_INVALID_OR_MARKET_LEAK")
        if raw.get("status") != "FINAL":
            raise MLBTotalCandidateError("ONLY_FINAL_SCORES_ADMISSIBLE")
        start = _timestamp(raw.get("event_start_ts"), "event_start_ts")
        observed = _timestamp(raw.get("final_observed_ts"), "final_observed_ts")
        if observed <= start:
            raise MLBTotalCandidateError("FINAL_OBSERVED_BEFORE_EVENT_END")
        away, home = _id(raw.get("away_id"), "away_id"), _id(raw.get("home_id"), "home_id")
        if away == home:
            raise MLBTotalCandidateError("SAME_TEAM_BOTH_SIDES")
        return cls(
            event_id=_id(raw.get("event_id"), "event_id"), away_id=away, home_id=home,
            event_start=start, final_observed=observed,
            away_runs=_runs(raw.get("away_runs"), "away_runs"),
            home_runs=_runs(raw.get("home_runs"), "home_runs"),
            game_number=_game_number(raw),
            double_header=_double_header(raw),
            game_end=_game_end(raw, start),
        )


def parse_finals(history: Iterable[Mapping[str, Any]]) -> tuple[FinalScore, ...]:
    """Legacy ungrounded structural + time-window screen.  Secondary only:
    predict_total / prequential_backtest load through load_grounded_finals."""
    if isinstance(history, (str, bytes, Mapping)):
        raise MLBTotalCandidateError("HISTORY_SEQUENCE_REQUIRED")
    records = tuple(FinalScore.parse(row) for row in history)
    if len({row.event_id for row in records}) != len(records):
        raise MLBTotalCandidateError("DUPLICATE_EVENT_ID")
    # Fixture identity (t211u/t212): one real game under two event ids, or a
    # club booked into overlapping games, would be counted twice.  Team ids
    # are compared by canonical club id (aliases, case, spacing).  Fail closed.
    fixtures: set = set()
    by_team: dict = {}
    for row in records:
        away, home = canonical_team_id(row.away_id), canonical_team_id(row.home_id)
        if away == home:
            raise MLBTotalCandidateError(f"SAME_TEAM_BOTH_SIDES:{row.event_id}")
        key = (away, home, row.event_start)
        if key in fixtures:
            raise MLBTotalCandidateError(f"DUPLICATE_FIXTURE_IDENTITY:{row.event_id}")
        fixtures.add(key)
        for team in (away, home):
            by_team.setdefault(team, []).append(row)
    for team, games in by_team.items():
        games.sort(key=lambda r: (r.event_start, r.event_id))
        for earlier, later in zip(games, games[1:]):
            if not _same_club_games_ok(earlier, later):
                raise MLBTotalCandidateError(
                    f"DUPLICATE_FIXTURE_IDENTITY:TEAM_OVERLAP:{team}:"
                    f"{earlier.event_id}:{later.event_id}")
    return records


# ---------------------------------------------------------------------------
# Grounded fixture identity (t212, owner redesign on #2357).
#
# Identity is the statsapi gamePk.  A row counts only when its gamePk resolves
# to a stored statsapi raw record in a hash-pinned index and the row's teams,
# start, scores, gameNumber, doubleHeader and any end/duration claim match that
# record.  Rows that cannot be grounded are excluded and listed in a refusal
# ledger as UNVERIFIED_FIXTURE_IDENTITY; the load fails closed only when the
# ledger exceeds the configured threshold.  Time windows are a secondary
# annotation on ungrounded rows only and never gate the load.
# ---------------------------------------------------------------------------
IDENTITY_CONFIG_PATH = (Path(__file__).resolve().parents[2] / "config" / "research"
                        / "mlb_challenger_fixture_identity_v1.json")
UNVERIFIED = "UNVERIFIED_FIXTURE_IDENTITY"


def _identity_config() -> dict[str, Any]:
    cfg = json.loads(IDENTITY_CONFIG_PATH.read_text(encoding="utf-8"))
    if cfg.get("identity") != "STATSAPI_GAMEPK_RAW_RECORD":
        raise MLBTotalCandidateError("FIXTURE_IDENTITY_CONFIG_INVALID")
    return cfg


def _pk(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


@dataclass(frozen=True)
class RawFixture:
    game_pk: int
    start: datetime
    official_date: str | None
    away: str
    home: str
    away_team_id: str | None
    home_team_id: str | None
    away_runs: int | None
    home_runs: int | None
    game_number: int | None
    double_header: str | None
    final: bool
    resumed_from_pk: int | None
    duration_minutes: float | None

    @classmethod
    def from_game(cls, game: Mapping[str, Any]) -> "RawFixture":
        pk = _pk(game.get("gamePk"))
        if pk is None:
            raise MLBTotalCandidateError("RAW_GAME_PK_INVALID")
        teams = game.get("teams") or {}
        def side(name):
            t = (teams.get(name) or {})
            team = t.get("team") or {}
            score = t.get("score")
            return (canonical_team_id(team.get("name") or team.get("abbreviation") or team.get("id")),
                    None if team.get("id") is None else str(team.get("id")),
                    score if type(score) is int else None)
        away, away_id, away_runs = side("away")
        home, home_id, home_runs = side("home")
        status = game.get("status") or {}
        info = game.get("gameInfo") or {}
        duration = info.get("gameDurationMinutes", game.get("gameDurationMinutes"))
        return cls(
            game_pk=pk, start=_timestamp(game.get("gameDate"), "raw_gameDate"),
            official_date=game.get("officialDate"), away=away, home=home,
            away_team_id=away_id, home_team_id=home_id,
            away_runs=away_runs, home_runs=home_runs,
            game_number=game.get("gameNumber") if type(game.get("gameNumber")) is int else None,
            double_header=(str(game["doubleHeader"]).upper() if game.get("doubleHeader") else None),
            final=str(status.get("abstractGameState") or "").lower() == "final",
            resumed_from_pk=_pk(game.get("resumedFromGamePk") or game.get("resumedFromPk")),
            duration_minutes=(float(duration) if isinstance(duration, (int, float))
                              and not isinstance(duration, bool) else None),
        )


def _documents_games(docs: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    games = []
    for doc in docs:
        if not isinstance(doc, Mapping):
            raise MLBTotalCandidateError("RAW_DOCUMENT_INVALID")
        for day in doc.get("dates") or []:
            games.extend(day.get("games") or [])
    return games


class FixtureIndex:
    """Hash-pinned index of stored statsapi raw schedule records."""

    def __init__(self, fixtures: Mapping[int, RawFixture], sha256: str):
        self._fixtures = dict(fixtures)
        self.sha256 = sha256

    @staticmethod
    def digest_documents(docs: Iterable[Mapping[str, Any]]) -> str:
        games = sorted(_documents_games(docs), key=lambda g: str(g.get("gamePk")))
        raw = json.dumps(games, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                         default=str).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    @classmethod
    def from_statsapi_documents(cls, docs: Iterable[Mapping[str, Any]], *,
                                expected_sha256: str | None) -> "FixtureIndex":
        docs = list(docs)
        if not isinstance(expected_sha256, str) or len(expected_sha256) != 64:
            raise MLBTotalCandidateError("FIXTURE_INDEX_HASH_REQUIRED")
        actual = cls.digest_documents(docs)
        if actual != expected_sha256.lower():
            raise MLBTotalCandidateError("FIXTURE_INDEX_HASH_MISMATCH")
        fixtures: dict[int, RawFixture] = {}
        for game in _documents_games(docs):
            fx = RawFixture.from_game(game)
            prior = fixtures.get(fx.game_pk)
            # The same gamePk may be listed on its original (suspended) date
            # and its resume date; the Final record is authoritative.
            if prior is None or (fx.final and not prior.final):
                fixtures[fx.game_pk] = fx
        return cls(fixtures, actual)

    @classmethod
    def from_raw_dir(cls, path: str | Path, *, expected_sha256: str | None) -> "FixtureIndex":
        docs = [json.loads(p.read_text(encoding="utf-8"))
                for p in sorted(Path(path).rglob("*.json"))]
        return cls.from_statsapi_documents(docs, expected_sha256=expected_sha256)

    def has(self, pk: int) -> bool:
        return pk in self._fixtures

    def get(self, pk: int) -> RawFixture | None:
        return self._fixtures.get(pk)


def _team_matches(row_team: str, canonical: str, team_id: str | None) -> bool:
    return canonical_team_id(row_team) == canonical or (
        team_id is not None and str(row_team).strip() == team_id)


def _ground(row: FinalScore, raw: Mapping[str, Any], index: FixtureIndex) -> tuple[RawFixture | None, str | None]:
    pk = _pk(_first(raw, "game_pk", "gamePk"))
    if pk is None:
        return None, "GAME_PK_MISSING"
    fx = index.get(pk)
    if fx is None:
        return None, f"GAME_PK_NOT_IN_INDEX:{pk}"
    if not fx.final:
        return None, f"RAW_RECORD_NOT_FINAL:{pk}"
    if not (_team_matches(row.away_id, fx.away, fx.away_team_id)
            and _team_matches(row.home_id, fx.home, fx.home_team_id)):
        return None, f"TEAMS_MISMATCH:{pk}"
    if row.event_start != fx.start:
        return None, f"START_MISMATCH:{pk}"
    if raw.get("official_date") is not None and raw.get("official_date") != fx.official_date:
        return None, f"DATE_MISMATCH:{pk}"
    if (fx.away_runs, fx.home_runs) != (row.away_runs, row.home_runs):
        return None, f"SCORE_MISMATCH:{pk}"
    if row.game_number is not None and row.game_number != fx.game_number:
        return None, f"GAME_NUMBER_MISMATCH:{pk}"
    if row.double_header is not None and row.double_header != fx.double_header:
        return None, f"DOUBLE_HEADER_MISMATCH:{pk}"
    if row.game_end is not None:
        if fx.duration_minutes is None:
            return None, f"GAME_END_UNGROUNDED:{pk}"
        if abs((row.game_end - row.event_start).total_seconds() / 60.0 - fx.duration_minutes) > 1.0:
            return None, f"GAME_END_MISMATCH:{pk}"
    return fx, None


@dataclass(frozen=True)
class GroundedLoad:
    records: tuple[FinalScore, ...]
    ledger: list = field(default_factory=list)
    index_sha256: str = ""


def load_grounded_finals(history: Iterable[Mapping[str, Any]], *, fixture_index: FixtureIndex,
                         max_unverified_rows: int | None = None,
                         max_unverified_fraction: float | None = None) -> GroundedLoad:
    if not isinstance(fixture_index, FixtureIndex):
        raise MLBTotalCandidateError("FIXTURE_INDEX_REQUIRED")
    if isinstance(history, (str, bytes, Mapping)):
        raise MLBTotalCandidateError("HISTORY_SEQUENCE_REQUIRED")
    raws = list(history)
    # Structural refusals (non-final, market leak, bad clocks) still raise.
    parsed = [FinalScore.parse(r) for r in raws]
    if len({r.event_id for r in parsed}) != len(parsed):
        raise MLBTotalCandidateError("DUPLICATE_EVENT_ID")
    ledger: list[dict[str, Any]] = []
    grounded: list[tuple[FinalScore, RawFixture]] = []
    for row, raw in zip(parsed, raws):
        fx, reason = _ground(row, raw, fixture_index)
        if fx is None:
            ledger.append({"event_id": row.event_id, "status": UNVERIFIED, "reason": reason, "_row": row})
        else:
            grounded.append((row, fx))
    # Duplicates: same gamePk, or gamePks linked as one resumed game.
    def root(fx: RawFixture) -> int:
        seen = set()
        while fx.resumed_from_pk is not None and fx.resumed_from_pk not in seen:
            seen.add(fx.game_pk)
            nxt = fixture_index.get(fx.resumed_from_pk)
            if nxt is None:
                return fx.resumed_from_pk
            fx = nxt
        return fx.game_pk
    groups: dict[int, list] = {}
    for row, fx in grounded:
        groups.setdefault(root(fx), []).append((row, fx))
    records = []
    for key, members in groups.items():
        if len(members) == 1:
            records.append(members[0][0])
            continue
        for row, fx in members:  # fail closed: every copy excluded
            ledger.append({"event_id": row.event_id, "status": UNVERIFIED,
                           "reason": f"DUPLICATE_FIXTURE_IDENTITY:{key}", "_row": row})
    # Secondary sanity annotation on ungrounded rows only (never a gate).
    by_team: dict[str, list[FinalScore]] = {}
    for row in [*records, *(e["_row"] for e in ledger)]:
        for team in (canonical_team_id(row.away_id), canonical_team_id(row.home_id)):
            by_team.setdefault(team, []).append(row)
    for entry in ledger:
        row = entry.pop("_row")
        conflict = False
        for team in (canonical_team_id(row.away_id), canonical_team_id(row.home_id)):
            for other in by_team.get(team, []):
                if other is row:
                    continue
                a, b = sorted((row, other), key=lambda r: (r.event_start, r.event_id))
                if not _same_club_games_ok(a, b):
                    conflict = True
        entry["time_window_check"] = "CONFLICT" if conflict else "CONSISTENT"
    cfg = _identity_config()
    limit_rows = cfg["max_unverified_rows"] if max_unverified_rows is None else max_unverified_rows
    limit_frac = (cfg["max_unverified_fraction"] if max_unverified_fraction is None
                  else max_unverified_fraction)
    total = max(len(parsed), 1)
    if len(ledger) > limit_rows or len(ledger) / total > limit_frac:
        raise MLBTotalCandidateError(
            f"UNVERIFIED_FIXTURE_LEDGER_EXCEEDED:{len(ledger)}>{limit_rows}rows/{limit_frac}")
    records.sort(key=lambda r: (r.event_start, r.event_id))
    return GroundedLoad(records=tuple(records), ledger=ledger, index_sha256=fixture_index.sha256)


def _predict(records: tuple[FinalScore, ...], target: Mapping[str, Any],
             spec: CandidateSpec) -> dict[str, Any]:
    if not isinstance(target, Mapping):
        raise MLBTotalCandidateError("TARGET_INVALID")
    start = _timestamp(target.get("event_start_ts"), "event_start_ts")
    event_id = _id(target.get("event_id"), "event_id")
    away = _id(target.get("away_id"), "away_id")
    home = _id(target.get("home_id"), "home_id")
    if away == home:
        raise MLBTotalCandidateError("SAME_TEAM_BOTH_SIDES")
    cutoff = start - timedelta(days=spec.lookback_days)
    # Strict availability: an earlier start is not sufficient unless its
    # final result was observed strictly before this game's start.
    league = [r for r in records if cutoff <= r.event_start < start
              and r.final_observed < start and r.event_id != event_id]
    if len(league) < spec.min_league_games:
        raise MLBTotalCandidateError("LEAGUE_HISTORY_INSUFFICIENT")
    baseline_away = sum(r.away_runs for r in league) / len(league)
    baseline_home = sum(r.home_runs for r in league) / len(league)
    league_mean = (baseline_away + baseline_home) / 2.0
    if league_mean <= 0:
        raise MLBTotalCandidateError("LEAGUE_RATE_ZERO")

    def rates(team: str) -> tuple[float, float, int]:
        chosen = [r for r in league if team in (r.away_id, r.home_id)]
        chosen.sort(key=lambda r: (r.event_start, r.event_id))
        chosen = chosen[-spec.recent_games:]
        if len(chosen) < spec.min_team_games:
            raise MLBTotalCandidateError(f"TEAM_HISTORY_INSUFFICIENT:{team}")
        scored = sum(r.away_runs if r.away_id == team else r.home_runs for r in chosen)
        allowed = sum(r.home_runs if r.away_id == team else r.away_runs for r in chosen)
        denom = len(chosen) + spec.prior_equivalent_games
        return ((scored + spec.prior_equivalent_games * league_mean) / denom,
                (allowed + spec.prior_equivalent_games * league_mean) / denom,
                len(chosen))

    away_for, away_against, away_n = rates(away)
    home_for, home_against, home_n = rates(home)
    # Team attack x opposing prevention, anchored to actual home/away scoring.
    # Predict *means only*. A Poisson, correlated score path and priced EV
    # still require separate untouched-holdout validation.
    away_runs = baseline_away * (away_for / league_mean) * (home_against / league_mean)
    home_runs = baseline_home * (home_for / league_mean) * (away_against / league_mean)
    if any(not isfinite(x) or x < 0 for x in (away_runs, home_runs)):
        raise MLBTotalCandidateError("PREDICTED_RATE_INVALID")
    return {
        "schema_version": "MLB_TOTAL_OFFENSE_DEFENSE_RESEARCH_V1",
        "candidate_id": "MLB_TOTAL_OD_SHRINKAGE_30_25_V1",
        "status": "RESEARCH_ONLY_NOT_VALIDATED",
        "pricing_authorized": False,
        "official_authorized": False,
        "point_in_time_capture_authenticated": False,
        "event_id": event_id,
        "away_team_mean": away_runs, "home_team_mean": home_runs,
        "candidate_total_mean": away_runs + home_runs,
        "league_only_total_baseline": baseline_away + baseline_home,
        "league_games": len(league),
        "away_history_games": away_n,
        "home_history_games": home_n,
    }


def predict_total(history: Iterable[Mapping[str, Any]], target: Mapping[str, Any],
                  *, fixture_index: FixtureIndex, spec: CandidateSpec = CandidateSpec(),
                  max_unverified_rows: int | None = None,
                  max_unverified_fraction: float | None = None) -> dict[str, Any]:
    load = load_grounded_finals(history, fixture_index=fixture_index,
                                max_unverified_rows=max_unverified_rows,
                                max_unverified_fraction=max_unverified_fraction)
    out = _predict(load.records, target, spec)
    out.update({"fixture_index_sha256": load.index_sha256,
                "n_unverified_fixture_identity": len(load.ledger),
                "refusal_ledger": load.ledger})
    return out


def prequential_backtest(history: Iterable[Mapping[str, Any]], *,
                         holdout_from: str, fixture_index: FixtureIndex,
                         spec: CandidateSpec = CandidateSpec(),
                         max_unverified_rows: int | None = None,
                         max_unverified_fraction: float | None = None) -> dict[str, Any]:
    """Development score-only comparison. Never treats row count as independent markets.

    Walks forward at each actual kickoff, using only finals *already observed*.
    Holdout boundary must have been selected externally before inspecting data.
    """
    load = load_grounded_finals(history, fixture_index=fixture_index,
                                max_unverified_rows=max_unverified_rows,
                                max_unverified_fraction=max_unverified_fraction)
    records = load.records
    boundary = _timestamp(holdout_from, "holdout_from")
    trials: list[tuple[float, float, float]] = []
    refused: dict[str, int] = {}
    for row in sorted(records, key=lambda r: (r.event_start, r.event_id)):
        if row.event_start < boundary:
            continue
        target = dict(event_id=row.event_id, away_id=row.away_id,
                      home_id=row.home_id, event_start_ts=row.event_start)
        try:
            pred = _predict(records, target, spec)
        except MLBTotalCandidateError as exc:
            refused[str(exc)] = refused.get(str(exc), 0) + 1
            continue
        actual = float(row.away_runs + row.home_runs)
        trials.append((actual, pred["candidate_total_mean"],
                       pred["league_only_total_baseline"]))
    if not trials:
        raise MLBTotalCandidateError("NO_EVALUABLE_HOLDOUT_GAMES")
    def metric(index: int):
        return {
            "mae": sum(abs(row[0] - row[index]) for row in trials) / len(trials),
            "rmse": sqrt(sum((row[0] - row[index]) ** 2 for row in trials) / len(trials)),
        }
    return {
        "status": "RETROSPECTIVE_DEVELOPMENT_ONLY",
        "validated": False, "official_authorized": False,
        "point_in_time_capture_authenticated": False,
        "holdout_from": boundary.isoformat(),
        "n_distinct_games": len(trials),
        "n_refused": sum(refused.values()), "refusal_reasons": refused,
        "candidate": metric(1), "league_only_baseline": metric(2),
        "paired_market_benchmark": "MISSING",
        "fixture_index_sha256": load.index_sha256,
        "n_unverified_fixture_identity": len(load.ledger),
        "refusal_ledger": load.ledger,
        "claim": "No calibrated distribution or market-relative edge established",
    }
