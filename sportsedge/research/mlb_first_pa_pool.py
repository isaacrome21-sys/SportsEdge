"""Point-in-time first-plate-appearance outcome pool (M49 foundation).

#2332 named the M49 gate PLATE_APPEARANCE_PBP_POOL_UNBUILT. This module is the
research-only pool builder that gate asks for. It consumes caller-supplied
StatsAPI-style play-by-play records (no network, no collector) and, for a
prediction cutoff, builds per-batter first-PA outcomes and per-starter
first-PA-faced outcomes strictly from games that started BEFORE the cutoff.

It also gives a research on-base readout: an empirical-Bayes beta mean with a
CALLER-FIXED prior strength (nothing here is fitted or tuned). The second M49
gate, PLATE_APPEARANCE_SELECTION_SET_UNVERIFIED, is NOT resolved: DK's exact
selection lists are unknown, so every readout carries that settlement gate and
no 1st-PA Result / Grouped Result probability is emitted.

UNVALIDATED_RESEARCH; no registry, runner, quote or settlement wiring.
"""
from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite
from typing import Iterable, Mapping

from sportsedge.source_lineage import canonical_json_sha256

OUTCOME_MAP = {
    "single": "SINGLE", "double": "DOUBLE", "triple": "TRIPLE",
    "home_run": "HOME_RUN", "walk": "WALK", "intent_walk": "WALK",
    "hit_by_pitch": "HIT_BY_PITCH", "strikeout": "STRIKEOUT",
    "strikeout_double_play": "STRIKEOUT", "strikeout_triple_play": "STRIKEOUT",
    "field_out": "OUT_IN_PLAY", "force_out": "OUT_IN_PLAY",
    "grounded_into_double_play": "OUT_IN_PLAY", "double_play": "OUT_IN_PLAY",
    "triple_play": "OUT_IN_PLAY", "fielders_choice": "OUT_IN_PLAY",
    "fielders_choice_out": "OUT_IN_PLAY", "sac_fly": "OUT_IN_PLAY",
    "sac_bunt": "OUT_IN_PLAY", "sac_fly_double_play": "OUT_IN_PLAY",
    "sac_bunt_double_play": "OUT_IN_PLAY", "field_error": "REACHED_ON_ERROR",
    "catcher_interf": "CATCHER_INTERFERENCE",
}
ON_BASE = frozenset({"SINGLE", "DOUBLE", "TRIPLE", "HOME_RUN", "WALK", "HIT_BY_PITCH"})
SELECTION_GATE = "PLATE_APPEARANCE_SELECTION_SET_UNVERIFIED"


def _utc(value, code):
    if not isinstance(value, str):
        raise ValueError(code)
    try:
        ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(code) from exc
    if ts.tzinfo is None:
        raise ValueError(code)
    return ts.astimezone(timezone.utc)


def _id(value, code):
    if isinstance(value, bool) or not isinstance(value, (int, str)) or value == "":
        raise ValueError(code)
    return str(value)


def _first_pas(game: Mapping) -> tuple[dict, dict]:
    """(batter -> outcome, starter -> list of first-PA-faced outcomes)."""
    plays = game.get("plays")
    if not isinstance(plays, list) or not plays:
        raise ValueError("FIRST_PA_PLAYS_MISSING")
    seen_idx, batters, faced = set(), {}, {}
    starters = {}
    last = -1
    for play in plays:
        if not isinstance(play, Mapping):
            raise ValueError("FIRST_PA_PLAY_INVALID")
        idx = play.get("at_bat_index")
        if isinstance(idx, bool) or not isinstance(idx, int) or idx < 0:
            raise ValueError("FIRST_PA_AT_BAT_INDEX_INVALID")
        if idx in seen_idx:
            raise ValueError("FIRST_PA_AT_BAT_INDEX_DUPLICATE")
        if idx <= last:
            raise ValueError("FIRST_PA_PLAYS_NOT_CHRONOLOGICAL")
        seen_idx.add(idx)
        last = idx
        half = play.get("half")
        if half not in {"top", "bottom"}:
            raise ValueError("FIRST_PA_HALF_INVALID")
        batter = _id(play.get("batter_id"), "FIRST_PA_BATTER_ID_INVALID")
        pitcher = _id(play.get("pitcher_id"), "FIRST_PA_PITCHER_ID_INVALID")
        event = play.get("event_type")
        if event not in OUTCOME_MAP:
            raise ValueError(f"FIRST_PA_EVENT_UNMAPPED:{event}")
        outcome = OUTCOME_MAP[event]
        starters.setdefault(half, pitcher)
        if batter not in batters:
            batters[batter] = outcome
            if pitcher == starters[half]:
                faced.setdefault(pitcher, []).append(outcome)
    # Completeness: the feed must start at the game's first PA and be gap-free,
    # the top half must open the game, and both first-inning halves must exist,
    # otherwise a truncated feed could fake a "first" PA or starter.
    if sorted(seen_idx) != list(range(len(seen_idx))):
        raise ValueError("FIRST_PA_PLAYS_INCOMPLETE")
    if plays[0].get("half") != "top" or set(starters) != {"top", "bottom"}:
        raise ValueError("FIRST_PA_PLAYS_INCOMPLETE")
    confirmed = game.get("starting_pitchers")
    if not isinstance(confirmed, Mapping) or set(confirmed) != {"home", "away"}:
        raise ValueError("FIRST_PA_STARTER_UNCONFIRMED")
    home_sp = _id(confirmed.get("home"), "FIRST_PA_STARTER_UNCONFIRMED")
    away_sp = _id(confirmed.get("away"), "FIRST_PA_STARTER_UNCONFIRMED")
    if starters["top"] != home_sp or starters["bottom"] != away_sp:
        raise ValueError("FIRST_PA_STARTER_MISMATCH")
    return batters, faced


def build_first_pa_pool(games: Iterable[Mapping], *, cutoff_utc: str) -> dict:
    cutoff = _utc(cutoff_utc, "FIRST_PA_CUTOFF_INVALID")
    batter_pool: dict[str, dict[str, int]] = {}
    starter_pool: dict[str, dict[str, int]] = {}
    used, excluded_not_prior, excluded_late_final, keys = [], 0, 0, set()
    for game in games:
        if not isinstance(game, Mapping):
            raise ValueError("FIRST_PA_GAME_INVALID")
        pk = _id(game.get("game_pk"), "FIRST_PA_GAME_PK_INVALID")
        if pk in keys:
            raise ValueError("FIRST_PA_GAME_DUPLICATE")
        keys.add(pk)
        start = _utc(game.get("first_pitch_utc"), "FIRST_PA_START_INVALID")
        if game.get("status") != "Final":
            raise ValueError("FIRST_PA_GAME_NOT_FINAL")
        if start >= cutoff:
            excluded_not_prior += 1
            continue  # Target game and anything later never enter the pool.
        batters, faced = _first_pas(game)
        # PIT proof: a start time is not enough. The final/settled PBP must have
        # been observed at or before the cutoff, or the game is refused/excluded.
        if "final_observed_utc" not in game or game.get("final_observed_utc") is None:
            raise ValueError("FIRST_PA_FINAL_AS_OF_MISSING")
        final_seen = _utc(game.get("final_observed_utc"), "FIRST_PA_FINAL_AS_OF_INVALID")
        if final_seen < start:
            raise ValueError("FIRST_PA_FINAL_BEFORE_START")
        if final_seen > cutoff:
            excluded_late_final += 1
            continue
        for pid, outcome in batters.items():
            row = batter_pool.setdefault(pid, {})
            row[outcome] = row.get(outcome, 0) + 1
        for pid, outcomes in faced.items():
            row = starter_pool.setdefault(pid, {})
            for outcome in outcomes:
                row[outcome] = row.get(outcome, 0) + 1
        used.append(pk)
    pool = {
        "schema": "MLB_FIRST_PA_POOL_V1", "cutoff_utc": cutoff.isoformat(),
        "games_used": sorted(used), "games_excluded_not_strictly_prior": excluded_not_prior,
        "games_excluded_final_not_observed_by_cutoff": excluded_late_final,
        "pit_basis": "FINAL_OBSERVED_UTC_AT_OR_BEFORE_CUTOFF",
        "batters": {k: dict(sorted(v.items())) for k, v in sorted(batter_pool.items())},
        "starters_first_pa_faced": {k: dict(sorted(v.items())) for k, v in sorted(starter_pool.items())},
        "settlement_gate": SELECTION_GATE, "validation_status": "UNVALIDATED_RESEARCH",
    }
    pool["pool_sha256"] = canonical_json_sha256(pool)
    return pool


def read_first_pa_on_base(pool: Mapping, *, batter_id: str, prior_strength: float) -> dict:
    """Beta(prior_strength * league_rate) shrinkage of first-PA on-base rate."""
    if pool.get("schema") != "MLB_FIRST_PA_POOL_V1":
        raise ValueError("FIRST_PA_POOL_INVALID")
    body = {k: v for k, v in pool.items() if k != "pool_sha256"}
    if canonical_json_sha256(body) != pool.get("pool_sha256"):
        raise ValueError("FIRST_PA_POOL_HASH_MISMATCH")
    if (isinstance(prior_strength, bool) or not isinstance(prior_strength, (int, float))
            or not isfinite(prior_strength) or prior_strength <= 0):
        raise ValueError("FIRST_PA_PRIOR_STRENGTH_INVALID")
    batter_id = _id(batter_id, "FIRST_PA_BATTER_ID_INVALID")
    league_n = sum(sum(v.values()) for v in pool["batters"].values())
    if league_n == 0:
        raise ValueError("FIRST_PA_POOL_EMPTY")
    league_ob = sum(c for v in pool["batters"].values() for o, c in v.items() if o in ON_BASE)
    league_rate = league_ob / league_n
    own = pool["batters"].get(batter_id, {})
    n = sum(own.values())
    ob = sum(c for o, c in own.items() if o in ON_BASE)
    p = (ob + prior_strength * league_rate) / (n + prior_strength)
    return {
        "batter_id": batter_id, "batter_first_pa_n": n, "batter_first_pa_on_base": ob,
        "league_first_pa_n": league_n, "league_on_base_rate": league_rate,
        "prior_strength": float(prior_strength), "research_p_on_base": p,
        "pool_sha256": pool["pool_sha256"], "settlement_gate": SELECTION_GATE,
        "validation_status": "UNVALIDATED_RESEARCH", "production_ready": False,
        "promotion_authority": False, "model_p_authority": False,
        "limitations": ["OPPOSING_STARTER_NOT_YET_COMBINED",
                        "SELECTION_SET_UNVERIFIED_NO_SETTLEMENT",
                        "CHRONOLOGICAL_BACKTEST_REQUIRED", "NOT_WIRED_TO_RUN_IT"],
    }
