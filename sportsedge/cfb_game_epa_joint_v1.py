"""CFB_GAME_EPA_JOINT_V1 — frozen-implementation candidate, NOT FROZEN.

Checklist item 4 of the CFB EPA freeze path (the implementation build
behind the confirmed preregistration draft
research/cfb_game_epa_joint_v1_20261031/PREREG_DRAFT_V2.md, confirmed
as the freeze-candidate text by the independent confirmation pass of
Oct 31, 2026). This module changes nothing about the family's state:

  * FREEZE_STATE stays "DRAFT_NOT_IN_FORCE"; the freeze act is the
    owner's separate act (checklist item 7) and this build does not
    perform it.
  * Every counted entry point refuses with
    CFB_GAME_EPA_JOINT_NOT_FROZEN until a freeze record is supplied.
  * Research mode runs on DESIGN DATA only (every admitted historical
    season is design data — consumed by the retired AM/PM, converged
    successor, and chrono constructions). Every research output is
    labeled RESEARCH_DESIGN_DATA_NOT_VALIDATION and claims nothing.
  * The records branch named by prereg section 1
    (records/cfb-game-epa-joint-v1) is a freeze-era creation; this
    build never creates it and never writes to any records location.

What is built here, section by section against PREREG_DRAFT_V2:

  * Section 1 construction: play-by-play EPA/possession features from
    sportsdataverse (cfbfastR-form) play-by-play joined to SDV
    schedules — offensive/defensive EPA per play and per possession,
    success rate, explosiveness rate, pace — each opponent-adjusted by
    iteration to a stated tolerance, plus a points-only margin rating
    carried as a blend component. Preseason prior: prior-season final
    ratings entering as pseudo-games with a stated retention.
    No market line, price, or closing value of any kind enters the
    construction.
  * Section 1 point-in-time machinery: weekly snapshots committed
    before the week's first kickoff; feature games are those completed
    at least 24 hours before each predicted game's kickoff (the repo's
    established kickoff+24h availability proxy, as in
    scripts/evaluate_cfb_sdv_closes.py); predictions are written and
    hashed into a prediction ledger before kickoff — a prediction not
    committed pre-kickoff does not exist for the test, enforced in the
    ledger and again in the evaluator.
  * Section 2.1 baseline: PM (CFB_MATCHUP_OFF_DEF_V1 /
    CFB_OPPONENT_ADJUSTED_V1) reproduced exactly as in
    scripts/evaluate_cfb_sdv_closes.py (last-5 opponent-adjusted
    off/def, 3-game shrinkage toward 28, HFA 2.5, >=3 prior games per
    team), with PM's probabilities formed under the pinned "prod" SD
    set (margin 19.0, total 18.5). The "lane" SD set plays no part.
  * Section 2.2 / section 4 evaluator: three arms on identical rows —
    construction, PM, and the market arm formed from the POWER_V1
    de-vigged DraftKings closing implied probability
    (sportsedge.devig.power_devig). The SDV evaluator's ln 2 market
    placeholder is expressly NOT used anywhere in this module.
    Close validity and the missing-close disposition follow prereg
    section 2.2(b)/(c) exactly; the section 2.2(d) market-leg
    sufficiency rule issues INSUFFICIENT_MARKET_DATA as a
    data-sufficiency outcome (not a VERIFIED gate, and it does not
    consume the single verdict look). Primary metric: mean log loss
    per market (SPREAD, TOTAL separately, never pooled); PASS requires
    the model's mean log loss strictly below BOTH baselines AND each
    difference's game-cluster bootstrap CI (10,000 resamples, seed
    20261028, two-sided percentile at 1 - alpha/k, k = max(k at
    freeze, k at verdict)) entirely below 0, at the single verdict
    look, at or after 300 graded games in the market. FAIL is
    terminal for the construction.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Iterable, Mapping, Optional

from sportsedge.devig import DevigError, power_devig

CONSTRUCTION_ID = "CFB_GAME_EPA_JOINT_V1"
FREEZE_STATE = "DRAFT_NOT_IN_FORCE"
REFUSAL_NOT_FROZEN = "CFB_GAME_EPA_JOINT_NOT_FROZEN"
RECORDS_BRANCH = "records/cfb-game-epa-joint-v1"
RESEARCH_MODE_LABEL = "RESEARCH_DESIGN_DATA_NOT_VALIDATION"

MARKETS = ("SPREAD", "TOTAL")

# ------------------------------------------------------------------
# Construction constants (prereg section 1: stated in the frozen
# implementation; enumerated again in the freeze record per section
# 5.3). Design-phase choices made under the prereg's silence are
# flagged in BUILD_RECORD.md -- none was fitted to validation data
# (no validation sample exists before the freeze).
# ------------------------------------------------------------------

EMBARGO_HOURS = 24  # feature game available 24h after its kickoff

ADJUSTMENT_TOLERANCE = 1e-6  # opponent-adjustment iteration tolerance
ADJUSTMENT_MAX_ITERATIONS = 500
ADJUSTMENT_DAMPING = 0.5

PRIOR_PSEUDO_GAMES = 3.0  # preseason prior weight, in games
PRIOR_SEASON_RETENTION = 0.65  # prior-season rating retained fraction

# Rate differentials are converted to points per play at these stated
# rates (EPA itself is already in points-per-play units and enters
# the per-play channel at coefficient 1.0).
SUCCESS_TO_EPA = 1.0
EXPLOSIVE_TO_EPA = 1.5
EXPLOSIVE_YARDS_THRESHOLD = 20.0  # loader-level: yards_gained >= 20

EPA_CHANNEL_PLAY_WEIGHT = 0.5  # per-play vs per-possession EPA channels
POINTS_BLEND_WEIGHT = 0.25  # points-only rating channel in the blend

HOME_FIELD_ADVANTAGE_POINTS = 2.5  # construction's own HFA constant

# The construction's OWN probability SDs (prereg section 1: the
# production PRIORS values are the baseline's and are NOT inherited).
CONSTRUCTION_SD_MARGIN = 16.0
CONSTRUCTION_SD_TOTAL = 15.0

# PM baseline pins (prereg section 2.1: "prod" set, pinned by F3).
PM_SD_MARGIN = 19.0
PM_SD_TOTAL = 18.5
PM_BASE = 28.0
PM_HFA = 2.5
PM_WINDOW = 5
PM_SHRINK = 3
PM_MIN_PRIOR_GAMES = 3

# ------------------------------------------------------------------
# Evaluator constants (prereg sections 2.2 and 4, as pinned by the
# V2 revision: F1 close validity + sufficiency, F4 bootstrap).
# ------------------------------------------------------------------

ALPHA = 0.05
BOOTSTRAP_RESAMPLES = 10000
BOOTSTRAP_SEED = 20261028
MIN_GRADED_GAMES = 300
MAX_MISSING_CLOSE_SHARE = 0.20  # strictly greater trips (prereg 2.2(d))
CLOSE_MAX_AGE = timedelta(minutes=60)  # exactly 60:00 is valid
CLOSE_FAILURE_CODES = (
    "NO_CLOSE_ROW", "CLOSE_STALE", "CLOSE_NOT_PREKICKOFF",
    "CLOSE_SINGLE_SIDED")
PROB_EPS = 1e-15  # log-loss numerical guard (never a stated probability)


class CfbEpaError(ValueError):
    """Named, fail-closed refusal (the reason code is stable)."""

    def __init__(self, reason: str, detail: str = "") -> None:
        self.reason = reason
        self.detail = detail
        super().__init__(reason if not detail else f"{reason}: {detail}")


# ------------------------------------------------------------------
# Small strict helpers (data boundaries fail closed, repo pattern).
# ------------------------------------------------------------------


def _strict_number(value) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _parse_ts(value) -> Optional[datetime]:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _require_ts(value, reason: str) -> datetime:
    parsed = _parse_ts(value)
    if parsed is None:
        raise CfbEpaError(reason, f"unparseable or naive timestamp: {value!r}")
    return parsed


def _phi(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _log_loss(p_realized: float) -> float:
    p = min(max(p_realized, PROB_EPS), 1.0 - PROB_EPS)
    return -math.log(p)


def _canonical_json(payload: Mapping) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      allow_nan=False)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ------------------------------------------------------------------
# Standing exclusions (prereg section 3: applied upstream; an
# excluded fixture in the sample is a defect, not a row).
# The program's canonical enforcement is ID-keyed
# (artifacts/free_models.py IL_COLLEGE_ESPN_IDS, with the name list
# as secondary signal). SDV data is name-keyed, so this module
# carries the exact-match name backstop: normalized full names only
# ("Northwestern State" and "Middle Tennessee" are NOT excluded).
# ------------------------------------------------------------------

ILLINOIS_COLLEGE_NAMES = frozenset({
    "illinois", "northwestern", "illinois state", "northern illinois",
    "southern illinois", "eastern illinois", "western illinois",
    "chicago state",
})
OWNER_BLOCKED_NAMES = frozenset({"tennessee"})  # Tennessee Volunteers


def _normalize_team(name) -> str:
    return " ".join(str(name).split()).casefold()


def is_excluded_team(name) -> bool:
    normalized = _normalize_team(name)
    return normalized in ILLINOIS_COLLEGE_NAMES or normalized in OWNER_BLOCKED_NAMES


def is_excluded_fixture(home, away) -> bool:
    return is_excluded_team(home) or is_excluded_team(away)


# ------------------------------------------------------------------
# Input records (normalized module contract; loaders below map the
# sportsdataverse release shapes onto these).
# ------------------------------------------------------------------


@dataclass(frozen=True)
class PlayRow:
    """One play from the SDV play-by-play release, normalized.

    `success` follows the standard down/distance definition (50% of
    yards to go on 1st down, 70% on 2nd, 100% on 3rd/4th) when the
    release's own success column is absent; `explosive` is
    yards_gained >= EXPLOSIVE_YARDS_THRESHOLD. Both are resolved at
    load time; feature computation consumes them as given.
    """

    game_id: str
    offense: str
    defense: str
    epa: float
    success: bool
    explosive: bool
    yards_gained: float
    drive_id: str

    def __post_init__(self) -> None:
        if _strict_number(self.epa) is None:
            raise CfbEpaError("NONFINITE_EPA_INPUT",
                              f"game {self.game_id}: epa={self.epa!r}")
        if _strict_number(self.yards_gained) is None:
            raise CfbEpaError(
                "NONFINITE_YARDS_INPUT",
                f"game {self.game_id}: yards_gained={self.yards_gained!r}")
        if not isinstance(self.success, bool) or not isinstance(
                self.explosive, bool):
            raise CfbEpaError("PLAY_FLAG_TYPE_INVALID",
                              f"game {self.game_id}")


@dataclass(frozen=True)
class GameResult:
    """A completed game with its final score (a feature/scoring game)."""

    game_id: str
    season: int
    week: int
    kickoff: datetime
    home: str
    away: str
    home_points: float
    away_points: float
    neutral_site: bool = False

    def __post_init__(self) -> None:
        _require_ts(self.kickoff, "GAME_KICKOFF_TIMESTAMP_INVALID")
        if _strict_number(self.home_points) is None or _strict_number(
                self.away_points) is None:
            raise CfbEpaError("NONFINITE_CFB_RESULT_INPUT",
                              f"game {self.game_id}")


@dataclass(frozen=True)
class GameFixture:
    """A game to be predicted (no final score exists yet)."""

    game_id: str
    season: int
    week: int
    kickoff: datetime
    home: str
    away: str
    neutral_site: bool = False

    def __post_init__(self) -> None:
        _require_ts(self.kickoff, "GAME_KICKOFF_TIMESTAMP_INVALID")


@dataclass(frozen=True)
class CloseRecord:
    """One market's closing two-sided DraftKings price for one game.

    For SPREAD, `line` is the closing margin line from the home
    team's perspective (the market's expected home margin, i.e.
    -home_team_spread in the SDV closes convention) and the prices
    are (home, away). For TOTAL, `line` is the closing total and
    the prices are (over, under). A missing side is None and is
    classified CLOSE_SINGLE_SIDED by the evaluator.
    """

    game_id: str
    market: str
    line: Optional[float]
    price_first: Optional[float]  # home (SPREAD) / over (TOTAL), American
    price_second: Optional[float]  # away (SPREAD) / under (TOTAL), American
    captured_at: Optional[datetime]

    def __post_init__(self) -> None:
        if self.market not in MARKETS:
            raise CfbEpaError("CLOSE_MARKET_INVALID", self.market)


# ------------------------------------------------------------------
# Loaders: sportsdataverse release shapes -> module contract.
# Exclusions are tallied by reason, never silently dropped (the
# repo's finite-source gate pattern).
# ------------------------------------------------------------------


@dataclass
class LoadResult:
    rows: list
    excluded: dict = field(default_factory=dict)

    def _tally(self, reason: str) -> None:
        self.excluded[reason] = self.excluded.get(reason, 0) + 1


def _first(row: Mapping, *keys: str):
    for key in keys:
        if key in row and row[key] is not None:
            return row[key]
    return None


def _require_row_list(rows, code: str) -> list:
    """Fail closed on a malformed container: a bare string would
    otherwise iterate character-by-character and tally nonsense
    instead of refusing."""
    if isinstance(rows, (str, bytes)) or not isinstance(rows, Iterable):
        raise CfbEpaError(code, "rows must be an iterable of mappings")
    out = list(rows)
    for row in out:
        if not isinstance(row, Mapping):
            raise CfbEpaError(code, "every row must be a mapping")
    return out


def play_success(down, yards_to_go, yards_gained) -> Optional[bool]:
    """The standard down/distance success definition."""
    down_n = _strict_number(down)
    dist = _strict_number(yards_to_go)
    gained = _strict_number(yards_gained)
    if down_n is None or dist is None or gained is None or dist <= 0:
        return None
    if down_n == 1:
        return gained >= 0.5 * dist
    if down_n == 2:
        return gained >= 0.7 * dist
    if down_n in (3, 4):
        return gained >= dist
    return None


def load_sdv_pbp_rows(rows: Iterable[Mapping]) -> LoadResult:
    """Map cfbfastR-form play-by-play rows onto PlayRow.

    Expected keys (first present wins): game_id; offense_play /
    offense; defense_play / defense; EPA / epa; yards_gained;
    drive_id / drive_number; success (optional 0/1); down and
    distance / yards_to_go (fallback for success).
    """
    rows = _require_row_list(rows, "PBP_ROWS_INVALID")
    out = LoadResult(rows=[])
    for row in rows:
        game_id = _first(row, "game_id")
        offense = _first(row, "offense_play", "offense")
        defense = _first(row, "defense_play", "defense")
        if game_id is None or offense is None or defense is None:
            out._tally("PLAY_IDENTITY_MISSING")
            continue
        epa = _strict_number(_first(row, "EPA", "epa"))
        if epa is None:
            out._tally("PLAY_EPA_NONFINITE")
            continue
        yards = _strict_number(_first(row, "yards_gained"))
        if yards is None:
            out._tally("PLAY_YARDS_MISSING")
            continue
        success_raw = _first(row, "success")
        if success_raw is not None:
            if success_raw in (0, 1, True, False):
                success = bool(success_raw)
            else:
                out._tally("PLAY_SUCCESS_INVALID")
                continue
        else:
            success = play_success(_first(row, "down"),
                                   _first(row, "distance", "yards_to_go"),
                                   yards)
            if success is None:
                out._tally("PLAY_SUCCESS_UNDEFINED")
                continue
        drive = _first(row, "drive_id", "drive_number")
        if drive is None:
            out._tally("PLAY_DRIVE_MISSING")
            continue
        out.rows.append(PlayRow(
            game_id=str(game_id), offense=str(offense),
            defense=str(defense), epa=float(epa), success=success,
            explosive=bool(yards >= EXPLOSIVE_YARDS_THRESHOLD),
            yards_gained=float(yards), drive_id=str(drive)))
    return out


def load_sdv_schedule_rows(rows: Iterable[Mapping]) -> LoadResult:
    """Map SDV schedule rows onto GameResult (completed games only).

    Expected keys: game_id; season; week; start_date (ISO kickoff);
    home_team; away_team; home_points; away_points; neutral_site
    (optional). Rows without a final score are tallied, not loaded:
    an uncompleted game is not a feature game.
    """
    rows = _require_row_list(rows, "SCHEDULE_ROWS_INVALID")
    out = LoadResult(rows=[])
    for row in rows:
        game_id = _first(row, "game_id")
        home = _first(row, "home_team")
        away = _first(row, "away_team")
        kickoff = _parse_ts(_first(row, "start_date"))
        if game_id is None or home is None or away is None or kickoff is None:
            out._tally("SCHEDULE_IDENTITY_MISSING")
            continue
        home_points = _strict_number(_first(row, "home_points"))
        away_points = _strict_number(_first(row, "away_points"))
        if home_points is None or away_points is None:
            out._tally("SCHEDULE_GAME_NOT_COMPLETED")
            continue
        season = _strict_number(_first(row, "season"))
        week = _strict_number(_first(row, "week"))
        if season is None or week is None:
            out._tally("SCHEDULE_IDENTITY_MISSING")
            continue
        out.rows.append(GameResult(
            game_id=str(game_id), season=int(season), week=int(week),
            kickoff=kickoff, home=str(home), away=str(away),
            home_points=float(home_points), away_points=float(away_points),
            neutral_site=bool(_first(row, "neutral_site") or False)))
    return out


# ------------------------------------------------------------------
# Section 1 construction: features, opponent adjustment, snapshots.
#
# Adjusted stat families (opponent-adjusted by iteration, centered
# on zero): EPA per play, EPA per possession, success rate,
# explosiveness rate, points per game. For each family a team's
# per-game offensive observation also serves as the opponent's
# defensive (allowed) observation for that game, so one iteration
# solves the two-way offense/defense system. Pace (plays and
# possessions per game) is a raw mean, never opponent-adjusted.
# All adjusted values are in the stat's own units ABOVE the league
# mean: a defensive value is what the defense ALLOWS above average
# (positive = worse defense), so projection adds off + def.
# ------------------------------------------------------------------

_ADJUSTED_STATS = ("epa_play", "epa_poss", "success", "explosive", "points")


@dataclass(frozen=True)
class TeamFeatures:
    team: str
    games: int  # completed games behind these features (pre-prior)
    off_epa_play: float
    def_epa_play: float
    off_epa_poss: float
    def_epa_poss: float
    off_success: float
    def_success: float
    off_explosive: float
    def_explosive: float
    off_points: float  # adjusted points scored per game above league
    def_points: float  # adjusted points allowed per game above league
    pace_plays: float  # offensive plays per game (raw)
    pace_possessions: float  # offensive possessions per game (raw)


@dataclass(frozen=True)
class LeagueAverages:
    points_per_play: float
    points_per_possession: float
    points_per_team_game: float
    pace_plays: float
    pace_possessions: float


def _game_offensive_values(results: list, plays: list) -> dict:
    """Per (game, team) offensive values for every adjusted family
    plus pace counts. Returns {(game_id, team): {...}} and validates
    that every play belongs to a known game between its two teams.
    """
    games = {g.game_id: g for g in results}
    plays_by_game: dict = {}
    for play in plays:
        game = games.get(play.game_id)
        if game is None:
            raise CfbEpaError("PLAY_FOR_UNKNOWN_GAME", play.game_id)
        if {play.offense, play.defense} != {game.home, game.away}:
            raise CfbEpaError(
                "PLAY_TEAM_MISMATCH",
                f"game {play.game_id}: {play.offense} vs {play.defense} "
                f"is not {game.away} @ {game.home}")
        plays_by_game.setdefault(play.game_id, []).append(play)
    values: dict = {}
    for game in results:
        game_plays = plays_by_game.get(game.game_id, [])
        for team, opp, scored in (
                (game.home, game.away, game.home_points),
                (game.away, game.home, game.away_points)):
            own = [p for p in game_plays if p.offense == team]
            if not own:
                raise CfbEpaError(
                    "GAME_WITHOUT_OFFENSIVE_PLAYS",
                    f"game {game.game_id}: {team} has no offensive plays")
            drives = {p.drive_id for p in own}
            total_epa = sum(p.epa for p in own)
            values[(game.game_id, team)] = {
                "opponent": opp,
                "epa_play": total_epa / len(own),
                "epa_poss": total_epa / len(drives),
                "success": sum(1 for p in own if p.success) / len(own),
                "explosive": sum(1 for p in own if p.explosive) / len(own),
                "points": float(scored),
                "plays": float(len(own)),
                "possessions": float(len(drives)),
            }
    return values


def _adjust_family(observations: dict, stat: str) -> tuple:
    """Iterate the two-way offense/defense adjustment for one stat.

    observations: {(game_id, team): {"opponent":..., stat:...}}.
    Returns (off_adj, def_adj), each {team: value}, weighted-mean
    zero. Simultaneous (Jacobi) updates with ADJUSTMENT_DAMPING;
    failure to converge inside ADJUSTMENT_MAX_ITERATIONS is a
    refusal, never a silent approximate answer.
    """
    off_games: dict = {}
    def_games: dict = {}
    for (_gid, team), obs in observations.items():
        off_games.setdefault(team, []).append((obs["opponent"], obs[stat]))
        def_games.setdefault(obs["opponent"], []).append((team, obs[stat]))
    teams = sorted(set(off_games) | set(def_games))
    off_adj = {t: 0.0 for t in teams}
    def_adj = {t: 0.0 for t in teams}

    def _recenter(adj: dict, counts: dict) -> dict:
        total = sum(counts.values())
        if total == 0:
            return adj
        mean = sum(adj[t] * counts.get(t, 0) for t in adj) / total
        return {t: adj[t] - mean for t in adj}

    off_counts = {t: len(off_games.get(t, [])) for t in teams}
    def_counts = {t: len(def_games.get(t, [])) for t in teams}
    for _ in range(ADJUSTMENT_MAX_ITERATIONS):
        new_off = {}
        for t in teams:
            games = off_games.get(t, [])
            if games:
                target = sum(v - def_adj[opp] for opp, v in games) / len(games)
                new_off[t] = off_adj[t] + ADJUSTMENT_DAMPING * (target - off_adj[t])
            else:
                new_off[t] = off_adj[t]
        new_def = {}
        for t in teams:
            games = def_games.get(t, [])
            if games:
                target = sum(v - off_adj[opp] for opp, v in games) / len(games)
                new_def[t] = def_adj[t] + ADJUSTMENT_DAMPING * (target - def_adj[t])
            else:
                new_def[t] = def_adj[t]
        new_off = _recenter(new_off, off_counts)
        new_def = _recenter(new_def, def_counts)
        delta = max(
            [abs(new_off[t] - off_adj[t]) for t in teams]
            + [abs(new_def[t] - def_adj[t]) for t in teams] or [0.0])
        off_adj, def_adj = new_off, new_def
        if delta < ADJUSTMENT_TOLERANCE:
            return off_adj, def_adj
    raise CfbEpaError(
        "OPPONENT_ADJUSTMENT_NOT_CONVERGED",
        f"stat {stat}: no convergence in {ADJUSTMENT_MAX_ITERATIONS} "
        f"iterations at tolerance {ADJUSTMENT_TOLERANCE}")


def _blend_with_prior(current: float, games: int, prior: Optional[float],
                      league_mean: float) -> float:
    """One mechanism for shrinkage AND the preseason prior (prereg
    section 1): the prior season's final value, retained at
    PRIOR_SEASON_RETENTION toward the league mean, enters as
    PRIOR_PSEUDO_GAMES pseudo-games. With no current games the
    retained prior (or the league mean) is the value."""
    if prior is None:
        prior_value = league_mean
    else:
        prior_value = league_mean + PRIOR_SEASON_RETENTION * (prior - league_mean)
    if games == 0:
        return prior_value
    return (games * current + PRIOR_PSEUDO_GAMES * prior_value) / (
        games + PRIOR_PSEUDO_GAMES)


def compute_features(results: list, plays: list,
                     prior_features: Optional[Mapping] = None) -> tuple:
    """Team features + league averages from completed games only.

    prior_features: {team: TeamFeatures} of the prior season's final
    state (the preseason prior); None early in the first season.
    """
    observations = _game_offensive_values(results, plays)
    adjusted: dict = {}
    for stat in _ADJUSTED_STATS:
        adjusted[stat] = _adjust_family(observations, stat)
    total_points = sum(g.home_points + g.away_points for g in results)
    total_plays = sum(obs["plays"] for obs in observations.values())
    total_poss = sum(obs["possessions"] for obs in observations.values())
    league = LeagueAverages(
        points_per_play=total_points / total_plays if total_plays else 0.0,
        points_per_possession=total_points / total_poss if total_poss else 0.0,
        points_per_team_game=total_points / (2 * len(results)) if results else 0.0,
        pace_plays=total_plays / (2 * len(results)) if results else 0.0,
        pace_possessions=total_poss / (2 * len(results)) if results else 0.0)
    teams = sorted({g.home for g in results} | {g.away for g in results})
    features: dict = {}
    for team in teams:
        own = [obs for (_gid, t), obs in observations.items() if t == team]
        games = len(own)
        prior = (prior_features or {}).get(team)
        raw_plays = sum(o["plays"] for o in own) / games if games else 0.0
        raw_poss = sum(o["possessions"] for o in own) / games if games else 0.0

        def adj(stat: str, side: str) -> float:
            off_adj, def_adj = adjusted[stat]
            raw = (off_adj if side == "off" else def_adj).get(team, 0.0)
            prior_val = None
            if prior is not None:
                prior_val = getattr(prior, f"{side}_{stat}")
            return _blend_with_prior(raw, games, prior_val, 0.0)

        features[team] = TeamFeatures(
            team=team, games=games,
            off_epa_play=adj("epa_play", "off"),
            def_epa_play=adj("epa_play", "def"),
            off_epa_poss=adj("epa_poss", "off"),
            def_epa_poss=adj("epa_poss", "def"),
            off_success=adj("success", "off"),
            def_success=adj("success", "def"),
            off_explosive=adj("explosive", "off"),
            def_explosive=adj("explosive", "def"),
            off_points=adj("points", "off"),
            def_points=adj("points", "def"),
            pace_plays=_blend_with_prior(
                raw_plays, games,
                prior.pace_plays if prior else None, league.pace_plays),
            pace_possessions=_blend_with_prior(
                raw_poss, games,
                prior.pace_possessions if prior else None,
                league.pace_possessions))
    return features, league


def _league_average_features(league: LeagueAverages) -> TeamFeatures:
    """A team with no completed games and no prior is league average."""
    return TeamFeatures(
        team="", games=0,
        off_epa_play=0.0, def_epa_play=0.0, off_epa_poss=0.0,
        def_epa_poss=0.0, off_success=0.0, def_success=0.0,
        off_explosive=0.0, def_explosive=0.0, off_points=0.0,
        def_points=0.0, pace_plays=league.pace_plays,
        pace_possessions=league.pace_possessions)


def _prior_only_features(team: str, prior: Optional[TeamFeatures],
                         league: LeagueAverages) -> TeamFeatures:
    """A team with a prior-season final state but no eligible
    current games: every value is the retained prior (the games=0
    case of the section 1 prior mechanism)."""
    if prior is None:
        base = _league_average_features(league)
        return replace(base, team=team)

    def adj(value: float) -> float:
        return _blend_with_prior(0.0, 0, value, 0.0)

    return TeamFeatures(
        team=team, games=0,
        off_epa_play=adj(prior.off_epa_play),
        def_epa_play=adj(prior.def_epa_play),
        off_epa_poss=adj(prior.off_epa_poss),
        def_epa_poss=adj(prior.def_epa_poss),
        off_success=adj(prior.off_success),
        def_success=adj(prior.def_success),
        off_explosive=adj(prior.off_explosive),
        def_explosive=adj(prior.def_explosive),
        off_points=adj(prior.off_points),
        def_points=adj(prior.def_points),
        pace_plays=_blend_with_prior(0.0, 0, prior.pace_plays,
                                     league.pace_plays),
        pace_possessions=_blend_with_prior(0.0, 0, prior.pace_possessions,
                                           league.pace_possessions))


def project_scores(home: TeamFeatures, away: TeamFeatures,
                   league: LeagueAverages, neutral_site: bool) -> tuple:
    """Expected (home_score, away_score) from team features.

    EPA channel: per-play and per-possession expected points, each
    the league rate plus the offense's adjusted value plus the
    defense's adjusted allowed value (all in points units; success
    and explosiveness differentials enter the per-play channel at
    the stated conversion constants). Points channel: league
    points per team-game plus adjusted points off/def. The blend
    carries the points-only rating at POINTS_BLEND_WEIGHT.
    """
    def team_points(off: TeamFeatures, deff: TeamFeatures) -> float:
        exp_possessions = (off.pace_possessions + deff.pace_possessions) / 2.0
        plays_per_poss = (off.pace_plays / off.pace_possessions
                          if off.pace_possessions > 0 else 0.0)
        exp_plays = exp_possessions * plays_per_poss
        ppp = (league.points_per_play + off.off_epa_play + deff.def_epa_play
               + SUCCESS_TO_EPA * (off.off_success + deff.def_success)
               + EXPLOSIVE_TO_EPA * (off.off_explosive + deff.def_explosive))
        play_channel = exp_plays * ppp
        poss_channel = exp_possessions * (
            league.points_per_possession + off.off_epa_poss
            + deff.def_epa_poss)
        epa_channel = (EPA_CHANNEL_PLAY_WEIGHT * play_channel
                       + (1.0 - EPA_CHANNEL_PLAY_WEIGHT) * poss_channel)
        points_channel = (league.points_per_team_game + off.off_points
                          + deff.def_points)
        return max(0.0, (1.0 - POINTS_BLEND_WEIGHT) * epa_channel
                   + POINTS_BLEND_WEIGHT * points_channel)

    home_score = team_points(home, away)
    away_score = team_points(away, home)
    if not neutral_site:
        home_score += HOME_FIELD_ADVANTAGE_POINTS / 2.0
        away_score -= HOME_FIELD_ADVANTAGE_POINTS / 2.0
        home_score = max(0.0, home_score)
        away_score = max(0.0, away_score)
    return home_score, away_score


# ------------------------------------------------------------------
# Snapshots (prereg section 1: committed before the week's first
# kickoff; hashed content; per-fixture 24h embargo at predict time).
# ------------------------------------------------------------------


@dataclass(frozen=True)
class Snapshot:
    snapshot_id: str
    season: int
    week_label: str
    committed_at: datetime
    mode: str  # "RESEARCH" (pre-freeze / design) or "FORWARD"
    content_hash: str
    results: tuple
    plays: tuple
    prior_features: Optional[Mapping] = None

    def eligible_results(self, kickoff: datetime) -> list:
        """Feature games for one predicted game: completed at least
        EMBARGO_HOURS before its kickoff (the repo's kickoff+24h
        availability proxy). A snapshot game after that line is
        excluded by construction, provably."""
        lag = timedelta(hours=EMBARGO_HOURS)
        return [g for g in self.results if g.kickoff + lag <= kickoff]

    def eligible_plays(self, kickoff: datetime) -> list:
        ids = {g.game_id for g in self.eligible_results(kickoff)}
        return [p for p in self.plays if p.game_id in ids]


def _snapshot_content_hash(season: int, week_label: str, results: list,
                           plays: list) -> str:
    payload = {
        "season": season,
        "week_label": week_label,
        "results": sorted(
            [g.game_id, g.kickoff.isoformat(), g.home, g.away,
             g.home_points, g.away_points, g.neutral_site]
            for g in results),
        "plays": sorted(
            [p.game_id, p.offense, p.defense, p.epa, p.success,
             p.explosive, p.yards_gained, p.drive_id] for p in plays),
    }
    return _sha256_text(_canonical_json(payload))


def build_snapshot(*, season: int, week_label: str, committed_at,
                   results: list, plays: list, mode: str,
                   prior_features: Optional[Mapping] = None) -> Snapshot:
    """Assemble a weekly snapshot. Fail-closed: every result must
    already be available at commit time under the 24h proxy
    (RESULT_NOT_AVAILABLE_AT_SNAPSHOT), and every play must belong
    to a result game between its two teams."""
    committed = _require_ts(committed_at, "SNAPSHOT_COMMIT_TIMESTAMP_INVALID")
    lag = timedelta(hours=EMBARGO_HOURS)
    for game in results:
        if game.kickoff + lag > committed:
            raise CfbEpaError(
                "RESULT_NOT_AVAILABLE_AT_SNAPSHOT",
                f"game {game.game_id} kicked off {game.kickoff.isoformat()} "
                f"is not available at snapshot commit {committed.isoformat()} "
                f"under the {EMBARGO_HOURS}h proxy")
    if len({g.game_id for g in results}) != len(results):
        raise CfbEpaError("SNAPSHOT_DUPLICATE_GAME_ID")
    _game_offensive_values(list(results), list(plays))  # integrity pass
    content_hash = _snapshot_content_hash(season, week_label, results, plays)
    return Snapshot(
        snapshot_id=f"{season}-{week_label}-{content_hash[:12]}",
        season=season, week_label=week_label, committed_at=committed,
        mode=mode, content_hash=content_hash, results=tuple(results),
        plays=tuple(plays), prior_features=prior_features)


# ------------------------------------------------------------------
# Section 2.1 baseline: PM, reproduced exactly as in
# scripts/evaluate_cfb_sdv_closes.py (project_season's PM branch).
# Within one season: walk-forward in kickoff order; a game enters
# history only when its kickoff is at least 24h before the current
# game's kickoff; each team's unit is its last-5 opponent-adjusted
# off/def with 3-game shrinkage toward 28, requiring >=3 prior
# games; HFA 2.5. Equivalence with the script itself is asserted by
# tests/test_cfb_game_epa_joint_v1.py against the script's own
# project_season on synthetic seasons.
# ------------------------------------------------------------------


def pm_project_season(games: list) -> list:
    """Yield (game_id, pm_margin, pm_total) in kickoff order.

    `games` are mappings with keys game_id, kickoff, home, away and
    (for completed games) home_points / away_points. Entries whose
    points are None are projection-only targets: projected when
    reached, never admitted to history. pm values are None where PM
    cannot project (fewer than PM_MIN_PRIOR_GAMES prior games for
    either team).
    """
    ordered = sorted(games, key=lambda g: (g["kickoff"], str(g["game_id"])))
    hist: dict = {}

    def avg(team, upto=None):
        h = hist.get(team, []) if upto is None else hist.get(team, [])[:upto]
        h = h[-PM_WINDOW:]
        if not h:
            return None
        return sum(x[0] for x in h) / len(h), sum(x[1] for x in h) / len(h)

    def pm_unit(team):
        recent = hist.get(team, [])[-PM_WINDOW:]
        if len(recent) < PM_MIN_PRIOR_GAMES:
            return None
        offs, defs = [], []
        for pf, pa, opp, opp_n in recent:
            o = avg(opp, opp_n)
            if o:
                offs.append(pf - (o[1] - PM_BASE))
                defs.append(pa - (o[0] - PM_BASE))
            else:
                offs.append(pf)
                defs.append(pa)
        n = len(recent)
        return ((sum(offs) + PM_BASE * PM_SHRINK) / (n + PM_SHRINK),
                (sum(defs) + PM_BASE * PM_SHRINK) / (n + PM_SHRINK))

    pending: list = []
    last_instant = None
    out = []

    def release_eligible(cutoff):
        lag = timedelta(hours=EMBARGO_HOURS)
        while pending and pending[0]["kickoff"] + lag <= cutoff:
            prior = pending.pop(0)
            nh = len(hist.get(prior["away"], []))
            na = len(hist.get(prior["home"], []))
            hist.setdefault(prior["home"], []).append(
                (prior["home_points"], prior["away_points"],
                 prior["away"], nh))
            hist.setdefault(prior["away"], []).append(
                (prior["away_points"], prior["home_points"],
                 prior["home"], na))

    for g in ordered:
        instant = g["kickoff"]
        if last_instant is not None and instant < last_instant:
            raise CfbEpaError("CFB_GAMES_NOT_CHRONOLOGICAL")
        last_instant = instant
        release_eligible(instant)
        pm_m = pm_t = None
        hu, au = pm_unit(g["home"]), pm_unit(g["away"])
        if hu and au:
            hp = hu[0] + au[1] - PM_BASE + PM_HFA / 2
            ap = au[0] + hu[1] - PM_BASE - PM_HFA / 2
            pm_m, pm_t = hp - ap, hp + ap
        out.append((g["game_id"], pm_m, pm_t))
        if g.get("home_points") is not None:
            pending.append(g)
    return out


def pm_projection_for_fixture(results: list, fixture: GameFixture):
    """PM's projection for one fixture from completed games (the
    same walk-forward, with the fixture as a projection-only tail)."""
    stream = [dict(game_id=g.game_id, kickoff=g.kickoff, home=g.home,
                   away=g.away, home_points=g.home_points,
                   away_points=g.away_points) for g in results]
    stream.append(dict(game_id=fixture.game_id, kickoff=fixture.kickoff,
                       home=fixture.home, away=fixture.away,
                       home_points=None, away_points=None))
    for game_id, pm_m, pm_t in pm_project_season(stream):
        if game_id == fixture.game_id:
            return pm_m, pm_t
    raise CfbEpaError("PM_PROJECTION_MISSING", fixture.game_id)


# ------------------------------------------------------------------
# Prediction ledger (prereg sections 1 and 7: predictions written
# and hashed before kickoff; a prediction not committed pre-kickoff
# does not exist for this test). The ledger is the in-code auditable
# mechanism; the freeze-era originals live on the records branch
# named in section 1, created by the freeze act -- never by this
# build.
# ------------------------------------------------------------------


@dataclass(frozen=True)
class PredictionRecord:
    game_id: str
    kickoff: datetime
    home: str
    away: str
    model_margin: float
    model_total: float
    pm_margin: Optional[float]
    pm_total: Optional[float]
    snapshot_id: str
    snapshot_content_hash: str
    committed_at: datetime
    mode: str  # "RESEARCH" or "COUNTED"
    record_hash: str

    def payload(self) -> dict:
        return {
            "game_id": self.game_id,
            "kickoff": self.kickoff.isoformat(),
            "home": self.home, "away": self.away,
            "model_margin": self.model_margin,
            "model_total": self.model_total,
            "pm_margin": self.pm_margin, "pm_total": self.pm_total,
            "snapshot_id": self.snapshot_id,
            "snapshot_content_hash": self.snapshot_content_hash,
            "committed_at": self.committed_at.isoformat(),
            "mode": self.mode,
        }

    def compute_hash(self) -> str:
        return _sha256_text(_canonical_json(self.payload()))


class PredictionLedger:
    def __init__(self) -> None:
        self._records: dict = {}

    def commit(self, *, game_id: str, kickoff, home: str, away: str,
               model_margin: float, model_total: float,
               pm_margin, pm_total, snapshot_id: str,
               snapshot_content_hash: str, committed_at,
               mode: str) -> PredictionRecord:
        kickoff = _require_ts(kickoff, "PREDICTION_KICKOFF_INVALID")
        committed = _require_ts(committed_at, "PREDICTION_COMMIT_TIMESTAMP_INVALID")
        if committed >= kickoff:
            raise CfbEpaError(
                "PREDICTION_NOT_COMMITTED_PREKICKOFF",
                f"game {game_id}: committed {committed.isoformat()} is not "
                f"before kickoff {kickoff.isoformat()}; a prediction not "
                f"committed pre-kickoff does not exist for this test")
        if game_id in self._records:
            raise CfbEpaError("DUPLICATE_PREDICTION_COMMIT", game_id)
        if _strict_number(model_margin) is None or _strict_number(
                model_total) is None:
            raise CfbEpaError("NONFINITE_PREDICTION_INPUT", game_id)
        draft = PredictionRecord(
            game_id=game_id, kickoff=kickoff, home=home, away=away,
            model_margin=float(model_margin), model_total=float(model_total),
            pm_margin=pm_margin, pm_total=pm_total,
            snapshot_id=snapshot_id,
            snapshot_content_hash=snapshot_content_hash,
            committed_at=committed, mode=mode, record_hash="")
        record = replace(draft, record_hash=draft.compute_hash())
        self._records[game_id] = record
        return record

    def verify(self, game_id: str) -> PredictionRecord:
        record = self._records.get(game_id)
        if record is None:
            raise CfbEpaError("PREDICTION_NOT_COMMITTED", game_id)
        if record.compute_hash() != record.record_hash:
            raise CfbEpaError("PREDICTION_HASH_MISMATCH", game_id)
        if record.committed_at >= record.kickoff:
            raise CfbEpaError("PREDICTION_NOT_COMMITTED_PREKICKOFF", game_id)
        return record

    def get(self, game_id: str) -> Optional[PredictionRecord]:
        return self._records.get(game_id)

    def __len__(self) -> int:
        return len(self._records)

    def to_jsonl(self) -> str:
        lines = []
        for game_id in sorted(self._records):
            record = self._records[game_id]
            payload = record.payload()
            payload["record_hash"] = record.record_hash
            lines.append(_canonical_json(payload))
        return "\n".join(lines)

    @classmethod
    def from_jsonl(cls, text: str) -> "PredictionLedger":
        ledger = cls()
        for line in text.splitlines():
            if not line.strip():
                continue
            payload = json.loads(line)
            record = PredictionRecord(
                game_id=payload["game_id"],
                kickoff=_require_ts(payload["kickoff"], "LEDGER_KICKOFF_INVALID"),
                home=payload["home"], away=payload["away"],
                model_margin=payload["model_margin"],
                model_total=payload["model_total"],
                pm_margin=payload["pm_margin"], pm_total=payload["pm_total"],
                snapshot_id=payload["snapshot_id"],
                snapshot_content_hash=payload["snapshot_content_hash"],
                committed_at=_require_ts(payload["committed_at"],
                                         "LEDGER_COMMIT_TIMESTAMP_INVALID"),
                mode=payload["mode"],
                record_hash=payload["record_hash"])
            if record.compute_hash() != record.record_hash:
                raise CfbEpaError("PREDICTION_HASH_MISMATCH", record.game_id)
            ledger._records[record.game_id] = record
        return ledger


# ------------------------------------------------------------------
# Freeze record + verdict ledger. A FreezeRecord is supplied by
# the freeze act (checklist items 5-7); this module defines its
# shape and validation, completed at checklist item 5 to carry the
# full section-7 pin set: the preregistration, the implementation
# (which contains the snapshot machinery), the section-2.1 baseline
# evaluator script, and the CFB branch of
# artifacts/free_models.py. FREEZE_STATE in this module stays
# DRAFT_NOT_IN_FORCE regardless: the act is external.
# ------------------------------------------------------------------


@dataclass(frozen=True)
class FreezeRecord:
    freeze_commit_sha: str
    frozen_at: datetime
    k_at_freeze: int
    prereg_sha256: str
    implementation_sha256: str
    evaluator_script_sha256: str
    free_models_sha256: str

    def __post_init__(self) -> None:
        _require_ts(self.frozen_at, "FREEZE_TIMESTAMP_INVALID")
        if len(self.freeze_commit_sha) != 40 or any(
                c not in "0123456789abcdef" for c in self.freeze_commit_sha):
            raise CfbEpaError("FREEZE_RECORD_INVALID", "freeze_commit_sha")
        for digest in (self.prereg_sha256, self.implementation_sha256,
                       self.evaluator_script_sha256,
                       self.free_models_sha256):
            if len(digest) != 64 or any(
                    c not in "0123456789abcdef" for c in digest):
                raise CfbEpaError("FREEZE_RECORD_INVALID", "sha256 pin")
        if isinstance(self.k_at_freeze, bool) or not isinstance(
                self.k_at_freeze, int) or self.k_at_freeze < 1:
            raise CfbEpaError("FREEZE_RECORD_INVALID", "k_at_freeze")


class VerdictLedger:
    """One verdict look per market, ever. INSUFFICIENT outcomes
    (sample minimum unmet, market-data sufficiency) record nothing:
    they issue no verdict and do not consume the look (prereg
    sections 2.2(d) and 4)."""

    def __init__(self, verdicts: Optional[Mapping] = None) -> None:
        self._verdicts: dict = dict(verdicts or {})

    def recorded(self, market: str) -> Optional[dict]:
        return self._verdicts.get(market)

    def record(self, market: str, verdict: Mapping) -> None:
        if market in self._verdicts:
            raise CfbEpaError("VERDICT_ALREADY_RECORDED", market)
        self._verdicts[market] = dict(verdict)

    def to_json(self) -> str:
        return _canonical_json(self._verdicts)

    @classmethod
    def from_json(cls, text: str) -> "VerdictLedger":
        return cls(json.loads(text))


# ------------------------------------------------------------------
# Section 2.2 close validity (in the prereg's own terms; check
# order mirrors the CBB Amendment 2 machinery precedent: missing
# row, single-sided, not-prekickoff, stale -- malformed records
# refuse outright rather than earning a disposition).
# ------------------------------------------------------------------


def _price_ok(value) -> bool:
    number = _strict_number(value)
    if number is None or number == 0:
        return False
    return number >= 100 or number <= -100


def classify_close(close: Optional[CloseRecord], kickoff: datetime) -> tuple:
    """Returns ("VALID", None) or ("MISSING", <reason code>)."""
    if close is None:
        return "MISSING", "NO_CLOSE_ROW"
    if close.line is not None and _strict_number(close.line) is None:
        raise CfbEpaError("CLOSE_RECORD_INVALID",
                          f"game {close.game_id}: non-finite line")
    if close.price_first is None or close.price_second is None:
        return "MISSING", "CLOSE_SINGLE_SIDED"
    if not _price_ok(close.price_first) or not _price_ok(close.price_second):
        raise CfbEpaError(
            "CLOSE_PRICE_INVALID",
            f"game {close.game_id}: prices {close.price_first!r} / "
            f"{close.price_second!r} are not valid American odds")
    if close.captured_at is None:
        raise CfbEpaError("CLOSE_RECORD_INVALID",
                          f"game {close.game_id}: no capture timestamp")
    captured = _require_ts(close.captured_at, "CLOSE_RECORD_INVALID")
    if captured >= kickoff:
        return "MISSING", "CLOSE_NOT_PREKICKOFF"
    if kickoff - captured > CLOSE_MAX_AGE:
        return "MISSING", "CLOSE_STALE"
    if close.line is None:
        raise CfbEpaError("CLOSE_RECORD_INVALID",
                          f"game {close.game_id}: valid close without a line")
    return "VALID", None


def _devig_event_probability(close: CloseRecord, market: str,
                               event_is_first: bool) -> float:
    """POWER_V1 de-vigged probability of one side of a valid close.

    The market arm is this de-vigged closing implied probability --
    never the SDV evaluator's ln 2 placeholder (prereg section 4).
    """
    # power_devig pairs two quotes of ONE identity (game, market,
    # entity) with complementary sides; the entity here is the game
    # itself, the sides carry the two prices.
    first = {"game_id": close.game_id, "market": market,
             "entity_id": close.game_id,
             "side": "HOME" if market == "SPREAD" else "OVER",
             "line": close.line, "american_odds": close.price_first}
    second = {"game_id": close.game_id, "market": market,
              "entity_id": close.game_id,
              "side": "AWAY" if market == "SPREAD" else "UNDER",
              "line": close.line, "american_odds": close.price_second}
    try:
        result = power_devig(first, second)
    except DevigError as exc:
        raise CfbEpaError("CLOSE_PRICE_INVALID",
                          f"game {close.game_id}: {exc}") from exc
    if result.method != "POWER_V1":
        raise CfbEpaError("DEVIG_METHOD_MISMATCH", result.method)
    return (result.candidate_fair_probability if event_is_first
            else result.opposite_fair_probability)


def _bootstrap_ci(differences: list, *, k: int) -> dict:
    """Game-cluster bootstrap of the mean paired difference.

    One difference per game (a cluster is one game, prereg section
    4). Operation order mirrors the CBB Amendment 2 machinery
    exactly -- fresh random.Random(seed) per interval, draws with
    replacement, nearest-rank ceil(q*B) percentile bounds at level
    1 - alpha/k -- so the program's verdict computations share one
    reproducible convention under the pinned seed.
    """
    rng = random.Random(BOOTSTRAP_SEED)
    n = len(differences)
    stats = []
    for _ in range(BOOTSTRAP_RESAMPLES):
        tot = 0.0
        for _ in range(n):
            tot += differences[rng.randrange(n)]
        stats.append(tot / n)
    stats.sort()
    level = 1.0 - ALPHA / k
    q_lo = (1.0 - level) / 2.0
    lo = stats[max(0, math.ceil(q_lo * BOOTSTRAP_RESAMPLES) - 1)]
    hi = stats[min(BOOTSTRAP_RESAMPLES - 1,
                   math.ceil((1.0 - q_lo) * BOOTSTRAP_RESAMPLES) - 1)]
    return {"point": sum(differences) / n, "ci_lower": lo, "ci_upper": hi,
            "level": level, "reps": BOOTSTRAP_RESAMPLES,
            "seed": BOOTSTRAP_SEED, "k": k}


def _calibration(rows: list) -> dict:
    """Deciles + logistic calibration slope for the construction's
    stated event probabilities on graded rows. Reported only;
    nothing in calibration gates the verdict (prereg section 4)."""
    bins = []
    for idx in range(10):
        lo, hi = idx / 10.0, (idx + 1) / 10.0
        sel = [(p, y) for p, y in rows if lo <= p < hi or (idx == 9 and p == 1.0)]
        bins.append({
            "band": f"{lo:.1f}-{hi:.1f}", "n": len(sel),
            "mean_stated": (sum(p for p, _ in sel) / len(sel)) if sel else None,
            "realized_rate": (sum(y for _, y in sel) / len(sel)) if sel else None})
    slope = None
    if rows and 0 < sum(y for _, y in rows) < len(rows):
        xs = [math.log(min(max(p, 1e-9), 1 - 1e-9) / (1 - min(max(p, 1e-9), 1 - 1e-9)))
              for p, _ in rows]
        ys = [float(y) for _, y in rows]
        a, b = 0.0, 0.0
        for _ in range(100):
            grad_a = grad_b = h_aa = h_ab = h_bb = 0.0
            for x, y in zip(xs, ys):
                mu = 1.0 / (1.0 + math.exp(-(a + b * x)))
                w = mu * (1.0 - mu) + 1e-12
                r = y - mu
                grad_a += r
                grad_b += r * x
                h_aa += w
                h_ab += w * x
                h_bb += w * x * x
            det = h_aa * h_bb - h_ab * h_ab
            if abs(det) < 1e-14:
                break
            da = (grad_a * h_bb - grad_b * h_ab) / det
            db = (h_aa * grad_b - h_ab * grad_a) / det
            a += da
            b += db
            if abs(da) + abs(db) < 1e-10:
                slope = b
                break
    return {"deciles": bins, "logistic_slope": slope}


def _market_row(prediction: PredictionRecord, final: GameResult,
                market: str, close: Optional[CloseRecord],
                sdv_close: Optional[Mapping]) -> tuple:
    """One game-market's disposition + arm values.

    Returns (kind, payload): kind is "graded", "excluded", or
    "mae_only" (missing close: out of the primary comparison in all
    three arms, retained in the MAE readout flagged MARKET_REF_SDV,
    prereg section 2.2(c)).
    """
    if market == "SPREAD":
        model_est = prediction.model_margin
        pm_est = prediction.pm_margin
        sd_model, sd_pm = CONSTRUCTION_SD_MARGIN, PM_SD_MARGIN
        actual = final.home_points - final.away_points
    else:
        model_est = prediction.model_total
        pm_est = prediction.pm_total
        sd_model, sd_pm = CONSTRUCTION_SD_TOTAL, PM_SD_TOTAL
        actual = final.home_points + final.away_points
    state, reason = classify_close(close, final.kickoff)
    if state == "MISSING":
        ref_line = None
        ref_kind = None
        if sdv_close is not None:
            ref_line = sdv_close.get(
                "spread_line" if market == "SPREAD" else "total_line")
            if _strict_number(ref_line) is not None:
                ref_kind = "SDV"
        return "mae_only", {
            "game_id": final.game_id, "reason": reason,
            "market_ref_sdv": True,
            "model_abs_err": abs(model_est - actual),
            "pm_abs_err": (abs(pm_est - actual) if pm_est is not None else None),
            "close_abs_err": (abs(float(ref_line) - actual)
                              if ref_line is not None else None),
            "close_ref": ref_kind}
    line = float(close.line)
    resid = actual - line
    mae = {
        "game_id": final.game_id, "reason": None, "market_ref_sdv": False,
        "model_abs_err": abs(model_est - actual),
        "pm_abs_err": (abs(pm_est - actual) if pm_est is not None else None),
        "close_abs_err": abs(line - actual), "close_ref": "DK"}
    if resid == 0:
        return "excluded", {"game_id": final.game_id, "reason": "PUSH",
                            "mae": mae}
    if pm_est is None:
        return "excluded", {"game_id": final.game_id,
                            "reason": "PM_BASELINE_UNAVAILABLE", "mae": mae}
    event = resid > 0  # home covered (SPREAD) / over (TOTAL)
    p_model = _phi((model_est - line) / sd_model)
    p_pm = _phi((pm_est - line) / sd_pm)
    p_market = _devig_event_probability(close, market, True)
    realized = {
        "model": p_model if event else 1.0 - p_model,
        "pm": p_pm if event else 1.0 - p_pm,
        "market": p_market if event else 1.0 - p_market}
    return "graded", {
        "game_id": final.game_id,
        "ll_model": _log_loss(realized["model"]),
        "ll_pm": _log_loss(realized["pm"]),
        "ll_market": _log_loss(realized["market"]),
        "event_probability_model": p_model,
        "event_realized": 1 if event else 0,
        "mae": mae}


def _mae_block(rows: list) -> dict:
    def mean(key):
        vals = [r[key] for r in rows if r.get(key) is not None]
        return (sum(vals) / len(vals)) if vals else None
    return {"n": len(rows), "model_mae": mean("model_abs_err"),
            "pm_mae": mean("pm_abs_err"), "close_mae": mean("close_abs_err"),
            "market_ref_sdv_rows": sum(1 for r in rows if r["market_ref_sdv"])}


def _clv_summary(sample: list, dk_closes: Mapping, entries: Optional[Mapping],
                 universe: int) -> dict:
    """Reported grade only (prereg section 4): never gates."""
    if entries is None:
        return {"status": "ENTRY_CAPTURES_NOT_PROVIDED",
                "mean_clv_probability": None, "n_selected": 0}
    out = {}
    for market in MARKETS:
        values = []
        missing_close = 0
        missing_entry = 0
        no_selection = 0
        for prediction, final in sample:
            close = dk_closes.get((final.game_id, market))
            state, _reason = classify_close(close, final.kickoff)
            if state != "VALID":
                missing_close += 1
                continue
            entry = entries.get((final.game_id, market))
            estate, _ereason = classify_close(entry, final.kickoff)
            if estate != "VALID":
                missing_entry += 1
                continue
            if market == "SPREAD":
                gap = prediction.model_margin - float(close.line)
                first_is_event = gap > 0
            else:
                gap = prediction.model_total - float(close.line)
                first_is_event = gap > 0
            if gap == 0:
                no_selection += 1
                continue
            p_close = _devig_event_probability(close, market, first_is_event)
            p_entry = _devig_event_probability(entry, market, first_is_event)
            values.append(p_close - p_entry)
        share = (missing_close / universe) if universe else 0.0
        out[market] = {
            "status": ("INSUFFICIENT_CLOSE_DATA"
                       if share > MAX_MISSING_CLOSE_SHARE else "REPORTED"),
            "mean_clv_probability": (sum(values) / len(values)) if values else None,
            "n_selected": len(values), "missing_close": missing_close,
            "missing_entry": missing_entry, "no_selection": no_selection}
    return out


def evaluate_validation_sample(*, freeze_record: Optional[FreezeRecord],
                               predictions: list, ledger: PredictionLedger,
                               finals: Mapping, dk_closes: Mapping,
                               sdv_closes: Optional[Mapping] = None,
                               entries: Optional[Mapping] = None,
                               k_at_verdict=None,
                               verdict_ledger: VerdictLedger) -> dict:
    """The section 2/4 evaluation over one assembled validation
    sample. Refuses CFB_GAME_EPA_JOINT_NOT_FROZEN without a freeze
    record -- no verdict, and no counted row, exists before the
    freeze act."""
    if freeze_record is None:
        raise CfbEpaError(
            REFUSAL_NOT_FROZEN,
            "no freeze record: the freeze act has not happened, so no "
            "validation sample can be evaluated and no game counted")
    if isinstance(k_at_verdict, bool) or not isinstance(k_at_verdict, int) \
            or k_at_verdict < 1:
        raise CfbEpaError(
            "K_UNESTABLISHED",
            "k at the verdict must be a positive integer; if k cannot "
            "be established, no verdict issues (prereg section 4)")
    k = max(freeze_record.k_at_freeze, k_at_verdict)

    sample = []
    game_exclusions: dict = {}
    for prediction in predictions:
        verified = ledger.verify(prediction.game_id)
        if verified.record_hash != prediction.record_hash:
            raise CfbEpaError("PREDICTION_RECORD_MISMATCH", prediction.game_id)
        if prediction.mode != "COUNTED":
            game_exclusions.setdefault("PREDICTION_NOT_COUNTED_MODE", []).append(
                prediction.game_id)
            continue
        if is_excluded_fixture(prediction.home, prediction.away):
            raise CfbEpaError(
                "EXCLUDED_FIXTURE_IN_SAMPLE",
                f"game {prediction.game_id}: an excluded fixture in the "
                f"validation sample is a defect, not a row (prereg section 3)")
        final = finals.get(prediction.game_id)
        if final is None:
            game_exclusions.setdefault("FINAL_UNAVAILABLE", []).append(
                prediction.game_id)
            continue
        if final.home != prediction.home or final.away != prediction.away:
            raise CfbEpaError("SAMPLE_GAME_IDENTITY_MISMATCH", prediction.game_id)
        sample.append((prediction, final))
    universe = len(sample)

    markets_report: dict = {}
    for market in MARKETS:
        graded = []
        mae_rows = []
        exclusions: dict = {}
        missing_close = 0
        for prediction, final in sample:
            close = dk_closes.get((final.game_id, market))
            sdv_close = (sdv_closes or {}).get(final.game_id)
            kind, payload = _market_row(prediction, final, market, close,
                                        sdv_close)
            if kind == "graded":
                graded.append(payload)
                mae_rows.append(payload["mae"])
            elif kind == "mae_only":
                missing_close += 1
                exclusions.setdefault(payload["reason"], []).append(
                    payload["game_id"])
                mae_rows.append(payload)
            else:
                exclusions.setdefault(payload["reason"], []).append(
                    payload["game_id"])
                if payload.get("mae") is not None:
                    mae_rows.append(payload["mae"])
        n_graded = len(graded)
        missing_share = (missing_close / universe) if universe else 0.0
        block: dict = {
            "graded_games": n_graded,
            "missing_close_games": missing_close,
            "missing_close_share": missing_share,
            "exclusions_by_reason": {
                reason: {"n": len(ids), "game_ids": ids}
                for reason, ids in sorted(exclusions.items())},
            "mae": _mae_block(mae_rows),
            "status": None, "verdict": None}
        if n_graded:
            ll_model = sum(r["ll_model"] for r in graded) / n_graded
            ll_pm = sum(r["ll_pm"] for r in graded) / n_graded
            ll_market = sum(r["ll_market"] for r in graded) / n_graded
            block["log_loss"] = {"model": ll_model, "pm": ll_pm,
                                 "market": ll_market}
            block["calibration"] = _calibration(
                [(r["event_probability_model"], r["event_realized"])
                 for r in graded])
        else:
            block["log_loss"] = {"model": None, "pm": None, "market": None}
            block["calibration"] = _calibration([])
        prior = verdict_ledger.recorded(market)
        reaches_verdict = (n_graded >= MIN_GRADED_GAMES
                           and missing_share <= MAX_MISSING_CLOSE_SHARE)
        if prior is not None:
            if reaches_verdict:
                raise CfbEpaError(
                    "VERDICT_ALREADY_RECORDED",
                    f"{market}: the single verdict look already happened; "
                    f"no re-looks (prereg section 4)")
            block["status"] = "VERDICT_ALREADY_RECORDED"
            block["verdict"] = prior
        elif n_graded < MIN_GRADED_GAMES:
            block["status"] = "SAMPLE_MINIMUM_UNMET"
        elif missing_share > MAX_MISSING_CLOSE_SHARE:
            block["status"] = "INSUFFICIENT_MARKET_DATA"
        else:
            diff_pm = [r["ll_model"] - r["ll_pm"] for r in graded]
            diff_market = [r["ll_model"] - r["ll_market"] for r in graded]
            ci_pm = _bootstrap_ci(diff_pm, k=k)
            ci_market = _bootstrap_ci(diff_market, k=k)
            passed = (ll_model < ll_pm and ll_model < ll_market
                      and ci_pm["ci_upper"] < 0 and ci_market["ci_upper"] < 0)
            verdict = {
                "market": market,
                "verdict": "PASS" if passed else "FAIL",
                "graded_games": n_graded, "k": k,
                "log_loss": block["log_loss"],
                "ci_model_minus_pm": ci_pm,
                "ci_model_minus_market": ci_market,
                "construction": CONSTRUCTION_ID,
                "terminal_if_fail": not passed}
            verdict_ledger.record(market, verdict)
            block["status"] = verdict["verdict"]
            block["verdict"] = verdict
            block["ci"] = {"model_minus_pm": ci_pm,
                           "model_minus_market": ci_market}
        markets_report[market] = block

    return {
        "construction": CONSTRUCTION_ID,
        "mode": "FORWARD_VALIDATION",
        "freeze_commit_sha": freeze_record.freeze_commit_sha,
        "k_at_freeze": freeze_record.k_at_freeze,
        "k_at_verdict": k_at_verdict, "k_governing": k,
        "universe_games": universe,
        "game_exclusions_by_reason": {
            reason: {"n": len(ids), "game_ids": ids}
            for reason, ids in sorted(game_exclusions.items())},
        "markets": markets_report,
        "clv_reported_only": _clv_summary(sample, dk_closes, entries, universe),
        "paper_units": 0}


# ------------------------------------------------------------------
# The runner. Pre-freeze it is a research instrument: predictions
# and backtests run on design data, labeled, and can never be
# consumed by the evaluator (which requires COUNTED records, a
# freeze record, and hash-verified ledger entries). Counted entry
# points refuse CFB_GAME_EPA_JOINT_NOT_FROZEN while no freeze
# record is supplied.
# ------------------------------------------------------------------


class CfbGameEpaJointV1:
    def __init__(self, freeze_record: Optional[FreezeRecord] = None) -> None:
        self._freeze_record = freeze_record

    @property
    def frozen(self) -> bool:
        return self._freeze_record is not None

    @property
    def freeze_state(self) -> str:
        return "FROZEN" if self.frozen else FREEZE_STATE

    def build_snapshot(self, *, season: int, week_label: str, committed_at,
                       results: list, plays: list,
                       prior_features: Optional[Mapping] = None) -> Snapshot:
        return build_snapshot(
            season=season, week_label=week_label, committed_at=committed_at,
            results=results, plays=plays,
            mode="FORWARD" if self.frozen else "RESEARCH",
            prior_features=prior_features)

    def predict_fixture(self, snapshot: Snapshot, fixture: GameFixture) -> dict:
        """Construction + PM estimates for one fixture from one
        snapshot, under the per-fixture 24h embargo. Labeled with
        the snapshot's mode; a bare estimate counts nothing."""
        if is_excluded_fixture(fixture.home, fixture.away):
            raise CfbEpaError(
                "EXCLUDED_FIXTURE",
                f"game {fixture.game_id}: excluded fixtures are never "
                f"predicted (prereg section 3)")
        if fixture.kickoff <= snapshot.committed_at:
            raise CfbEpaError(
                "FIXTURE_NOT_AFTER_SNAPSHOT_COMMIT",
                f"game {fixture.game_id} kicks off at "
                f"{fixture.kickoff.isoformat()}, not after the snapshot "
                f"commit {snapshot.committed_at.isoformat()}")
        results = snapshot.eligible_results(fixture.kickoff)
        plays = snapshot.eligible_plays(fixture.kickoff)
        features, league = compute_features(results, plays,
                                            snapshot.prior_features)
        priors = snapshot.prior_features or {}
        home_f = features.get(fixture.home)
        away_f = features.get(fixture.away)
        if home_f is None:
            home_f = _prior_only_features(fixture.home,
                                          priors.get(fixture.home), league)
        if away_f is None:
            away_f = _prior_only_features(fixture.away,
                                          priors.get(fixture.away), league)
        home_score, away_score = project_scores(home_f, away_f, league,
                                                fixture.neutral_site)
        pm_margin, pm_total = pm_projection_for_fixture(results, fixture)
        return {
            "game_id": fixture.game_id,
            "home": fixture.home, "away": fixture.away,
            "model_home_score": home_score, "model_away_score": away_score,
            "model_margin": home_score - away_score,
            "model_total": home_score + away_score,
            "pm_margin": pm_margin, "pm_total": pm_total,
            "snapshot_id": snapshot.snapshot_id,
            "mode": ("FORWARD" if snapshot.mode == "FORWARD"
                     else RESEARCH_MODE_LABEL)}

    def commit_predictions(self, snapshot: Snapshot, fixtures: list,
                           ledger: PredictionLedger, *, committed_at,
                           counted: bool = False) -> list:
        """Write predictions into the ledger, hashed, pre-kickoff.

        counted=True is a counted entry point: refused while no
        freeze record exists. Research commits (counted=False) are
        labeled RESEARCH and can never enter a validation sample.
        """
        if counted and not self.frozen:
            raise CfbEpaError(
                REFUSAL_NOT_FROZEN,
                "counted predictions are refused before the freeze act; "
                "this build commits research predictions only")
        committed = _require_ts(committed_at,
                                "PREDICTION_COMMIT_TIMESTAMP_INVALID")
        if committed < snapshot.committed_at:
            raise CfbEpaError(
                "PREDICTION_COMMITTED_BEFORE_SNAPSHOT",
                "a prediction cannot be committed before its snapshot")
        out = []
        for fixture in fixtures:
            pred = self.predict_fixture(snapshot, fixture)
            out.append(ledger.commit(
                game_id=fixture.game_id, kickoff=fixture.kickoff,
                home=fixture.home, away=fixture.away,
                model_margin=pred["model_margin"],
                model_total=pred["model_total"],
                pm_margin=pred["pm_margin"], pm_total=pred["pm_total"],
                snapshot_id=snapshot.snapshot_id,
                snapshot_content_hash=snapshot.content_hash,
                committed_at=committed,
                mode="COUNTED" if counted else "RESEARCH"))
        return out

    def run_verdict(self, **kwargs) -> dict:
        """The single verdict evaluation. A counted entry point:
        refused CFB_GAME_EPA_JOINT_NOT_FROZEN before the freeze."""
        if not self.frozen:
            raise CfbEpaError(
                REFUSAL_NOT_FROZEN,
                "no verdict can be produced before the freeze act; "
                "FREEZE_STATE is DRAFT_NOT_IN_FORCE")
        return evaluate_validation_sample(
            freeze_record=self._freeze_record, **kwargs)

    def research_backtest(self, seasons: list) -> dict:
        """Walk-forward readout over DESIGN DATA seasons.

        seasons: [{season, results, plays, sdv_closes}] with
        sdv_closes {game_id: {"spread_line": margin line,
        "total_line": total}}. Weekly snapshots, chained
        prior-season priors. The market arm does not exist here --
        SDV closes carry no prices -- and every figure is a
        research readout against the SDV closing line, labeled
        RESEARCH_DESIGN_DATA_NOT_VALIDATION, claiming nothing.
        """
        season_reports = {}
        overall = {m: {"ll_n": 0, "ll_model": 0.0, "ll_pm": 0.0,
                       "mae_n": 0, "mae_model": 0.0, "mae_close": 0.0,
                       "mae_pm_n": 0, "mae_pm": 0.0}
                   for m in MARKETS}
        prior_features = None
        for season_data in seasons:
            results = sorted(season_data["results"],
                             key=lambda g: (g.kickoff, g.game_id))
            plays = list(season_data["plays"])
            sdv_closes = season_data.get("sdv_closes") or {}
            by_week: dict = {}
            for game in results:
                by_week.setdefault(game.week, []).append(game)
            agg = {m: {"ll_n": 0, "ll_model": 0.0, "ll_pm": 0.0,
                       "mae_n": 0, "mae_model": 0.0, "mae_close": 0.0,
                       "mae_pm_n": 0, "mae_pm": 0.0,
                       "no_sdv_close": 0, "pm_unavailable": 0, "pushes": 0}
                   for m in MARKETS}
            for week in sorted(by_week):
                week_games = by_week[week]
                committed = week_games[0].kickoff - timedelta(minutes=1)
                eligible = [g for g in results
                            if g.kickoff + timedelta(hours=EMBARGO_HOURS)
                            <= committed]
                eligible_ids = {g.game_id for g in eligible}
                snapshot = build_snapshot(
                    season=season_data["season"], week_label=f"W{week}",
                    committed_at=committed, results=eligible,
                    plays=[p for p in plays if p.game_id in eligible_ids],
                    mode="RESEARCH", prior_features=prior_features)
                for game in week_games:
                    fixture = GameFixture(
                        game_id=game.game_id, season=game.season,
                        week=game.week, kickoff=game.kickoff,
                        home=game.home, away=game.away,
                        neutral_site=game.neutral_site)
                    pred = self.predict_fixture(snapshot, fixture)
                    close = sdv_closes.get(game.game_id)
                    for market in MARKETS:
                        a = agg[market]
                        line = None
                        if close is not None:
                            line = _strict_number(close.get(
                                "spread_line" if market == "SPREAD"
                                else "total_line"))
                        if line is None:
                            a["no_sdv_close"] += 1
                            continue
                        if market == "SPREAD":
                            model_est, pm_est = pred["model_margin"], pred["pm_margin"]
                            sd_m, sd_p = CONSTRUCTION_SD_MARGIN, PM_SD_MARGIN
                            actual = game.home_points - game.away_points
                        else:
                            model_est, pm_est = pred["model_total"], pred["pm_total"]
                            sd_m, sd_p = CONSTRUCTION_SD_TOTAL, PM_SD_TOTAL
                            actual = game.home_points + game.away_points
                        a["mae_n"] += 1
                        a["mae_model"] += abs(model_est - actual)
                        a["mae_close"] += abs(line - actual)
                        if pm_est is not None:
                            a["mae_pm_n"] += 1
                            a["mae_pm"] += abs(pm_est - actual)
                        resid = actual - line
                        if resid == 0:
                            a["pushes"] += 1
                            continue
                        if pm_est is None:
                            a["pm_unavailable"] += 1
                            continue
                        event = resid > 0
                        p_m = _phi((model_est - line) / sd_m)
                        p_p = _phi((pm_est - line) / sd_p)
                        a["ll_model"] += _log_loss(p_m if event else 1.0 - p_m)
                        a["ll_pm"] += _log_loss(p_p if event else 1.0 - p_p)
                        a["ll_n"] += 1
            season_report = {}
            for market in MARKETS:
                a = agg[market]
                season_report[market] = {
                    "graded_rows": a["ll_n"],
                    "mean_log_loss_model": (
                        a["ll_model"] / a["ll_n"]) if a["ll_n"] else None,
                    "mean_log_loss_pm": (
                        a["ll_pm"] / a["ll_n"]) if a["ll_n"] else None,
                    "mae_model": (
                        a["mae_model"] / a["mae_n"]) if a["mae_n"] else None,
                    "mae_pm": (
                        a["mae_pm"] / a["mae_pm_n"]) if a["mae_pm_n"] else None,
                    "mae_close": (
                        a["mae_close"] / a["mae_n"]) if a["mae_n"] else None,
                    "no_sdv_close": a["no_sdv_close"],
                    "pm_unavailable": a["pm_unavailable"],
                    "pushes": a["pushes"]}
                o = overall[market]
                for key in ("ll_n", "ll_model", "ll_pm", "mae_n", "mae_model",
                            "mae_close", "mae_pm_n", "mae_pm"):
                    o[key] += a[key]
            season_reports[str(season_data["season"])] = season_report
            prior_features, _league = compute_features(results, plays,
                                                       prior_features)
        overall_report = {}
        for market in MARKETS:
            o = overall[market]
            overall_report[market] = {
                "graded_rows": o["ll_n"],
                "mean_log_loss_model": (
                    o["ll_model"] / o["ll_n"]) if o["ll_n"] else None,
                "mean_log_loss_pm": (
                    o["ll_pm"] / o["ll_n"]) if o["ll_n"] else None,
                "mae_model": (
                    o["mae_model"] / o["mae_n"]) if o["mae_n"] else None,
                "mae_pm": (
                    o["mae_pm"] / o["mae_pm_n"]) if o["mae_pm_n"] else None,
                "mae_close": (
                    o["mae_close"] / o["mae_n"]) if o["mae_n"] else None}
        return {
            "construction": CONSTRUCTION_ID,
            "mode": RESEARCH_MODE_LABEL,
            "claims": "NONE",
            "production_eligible": False,
            "market_arm": "NOT_AVAILABLE_SDV_CLOSES_CARRY_NO_PRICES",
            "seasons": season_reports,
            "overall": overall_report}


__all__ = [
    "ADJUSTMENT_DAMPING", "ADJUSTMENT_MAX_ITERATIONS",
    "ADJUSTMENT_TOLERANCE", "ALPHA", "BOOTSTRAP_RESAMPLES",
    "BOOTSTRAP_SEED", "CLOSE_FAILURE_CODES", "CLOSE_MAX_AGE",
    "CONSTRUCTION_ID", "CONSTRUCTION_SD_MARGIN", "CONSTRUCTION_SD_TOTAL",
    "CfbEpaError", "CfbGameEpaJointV1", "CloseRecord", "EMBARGO_HOURS",
    "EPA_CHANNEL_PLAY_WEIGHT", "EXPLOSIVE_TO_EPA",
    "EXPLOSIVE_YARDS_THRESHOLD", "FREEZE_STATE", "FreezeRecord",
    "GameFixture", "GameResult", "HOME_FIELD_ADVANTAGE_POINTS",
    "ILLINOIS_COLLEGE_NAMES", "LeagueAverages", "LoadResult", "MARKETS",
    "MAX_MISSING_CLOSE_SHARE", "MIN_GRADED_GAMES",
    "OWNER_BLOCKED_NAMES", "PM_BASE", "PM_HFA", "PM_MIN_PRIOR_GAMES",
    "PM_SD_MARGIN", "PM_SD_TOTAL", "PM_SHRINK", "PM_WINDOW",
    "POINTS_BLEND_WEIGHT", "PRIOR_PSEUDO_GAMES", "PRIOR_SEASON_RETENTION",
    "PROB_EPS", "PlayRow", "PredictionLedger", "PredictionRecord",
    "RECORDS_BRANCH", "REFUSAL_NOT_FROZEN", "RESEARCH_MODE_LABEL",
    "SUCCESS_TO_EPA", "Snapshot", "TeamFeatures", "VerdictLedger",
    "build_snapshot", "classify_close", "compute_features",
    "evaluate_validation_sample", "is_excluded_fixture", "is_excluded_team",
    "load_sdv_pbp_rows", "load_sdv_schedule_rows", "play_success",
    "pm_project_season", "pm_projection_for_fixture", "project_scores",
]
