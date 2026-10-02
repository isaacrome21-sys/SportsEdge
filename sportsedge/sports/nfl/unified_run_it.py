"""Operational RUN IT adapter for the unified NFL research engine.

The adapter deliberately keeps model construction and sportsbook economics
separate:
- score/player probabilities are generated first from the unified NFL engine;
- sportsbook quote objects are used only to choose the posted threshold/side and
  then handed to the existing RUN IT pricing/Score-B boards;
- the same discrete score distribution supplies integer-line push mass.

Research-only.  This does not change Attempt-9 ownership or grant Model_P,
Truth-Gate, OFFICIAL, promotion, or staking authority.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any, Mapping, Sequence

from sportsedge.nfl_prop_run_it_score_b import PROP_FAMILIES, run_prop_board
from sportsedge.nfl_run_it import normalize_quote
from sportsedge.nfl_run_it_scored import run_it_scored
from sportsedge.nfl_td_run_it_score_b import run_td_board
from sportsedge.sports.nfl.discrete_v2 import load_freeze, means_from_attempt9, score_grid
from sportsedge.sports.nfl.unified_market_engine import (
    TD_PROP_MARKETS,
    run_unified_nfl_model,
    sample_score_paths,
)

SCHEMA = "SPORTSEDGE_NFL_UNIFIED_RUN_IT_V1"


class UnifiedNflRunItError(ValueError):
    pass


def _text(value: Any, field: str) -> str:
    out = str(value or "").strip()
    if not out:
        raise UnifiedNflRunItError(f"{field}:REQUIRED")
    return out


def _player_rows(team_model: Mapping[str, Any] | None) -> list[Mapping[str, Any]]:
    if not isinstance(team_model, Mapping):
        return []
    out: list[Mapping[str, Any]] = []
    qb = team_model.get("qb")
    if isinstance(qb, Mapping):
        out.append(qb)
    skills = team_model.get("skill_players")
    if isinstance(skills, Sequence) and not isinstance(skills, (str, bytes, bytearray)):
        out.extend(row for row in skills if isinstance(row, Mapping))
    return out


def _player_side_index(
    home_model: Mapping[str, Any] | None,
    away_model: Mapping[str, Any] | None,
) -> dict[str, set[str]]:
    index: dict[str, set[str]] = {}
    for side, model in (("home", home_model), ("away", away_model)):
        for row in _player_rows(model):
            name = str(row.get("player") or "").strip()
            if name:
                index.setdefault(name, set()).add(side)
    return index


def _resolve_side(
    quote: Mapping[str, Any],
    *,
    player: str,
    player_sides: Mapping[str, set[str]],
    home_team: str,
    away_team: str,
) -> str:
    hint = str(quote.get("team") or "").strip()
    if hint:
        lowered = hint.lower()
        if lowered in {"home", "away"}:
            return lowered
        if hint.upper() == home_team.upper():
            return "home"
        if hint.upper() == away_team.upper():
            return "away"
        raise UnifiedNflRunItError(f"PROP_TEAM_HINT_INVALID:{player}:{hint}")
    sides = set(player_sides.get(player) or ())
    if len(sides) != 1:
        raise UnifiedNflRunItError(f"PROP_PLAYER_SIDE_AMBIGUOUS:{player}")
    return next(iter(sides))


def _game_requests(
    quotes: Sequence[Mapping[str, Any]],
    *,
    home_team: str,
    away_team: str,
) -> list[dict[str, Any]]:
    unique: dict[tuple[Any, ...], dict[str, Any]] = {}
    for raw in quotes:
        q = normalize_quote(raw)
        if q["home"].upper() != home_team.upper() or q["away"].upper() != away_team.upper():
            raise UnifiedNflRunItError("GAME_QUOTE_TEAM_IDENTITY_MISMATCH")
        market = q["market"]
        if market == "total":
            selection = str(q["selection"]).lower()
        else:
            selection = "home" if str(q["selection"]).upper() == home_team.upper() else "away"
        request = {
            "market": market,
            "selection": selection,
            "line": q["line"],
        }
        key = (market, selection, q["line"])
        unique[key] = request
    return list(unique.values())


def _prop_requests(
    quotes: Sequence[Mapping[str, Any]],
    *,
    player_sides: Mapping[str, set[str]],
    home_team: str,
    away_team: str,
) -> list[dict[str, Any]]:
    unique: dict[tuple[Any, ...], dict[str, Any]] = {}
    for quote in quotes:
        player = _text(quote.get("player"), "prop.player")
        market = _text(quote.get("market"), "prop.market").lower()
        if market not in PROP_FAMILIES:
            raise UnifiedNflRunItError(f"PROP_MARKET_UNSUPPORTED:{market}")
        selection = _text(quote.get("selection"), "prop.selection").lower()
        if selection not in {"over", "under"}:
            raise UnifiedNflRunItError("PROP_SELECTION_INVALID")
        try:
            line = float(quote["line"])
        except (KeyError, TypeError, ValueError) as exc:
            raise UnifiedNflRunItError("PROP_LINE_INVALID") from exc
        side = _resolve_side(
            quote,
            player=player,
            player_sides=player_sides,
            home_team=home_team,
            away_team=away_team,
        )
        key = (side, player, market, selection, line)
        unique[key] = {
            "team": side,
            "player": player,
            "market": market,
            "selection": selection,
            "line": line,
        }
    return list(unique.values())


def _td_requests(
    quotes: Sequence[Mapping[str, Any]],
    *,
    player_sides: Mapping[str, set[str]],
    home_team: str,
    away_team: str,
) -> list[dict[str, Any]]:
    unique: dict[tuple[str, str], dict[str, Any]] = {}
    for quote in quotes:
        player = _text(quote.get("player"), "td.player")
        side = _resolve_side(
            quote,
            player=player,
            player_sides=player_sides,
            home_team=home_team,
            away_team=away_team,
        )
        unique[(side, player)] = {
            "team": side,
            "player": player,
            "market": "anytime_tds",
            "selection": "over",
            "line": 0.5,
        }
    return list(unique.values())


def _game_estimates(
    *,
    game_id: str,
    home_team: str,
    away_team: str,
    rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        if row.get("status") != "PRICED_RESEARCH":
            continue
        p = float(row["estimate_p"])
        if not 0.0 < p < 1.0:
            continue
        market = str(row["market"])
        selection = str(row["selection"])
        if market == "total":
            bound_selection = selection.upper()
        else:
            bound_selection = home_team if selection == "home" else away_team
        out.append({
            "game_id": game_id,
            "home": home_team,
            "away": away_team,
            "market": market,
            "selection": bound_selection,
            "line": row.get("line"),
            "estimate_p": p,
        })
    return out


def _ordinary_prop_estimates(
    *,
    game_id: str,
    rows: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    estimates: list[dict[str, Any]] = []
    blocks: list[dict[str, Any]] = []
    for row in rows:
        market = str(row.get("market") or "")
        if market in TD_PROP_MARKETS and market == "anytime_tds":
            continue
        if row.get("status") != "PRICED_RESEARCH":
            blocks.append(dict(row))
            continue
        p = float(row["estimate_p"])
        push = float(row.get("push_p", 0.0))
        if not 0.0 < p < 1.0 or push < 0.0 or p + push > 1.0:
            blocks.append({**dict(row), "status": "NO_MODEL", "reason": "PROP_ESTIMATE_MASS_INVALID"})
            continue
        estimates.append({
            "game_id": game_id,
            "player": row["player"],
            "market": market,
            "selection": str(row["selection"]).upper(),
            "line": float(row["line"]),
            "estimate_p": p,
            "push_p": push,
        })
    return estimates, blocks


def _td_estimates(
    *,
    game_id: str,
    rows: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    estimates: list[dict[str, Any]] = []
    blocks: list[dict[str, Any]] = []
    for row in rows:
        if str(row.get("market") or "") != "anytime_tds":
            continue
        if row.get("status") != "PRICED_RESEARCH":
            blocks.append(dict(row))
            continue
        p = float(row["estimate_p"])
        if not 0.0 < p < 1.0:
            blocks.append({**dict(row), "status": "NO_MODEL", "reason": "TD_ESTIMATE_MASS_INVALID"})
            continue
        estimates.append({
            "game_id": game_id,
            "player": row["player"],
            "estimate_p": p,
        })
    return estimates, blocks


def run_unified_nfl_run_it(
    *,
    game_id: str,
    home_team: str,
    away_team: str,
    attempt9_margin: float,
    attempt9_total: float,
    game_quotes: Sequence[Mapping[str, Any]],
    prop_quotes: Sequence[Mapping[str, Any]] = (),
    td_quotes: Sequence[Mapping[str, Any]] = (),
    qualification_snapshots: Sequence[Mapping[str, Any]] = (),
    home_model: Mapping[str, Any] | None = None,
    away_model: Mapping[str, Any] | None = None,
    scoring_prior: Any = None,
    as_of: Any,
    edge_floor: float = 0.02,
    executable_book: str = "draftkings",
    n_sims: int = 20000,
    seed: int = 21,
) -> dict[str, Any]:
    """Run model -> existing NFL pricing boards as one operational call."""
    game_id = _text(game_id, "game_id")
    home_team = _text(home_team, "home_team")
    away_team = _text(away_team, "away_team")

    player_sides = _player_side_index(home_model, away_model)
    game_requests = _game_requests(game_quotes, home_team=home_team, away_team=away_team)
    prop_requests = _prop_requests(
        prop_quotes,
        player_sides=player_sides,
        home_team=home_team,
        away_team=away_team,
    )
    td_requests = _td_requests(
        td_quotes,
        player_sides=player_sides,
        home_team=home_team,
        away_team=away_team,
    )

    model = run_unified_nfl_model(
        game_id=game_id,
        home_team=home_team,
        away_team=away_team,
        attempt9_margin=attempt9_margin,
        attempt9_total=attempt9_total,
        game_markets=game_requests,
        prop_markets=[*prop_requests, *td_requests],
        home_model=home_model,
        away_model=away_model,
        scoring_prior=scoring_prior,
        n_sims=n_sims,
        seed=seed,
    )

    # Existing game RUN IT intentionally requires explicit score paths for
    # integer spreads/totals. Re-sample the same frozen grid with the exact same
    # seed so this is the same model distribution, not a second model.
    freeze = load_freeze()
    means = means_from_attempt9(float(attempt9_margin), float(attempt9_total))
    grid = score_grid(means["mean_home"], means["mean_away"], freeze)
    score_paths = sample_score_paths(grid, n_sims=n_sims, seed=seed)

    game_estimates = _game_estimates(
        game_id=game_id,
        home_team=home_team,
        away_team=away_team,
        rows=model["game_markets"],
    )
    game_card = run_it_scored(
        game_quotes,
        game_estimates,
        qualification_snapshots,
        simulations={game_id: score_paths},
        as_of=as_of,
        edge_floor=edge_floor,
    )

    prop_estimates, prop_blocks = _ordinary_prop_estimates(
        game_id=game_id,
        rows=model["prop_markets"],
    )
    prop_board = run_prop_board(
        estimates=prop_estimates,
        quotes=prop_quotes,
        qualification_snapshots=qualification_snapshots,
        as_of=as_of,
        executable_book=executable_book,
    ) if prop_quotes else []

    td_estimates, td_blocks = _td_estimates(
        game_id=game_id,
        rows=model["prop_markets"],
    )
    td_board = run_td_board(
        estimates=td_estimates,
        quotes=td_quotes,
        qualification_snapshots=qualification_snapshots,
        as_of=as_of,
        executable_book=executable_book,
    ) if td_quotes and td_estimates else []

    return {
        "schema": SCHEMA,
        "game_id": game_id,
        "model": model,
        "game_card": game_card.to_dict(),
        "prop_board": [asdict(row) for row in prop_board],
        "td_board": [asdict(row) for row in td_board],
        "model_blocks": [*prop_blocks, *td_blocks],
        "authority": {
            "research_only": True,
            "creates_model_p": False,
            "changes_attempt9_owner": False,
            "truth_gate_authority": False,
            "official_authority": False,
            "promotion_authority": False,
            "staking_authority": False,
        },
    }


__all__ = ["SCHEMA", "UnifiedNflRunItError", "run_unified_nfl_run_it"]
