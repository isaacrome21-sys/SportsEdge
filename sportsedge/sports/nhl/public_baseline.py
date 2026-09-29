from __future__ import annotations

"""Chronological NHL public-boxscore baseline model.

This is an original, market-blind baseline built from official completed-game
boxscores.  It is intentionally separate from ``rate_model.py`` because official
boxscores do not contain xG and non-xG statistics must never be mislabeled as xG.

The builder walks games chronologically and constructs every target game's
features strictly from earlier games.  Historical receipts fetched today are
still retrospective development data, not retroactive PIT betting evidence.
Forward evaluation must use receipts captured before each future target game.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
from typing import Iterable, Sequence

from .official_boxscore_source import NHLOfficialCompletedGame
from .simulation import NHLGameState

BASELINE_FEATURES = (
    "offense_reg_gf_per_game",
    "opponent_reg_ga_per_game",
    "shot_share",
    "special_teams_delta",
    "shooting_pct",
    "opponent_save_pct",
    "rest_delta_days",
    "home_ice",
)


def _utc(value: str) -> datetime:
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return dt.astimezone(timezone.utc)


@dataclass
class _TeamHistory:
    games: int = 0
    regulation_gf: int = 0
    regulation_ga: int = 0
    sog_for: int = 0
    sog_against: int = 0
    pp_goals: int = 0
    pp_opportunities: int = 0
    pk_goals_allowed: int = 0
    pk_opportunities: int = 0
    last_start_utc: datetime | None = None

    def add(
        self, *, gf: int, ga: int, sog_for: int, sog_against: int,
        pp_goals: int | None, pp_opportunities: int | None,
        opponent_pp_goals: int | None, opponent_pp_opportunities: int | None,
        start: datetime,
    ) -> None:
        self.games += 1
        self.regulation_gf += gf
        self.regulation_ga += ga
        self.sog_for += sog_for
        self.sog_against += sog_against
        if pp_goals is not None and pp_opportunities is not None:
            self.pp_goals += pp_goals
            self.pp_opportunities += pp_opportunities
        if opponent_pp_goals is not None and opponent_pp_opportunities is not None:
            self.pk_goals_allowed += opponent_pp_goals
            self.pk_opportunities += opponent_pp_opportunities
        self.last_start_utc = start


@dataclass(frozen=True)
class NHLBaselineTrainingRow:
    game_id: str
    team_id: str
    opponent_id: str
    start_time_utc: str
    is_home: bool
    features: tuple[float, ...]
    regulation_goals: int

    def __post_init__(self) -> None:
        if not self.game_id or not self.team_id or not self.opponent_id or self.team_id == self.opponent_id:
            raise ValueError("complete distinct game/team identity required")
        _utc(self.start_time_utc)
        if len(self.features) != len(BASELINE_FEATURES):
            raise ValueError("baseline feature width mismatch")
        if any(not math.isfinite(v) for v in self.features):
            raise ValueError("baseline features must be finite")
        if self.regulation_goals < 0:
            raise ValueError("regulation_goals must be nonnegative")


@dataclass(frozen=True)
class NHLBaselineMatchup:
    game_id: str
    puck_drop: str
    home_team_id: str
    away_team_id: str
    home_features: tuple[float, ...]
    away_features: tuple[float, ...]
    history_games: int
    latest_history_start: str

    def __post_init__(self) -> None:
        puck = _utc(self.puck_drop)
        latest = _utc(self.latest_history_start)
        if latest >= puck:
            raise ValueError("baseline matchup history must predate puck drop")
        if not self.game_id or not self.home_team_id or not self.away_team_id:
            raise ValueError("matchup identity required")
        if self.home_team_id == self.away_team_id:
            raise ValueError("home and away teams must differ")
        if len(self.home_features) != len(BASELINE_FEATURES) or len(self.away_features) != len(BASELINE_FEATURES):
            raise ValueError("baseline feature width mismatch")
        if self.history_games <= 0:
            raise ValueError("history_games must be positive")


@dataclass(frozen=True)
class NHLPublicBaselineArtifact:
    version: str
    feature_names: tuple[str, ...]
    means: tuple[float, ...]
    scales: tuple[float, ...]
    intercept: float
    coefficients: tuple[float, ...]
    ridge: float
    training_rows: int
    training_sha256: str
    first_start_time_utc: str
    last_start_time_utc: str
    authority: str = "DEVELOPMENT_BASELINE / NOT Model_P / NOT TRUTH_GATE / NOT OFFICIAL"

    def __post_init__(self) -> None:
        n = len(BASELINE_FEATURES)
        if not self.version or self.feature_names != BASELINE_FEATURES:
            raise ValueError("version and frozen baseline feature schema required")
        if not (len(self.means) == len(self.scales) == len(self.coefficients) == n):
            raise ValueError("baseline artifact dimension mismatch")
        if any(not math.isfinite(v) for v in (*self.means, *self.scales, self.intercept, *self.coefficients)):
            raise ValueError("baseline artifact values must be finite")
        if any(s <= 0 for s in self.scales):
            raise ValueError("baseline feature scales must be positive")
        if self.ridge < 0 or self.training_rows <= n + 1:
            raise ValueError("ridge and sufficient training rows required")
        if len(self.training_sha256) != 64:
            raise ValueError("training_sha256 required")
        if _utc(self.first_start_time_utc) > _utc(self.last_start_time_utc):
            raise ValueError("invalid training time range")

    def regulation_goal_rate(self, features: Sequence[float]) -> float:
        if len(features) != len(self.feature_names):
            raise ValueError("baseline feature width mismatch")
        if any(not math.isfinite(float(v)) for v in features):
            raise ValueError("baseline features must be finite")
        z = [(float(v) - mean) / scale for v, mean, scale in zip(features, self.means, self.scales)]
        eta = self.intercept + sum(beta * value for beta, value in zip(self.coefficients, z))
        return math.exp(max(-8.0, min(4.0, eta)))

    def as_json_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "feature_names": list(self.feature_names),
            "means": list(self.means),
            "scales": list(self.scales),
            "intercept": self.intercept,
            "coefficients": list(self.coefficients),
            "ridge": self.ridge,
            "training_rows": self.training_rows,
            "training_sha256": self.training_sha256,
            "first_start_time_utc": self.first_start_time_utc,
            "last_start_time_utc": self.last_start_time_utc,
            "authority": self.authority,
        }


def _metrics(history: _TeamHistory, *, target_start: datetime) -> dict[str, float] | None:
    if history.games <= 0 or history.sog_for <= 0 or history.sog_against <= 0 or history.last_start_utc is None:
        return None
    if history.pp_opportunities <= 0 or history.pk_opportunities <= 0:
        return None
    elapsed_days = (target_start - history.last_start_utc).total_seconds() / 86400.0
    if elapsed_days <= 0:
        return None
    return {
        "gfpg": history.regulation_gf / history.games,
        "gapg": history.regulation_ga / history.games,
        "sog_for_pg": history.sog_for / history.games,
        "sog_against_pg": history.sog_against / history.games,
        "pp_pct": history.pp_goals / history.pp_opportunities,
        "pk_pct": 1.0 - history.pk_goals_allowed / history.pk_opportunities,
        "shooting_pct": history.regulation_gf / history.sog_for,
        "save_pct": 1.0 - history.regulation_ga / history.sog_against,
        "days_since_last": elapsed_days,
    }


def _feature_pair(home: _TeamHistory, away: _TeamHistory, target_start: datetime) -> tuple[tuple[float, ...], tuple[float, ...]] | None:
    hm = _metrics(home, target_start=target_start)
    am = _metrics(away, target_start=target_start)
    if hm is None or am is None:
        return None

    home_shot_share = hm["sog_for_pg"] / max(1e-12, hm["sog_for_pg"] + am["sog_against_pg"])
    away_shot_share = am["sog_for_pg"] / max(1e-12, am["sog_for_pg"] + hm["sog_against_pg"])
    home_features = (
        hm["gfpg"], am["gapg"], home_shot_share,
        hm["pp_pct"] - am["pk_pct"], hm["shooting_pct"], am["save_pct"],
        hm["days_since_last"] - am["days_since_last"], 1.0,
    )
    away_features = (
        am["gfpg"], hm["gapg"], away_shot_share,
        am["pp_pct"] - hm["pk_pct"], am["shooting_pct"], hm["save_pct"],
        am["days_since_last"] - hm["days_since_last"], 0.0,
    )
    return home_features, away_features


def _update_histories(histories: dict[str, _TeamHistory], game: NHLOfficialCompletedGame) -> None:
    start = _utc(game.start_time_utc)
    home = histories.setdefault(game.home_team_id, _TeamHistory())
    away = histories.setdefault(game.away_team_id, _TeamHistory())
    home.add(
        gf=game.home_regulation_goals, ga=game.away_regulation_goals,
        sog_for=game.home_sog, sog_against=game.away_sog,
        pp_goals=game.home_pp_goals, pp_opportunities=game.home_pp_opportunities,
        opponent_pp_goals=game.away_pp_goals, opponent_pp_opportunities=game.away_pp_opportunities,
        start=start,
    )
    away.add(
        gf=game.away_regulation_goals, ga=game.home_regulation_goals,
        sog_for=game.away_sog, sog_against=game.home_sog,
        pp_goals=game.away_pp_goals, pp_opportunities=game.away_pp_opportunities,
        opponent_pp_goals=game.home_pp_goals, opponent_pp_opportunities=game.home_pp_opportunities,
        start=start,
    )


def _ordered_unique_games(games: Iterable[NHLOfficialCompletedGame], allowed_game_types: Sequence[int]) -> list[NHLOfficialCompletedGame]:
    allowed = {int(x) for x in allowed_game_types}
    if not allowed:
        raise ValueError("allowed_game_types cannot be empty")
    ordered = sorted((g for g in games if g.game_type in allowed), key=lambda g: (_utc(g.start_time_utc), g.game_id))
    ids: set[str] = set()
    for game in ordered:
        if game.game_id in ids:
            raise ValueError(f"duplicate completed game id:{game.game_id}")
        ids.add(game.game_id)
    return ordered


def build_baseline_training_rows(
    games: Iterable[NHLOfficialCompletedGame], *, min_team_games: int = 10,
    allowed_game_types: Sequence[int] = (2, 3),
) -> tuple[NHLBaselineTrainingRow, ...]:
    """Create leakage-resistant chronological rows from earlier games only."""
    if min_team_games < 1:
        raise ValueError("min_team_games must be positive")
    histories: dict[str, _TeamHistory] = {}
    rows: list[NHLBaselineTrainingRow] = []
    for game in _ordered_unique_games(games, allowed_game_types):
        start = _utc(game.start_time_utc)
        home = histories.setdefault(game.home_team_id, _TeamHistory())
        away = histories.setdefault(game.away_team_id, _TeamHistory())
        if home.games >= min_team_games and away.games >= min_team_games:
            pair = _feature_pair(home, away, start)
            if pair is not None:
                home_features, away_features = pair
                rows.extend((
                    NHLBaselineTrainingRow(
                        game_id=game.game_id, team_id=game.home_team_id,
                        opponent_id=game.away_team_id, start_time_utc=game.start_time_utc,
                        is_home=True, features=home_features,
                        regulation_goals=game.home_regulation_goals,
                    ),
                    NHLBaselineTrainingRow(
                        game_id=game.game_id, team_id=game.away_team_id,
                        opponent_id=game.home_team_id, start_time_utc=game.start_time_utc,
                        is_home=False, features=away_features,
                        regulation_goals=game.away_regulation_goals,
                    ),
                ))
        _update_histories(histories, game)
    return tuple(rows)


def build_baseline_matchup(
    games: Iterable[NHLOfficialCompletedGame], *, game_id: str,
    home_team_id: str, away_team_id: str, puck_drop: str,
    min_team_games: int = 10, allowed_game_types: Sequence[int] = (2, 3),
) -> NHLBaselineMatchup:
    """Build a future matchup solely from completed games before ``puck_drop``."""
    if min_team_games < 1:
        raise ValueError("min_team_games must be positive")
    puck = _utc(puck_drop)
    histories: dict[str, _TeamHistory] = {}
    used: list[NHLOfficialCompletedGame] = []
    for game in _ordered_unique_games(games, allowed_game_types):
        if _utc(game.start_time_utc) >= puck:
            break
        _update_histories(histories, game)
        used.append(game)
    if not used:
        raise ValueError("no eligible completed history before puck drop")
    home = histories.get(home_team_id)
    away = histories.get(away_team_id)
    if home is None or away is None or home.games < min_team_games or away.games < min_team_games:
        raise ValueError("insufficient chronological team history")
    pair = _feature_pair(home, away, puck)
    if pair is None:
        raise ValueError("insufficient shot/special-teams history for matchup")
    home_features, away_features = pair
    latest = max(_utc(g.start_time_utc) for g in used)
    return NHLBaselineMatchup(
        game_id=game_id, puck_drop=puck.isoformat(),
        home_team_id=home_team_id, away_team_id=away_team_id,
        home_features=home_features, away_features=away_features,
        history_games=len(used), latest_history_start=latest.isoformat(),
    )


def _solve(a: list[list[float]], b: list[float]) -> list[float]:
    n = len(b)
    aug = [a[i][:] + [b[i]] for i in range(n)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(aug[r][col]))
        if abs(aug[pivot][col]) < 1e-12:
            raise ValueError("singular baseline training design")
        aug[col], aug[pivot] = aug[pivot], aug[col]
        scale = aug[col][col]
        aug[col] = [v / scale for v in aug[col]]
        for row in range(n):
            if row == col:
                continue
            factor = aug[row][col]
            aug[row] = [x - factor * y for x, y in zip(aug[row], aug[col])]
    return [aug[i][-1] for i in range(n)]


def _training_hash(rows: Sequence[NHLBaselineTrainingRow]) -> str:
    payload = [
        {
            "game_id": row.game_id, "team_id": row.team_id, "opponent_id": row.opponent_id,
            "start_time_utc": row.start_time_utc, "is_home": row.is_home,
            "features": list(row.features), "regulation_goals": row.regulation_goals,
        }
        for row in sorted(rows, key=lambda r: (_utc(r.start_time_utc), r.game_id, r.team_id))
    ]
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return sha256(raw).hexdigest()


def fit_public_baseline(
    rows: Iterable[NHLBaselineTrainingRow], *, version: str, ridge: float = 1.0,
) -> NHLPublicBaselineArtifact:
    """Fit standardized log-goal ridge regression with no sportsbook inputs."""
    data = list(rows)
    p = len(BASELINE_FEATURES)
    if not version or ridge < 0 or len(data) <= p + 1:
        raise ValueError("version, nonnegative ridge and sufficient rows required")
    for row in data:
        row.__post_init__()

    means = tuple(sum(row.features[j] for row in data) / len(data) for j in range(p))
    raw_scales = []
    for j, mean in enumerate(means):
        variance = sum((row.features[j] - mean) ** 2 for row in data) / len(data)
        raw_scales.append(math.sqrt(variance) if variance > 1e-12 else 1.0)
    scales = tuple(raw_scales)
    x = [[1.0, *[(row.features[j] - means[j]) / scales[j] for j in range(p)]] for row in data]
    y = [math.log(row.regulation_goals + 0.5) for row in data]
    width = p + 1
    gram = [[sum(obs[i] * obs[j] for obs in x) for j in range(width)] for i in range(width)]
    rhs = [sum(obs[i] * target for obs, target in zip(x, y)) for i in range(width)]
    for i in range(1, width):
        gram[i][i] += ridge
    beta = _solve(gram, rhs)
    starts = sorted(_utc(row.start_time_utc) for row in data)
    return NHLPublicBaselineArtifact(
        version=version,
        feature_names=BASELINE_FEATURES,
        means=means,
        scales=scales,
        intercept=beta[0],
        coefficients=tuple(beta[1:]),
        ridge=float(ridge),
        training_rows=len(data),
        training_sha256=_training_hash(data),
        first_start_time_utc=starts[0].isoformat(),
        last_start_time_utc=starts[-1].isoformat(),
    )


def artifact_from_json_dict(payload: dict[str, object]) -> NHLPublicBaselineArtifact:
    data = dict(payload)
    data["feature_names"] = tuple(str(x) for x in data["feature_names"])
    data["means"] = tuple(float(x) for x in data["means"])
    data["scales"] = tuple(float(x) for x in data["scales"])
    data["coefficients"] = tuple(float(x) for x in data["coefficients"])
    return NHLPublicBaselineArtifact(**data)


def game_state_from_public_baseline(
    matchup: NHLBaselineMatchup, artifact: NHLPublicBaselineArtifact, *,
    home_ot_win_probability: float = 0.5,
) -> NHLGameState:
    if not 0.0 <= home_ot_win_probability <= 1.0:
        raise ValueError("home_ot_win_probability must be in [0,1]")
    return NHLGameState(
        game_id=matchup.game_id,
        home_regulation_goals=artifact.regulation_goal_rate(matchup.home_features),
        away_regulation_goals=artifact.regulation_goal_rate(matchup.away_features),
        home_ot_win_probability=home_ot_win_probability,
    )


__all__ = [
    "BASELINE_FEATURES", "NHLBaselineTrainingRow", "NHLBaselineMatchup",
    "NHLPublicBaselineArtifact", "build_baseline_training_rows",
    "build_baseline_matchup", "fit_public_baseline", "artifact_from_json_dict",
    "game_state_from_public_baseline",
]
