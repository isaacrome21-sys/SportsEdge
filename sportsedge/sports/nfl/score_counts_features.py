"""PIT-safe feature and scoring-count row builder for NFL_SCORE_COUNTS_G1.

The current game's play-by-play is used only as the realized label after its
feature row has been built. All predictive state comes from strictly earlier
completed games plus a PIT starting-QB depth-chart identity.
"""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from math import isfinite
from typing import Any, Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo

from sportsedge.sports.nfl.m2_history_features import select_starting_qb
from sportsedge.sports.nfl.score_counts_g1 import FEATURE_NAMES, ScoreCountsError, empirical_bayes_rate

_EASTERN = ZoneInfo("America/New_York")
TEAM_ALIASES = {"LA": "LAR", "WSH": "WAS", "OAK": "LV", "SD": "LAC", "STL": "LAR"}
LOOKBACK_GAMES = 8
DECAY = 0.85
QB_PSEUDO_DROPBACKS = 100.0
QB_MIN_PRIOR_DROPBACKS = 20

FORBIDDEN_KEYS = (
    "odds", "price", "sportsbook", "market", "spread_line", "total_line",
    "closing", "opening", "implied", "vig", "handle", "tickets",
)


class ScoreCountFeatureError(ValueError):
    pass


@dataclass
class TeamGame:
    off_epa_sum: float = 0.0
    off_plays: int = 0
    def_epa_sum: float = 0.0
    def_plays: int = 0
    off_success: int = 0
    def_success: int = 0
    pass_epa_sum: float = 0.0
    pass_dropbacks: int = 0
    def_pass_epa_sum: float = 0.0
    def_pass_dropbacks: int = 0
    rush_epa_sum: float = 0.0
    rush_attempts: int = 0
    def_rush_epa_sum: float = 0.0
    def_rush_attempts: int = 0
    turnovers: int = 0
    takeaways: int = 0
    sacks_allowed: int = 0
    sacks_for: int = 0
    offense_touchdowns: int = 0
    offensive_tds_allowed: int = 0
    made_field_goals: int = 0
    field_goals_allowed: int = 0
    def_st_touchdowns: int = 0
    safeties: int = 0
    pat_made: int = 0
    two_point_made: int = 0


@dataclass
class QBGame:
    epa_sum: float = 0.0
    dropbacks: int = 0
    cpoe_sum: float = 0.0
    cpoe_n: int = 0


def _assert_market_blind(value: Any, path: str = "root") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            low = str(key).strip().lower()
            if any(token in low for token in FORBIDDEN_KEYS):
                raise ScoreCountFeatureError(f"MARKET_FIELD_FORBIDDEN:{path}.{key}")
            _assert_market_blind(child, f"{path}.{key}")
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for idx, child in enumerate(value):
            _assert_market_blind(child, f"{path}[{idx}]")


def _team(value: Any) -> str:
    raw = str(value or "").strip().upper()
    return TEAM_ALIASES.get(raw, raw)


def _float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if isfinite(out) else None


def _int(value: Any) -> int | None:
    x = _float(value)
    if x is None:
        return None
    if abs(x - round(x)) > 1e-9:
        return None
    return int(round(x))


def _flag(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value in (None, ""):
        return False
    if isinstance(value, (int, float)):
        return float(value) != 0.0
    return str(value).strip().lower() in {"1", "true", "t", "yes", "y"}


def _start(row: Mapping[str, Any]) -> datetime:
    raw = row.get("game_start_ts") or row.get("start_time")
    if raw not in (None, ""):
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            raise ScoreCountFeatureError("GAME_START_TIMEZONE_REQUIRED")
        return dt.astimezone(timezone.utc)
    day = str(row.get("gameday") or row.get("game_date") or "").strip()
    clock = str(row.get("gametime") or "").strip()
    if not day or not clock:
        raise ScoreCountFeatureError("GAME_START_REQUIRED")
    local = datetime.combine(date.fromisoformat(day[:10]), time.fromisoformat(clock), tzinfo=_EASTERN)
    return local.astimezone(timezone.utc)


def _game_id(row: Mapping[str, Any]) -> str:
    gid = str(row.get("game_id") or row.get("nflverse_game_id") or "").strip()
    if not gid:
        raise ScoreCountFeatureError("GAME_ID_REQUIRED")
    return gid


def _scrimmage_flags(row: Mapping[str, Any]) -> tuple[bool, bool, bool]:
    kneel = _flag(row.get("qb_kneel"))
    spike = _flag(row.get("qb_spike"))
    dropback = _flag(row.get("qb_dropback")) or _flag(row.get("pass"))
    rush = _flag(row.get("rush_attempt")) or _flag(row.get("rush"))
    if kneel or spike:
        rush = False
    scrimmage = dropback or rush
    return scrimmage, dropback, rush


def aggregate_game_pbp(
    pbp_rows: Iterable[Mapping[str, Any]],
) -> tuple[dict[tuple[str, str], TeamGame], dict[tuple[str, str], QBGame]]:
    """Aggregate factual game PBP into team labels/history and QB game stats."""
    rows = [dict(row) for row in pbp_rows]
    _assert_market_blind(rows)
    teams: dict[tuple[str, str], TeamGame] = {}
    qbs: dict[tuple[str, str], QBGame] = {}
    seen_plays: set[tuple[str, str]] = set()

    def stat(gid: str, team: str) -> TeamGame:
        if not team:
            raise ScoreCountFeatureError(f"TEAM_ID_REQUIRED:{gid}")
        return teams.setdefault((gid, team), TeamGame())

    for row in rows:
        gid = _game_id(row)
        play_id = str(row.get("play_id") or "").strip()
        if play_id:
            key = (gid, play_id)
            if key in seen_plays:
                raise ScoreCountFeatureError(f"DUPLICATE_PLAY:{gid}:{play_id}")
            seen_plays.add(key)

        offense = _team(row.get("posteam") or row.get("possession_team"))
        defense = _team(row.get("defteam"))
        epa = _float(row.get("epa"))
        scrimmage, dropback, rush = _scrimmage_flags(row)
        if scrimmage:
            if not offense or not defense or epa is None:
                raise ScoreCountFeatureError(f"SCRIMMAGE_IDENTITY_OR_EPA_MISSING:{gid}:{play_id}")
            off = stat(gid, offense)
            deff = stat(gid, defense)
            off.off_epa_sum += epa
            off.off_plays += 1
            deff.def_epa_sum += epa
            deff.def_plays += 1
            off.off_success += int(epa > 0)
            deff.def_success += int(epa > 0)
            if dropback:
                off.pass_epa_sum += epa
                off.pass_dropbacks += 1
                deff.def_pass_epa_sum += epa
                deff.def_pass_dropbacks += 1
                sack = _flag(row.get("sack"))
                off.sacks_allowed += int(sack)
                deff.sacks_for += int(sack)
                passer = str(row.get("passer_player_id") or row.get("passer_id") or "").strip()
                if passer:
                    qb = qbs.setdefault((gid, passer), QBGame())
                    qb_epa = _float(row.get("qb_epa"))
                    qb.epa_sum += epa if qb_epa is None else qb_epa
                    qb.dropbacks += 1
                    cpoe = _float(row.get("cpoe"))
                    if cpoe is not None:
                        qb.cpoe_sum += cpoe
                        qb.cpoe_n += 1
            if rush:
                off.rush_epa_sum += epa
                off.rush_attempts += 1
                deff.def_rush_epa_sum += epa
                deff.def_rush_attempts += 1
            turnover = _flag(row.get("interception")) or _flag(row.get("fumble_lost"))
            off.turnovers += int(turnover)
            deff.takeaways += int(turnover)

        if _flag(row.get("touchdown")):
            td_team = _team(row.get("td_team"))
            if not td_team:
                raise ScoreCountFeatureError(f"TD_TEAM_REQUIRED:{gid}:{play_id}")
            return_td = _flag(row.get("return_touchdown"))
            if td_team == offense and not return_td:
                stat(gid, td_team).offense_touchdowns += 1
                if defense:
                    stat(gid, defense).offensive_tds_allowed += 1
            else:
                stat(gid, td_team).def_st_touchdowns += 1

        fg_result = str(row.get("field_goal_result") or "").strip().lower()
        if fg_result in {"made", "good"}:
            if not offense:
                raise ScoreCountFeatureError(f"FG_TEAM_REQUIRED:{gid}:{play_id}")
            stat(gid, offense).made_field_goals += 1
            if defense:
                stat(gid, defense).field_goals_allowed += 1

        xp = str(row.get("extra_point_result") or "").strip().lower()
        if xp in {"good", "made"}:
            if not offense:
                raise ScoreCountFeatureError(f"PAT_TEAM_REQUIRED:{gid}:{play_id}")
            stat(gid, offense).pat_made += 1

        two = str(row.get("two_point_conv_result") or "").strip().lower()
        if two in {"success", "successful", "good", "made"}:
            if not offense:
                raise ScoreCountFeatureError(f"TWO_POINT_TEAM_REQUIRED:{gid}:{play_id}")
            stat(gid, offense).two_point_made += 1

        if _flag(row.get("safety")):
            if not defense:
                raise ScoreCountFeatureError(f"SAFETY_TEAM_REQUIRED:{gid}:{play_id}")
            stat(gid, defense).safeties += 1

    return teams, qbs


def _rate(num: float, den: float) -> float:
    return float(num / den) if den > 0 else 0.0


def _weighted(history: Sequence[TeamGame], getter) -> float:
    rows = list(history)[-LOOKBACK_GAMES:]
    if not rows:
        raise ScoreCountFeatureError("TEAM_HISTORY_REQUIRED")
    weights = [DECAY ** (len(rows) - 1 - idx) for idx in range(len(rows))]
    den = sum(weights)
    return float(sum(w * getter(row) for w, row in zip(weights, rows)) / den)


def _team_features(history: Sequence[TeamGame]) -> dict[str, float]:
    if len(history) < 4:
        raise ScoreCountFeatureError("MINIMUM_PRIOR_TEAM_GAMES")
    return {
        "off_epa_per_play": _weighted(history, lambda r: _rate(r.off_epa_sum, r.off_plays)),
        "def_epa_allowed_per_play": _weighted(history, lambda r: _rate(r.def_epa_sum, r.def_plays)),
        "off_success_rate": _weighted(history, lambda r: _rate(r.off_success, r.off_plays)),
        "def_success_rate_allowed": _weighted(history, lambda r: _rate(r.def_success, r.def_plays)),
        "off_pass_epa_per_dropback": _weighted(history, lambda r: _rate(r.pass_epa_sum, r.pass_dropbacks)),
        "def_pass_epa_allowed_per_dropback": _weighted(history, lambda r: _rate(r.def_pass_epa_sum, r.def_pass_dropbacks)),
        "off_rush_epa_per_rush": _weighted(history, lambda r: _rate(r.rush_epa_sum, r.rush_attempts)),
        "def_rush_epa_allowed_per_rush": _weighted(history, lambda r: _rate(r.def_rush_epa_sum, r.def_rush_attempts)),
        "off_plays_per_game": _weighted(history, lambda r: float(r.off_plays)),
        "off_td_per_game": _weighted(history, lambda r: float(r.offense_touchdowns)),
        "td_allowed_per_game": _weighted(history, lambda r: float(r.offensive_tds_allowed)),
        "made_fg_per_game": _weighted(history, lambda r: float(r.made_field_goals)),
        "fg_allowed_per_game": _weighted(history, lambda r: float(r.field_goals_allowed)),
        "off_turnover_rate": _weighted(history, lambda r: _rate(r.turnovers, r.off_plays)),
        "def_takeaway_rate": _weighted(history, lambda r: _rate(r.takeaways, r.def_plays)),
        "off_sack_rate_allowed": _weighted(history, lambda r: _rate(r.sacks_allowed, r.pass_dropbacks)),
        "def_sack_rate": _weighted(history, lambda r: _rate(r.sacks_for, r.def_pass_dropbacks)),
    }


def _qb_prior(
    *,
    player_id: str,
    prior_game_ids: set[str],
    game_qbs: Mapping[tuple[str, str], QBGame],
) -> tuple[float, float, int]:
    player = [stats for (gid, pid), stats in game_qbs.items() if pid == player_id and gid in prior_game_ids]
    dropbacks = sum(s.dropbacks for s in player)
    if dropbacks < QB_MIN_PRIOR_DROPBACKS:
        raise ScoreCountFeatureError(f"QB_PRIOR_DROPBACKS_INSUFFICIENT:{player_id}:{dropbacks}")

    league = [stats for (gid, _pid), stats in game_qbs.items() if gid in prior_game_ids]
    league_dropbacks = sum(s.dropbacks for s in league)
    if league_dropbacks <= 0:
        raise ScoreCountFeatureError("QB_LEAGUE_PRIOR_EMPTY")
    league_epa = sum(s.epa_sum for s in league) / league_dropbacks
    league_cpoe_n = sum(s.cpoe_n for s in league)
    league_cpoe = sum(s.cpoe_sum for s in league) / league_cpoe_n if league_cpoe_n > 0 else 0.0

    epa_sum = sum(s.epa_sum for s in player)
    cpoe_sum = sum(s.cpoe_sum for s in player)
    cpoe_n = sum(s.cpoe_n for s in player)
    epa = (epa_sum + QB_PSEUDO_DROPBACKS * league_epa) / (dropbacks + QB_PSEUDO_DROPBACKS)
    cpoe = (cpoe_sum + QB_PSEUDO_DROPBACKS * league_cpoe) / (cpoe_n + QB_PSEUDO_DROPBACKS)
    return float(epa), float(cpoe), int(dropbacks)


def _rare_and_conversion_context(
    *,
    team: str,
    team_prior: Sequence[TeamGame],
    league_prior: Sequence[TeamGame],
) -> dict[str, float]:
    """Build strictly-prior rare-score and conversion rates for one team.

    Rare score rates use empirical-Bayes shrinkage toward the prior league
    per-team-game rate with 25 pseudo-games. Conversion composition uses a
    team-specific empirical rate only after 50 prior touchdown conversion
    opportunities; otherwise it uses the strictly-prior league composition.
    """
    if not team_prior or not league_prior:
        raise ScoreCountFeatureError(f"RARE_CONTEXT_HISTORY_REQUIRED:{team}")

    league_games = float(len(league_prior))
    league_dst = sum(float(r.def_st_touchdowns) for r in league_prior) / league_games
    league_safety = sum(float(r.safeties) for r in league_prior) / league_games
    if not 0.0 <= league_dst <= 1.0:
        raise ScoreCountFeatureError("LEAGUE_DEF_ST_TD_RATE_OUT_OF_RANGE")
    if not 0.0 <= league_safety <= 1.0:
        raise ScoreCountFeatureError("LEAGUE_SAFETY_RATE_OUT_OF_RANGE")

    team_games = float(len(team_prior))
    dst = empirical_bayes_rate(
        events=sum(float(r.def_st_touchdowns) for r in team_prior),
        exposure=team_games,
        league_rate=league_dst,
        prior_exposure=25.0,
    )
    safety = empirical_bayes_rate(
        events=sum(float(r.safeties) for r in team_prior),
        exposure=team_games,
        league_rate=league_safety,
        prior_exposure=25.0,
    )

    def conversion_counts(rows: Sequence[TeamGame]) -> tuple[float, float, float]:
        td = sum(float(r.offense_touchdowns + r.def_st_touchdowns) for r in rows)
        pat = sum(float(r.pat_made) for r in rows)
        two = sum(float(r.two_point_made) for r in rows)
        no = max(0.0, td - pat - two)
        return pat, two, no

    league_pat, league_two, league_no = conversion_counts(league_prior)
    league_total = league_pat + league_two + league_no
    if league_total <= 0:
        raise ScoreCountFeatureError("LEAGUE_CONVERSION_HISTORY_REQUIRED")
    league_probs = (
        league_pat / league_total,
        league_two / league_total,
        league_no / league_total,
    )

    team_pat, team_two, team_no = conversion_counts(team_prior)
    team_total = team_pat + team_two + team_no
    if team_total >= 50.0:
        conversion = (
            team_pat / team_total,
            team_two / team_total,
            team_no / team_total,
        )
    else:
        conversion = league_probs

    return {
        "def_st_td_rate": float(dst),
        "safety_rate": float(safety),
        "conversion_pat_p": float(conversion[0]),
        "conversion_two_p": float(conversion[1]),
        "conversion_no_p": float(conversion[2]),
    }


def _flatten(
    *,
    own: Mapping[str, float],
    opponent: Mapping[str, float],
    qb_epa: float,
    qb_cpoe: float,
    home: bool,
) -> dict[str, float]:
    row = {
        "off_epa_per_play": own["off_epa_per_play"],
        "opp_def_epa_allowed_per_play": opponent["def_epa_allowed_per_play"],
        "off_success_rate": own["off_success_rate"],
        "opp_def_success_rate_allowed": opponent["def_success_rate_allowed"],
        "off_pass_epa_per_dropback": own["off_pass_epa_per_dropback"],
        "opp_def_pass_epa_allowed_per_dropback": opponent["def_pass_epa_allowed_per_dropback"],
        "off_rush_epa_per_rush": own["off_rush_epa_per_rush"],
        "opp_def_rush_epa_allowed_per_rush": opponent["def_rush_epa_allowed_per_rush"],
        "off_plays_per_game": own["off_plays_per_game"],
        "off_td_per_game": own["off_td_per_game"],
        "opp_td_allowed_per_game": opponent["td_allowed_per_game"],
        "made_fg_per_game": own["made_fg_per_game"],
        "opp_fg_allowed_per_game": opponent["fg_allowed_per_game"],
        "off_turnover_rate": own["off_turnover_rate"],
        "opp_takeaway_rate": opponent["def_takeaway_rate"],
        "off_sack_rate_allowed": own["off_sack_rate_allowed"],
        "opp_def_sack_rate": opponent["def_sack_rate"],
        "starting_qb_epa_shrunk": float(qb_epa),
        "starting_qb_cpoe_shrunk": float(qb_cpoe),
        "home_indicator": 1.0 if home else 0.0,
    }
    if set(row) != set(FEATURE_NAMES):
        raise ScoreCountFeatureError("FROZEN_FEATURE_IDENTITY_MISMATCH")
    return row


def build_score_count_training_rows(
    *,
    schedule_rows: Sequence[Mapping[str, Any]],
    pbp_rows: Sequence[Mapping[str, Any]],
    depth_rows: Sequence[Mapping[str, Any]],
    seasons: Sequence[int] = tuple(range(2018, 2026)),
) -> list[dict[str, Any]]:
    """Build two team rows per eligible completed game with strict PIT state."""
    schedule = [dict(row) for row in schedule_rows]
    pbp = [dict(row) for row in pbp_rows]
    depth = [dict(row) for row in depth_rows]
    # Schedule rows may physically carry sportsbook columns in the upstream
    # factual dataset. They are never read by this builder. PBP/depth, which
    # actually feed predictive state, must remain market-blind.
    _assert_market_blind(pbp)
    _assert_market_blind(depth)

    allowed_seasons = {int(s) for s in seasons}
    games = []
    starts: dict[str, datetime] = {}
    for raw in schedule:
        season = _int(raw.get("season"))
        if season not in allowed_seasons:
            continue
        gid = _game_id(raw)
        start = _start(raw)
        home = _team(raw.get("home_team") or raw.get("home"))
        away = _team(raw.get("away_team") or raw.get("away"))
        week = _int(raw.get("week"))
        if not home or not away or week is None:
            raise ScoreCountFeatureError(f"SCHEDULE_IDENTITY_INCOMPLETE:{gid}")
        games.append((start, gid, season, week, home, away, raw))
        starts[gid] = start
    games.sort(key=lambda x: (x[0], x[1]))

    team_game, game_qbs = aggregate_game_pbp(pbp)
    pbp_game_ids = {gid for gid, _team_id in team_game}
    history: dict[str, deque[TeamGame]] = defaultdict(lambda: deque(maxlen=LOOKBACK_GAMES))
    all_history: dict[str, list[TeamGame]] = defaultdict(list)
    completed_ids: set[str] = set()
    out: list[dict[str, Any]] = []

    for start, gid, season, week, home, away, raw in games:
        if gid not in pbp_game_ids:
            continue
        h_label = team_game.get((gid, home))
        a_label = team_game.get((gid, away))
        if h_label is None or a_label is None:
            raise ScoreCountFeatureError(f"GAME_TEAM_PBP_MISSING:{gid}")

        if len(history[home]) >= 4 and len(history[away]) >= 4:
            h_own = _team_features(history[home])
            a_own = _team_features(history[away])
            try:
                h_qb = select_starting_qb(
                    depth, team=home, season=season, week=week, game_start_ts=start
                )
                a_qb = select_starting_qb(
                    depth, team=away, season=season, week=week, game_start_ts=start
                )
                h_qb_epa, h_qb_cpoe, h_qb_db = _qb_prior(
                    player_id=h_qb, prior_game_ids=completed_ids, game_qbs=game_qbs
                )
                a_qb_epa, a_qb_cpoe, a_qb_db = _qb_prior(
                    player_id=a_qb, prior_game_ids=completed_ids, game_qbs=game_qbs
                )
            except (ValueError, ScoreCountFeatureError):
                h_qb = a_qb = ""
            if h_qb and a_qb:
                league_prior = [
                    item
                    for team_rows in all_history.values()
                    for item in team_rows
                ]
                h_rare = _rare_and_conversion_context(
                    team=home, team_prior=all_history[home], league_prior=league_prior
                )
                a_rare = _rare_and_conversion_context(
                    team=away, team_prior=all_history[away], league_prior=league_prior
                )
                for team_id, opponent, home_flag, own, opp, label, qb_id, qb_epa, qb_cpoe, qb_db, rare in (
                    (home, away, True, h_own, a_own, h_label, h_qb, h_qb_epa, h_qb_cpoe, h_qb_db, h_rare),
                    (away, home, False, a_own, h_own, a_label, a_qb, a_qb_epa, a_qb_cpoe, a_qb_db, a_rare),
                ):
                    features = _flatten(
                        own=own, opponent=opp, qb_epa=qb_epa, qb_cpoe=qb_cpoe, home=home_flag
                    )
                    item = {
                        "game_id": gid,
                        "season": int(season),
                        "week": int(week),
                        "game_start_ts": start.isoformat(),
                        "team": team_id,
                        "opponent": opponent,
                        "starting_qb_id": qb_id,
                        "starting_qb_prior_dropbacks": qb_db,
                        **features,
                        **rare,
                        "offense_touchdowns": int(label.offense_touchdowns),
                        "made_field_goals": int(label.made_field_goals),
                        "def_st_touchdowns": int(label.def_st_touchdowns),
                        "safeties": int(label.safeties),
                        "pat_made": int(label.pat_made),
                        "two_point_made": int(label.two_point_made),
                    }
                    out.append(item)

        # State update occurs only after feature construction and label emission.
        history[home].append(h_label)
        history[away].append(a_label)
        all_history[home].append(h_label)
        all_history[away].append(a_label)
        completed_ids.add(gid)

    return out


__all__ = [
    "DECAY",
    "LOOKBACK_GAMES",
    "QB_MIN_PRIOR_DROPBACKS",
    "QB_PSEUDO_DROPBACKS",
    "ScoreCountFeatureError",
    "TeamGame",
    "QBGame",
    "aggregate_game_pbp",
    "build_score_count_training_rows",
]
