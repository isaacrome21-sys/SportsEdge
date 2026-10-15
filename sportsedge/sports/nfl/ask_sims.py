"""Research-only NFL score-path queries: count outcomes before evaluating a quote.

Reads *the same* seeded score paths as unified_market_engine. It does not
fit/recalibrate a model, certify quote provenance, bypass admission gates,
promote a family, or create a bet/PLAY. Unsupported language refuses by name.
"""
from __future__ import annotations

from math import isfinite, sqrt
import re
from typing import Any, Mapping, Sequence

SCHEMA = "SPORTSEDGE_NFL_ASK_SCORE_SIMS_RESEARCH_V1"
MAX_PATHS = 100_000
MAX_AND_TERMS = 8
Z95 = 1.959963984540054


class AskSimsError(ValueError):
    """Refusal with a stable name; never answer an unrecognized question."""


def _team(value: Any, home: str, away: str, aliases: Mapping[str, str]) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AskSimsError("ASK_SIMS_TEAM_REQUIRED")
    key = value.strip().casefold()
    candidates = {home.casefold(): "home", away.casefold(): "away"}
    for alias, mapped in aliases.items():
        if not isinstance(alias, str) or not isinstance(mapped, str):
            raise AskSimsError("ASK_SIMS_ALIAS_INVALID")
        if mapped.casefold() not in {home.casefold(), away.casefold()}:
            raise AskSimsError("ASK_SIMS_ALIAS_UNKNOWN_TEAM")
        role = "home" if mapped.casefold() == home.casefold() else "away"
        if alias.casefold() in candidates and candidates[alias.casefold()] != role:
            raise AskSimsError("ASK_SIMS_ALIAS_COLLISION")
        candidates[alias.casefold()] = role
    if key not in candidates:
        raise AskSimsError("ASK_SIMS_TEAM_UNKNOWN")
    return candidates[key]


def parse_question(question: str, *, home_team: str, away_team: str,
                   aliases: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Small, explicit question grammar: unsupported language always refuses.

    Examples: 'Seahawks win by 7+', 'SEA wins', 'total over 45.5',
    'DEN team total under 24.5'. Aliases are supplied by caller.
    """
    if not isinstance(question, str) or not question.strip() or len(question) > 160:
        raise AskSimsError("ASK_SIMS_QUESTION_INVALID")
    value = " ".join(question.strip().split())
    aka = aliases or {}
    win_by = re.fullmatch(r"(.+?)\s+wins?\s+by\s+([1-9]\d{0,2})\+", value, re.I)
    if win_by:
        return {"market": "win_by",
                "team": _team(win_by.group(1), home_team, away_team, aka),
                "points": int(win_by.group(2))}
    win = re.fullmatch(r"(.+?)\s+wins?", value, re.I)
    if win:
        return {"market": "win", "team": _team(win.group(1), home_team, away_team, aka)}
    total = re.fullmatch(r"total\s+(over|under)\s+(\d{1,3}(?:\.\d+)?)", value, re.I)
    if total:
        return {"market": "total_" + total.group(1).lower(),
                "line": float(total.group(2))}
    team_total = re.fullmatch(
        r"(.+?)\s+team\s+total\s+(over|under)\s+(\d{1,3}(?:\.\d+)?)",
        value, re.I,
    )
    if team_total:
        return {"market": "team_total_" + team_total.group(2).lower(),
                "team": _team(team_total.group(1), home_team, away_team, aka),
                "line": float(team_total.group(3))}
    raise AskSimsError("ASK_SIMS_UNSUPPORTED_QUESTION")


def _line(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value) or not 0 <= value <= 255:
        raise AskSimsError("ASK_SIMS_LINE_INVALID")
    return float(value)


def _evaluate(q: Mapping[str, Any], home: int, away: int) -> int:
    """1 win, 0 push, -1 loss; integer-line pushes are retained."""
    if not isinstance(q, Mapping):
        raise AskSimsError("ASK_SIMS_QUERY_INVALID")
    if "all" in q:
        terms = q["all"]
        if not isinstance(terms, (list, tuple)) or not 1 <= len(terms) <= MAX_AND_TERMS:
            raise AskSimsError("ASK_SIMS_AND_TERMS_INVALID")
        outcomes = [_evaluate(term, home, away) for term in terms]
        return -1 if -1 in outcomes else (0 if 0 in outcomes else 1)
    market = q.get("market")
    if market in ("win", "win_by", "team_total_over", "team_total_under"):
        side = q.get("team")
        if side not in ("home", "away"):
            raise AskSimsError("ASK_SIMS_TEAM_SIDE_INVALID")
        score = home if side == "home" else away
        opponent = away if side == "home" else home
        if market == "win":
            # NFL two-way moneyline ties push; a three-way market is not supported.
            return 1 if score > opponent else (0 if score == opponent else -1)
        if market == "win_by":
            points = q.get("points")
            if isinstance(points, bool) or not isinstance(points, int) or not 1 <= points <= 255:
                raise AskSimsError("ASK_SIMS_POINTS_INVALID")
            return 1 if score - opponent >= points else -1
        delta = score - _line(q.get("line"))
        if market.endswith("under"):
            delta = -delta
    elif market in ("total_over", "total_under"):
        delta = home + away - _line(q.get("line"))
        if market.endswith("under"):
            delta = -delta
    else:
        raise AskSimsError("ASK_SIMS_MARKET_UNSUPPORTED")
    return 1 if delta > 0 else (0 if delta == 0 else -1)


def _price(price: Any) -> int:
    if isinstance(price, bool) or not isinstance(price, int) or (-100 < price < 100):
        raise AskSimsError("ASK_SIMS_AMERICAN_PRICE_INVALID")
    if abs(price) > 100000:
        raise AskSimsError("ASK_SIMS_AMERICAN_PRICE_INVALID")
    return price


def _wilson_interval(hits: int, n: int) -> list[float]:
    p = hits / n
    d = 1 + Z95**2 / n
    center = (p + Z95**2 / (2*n)) / d
    half = Z95 * sqrt((p * (1 - p) / n) + Z95**2 / (4*n*n)) / d
    return [max(0.0, center - half), min(1.0, center + half)]


def ask_score_paths(
    score_paths: Sequence[Mapping[str, Any]], question: str | Mapping[str, Any], *,
    home_team: str, away_team: str, aliases: Mapping[str, str] | None = None,
    price_american: int | None = None,
) -> dict[str, Any]:
    """Empirical outcomes from caller-supplied paths and optional UNVERIFIED quote."""
    if not home_team or not away_team or home_team.casefold() == away_team.casefold():
        raise AskSimsError("ASK_SIMS_GAME_IDENTITY_INVALID")
    if isinstance(question, str):
        query = parse_question(question, home_team=home_team, away_team=away_team, aliases=aliases)
    elif isinstance(question, Mapping):
        query = dict(question)
    else:
        raise AskSimsError("ASK_SIMS_QUERY_INVALID")
    if not isinstance(score_paths, (list, tuple)) or not 1 <= len(score_paths) <= MAX_PATHS:
        raise AskSimsError("ASK_SIMS_PATH_COUNT_INVALID")
    wins = pushes = 0
    for path in score_paths:
        if not isinstance(path, Mapping):
            raise AskSimsError("ASK_SIMS_PATH_INVALID")
        h, a = path.get("home_score"), path.get("away_score")
        if any(isinstance(x, bool) or not isinstance(x, int) or not 0 <= x <= 255 for x in (h, a)):
            raise AskSimsError("ASK_SIMS_SCORE_INVALID")
        result = _evaluate(query, h, a)
        wins += result == 1
        pushes += result == 0
    n = len(score_paths)
    losses = n - wins - pushes
    conditional = wins / (n - pushes) if n != pushes else None
    out = {
        "schema": SCHEMA, "query": query, "home_team": home_team, "away_team": away_team,
        "sample_count": n, "win_count": wins, "push_count": pushes, "loss_count": losses,
        "sample_win_probability": wins / n, "sample_conditional_win_probability": conditional,
        "sample_wilson_95_interval": _wilson_interval(wins, n),
        "sampling_interval_not_model_uncertainty": True,
        "quote_status": "NOT_PROVIDED", "price_american": None,
        "estimated_roi_per_dollar": None, "raw_implied_probability": None,
        "source_status": "SUPPLIED_PATHS_UNVERIFIED",
        "status": "RESEARCH_ONLY_NOT_VALIDATED",
        "eligible_as_bet": False, "official_authority": False,
        "staking_authority": False, "picks": [],
    }
    if price_american is not None:
        p = _price(price_american)
        profit_per_dollar = p / 100 if p > 0 else 100 / -p
        out.update({
            "price_american": p,
            "quote_status": "USER_SUPPLIED_UNVERIFIED",
            "raw_implied_probability": 1 / (1 + profit_per_dollar),
            "estimated_roi_per_dollar": (wins * profit_per_dollar - losses) / n,
        })
    return out


def ask_unified_score_sims(
    engine: Mapping[str, Any], question: str | Mapping[str, Any], *,
    home_team: str, away_team: str, aliases: Mapping[str, str] | None = None,
    price_american: int | None = None,
) -> dict[str, Any]:
    """Replay exact seeded score grid from unified engine research metadata.

    This verifies grid *identity*, not fitted model performance or provenance.
    """
    from sportsedge.sports.nfl.discrete_v2 import load_freeze, score_grid
    from sportsedge.sports.nfl.unified_market_engine import sample_score_paths

    if not isinstance(engine, Mapping) or engine.get("schema") not in (
        "SPORTSEDGE_NFL_UNIFIED_RESEARCH_MARKET_ENGINE_V1",
        "SPORTSEDGE_NFL_UNIFIED_RESIDUAL_RESEARCH_V1",
    ):
        raise AskSimsError("ASK_SIMS_ENGINE_IDENTITY_INVALID")
    freeze = load_freeze()
    dist = engine.get("score_distribution")
    if not isinstance(dist, Mapping) or dist.get("family") != freeze["family"] or (
        dist.get("freeze_sha256") != freeze["artifact_sha256"]
    ):
        raise AskSimsError("ASK_SIMS_FROZEN_GRID_MISMATCH")
    n_sims, seed = dist.get("sampled_paths"), dist.get("seed")
    if (isinstance(n_sims, bool) or not isinstance(n_sims, int) or
        not 1 <= n_sims <= MAX_PATHS or isinstance(seed, bool) or not isinstance(seed, int)):
        raise AskSimsError("ASK_SIMS_REPLAY_PARAMETERS_INVALID")
    means = engine.get("score_means")
    if not isinstance(means, Mapping):
        raise AskSimsError("ASK_SIMS_MEANS_INVALID")
    h, a = means.get("mean_home"), means.get("mean_away")
    if any(isinstance(x, bool) or not isinstance(x, (int, float)) or
           not isfinite(x) or not 0.5 <= x <= 70 for x in (h, a)):
        raise AskSimsError("ASK_SIMS_MEANS_INVALID")
    for key, supplied in (("home_team", home_team), ("away_team", away_team)):
        if engine.get(key) is not None and engine[key].casefold() != supplied.casefold():
            raise AskSimsError("ASK_SIMS_GAME_IDENTITY_MISMATCH")
    paths = sample_score_paths(score_grid(float(h), float(a), freeze), n_sims=n_sims, seed=seed)
    result = ask_score_paths(paths, question, home_team=home_team, away_team=away_team,
                             aliases=aliases, price_american=price_american)
    result.update({
        "source_status": "FROZEN_GRID_SEEDED_REPLAY_RESEARCH_ONLY",
        "freeze_sha256": freeze["artifact_sha256"], "replayed_seed": seed,
    })
    return result
