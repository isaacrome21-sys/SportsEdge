"""Research card for every MLB side, total, and prop family.

Full-game sides and totals and pitcher count props are priced from the existing
joint research path set. Batter props are priced from strictly prior game rows
on that same simulation id. F5 sides and totals are priced only when an
independent F5 history bundle is supplied. Binary and first-inning markets stay
NO_MODEL unless the caller already attached a research probability.

Nothing here is Model_P, Truth Gate, OFFICIAL, or staking authority. Batter and
either-pitcher samples are score-independent research couplings.
"""
from __future__ import annotations

from math import isfinite
from typing import Any, Mapping, Sequence

from .f5_distribution import F5_MARKETS, build_f5_distribution, read_f5_probability
from .hitter_joint_engine import HITTER_MARKETS
from .identity_rng import candidate_rng
from .mlb_joint_card_research import (
    GAME_MARKETS,
    PITCHER_MARKETS,
    MLBJointCardResearchError,
    _normalize_pool,
    _pitcher_value,
    simulate_joint_card,
)
from .source_lineage import canonical_json_sha256

SCHEMA_VERSION = "MLB_FULL_RESEARCH_CARD_V1"
SIDE_MARKETS = frozenset({"MONEYLINE", "RUN_LINE", "F5_MONEYLINE", "F5_RUN_LINE"})
TOTAL_MARKETS = frozenset({"TOTALS", "TEAM_TOTALS", "F5_TOTALS", "F5_TEAM_TOTALS"})
EITHER_PITCHER_MARKETS = frozenset({
    "EITHER_PITCHER_HITS_ALLOWED",
    "EITHER_PITCHER_BB",
    "EITHER_PITCHER_ER",
})
BINARY_OR_PERIOD_MARKETS = frozenset({
    "NRFI",
    "YRFI",
    "FIRST_HOME_RUN",
    "PITCHER_RECORD_WIN",
})
PROP_MARKETS = frozenset(HITTER_MARKETS | PITCHER_MARKETS | EITHER_PITCHER_MARKETS | BINARY_OR_PERIOD_MARKETS)
ALL_CARD_MARKETS = frozenset(SIDE_MARKETS | TOTAL_MARKETS | PROP_MARKETS)
_EITHER_BASE = {
    "EITHER_PITCHER_HITS_ALLOWED": "PITCHER_HITS_ALLOWED",
    "EITHER_PITCHER_BB": "PITCHER_BB",
    "EITHER_PITCHER_ER": "PITCHER_ER",
}
_BATTER_FIELDS = (
    "plate_appearances",
    "hits",
    "singles",
    "doubles",
    "triples",
    "home_runs",
    "total_bases",
    "rbi",
    "runs",
    "stolen_bases",
    "walks",
    "strikeouts",
    "extra_base_hits",
)


class MLBFullResearchCardError(ValueError):
    pass


def _probability(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    out = float(value)
    return out if isfinite(out) and 0.0 <= out <= 1.0 else None


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    out = float(value)
    return out if isfinite(out) else None


def _lane(market: str) -> str:
    if market in SIDE_MARKETS:
        return "SIDE"
    if market in TOTAL_MARKETS:
        return "TOTAL"
    return "PROP"


def _batter_value(row: Mapping[str, int], market: str) -> int:
    if market == "HITS_RUNS_RBIS":
        return int(row["hits"] + row["runs"] + row["rbi"])
    if market == "HITS_RUNS_STOLEN_BASES":
        return int(row["hits"] + row["runs"] + row["stolen_bases"])
    if market == "RUNS_RBIS":
        return int(row["runs"] + row["rbi"])
    if market == "HITS_STOLEN_BASES":
        return int(row["hits"] + row["stolen_bases"])
    if market == "HITS_WALKS_STOLEN_BASES":
        return int(row["hits"] + row["walks"] + row["stolen_bases"])
    key = {
        "HITS": "hits",
        "HOME_RUNS": "home_runs",
        "TOTAL_BASES": "total_bases",
        "RBI": "rbi",
        "RUNS": "runs",
        "STOLEN_BASES": "stolen_bases",
        "BATTER_BB": "walks",
        "EXTRA_BASE_HITS": "extra_base_hits",
        "SINGLES": "singles",
        "DOUBLES": "doubles",
        "TRIPLES": "triples",
        "BATTER_K": "strikeouts",
    }.get(market)
    if key is None:
        raise MLBFullResearchCardError(f"unsupported batter market {market}")
    return int(row[key])


def _normalize_batter_pool(raw: Any, batter_id: str) -> list[dict[str, int]]:
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        raise MLBFullResearchCardError(f"batter {batter_id} history must be a sequence")
    rows: list[dict[str, int]] = []
    for i, item in enumerate(raw):
        if not isinstance(item, Mapping):
            raise MLBFullResearchCardError(f"batter {batter_id} history[{i}] must be an object")
        row: dict[str, int] = {}
        for field in _BATTER_FIELDS:
            value = item.get(field)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not float(value).is_integer():
                raise MLBFullResearchCardError(f"batter {batter_id} history[{i}].{field} must be an integer")
            if int(value) < 0:
                raise MLBFullResearchCardError(f"batter {batter_id} history[{i}].{field} must be >= 0")
            row[field] = int(value)
        plate_appearances = row["plate_appearances"]
        if plate_appearances <= 0:
            raise MLBFullResearchCardError(f"batter {batter_id} history[{i}] requires plate appearances")
        if row["singles"] + row["doubles"] + row["triples"] + row["home_runs"] != row["hits"]:
            raise MLBFullResearchCardError(f"batter {batter_id} history[{i}] hit-type sum mismatch")
        if row["doubles"] + row["triples"] + row["home_runs"] != row["extra_base_hits"]:
            raise MLBFullResearchCardError(f"batter {batter_id} history[{i}] XBH arithmetic mismatch")
        if row["singles"] + 2 * row["doubles"] + 3 * row["triples"] + 4 * row["home_runs"] != row["total_bases"]:
            raise MLBFullResearchCardError(f"batter {batter_id} history[{i}] total-base arithmetic mismatch")
        rows.append(row)
    if len(rows) < 5:
        raise MLBFullResearchCardError(f"batter {batter_id} requires at least 5 prior games")
    return rows


def _line(selection: Mapping[str, Any]) -> float:
    try:
        line = float(selection.get("line"))
    except (TypeError, ValueError) as exc:
        raise MLBFullResearchCardError("selection line must be numeric") from exc
    if not isfinite(line):
        raise MLBFullResearchCardError("selection line must be finite")
    return line


def _settle_count(observed: int, *, side: str, line: float) -> int:
    if side == "OVER":
        if observed > line:
            return 1
        if observed < line:
            return -1
        return 0
    if side == "UNDER":
        if observed < line:
            return 1
        if observed > line:
            return -1
        return 0
    raise MLBFullResearchCardError("count side must be OVER/UNDER")


def _sample_indexes(rng: Any, size: int, simulations: int) -> list[int]:
    return [rng.randrange(size) for _ in range(simulations)]


def _count_result(settlements: Sequence[int]) -> dict[str, float]:
    n = float(len(settlements))
    wins = sum(item == 1 for item in settlements)
    pushes = sum(item == 0 for item in settlements)
    return {"research_p": wins / n, "push_p": pushes / n}


def _no_model(selection: Mapping[str, Any], reason: str, *, simulation_id: str) -> dict[str, Any]:
    market = str(selection.get("market") or "").upper()
    return {
        "selection_id": str(selection.get("selection_id") or ""),
        "lane": _lane(market),
        "market": market,
        "side": str(selection.get("side") or ""),
        "line": _number(selection.get("line")),
        "subject_id": selection.get("batter_id") or selection.get("pitcher_id") or selection.get("entity_id"),
        "research_p": None,
        "push_p": None,
        "display_status": "NO_MODEL",
        "official_eligible": False,
        "reason": reason,
        "simulation_id": simulation_id,
    }


def _priced(selection: Mapping[str, Any], *, research_p: float, push_p: float, simulation_id: str, distribution_sha256: str, reason: str) -> dict[str, Any]:
    market = str(selection.get("market") or "").upper()
    return {
        "selection_id": str(selection.get("selection_id") or ""),
        "lane": _lane(market),
        "market": market,
        "side": str(selection.get("side") or ""),
        "line": _number(selection.get("line")),
        "subject_id": selection.get("batter_id") or selection.get("pitcher_id") or selection.get("entity_id"),
        "team_side": selection.get("team_side"),
        "research_p": research_p,
        "push_p": push_p,
        "display_status": "LEAN",
        "official_eligible": False,
        "reason": reason,
        "simulation_id": simulation_id,
        "distribution_sha256": distribution_sha256,
    }


def simulate_mlb_all_markets(
    *,
    game_id: str,
    away_mean_runs: Any,
    home_mean_runs: Any,
    feature_source_hash: str | None,
    selections: Sequence[Mapping[str, Any]],
    pitcher_pools: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
    batter_pools: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
    f5_features: Mapping[str, Any] | None = None,
    simulations: int = 4000,
) -> dict[str, Any]:
    """Price requested sides, totals, and props without inventing a missing model."""
    if not selections:
        raise MLBFullResearchCardError("selections required")
    pitcher_pools = pitcher_pools or {}
    batter_pools = batter_pools or {}
    normalized_batters = {
        str(batter_id): _normalize_batter_pool(pool, str(batter_id))
        for batter_id, pool in sorted(batter_pools.items(), key=lambda item: str(item[0]))
    }
    joint_selections = []
    other_selections = []
    for i, raw in enumerate(selections):
        if not isinstance(raw, Mapping):
            raise MLBFullResearchCardError(f"selection[{i}] must be an object")
        row = dict(raw)
        row["selection_id"] = str(row.get("selection_id") or f"selection-{i}")
        row["market"] = str(row.get("market") or "").upper()
        if row["market"] not in ALL_CARD_MARKETS:
            raise MLBFullResearchCardError(f"unsupported catalog market {row['market']}")
        if row["market"] in GAME_MARKETS | PITCHER_MARKETS:
            joint_selections.append(row)
        else:
            other_selections.append(row)

    probe_id = "__probe_total__"
    joint_input = list(joint_selections)
    if not joint_input:
        joint_input.append({"selection_id": probe_id, "market": "TOTALS", "side": "OVER", "line": 0.5})
    try:
        joint = simulate_joint_card(
            game_id=game_id,
            away_mean_runs=away_mean_runs,
            home_mean_runs=home_mean_runs,
            feature_source_hash=feature_source_hash,
            selections=joint_input,
            pitcher_pools=pitcher_pools,
            simulations=simulations,
        )
    except MLBJointCardResearchError as exc:
        raise MLBFullResearchCardError(str(exc)) from exc
    simulation_id = str(joint["simulation_id"])
    score_sha = str(joint["score_distribution_sha256"])
    results = [
        _priced(
            row,
            research_p=float(row["research_p"]),
            push_p=float(row["push_p"]),
            simulation_id=simulation_id,
            distribution_sha256=score_sha,
            reason="MLB_JOINT_RESEARCH_PATHS_SCORE_INDEPENDENT_PITCHER",
        )
        for row in joint["results"]
        if row["selection_id"] != probe_id
    ]

    batter_hashes = {batter_id: canonical_json_sha256(pool) for batter_id, pool in normalized_batters.items()}
    batter_draws = {
        batter_id: _sample_indexes(
            candidate_rng(canonical_json_sha256({
                "card": SCHEMA_VERSION,
                "simulation_id": simulation_id,
                "batter_id": batter_id,
                "pool_sha256": batter_hashes[batter_id],
            })),
            len(pool),
            int(simulations),
        )
        for batter_id, pool in normalized_batters.items()
    }
    normalized_pitchers = {
        str(pitcher_id): _normalize_pool(pool, str(pitcher_id))
        for pitcher_id, pool in sorted((pitcher_pools or {}).items(), key=lambda item: str(item[0]))
    }
    either_draws = {
        pitcher_id: _sample_indexes(
            candidate_rng(canonical_json_sha256({
                "card": SCHEMA_VERSION,
                "simulation_id": simulation_id,
                "pitcher_id": pitcher_id,
                "role": "either_pitcher_research",
            })),
            len(pool),
            int(simulations),
        )
        for pitcher_id, pool in normalized_pitchers.items()
        if any(row["market"] in EITHER_PITCHER_MARKETS for row in other_selections)
    }

    f5_distribution = build_f5_distribution(f5_features) if f5_features is not None else None
    for selection in other_selections:
        market = selection["market"]
        supplied = _probability(selection.get("research_p"))
        if supplied is not None and market in BINARY_OR_PERIOD_MARKETS:
            results.append(_priced(
                selection,
                research_p=supplied,
                push_p=_probability(selection.get("push_p")) or 0.0,
                simulation_id=simulation_id,
                distribution_sha256=score_sha,
                reason="CALLER_SUPPLIED_RESEARCH_PROBABILITY",
            ))
            continue
        if market in HITTER_MARKETS:
            batter_id = str(selection.get("batter_id") or "")
            pool = normalized_batters.get(batter_id)
            if pool is None:
                results.append(_no_model(selection, "BATTER_HISTORY_MISSING", simulation_id=simulation_id))
                continue
            line = _line(selection)
            side = str(selection.get("side") or "").upper()
            settlements = [
                _settle_count(_batter_value(pool[index], market), side=side, line=line)
                for index in batter_draws[batter_id]
            ]
            counted = _count_result(settlements)
            results.append(_priced(
                selection,
                research_p=counted["research_p"],
                push_p=counted["push_p"],
                simulation_id=simulation_id,
                distribution_sha256=score_sha,
                reason="MLB_BATTER_PRIOR_GAMES_SCORE_INDEPENDENT_RESEARCH",
            ))
            continue
        if market in EITHER_PITCHER_MARKETS:
            left = str(selection.get("pitcher_a_id") or "")
            right = str(selection.get("pitcher_b_id") or "")
            if left not in normalized_pitchers or right not in normalized_pitchers:
                results.append(_no_model(selection, "EITHER_PITCHER_POOLS_MISSING", simulation_id=simulation_id))
                continue
            line = _line(selection)
            side = str(selection.get("side") or "").upper()
            base = _EITHER_BASE[market]
            left_pool = normalized_pitchers[left]
            right_pool = normalized_pitchers[right]
            settlements = []
            for left_index, right_index in zip(either_draws[left], either_draws[right]):
                left_value = _pitcher_value(left_pool[left_index], base)
                right_value = _pitcher_value(right_pool[right_index], base)
                if side == "OVER":
                    settlements.append(1 if left_value > line or right_value > line else (-1 if left_value < line and right_value < line else 0))
                elif side == "UNDER":
                    settlements.append(1 if left_value < line and right_value < line else (-1 if left_value > line or right_value > line else 0))
                else:
                    raise MLBFullResearchCardError("either-pitcher side must be OVER/UNDER")
            counted = _count_result(settlements)
            results.append(_priced(
                selection,
                research_p=counted["research_p"],
                push_p=counted["push_p"],
                simulation_id=simulation_id,
                distribution_sha256=score_sha,
                reason="MLB_EITHER_PITCHER_INDEPENDENT_START_RESEARCH",
            ))
            continue
        if market in F5_MARKETS:
            if f5_distribution is None:
                results.append(_no_model(selection, "F5_HISTORY_MISSING", simulation_id=simulation_id))
                continue
            readout = read_f5_probability(
                f5_distribution,
                market=market,
                line=selection.get("line"),
                side=str(selection.get("side") or ""),
                team_side=selection.get("team_side"),
            )
            results.append(_priced(
                selection,
                research_p=float(readout.probability),
                push_p=float(readout.push_probability),
                simulation_id=simulation_id,
                distribution_sha256=f5_distribution.distribution_sha256,
                reason="MLB_F5_INDEPENDENT_EMPIRICAL_MARGINAL",
            ))
            continue
        results.append(_no_model(selection, "NO_VALIDATED_RESEARCH_PROBABILITY", simulation_id=simulation_id))

    return assemble_mlb_research_card(
        game_id=str(game_id),
        simulation_id=simulation_id,
        rows=results,
        simulations=int(simulations),
    )


def assemble_mlb_research_card(
    *,
    game_id: str,
    simulation_id: str,
    rows: Sequence[Mapping[str, Any]],
    simulations: int,
) -> dict[str, Any]:
    normalized = [dict(row) for row in rows]
    for row in normalized:
        row["official_eligible"] = False
        row["lane"] = _lane(str(row.get("market") or ""))
        if row.get("display_status") not in {"LEAN", "NO_MODEL", "BLOCKED"}:
            row["display_status"] = "LEAN" if _probability(row.get("research_p")) is not None else "NO_MODEL"
    leans = [row for row in normalized if row.get("display_status") == "LEAN"]
    return {
        "schema_version": SCHEMA_VERSION,
        "sport": "MLB",
        "game_id": game_id,
        "simulation_id": simulation_id,
        "simulations": simulations,
        "run_status": "RESEARCH_LEANS_AVAILABLE" if leans else "RESEARCH_BLOCKED_NO_LEANS",
        "rows": normalized,
        "summary": {
            "side_rows": sum(row["lane"] == "SIDE" for row in normalized),
            "total_rows": sum(row["lane"] == "TOTAL" for row in normalized),
            "prop_rows": sum(row["lane"] == "PROP" for row in normalized),
            "lean_rows": len(leans),
            "no_model_rows": sum(row.get("display_status") == "NO_MODEL" for row in normalized),
            "official_bets": 0,
            "markets_seen": sorted({str(row.get("market")) for row in normalized}),
        },
        "governance": {
            "research_only": True,
            "not_model_p": True,
            "production_authority_changed": False,
            "truth_gate_changed": False,
            "promotion_authority": False,
            "official_authority": False,
            "staking_authority": False,
            "batter_coupling": "score_independent_prior_game_bootstrap",
            "either_pitcher_coupling": "score_independent_prior_start_bootstrap",
        },
    }


__all__ = [
    "ALL_CARD_MARKETS",
    "MLBFullResearchCardError",
    "PROP_MARKETS",
    "SCHEMA_VERSION",
    "SIDE_MARKETS",
    "TOTAL_MARKETS",
    "assemble_mlb_research_card",
    "simulate_mlb_all_markets",
]
