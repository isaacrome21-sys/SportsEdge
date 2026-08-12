"""Reusable cutoff-correct live feature construction for core MLB game markets.

This module is the production counterpart of the admissible v3/v3.1 historical
rebuild lineage. It deliberately preserves the exact frozen feature contracts
used by sportsedge_game_score_v4.joblib and sportsedge_nrfi_v4.joblib.
Sportsbook data is not accepted here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
import math
from typing import Iterable, Mapping, Any

RUN_PRIOR = 4.4
FI_PRIOR = 0.28
PRIOR_GAMES = 20.0
RUN_FEATURES = (
    "off_rf_pg", "opp_ra_pg", "off_ewm_rf", "opp_ewm_ra", "league_runs_pg",
    "home_flag", "rest_days", "season_games", "month_sin", "month_cos",
)
FI_FEATURES = (
    "away_fi_for", "home_fi_for", "home_fi_against", "away_fi_against",
    "away_ewm_fi_for", "home_ewm_fi_for", "home_ewm_fi_against", "away_ewm_fi_against",
    "away_rf_pg", "home_rf_pg", "home_ra_pg", "away_ra_pg", "league_fi_rate",
    "away_rest", "home_rest", "month_sin", "month_cos",
)

class GameLiveFeatureError(ValueError):
    pass

@dataclass
class TeamState:
    n: int = 0
    rf: float = 0.0
    ra: float = 0.0
    fi_for: float = 0.0
    fi_against: float = 0.0
    ewm_rf: float = RUN_PRIOR
    ewm_ra: float = RUN_PRIOR
    ewm_fi_for: float = FI_PRIOR
    ewm_fi_against: float = FI_PRIOR
    last_date: date | None = None

@dataclass
class HistoryState:
    teams: dict[int, TeamState] = field(default_factory=dict)
    league_n: int = 0
    league_runs: float = 0.0
    league_fi_events: float = 0.0

def new_history_state() -> HistoryState:
    return HistoryState(teams={})

def _smooth(num: float, n: int, prior: float) -> float:
    return (float(num) + PRIOR_GAMES * prior) / (int(n) + PRIOR_GAMES)

def _rest(st: TeamState, d: date) -> float:
    if st.last_date is None:
        return 4.0
    return float(min(max((d - st.last_date).days, 0), 7))

def _game_date(game: Mapping[str, Any]) -> date:
    raw = game.get("officialDate") or game.get("date")
    if not isinstance(raw, str) or not raw:
        raise GameLiveFeatureError("OFFICIAL_DATE_INVALID_OR_MISSING")
    try:
        return date.fromisoformat(raw)
    except Exception as exc:
        raise GameLiveFeatureError("OFFICIAL_DATE_INVALID_OR_MISSING") from exc

def _team_id(game: Mapping[str, Any], key: str) -> int:
    raw = game.get(key)
    if isinstance(raw, bool):
        raise GameLiveFeatureError(f"{key.upper()}_INVALID")
    try:
        return int(raw)
    except Exception as exc:
        raise GameLiveFeatureError(f"{key.upper()}_INVALID") from exc

def feature_one(state: HistoryState, game: Mapping[str, Any]) -> tuple[list[list[float]], list[float]]:
    d = _game_date(game)
    away_id = _team_id(game, "away_id")
    home_id = _team_id(game, "home_id")
    a = state.teams.get(away_id, TeamState())
    h = state.teams.get(home_id, TeamState())
    if state.league_n:
        league_run = (state.league_runs + PRIOR_GAMES * 2 * RUN_PRIOR) / (2 * state.league_n + PRIOR_GAMES * 2)
        league_fi = (state.league_fi_events + PRIOR_GAMES * 2 * FI_PRIOR) / (2 * state.league_n + PRIOR_GAMES * 2)
    else:
        league_run = RUN_PRIOR
        league_fi = FI_PRIOR
    ms = math.sin(2 * math.pi * d.timetuple().tm_yday / 365.25)
    mc = math.cos(2 * math.pi * d.timetuple().tm_yday / 365.25)
    af = _smooth(a.rf, a.n, RUN_PRIOR)
    aa = _smooth(a.ra, a.n, RUN_PRIOR)
    hf = _smooth(h.rf, h.n, RUN_PRIOR)
    ha = _smooth(h.ra, h.n, RUN_PRIOR)
    run_rows = [
        [af, ha, a.ewm_rf, h.ewm_ra, league_run, 0.0, _rest(a, d), float(a.n), ms, mc],
        [hf, aa, h.ewm_rf, a.ewm_ra, league_run, 1.0, _rest(h, d), float(h.n), ms, mc],
    ]
    aff = _smooth(a.fi_for, a.n, FI_PRIOR)
    afa = _smooth(a.fi_against, a.n, FI_PRIOR)
    hff = _smooth(h.fi_for, h.n, FI_PRIOR)
    hfa = _smooth(h.fi_against, h.n, FI_PRIOR)
    fi_row = [
        aff, hff, hfa, afa,
        a.ewm_fi_for, h.ewm_fi_for, h.ewm_fi_against, a.ewm_fi_against,
        af, hf, ha, aa, league_fi, _rest(a, d), _rest(h, d), ms, mc,
    ]
    return run_rows, fi_row

def apply_result(state: HistoryState, game: Mapping[str, Any] | None = None, **kwargs) -> None:
    if game is None:
        game = {
            "officialDate": kwargs.get("official_date"), "away_id": kwargs.get("away_id"), "home_id": kwargs.get("home_id"),
            "away_runs": kwargs.get("away_runs"), "home_runs": kwargs.get("home_runs"),
            "away_fi": kwargs.get("away_fi"), "home_fi": kwargs.get("home_fi"),
        }
    d = _game_date(game)
    away_id = _team_id(game, "away_id")
    home_id = _team_id(game, "home_id")
    required = ("away_runs", "home_runs", "away_fi", "home_fi")
    try:
        vals = {k: int(game[k]) for k in required}
    except Exception as exc:
        raise GameLiveFeatureError("FINAL_RESULT_FIELDS_INVALID") from exc
    a = state.teams.setdefault(away_id, TeamState())
    h = state.teams.setdefault(home_id, TeamState())
    away_event = int(vals["away_fi"] > 0)
    home_event = int(vals["home_fi"] > 0)
    for st, rf, ra, ff, fa in (
        (a, vals["away_runs"], vals["home_runs"], away_event, home_event),
        (h, vals["home_runs"], vals["away_runs"], home_event, away_event),
    ):
        st.n += 1; st.rf += rf; st.ra += ra; st.fi_for += ff; st.fi_against += fa
        st.ewm_rf = 0.94 * st.ewm_rf + 0.06 * rf
        st.ewm_ra = 0.94 * st.ewm_ra + 0.06 * ra
        st.ewm_fi_for = 0.94 * st.ewm_fi_for + 0.06 * ff
        st.ewm_fi_against = 0.94 * st.ewm_fi_against + 0.06 * fa
        st.last_date = d
    state.league_n += 1
    state.league_runs += vals["away_runs"] + vals["home_runs"]
    state.league_fi_events += away_event + home_event

def build_run_rows(state: HistoryState, *, away_id: int, home_id: int, official_date: str) -> list[list[float]]:
    rows, _ = feature_one(state, {"away_id": away_id, "home_id": home_id, "officialDate": official_date})
    return rows

def build_fi_row(state: HistoryState, *, away_id: int, home_id: int, official_date: str) -> list[float]:
    _, row = feature_one(state, {"away_id": away_id, "home_id": home_id, "officialDate": official_date})
    return row

def build_history_and_features(games: Iterable[Mapping[str, Any]]) -> tuple[HistoryState, list[dict[str, Any]]]:
    ordered = sorted(list(games), key=lambda g: (str(g.get("officialDate") or g.get("date") or ""), int(g.get("game_pk") or 0)))
    state = new_history_state(); out: list[dict[str, Any]] = []; i = 0
    while i < len(ordered):
        day = str(ordered[i].get("officialDate") or ordered[i].get("date") or "")
        batch: list[Mapping[str, Any]] = []
        while i < len(ordered) and str(ordered[i].get("officialDate") or ordered[i].get("date") or "") == day:
            batch.append(ordered[i]); i += 1
        pending = []
        for g in batch:
            run_rows, fi_row = feature_one(state, g); pending.append((g, run_rows, fi_row))
        for g, run_rows, fi_row in pending:
            out.append({"game_pk": int(g.get("game_pk") or 0), "officialDate": day, "run_rows": run_rows, "fi_row": fi_row})
        for g, _, _ in pending:
            apply_result(state, g)
    return state, out

def verify_artifact_feature_contract(artifact: Mapping[str, Any], *, kind: str) -> None:
    if kind == "run":
        got = tuple(artifact.get("run_features") or ()); expected = RUN_FEATURES
    elif kind == "nrfi":
        got = tuple(artifact.get("features") or ()); expected = FI_FEATURES
    else:
        raise GameLiveFeatureError("UNKNOWN_ARTIFACT_KIND")
    if got != expected:
        raise GameLiveFeatureError(f"ARTIFACT_FEATURE_CONTRACT_MISMATCH kind={kind} expected={expected!r} got={got!r}")
