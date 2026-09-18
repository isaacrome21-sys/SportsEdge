"""Canonical runtime adapter for a frozen selected CFB candidate family.

This module bridges the preregistered selected-candidate model surface to the existing
CFB run machine without changing market pricing, de-vigging, seed identity, or betting
authority. It is serving plumbing only: no candidate evaluation, attempt consumption,
Model_P promotion, Truth Gate, eligibility, staking, evidence clock, backfill, or
OFFICIAL authority is created here.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import MISSING, dataclass, replace
from datetime import datetime
from typing import Any, Callable, Mapping, Sequence
from urllib.request import urlopen

from .candidate_live_source import (
    attach_candidate_snapshots_to_game_row,
    fetch_cfbd_candidate_metric_snapshots,
)
from .joint_model import CFB_FEATURE_CONTRACT, CFB_JOINT_MODEL_ID
from .run_machine import CFBMachineReport, DEFAULT_QUOTE_TTL_SECONDS, run_cfb_machine
from .selected_candidate_model import CFBSelectedCandidateScoreModel
from .source import (
    CFBGame,
    CFBQuote,
    CFBTeamMetrics,
    attach_weather,
    build_team_alias_index,
    fetch_cfbd_games,
    fetch_cfbd_teams,
    fetch_cfbd_weather,
    fetch_the_odds_api_quotes,
)

CFB_SELECTED_CANDIDATE_RUNTIME_CONTRACT = "CFB_SELECTED_CANDIDATE_CANONICAL_RUNTIME_V1"
VALID_SELECTED_RUNTIME_MODES = frozenset({"MANUAL", "HYBRID", "AUTOMATIC"})


class CFBSelectedCandidateRuntimeError(ValueError):
    pass


@dataclass(frozen=True)
class CFBSelectedCandidateRuntimeAdapter:
    """Duck-typed joint-model adapter with selected-family prediction semantics.

    ``simulate_cfb_joint_distribution`` only requires the joint identity constants,
    residual/OT state, ``predict_means`` and ``artifact_sha256``. Those stochastic
    mechanics are intentionally identical to the selected-candidate simulator, so the
    adapter changes only the feature transform used for the conditional score means.
    """

    selected_model: CFBSelectedCandidateScoreModel
    candidate_rows_by_game_id: Mapping[str, Mapping[str, Any]]

    model_id: str = CFB_JOINT_MODEL_ID
    feature_contract: str = CFB_FEATURE_CONTRACT

    @property
    def residual_pairs(self):
        return self.selected_model.residual_pairs

    @property
    def overtime_deltas(self):
        return self.selected_model.overtime_deltas

    def artifact_sha256(self) -> str:
        return self.selected_model.artifact_sha256()

    def predict_means(self, row: Mapping[str, Any]) -> tuple[float, float]:
        game_id = str(row.get("game_id") or "").strip()
        bound = self.candidate_rows_by_game_id.get(game_id)
        if not isinstance(bound, Mapping):
            raise CFBSelectedCandidateRuntimeError(
                f"CFB_SELECTED_RUNTIME_GAME_ROW_MISSING:{game_id or 'UNKNOWN'}"
            )
        candidate_row = deepcopy(dict(bound))
        # The canonical run machine owns live game/weather state. Preserve that state
        # while the adapter supplies only the frozen dual-snapshot candidate features.
        candidate_row["neutral_site"] = row.get(
            "neutral_site", candidate_row.get("neutral_site", False)
        )
        weather = row.get("weather")
        if isinstance(weather, Mapping):
            candidate_row["weather"] = dict(weather)
        return self.selected_model.predict_means(candidate_row)


def _metric_object(raw: Mapping[str, Any]) -> CFBTeamMetrics:
    fields = CFBTeamMetrics.__dataclass_fields__
    missing = [
        name
        for name, field in fields.items()
        if name not in raw
        and field.default is MISSING
        and field.default_factory is MISSING
    ]
    if missing:
        raise CFBSelectedCandidateRuntimeError(
            "CFB_SELECTED_RUNTIME_METRIC_FIELDS_MISSING:" + ",".join(sorted(missing))
        )
    values = {name: raw[name] for name in fields if name in raw}
    try:
        return CFBTeamMetrics(**values)
    except (KeyError, TypeError, ValueError) as exc:
        raise CFBSelectedCandidateRuntimeError("CFB_SELECTED_RUNTIME_METRIC_INVALID") from exc


def _current_metric_objects(
    snapshots: Mapping[str, Mapping[str, Mapping[str, Any]]],
) -> dict[str, CFBTeamMetrics]:
    out: dict[str, CFBTeamMetrics] = {}
    for team, pair in snapshots.items():
        if not isinstance(pair, Mapping) or not isinstance(pair.get("current"), Mapping):
            raise CFBSelectedCandidateRuntimeError(
                f"CFB_SELECTED_RUNTIME_CURRENT_SNAPSHOT_MISSING:{team}"
            )
        out[str(team)] = _metric_object(pair["current"])
    if not out:
        raise CFBSelectedCandidateRuntimeError("CFB_SELECTED_RUNTIME_SNAPSHOTS_EMPTY")
    return out


def build_selected_candidate_runtime_adapter(
    *,
    model: CFBSelectedCandidateScoreModel,
    games: Sequence[CFBGame],
    candidate_snapshots: Mapping[str, Mapping[str, Mapping[str, Any]]],
) -> tuple[CFBSelectedCandidateRuntimeAdapter, dict[str, CFBTeamMetrics]]:
    if not isinstance(model, CFBSelectedCandidateScoreModel):
        raise CFBSelectedCandidateRuntimeError("CFB_SELECTED_RUNTIME_MODEL_REQUIRED")
    current_metrics = _current_metric_objects(candidate_snapshots)
    rows: dict[str, dict[str, Any]] = {}
    for game in games:
        if not isinstance(game, CFBGame):
            raise CFBSelectedCandidateRuntimeError("CFB_SELECTED_RUNTIME_GAME_INVALID")
        if not isinstance(game.weather, Mapping):
            raise CFBSelectedCandidateRuntimeError(
                f"CFB_SELECTED_RUNTIME_WEATHER_MISSING:{game.game_id}"
            )
        base = {
            "game_id": game.game_id,
            "season": game.season,
            "week": game.week,
            "neutral_site": game.neutral_site,
            "weather": dict(game.weather),
        }
        rows[game.game_id] = attach_candidate_snapshots_to_game_row(
            base,
            home_team=game.home_team,
            away_team=game.away_team,
            snapshots=candidate_snapshots,
        )
    if not rows:
        raise CFBSelectedCandidateRuntimeError("CFB_SELECTED_RUNTIME_GAMES_EMPTY")
    return CFBSelectedCandidateRuntimeAdapter(model, rows), current_metrics


def run_selected_candidate_cfb_machine(
    *,
    mode: str,
    season: int,
    week: int,
    model: CFBSelectedCandidateScoreModel,
    now: datetime,
    games: Sequence[CFBGame] | None = None,
    candidate_snapshots: Mapping[str, Mapping[str, Mapping[str, Any]]] | None = None,
    quotes: Sequence[CFBQuote | Mapping[str, Any]] | None = None,
    fbs_team_rows: Sequence[Mapping[str, Any]] | None = None,
    cfbd_api_key: str | None = None,
    odds_api_key: str | None = None,
    bookmakers: Sequence[str] = ("draftkings",),
    root_seed: int = 20260826,
    n_paths: int = 20000,
    quote_ttl_seconds: int = DEFAULT_QUOTE_TTL_SECONDS,
    opener: Callable = urlopen,
    team_fetcher=fetch_cfbd_teams,
    game_fetcher=fetch_cfbd_games,
    weather_fetcher=fetch_cfbd_weather,
    candidate_metric_fetcher=fetch_cfbd_candidate_metric_snapshots,
    odds_fetcher=fetch_the_odds_api_quotes,
) -> CFBMachineReport:
    """Serve one already-selected family through the canonical CFB run machine.

    MANUAL requires games, dual candidate snapshots, quotes, and FBS membership.
    HYBRID owns only quotes; AUTOMATIC owns all external inputs. Fetched modes build
    the same dual prior/current snapshots required by the frozen candidate transform.
    """
    selected = str(mode or "").strip().upper()
    if selected not in VALID_SELECTED_RUNTIME_MODES:
        raise CFBSelectedCandidateRuntimeError(
            f"CFB_SELECTED_RUNTIME_MODE_UNSUPPORTED:{selected}"
        )

    if selected == "MANUAL":
        if games is None or candidate_snapshots is None or quotes is None or fbs_team_rows is None:
            raise CFBSelectedCandidateRuntimeError(
                "CFB_SELECTED_RUNTIME_MANUAL_REQUIRES_GAMES_SNAPSHOTS_QUOTES_FBS"
            )
        canonical_games = list(games)
        snapshots = candidate_snapshots
        canonical_quotes = list(quotes)
        team_rows = list(fbs_team_rows)
    else:
        if games is not None or candidate_snapshots is not None or fbs_team_rows is not None:
            raise CFBSelectedCandidateRuntimeError(
                "CFB_SELECTED_RUNTIME_FETCHED_MODE_OWNS_GAMES_SNAPSHOTS_FBS"
            )
        key = str(cfbd_api_key or "").strip()
        if not key:
            raise CFBSelectedCandidateRuntimeError("CFBD_API_KEY_REQUIRED")
        team_rows = team_fetcher(season=season, cfbd_api_key=key, opener=opener)
        canonical_games = game_fetcher(
            season=season, week=week, cfbd_api_key=key, opener=opener
        )
        canonical_games = attach_weather(
            canonical_games,
            weather_fetcher(
                season=season, week=week, cfbd_api_key=key, opener=opener
            ),
        )
        snapshots = candidate_metric_fetcher(
            season=season,
            week=week,
            cfbd_api_key=key,
            now=now,
            opener=opener,
        )
        if selected == "HYBRID":
            if quotes is None:
                raise CFBSelectedCandidateRuntimeError(
                    "CFB_SELECTED_RUNTIME_HYBRID_REQUIRES_QUOTES"
                )
            canonical_quotes = list(quotes)
        else:
            if quotes is not None:
                raise CFBSelectedCandidateRuntimeError(
                    "CFB_SELECTED_RUNTIME_AUTOMATIC_OWNS_QUOTES"
                )
            odds_key = str(odds_api_key or "").strip()
            if not odds_key:
                raise CFBSelectedCandidateRuntimeError("ODDS_API_KEY_REQUIRED")
            alias_index = build_team_alias_index(team_rows)
            canonical_quotes = odds_fetcher(
                api_key=odds_key,
                games=canonical_games,
                alias_index=alias_index,
                bookmakers=bookmakers,
                opener=opener,
            )

    adapter, current_metrics = build_selected_candidate_runtime_adapter(
        model=model,
        games=canonical_games,
        candidate_snapshots=snapshots,
    )
    report = run_cfb_machine(
        mode="MANUAL",
        season=season,
        week=week,
        model=adapter,
        now=now,
        games=canonical_games,
        metrics=current_metrics,
        quotes=canonical_quotes,
        fbs_team_rows=team_rows,
        root_seed=root_seed,
        n_paths=n_paths,
        quote_ttl_seconds=quote_ttl_seconds,
    )
    return replace(report, mode=selected)


__all__ = [
    "CFB_SELECTED_CANDIDATE_RUNTIME_CONTRACT",
    "CFBSelectedCandidateRuntimeAdapter",
    "CFBSelectedCandidateRuntimeError",
    "build_selected_candidate_runtime_adapter",
    "run_selected_candidate_cfb_machine",
]
