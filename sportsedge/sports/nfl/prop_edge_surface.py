"""NFL prop presentation and research analytics over governed SportsEdge outputs.

This module intentionally sits *after* the football prop run machines.  It does
not create model probabilities, mutate the shared Engine A/B/C path, devig
prices, or promote a bet.  It only turns already-produced model/market rows
into a richer board with model fair prices, book prices, edge/EV, a transparent
SportsEdge research score, filters, and research-only what-if projections.

External market/sharp context can be attached for display, but is explicitly
excluded from scoring and has no promotion authority.
"""

from __future__ import annotations

from math import isfinite
from statistics import mean
from typing import Any, Iterable, Mapping, Sequence


NFL_PROPS_EDGE_SCHEMA = "NFL_PROPS_EDGE_V1"
SUPPORTED_VIEWS = frozenset(
    {"all_priced", "featured", "research_featured", "all_projections"}
)
SUPPORTED_SORTS = frozenset({"score", "model_probability", "edge", "ev"})
_EPSILON = 1e-9


class NFLPropsEdgeError(ValueError):
    """Raised when an input row would make the presentation surface misleading."""


def _finite(value: Any, error: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise NFLPropsEdgeError(error) from exc
    if not isfinite(out):
        raise NFLPropsEdgeError(error)
    return out


def _optional_probability(value: Any, error: str) -> float | None:
    if value is None:
        return None
    out = _finite(value, error)
    if not 0.0 <= out <= 1.0:
        raise NFLPropsEdgeError(error)
    return out


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def american_implied_probability(american_odds: float | int) -> float:
    """Return the break-even probability for valid American odds."""
    odds = _finite(american_odds, "NFL_PROP_AMERICAN_ODDS_INVALID")
    if abs(odds) < 100.0:
        raise NFLPropsEdgeError("NFL_PROP_AMERICAN_ODDS_INVALID")
    if odds < 0:
        return (-odds) / ((-odds) + 100.0)
    return 100.0 / (odds + 100.0)


def probability_to_american(probability: float) -> int:
    """Convert a no-push probability to a rounded American fair price."""
    p = _finite(probability, "NFL_PROP_PROBABILITY_INVALID")
    if not 0.0 < p < 1.0:
        raise NFLPropsEdgeError("NFL_PROP_PROBABILITY_INVALID")
    if p >= 0.5:
        return int(round(-100.0 * p / (1.0 - p)))
    return int(round(100.0 * (1.0 - p) / p))


def settled_model_probability(model_p: float, push_p: float = 0.0) -> float:
    """Condition the model win probability on non-push outcomes."""
    win = _finite(model_p, "NFL_PROP_MODEL_P_INVALID")
    push = _finite(push_p, "NFL_PROP_PUSH_P_INVALID")
    if not 0.0 <= win <= 1.0 or not 0.0 <= push <= 1.0:
        raise NFLPropsEdgeError("NFL_PROP_PROBABILITY_MASS_INVALID")
    if win + push > 1.0 + _EPSILON:
        raise NFLPropsEdgeError("NFL_PROP_PROBABILITY_MASS_INVALID")
    settled = 1.0 - push
    if settled <= _EPSILON:
        raise NFLPropsEdgeError("NFL_PROP_SETTLED_SAMPLE_SPACE_EMPTY")
    return _clamp(win / settled)


def _optional_quality(row: Mapping[str, Any], key: str) -> float:
    value = row.get(key)
    if value is None:
        return 0.5
    out = _finite(value, f"NFL_PROP_{key.upper()}_INVALID")
    return _clamp(out)


def compute_prop_score(
    *,
    model_probability: float,
    edge: float | None,
    ev_per_dollar: float | None,
    quote_fresh: bool,
    role_certainty: float = 0.5,
    data_quality: float = 0.5,
) -> float:
    """Return a transparent 0-100 research-ranking score.

    The score is intentionally SportsEdge-owned rather than an attempt to
    reverse-engineer another product's proprietary ranking.  It is monotone in
    edge and EV within the capped ranges and does not consume sharp-money,
    capper, ticket, or handle context.
    """
    p = _optional_probability(model_probability, "NFL_PROP_MODEL_PROBABILITY_INVALID")
    assert p is not None

    conviction = abs(p - 0.5) * 2.0
    if edge is None:
        edge_component = 0.0
    else:
        edge_value = _finite(edge, "NFL_PROP_EDGE_INVALID")
        # -5% maps to 0; +15% maps to 1.  Values outside that range are capped.
        edge_component = _clamp((edge_value + 0.05) / 0.20)

    if ev_per_dollar is None:
        ev_component = 0.0
    else:
        ev_value = _finite(ev_per_dollar, "NFL_PROP_EV_INVALID")
        # -5% maps to 0; +25% maps to 1.
        ev_component = _clamp((ev_value + 0.05) / 0.30)

    role = _clamp(_finite(role_certainty, "NFL_PROP_ROLE_CERTAINTY_INVALID"))
    quality = _clamp(_finite(data_quality, "NFL_PROP_DATA_QUALITY_INVALID"))
    freshness = 1.0 if bool(quote_fresh) else 0.0

    score = 100.0 * (
        0.35 * edge_component
        + 0.25 * ev_component
        + 0.15 * conviction
        + 0.10 * role
        + 0.10 * quality
        + 0.05 * freshness
    )
    return round(_clamp(score / 100.0) * 100.0, 1)


def grade_score(score: float) -> str:
    value = _finite(score, "NFL_PROP_SCORE_INVALID")
    if value >= 90:
        return "A+"
    if value >= 82:
        return "A"
    if value >= 74:
        return "B+"
    if value >= 66:
        return "B"
    if value >= 58:
        return "C+"
    if value >= 50:
        return "C"
    return "D"


def prop_row_key(row: Mapping[str, Any]) -> str:
    """Build a stable display/context key without granting evidence authority."""
    parts = (
        row.get("game_id"),
        row.get("provider_market") or row.get("market"),
        row.get("player_id") or row.get("player_name"),
        row.get("side"),
        row.get("line"),
        row.get("bookmaker") or row.get("sportsbook"),
    )
    return "|".join("" if value is None else str(value).strip() for value in parts)


def _projection_value(row: Mapping[str, Any]) -> float | None:
    for key in ("projection", "projected_mean", "model_projection", "mean_projection"):
        if row.get(key) is not None:
            return _finite(row[key], f"NFL_PROP_{key.upper()}_INVALID")
    return None


def _row_teams(row: Mapping[str, Any]) -> set[str]:
    values: set[str] = set()
    for key in ("team", "team_abbr", "home_team", "away_team"):
        raw = str(row.get(key) or "").strip().upper()
        if raw:
            values.add(raw)
    return values


def _normalize_sharp_context(context: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if context is None:
        return None
    if not isinstance(context, Mapping):
        raise NFLPropsEdgeError("NFL_PROP_SHARP_CONTEXT_INVALID")
    normalized = dict(context)
    normalized["promotion_authority"] = False
    normalized["used_in_model_probability"] = False
    normalized["used_in_score"] = False
    return normalized


def enrich_prop_row(
    row: Mapping[str, Any],
    *,
    sharp_context: Mapping[str, Any] | None = None,
    verify_edge: bool = True,
) -> dict[str, Any]:
    """Add MySpariEdge-like board fields without changing governing economics."""
    if not isinstance(row, Mapping):
        raise NFLPropsEdgeError("NFL_PROP_ROW_REQUIRED")
    sport = str(row.get("sport") or "NFL").strip().upper()
    if sport != "NFL":
        raise NFLPropsEdgeError(f"NFL_PROP_SPORT_MISMATCH:{sport}")

    model_p = _optional_probability(row.get("model_p"), "NFL_PROP_MODEL_P_INVALID")
    push_p = _optional_probability(row.get("push_p", 0.0), "NFL_PROP_PUSH_P_INVALID")
    settled_p: float | None = None
    fair_american: int | None = None
    if model_p is not None:
        settled_p = settled_model_probability(model_p, 0.0 if push_p is None else push_p)
        if 0.0 < settled_p < 1.0:
            fair_american = probability_to_american(settled_p)

    odds_value = row.get("american_odds")
    book_odds: float | None = None
    book_implied: float | None = None
    if odds_value is not None:
        book_odds = _finite(odds_value, "NFL_PROP_AMERICAN_ODDS_INVALID")
        book_implied = american_implied_probability(book_odds)

    market_fair = _optional_probability(
        row.get("fair_market_p"), "NFL_PROP_FAIR_MARKET_P_INVALID"
    )
    edge_value = row.get("edge")
    edge: float | None = None
    if edge_value is not None:
        edge = _finite(edge_value, "NFL_PROP_EDGE_INVALID")
    if (
        verify_edge
        and settled_p is not None
        and market_fair is not None
        and edge is not None
        and abs(edge - (settled_p - market_fair)) > 1e-7
    ):
        raise NFLPropsEdgeError("NFL_PROP_EDGE_INTEGRITY_MISMATCH")

    ev_value = row.get("ev_per_dollar")
    ev: float | None = None
    if ev_value is not None:
        ev = _finite(ev_value, "NFL_PROP_EV_INVALID")

    quote_fresh = bool(row.get("quote_fresh", True))
    has_offer = book_odds is not None and settled_p is not None
    economics_available = edge is not None or ev is not None
    if has_offer and quote_fresh and economics_available:
        price_state = "PRICED"
    elif has_offer and not quote_fresh:
        price_state = "STALE"
    elif settled_p is not None:
        price_state = "MODEL_ONLY"
    else:
        price_state = "NO_MODEL_P"

    projection = _projection_value(row)
    line_value = row.get("line")
    line: float | None = None
    if line_value is not None:
        line = _finite(line_value, "NFL_PROP_LINE_INVALID")
    projection_diff = (
        None if projection is None or line is None else round(projection - line, 4)
    )

    role_certainty = _optional_quality(row, "role_certainty")
    data_quality = _optional_quality(row, "data_quality")
    score = (
        None
        if settled_p is None
        else compute_prop_score(
            model_probability=settled_p,
            edge=edge,
            ev_per_dollar=ev,
            quote_fresh=quote_fresh,
            role_certainty=role_certainty,
            data_quality=data_quality,
        )
    )

    out = dict(row)
    out.update(
        {
            "schema_version": NFL_PROPS_EDGE_SCHEMA,
            "row_key": prop_row_key(row),
            "model_probability": settled_p,
            "model_probability_pct": None
            if settled_p is None
            else round(settled_p * 100.0, 1),
            "model_fair_american": fair_american,
            "book_american": book_odds,
            "book_implied_probability": book_implied,
            "market_fair_probability": market_fair,
            "edge_pct": None if edge is None else round(edge * 100.0, 1),
            "ev_pct": None if ev is None else round(ev * 100.0, 1),
            "price_state": price_state,
            "projection": projection,
            "projection_diff": projection_diff,
            "score": score,
            "grade": None if score is None else grade_score(score),
            "sharp_context": _normalize_sharp_context(sharp_context),
        }
    )
    return out


def _view_match(
    row: Mapping[str, Any],
    *,
    view: str,
    min_score: float,
    min_edge: float,
    min_ev: float,
) -> bool:
    if view == "all_projections":
        return row.get("model_probability") is not None
    if row.get("price_state") != "PRICED":
        return False
    if view == "all_priced":
        return True

    score = row.get("score")
    if score is None or float(score) < min_score:
        return False
    edge = row.get("edge")
    ev = row.get("ev_per_dollar")
    economic_threshold_pass = (
        (edge is not None and float(edge) >= min_edge)
        or (edge is None and ev is not None and float(ev) >= min_ev)
    )
    if not economic_threshold_pass:
        return False

    if view == "featured":
        return bool(row.get("official_eligible"))
    if view == "research_featured":
        return True
    raise NFLPropsEdgeError(f"NFL_PROP_VIEW_UNSUPPORTED:{view}")


def _sort_value(row: Mapping[str, Any], sort_by: str) -> tuple[float, str]:
    if sort_by == "score":
        value = row.get("score")
    elif sort_by == "model_probability":
        value = row.get("model_probability")
    elif sort_by == "edge":
        value = row.get("edge")
    elif sort_by == "ev":
        value = row.get("ev_per_dollar")
    else:
        raise NFLPropsEdgeError(f"NFL_PROP_SORT_UNSUPPORTED:{sort_by}")
    numeric = float(value) if value is not None else float("-inf")
    name = str(row.get("player_name") or row.get("player_id") or "")
    return numeric, name


def _matches_market(row: Mapping[str, Any], market: str | None) -> bool:
    if market is None:
        return True
    target = str(market).strip().lower()
    choices = {
        str(row.get("provider_market") or "").strip().lower(),
        str(row.get("market") or "").strip().lower(),
        str(row.get("stat") or "").strip().lower(),
    }
    return target in choices


def build_props_edge_board(
    run_payload: Mapping[str, Any] | Sequence[Mapping[str, Any]],
    *,
    view: str = "all_priced",
    market: str | None = None,
    teams: Iterable[str] | None = None,
    sort_by: str = "score",
    limit: int | None = None,
    featured_min_score: float = 0.0,
    featured_min_edge: float = 0.0,
    featured_min_ev: float = 0.0,
    research_min_score: float = 0.0,
    research_min_edge: float = 0.0,
    research_min_ev: float = 0.0,
    sharp_context_by_key: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build an NFL props-edge board from a governed run payload."""
    normalized_view = str(view).strip().lower()
    if normalized_view not in SUPPORTED_VIEWS:
        raise NFLPropsEdgeError(f"NFL_PROP_VIEW_UNSUPPORTED:{view}")
    normalized_sort = str(sort_by).strip().lower()
    if normalized_sort not in SUPPORTED_SORTS:
        raise NFLPropsEdgeError(f"NFL_PROP_SORT_UNSUPPORTED:{sort_by}")

    if isinstance(run_payload, Mapping):
        sport = str(run_payload.get("sport") or "NFL").strip().upper()
        if sport != "NFL":
            raise NFLPropsEdgeError(f"NFL_PROP_SPORT_MISMATCH:{sport}")
        raw_rows = run_payload.get("results")
        if raw_rows is None:
            raise NFLPropsEdgeError("NFL_PROP_RESULTS_REQUIRED")
    else:
        raw_rows = run_payload

    if isinstance(raw_rows, (str, bytes)) or not isinstance(raw_rows, Sequence):
        raise NFLPropsEdgeError("NFL_PROP_RESULTS_REQUIRED")

    team_filter = {
        str(team).strip().upper()
        for team in (teams or ())
        if str(team).strip()
    }
    context_map = sharp_context_by_key or {}
    candidates: list[dict[str, Any]] = []
    for raw in raw_rows:
        if not isinstance(raw, Mapping):
            raise NFLPropsEdgeError("NFL_PROP_ROW_REQUIRED")
        if not _matches_market(raw, market):
            continue
        if team_filter and not (_row_teams(raw) & team_filter):
            continue
        key = prop_row_key(raw)
        candidates.append(
            enrich_prop_row(raw, sharp_context=context_map.get(key))
        )

    model_rows = [row for row in candidates if row.get("model_probability") is not None]
    priced_rows = [row for row in candidates if row.get("price_state") == "PRICED"]
    official_featured = [
        row
        for row in candidates
        if _view_match(
            row,
            view="featured",
            min_score=_finite(featured_min_score, "NFL_PROP_FEATURED_SCORE_INVALID"),
            min_edge=_finite(featured_min_edge, "NFL_PROP_FEATURED_EDGE_INVALID"),
            min_ev=_finite(featured_min_ev, "NFL_PROP_FEATURED_EV_INVALID"),
        )
    ]
    research_featured = [
        row
        for row in candidates
        if _view_match(
            row,
            view="research_featured",
            min_score=_finite(research_min_score, "NFL_PROP_RESEARCH_SCORE_INVALID"),
            min_edge=_finite(research_min_edge, "NFL_PROP_RESEARCH_EDGE_INVALID"),
            min_ev=_finite(research_min_ev, "NFL_PROP_RESEARCH_EV_INVALID"),
        )
    ]

    min_score = featured_min_score if normalized_view == "featured" else research_min_score
    min_edge = featured_min_edge if normalized_view == "featured" else research_min_edge
    min_ev = featured_min_ev if normalized_view == "featured" else research_min_ev
    selected = [
        row
        for row in candidates
        if _view_match(
            row,
            view=normalized_view,
            min_score=_finite(min_score, "NFL_PROP_SCORE_THRESHOLD_INVALID"),
            min_edge=_finite(min_edge, "NFL_PROP_EDGE_THRESHOLD_INVALID"),
            min_ev=_finite(min_ev, "NFL_PROP_EV_THRESHOLD_INVALID"),
        )
    ]
    selected.sort(key=lambda row: _sort_value(row, normalized_sort), reverse=True)
    if limit is not None:
        if isinstance(limit, bool) or int(limit) < 0:
            raise NFLPropsEdgeError("NFL_PROP_LIMIT_INVALID")
        selected = selected[: int(limit)]

    model_probabilities = [
        float(row["model_probability"])
        for row in model_rows
        if row.get("model_probability") is not None
    ]
    edges = [
        float(row["edge"])
        for row in priced_rows
        if row.get("edge") is not None
    ]
    return {
        "schema_version": NFL_PROPS_EDGE_SCHEMA,
        "sport": "NFL",
        "view": normalized_view,
        "sort_by": normalized_sort,
        "market": market,
        "rows": selected,
        "summary": {
            "candidate_rows": len(candidates),
            "projection_rows": len(model_rows),
            "priced_rows": len(priced_rows),
            "featured_rows": len(official_featured),
            "research_featured_rows": len(research_featured),
            "top_model_probability": max(model_probabilities)
            if model_probabilities
            else None,
            "average_model_probability": mean(model_probabilities)
            if model_probabilities
            else None,
            "best_edge": max(edges) if edges else None,
        },
        "governance": {
            "model_market_firewall_preserved": True,
            "presentation_can_create_model_p": False,
            "presentation_can_devig_market": False,
            "sharp_context_promotion_authority": False,
            "sharp_context_used_in_score": False,
            "featured_requires_official_eligibility": True,
            "research_featured_is_official": False,
            "role_scenarios_are_official": False,
        },
    }


def top_prop_picks(
    run_payload: Mapping[str, Any] | Sequence[Mapping[str, Any]],
    *,
    research_only: bool = False,
    limit: int = 10,
    **board_kwargs: Any,
) -> dict[str, Any]:
    """Return a compact top-picks view.

    Governed/official eligibility is the default.  Research-only must be
    requested explicitly and never changes eligibility in the underlying rows.
    """
    view = "research_featured" if research_only else "featured"
    board = build_props_edge_board(
        run_payload,
        view=view,
        sort_by="score",
        limit=limit,
        **board_kwargs,
    )
    board["top_picks_mode"] = "RESEARCH_ONLY" if research_only else "GOVERNED_OFFICIAL"
    return board


def apply_role_scenario(
    row: Mapping[str, Any],
    *,
    role_name: str,
    baseline_role_value: float,
    scenario_role_value: float,
    min_multiplier: float = 0.5,
    max_multiplier: float = 1.75,
) -> dict[str, Any]:
    """Scale a projection for a What-If role scenario.

    This deliberately suppresses model probability, price, edge, EV and score:
    changing targets/carries/pass attempts without rerunning the full path model
    is a research projection, not a new Model_P.
    """
    if not isinstance(row, Mapping):
        raise NFLPropsEdgeError("NFL_PROP_ROW_REQUIRED")
    projection = _projection_value(row)
    if projection is None:
        raise NFLPropsEdgeError("NFL_PROP_SCENARIO_PROJECTION_REQUIRED")
    baseline = _finite(baseline_role_value, "NFL_PROP_SCENARIO_BASELINE_ROLE_INVALID")
    scenario = _finite(scenario_role_value, "NFL_PROP_SCENARIO_ROLE_INVALID")
    low = _finite(min_multiplier, "NFL_PROP_SCENARIO_MIN_MULTIPLIER_INVALID")
    high = _finite(max_multiplier, "NFL_PROP_SCENARIO_MAX_MULTIPLIER_INVALID")
    if baseline <= 0.0 or scenario < 0.0 or low <= 0.0 or high < low:
        raise NFLPropsEdgeError("NFL_PROP_SCENARIO_BOUNDS_INVALID")

    multiplier = _clamp(scenario / baseline, low, high)
    projected = projection * multiplier
    line = row.get("line")
    line_value = None if line is None else _finite(line, "NFL_PROP_LINE_INVALID")

    out = dict(row)
    out.update(
        {
            "projection": round(projected, 4),
            "projection_diff": None
            if line_value is None
            else round(projected - line_value, 4),
            "scenario": {
                "role_name": str(role_name).strip(),
                "baseline_role_value": baseline,
                "scenario_role_value": scenario,
                "multiplier": round(multiplier, 6),
                "research_only": True,
                "promotion_authority": False,
            },
            "model_p": None,
            "push_p": None,
            "model_probability": None,
            "model_probability_pct": None,
            "model_fair_american": None,
            "fair_market_p": None,
            "market_fair_probability": None,
            "edge": None,
            "edge_pct": None,
            "ev_per_dollar": None,
            "ev_pct": None,
            "kelly_fraction": None,
            "score": None,
            "grade": None,
            "official_eligible": False,
            "bet_status": "RESEARCH_SCENARIO",
            "reason": "NFL_PROP_SCENARIO_REQUIRES_FULL_MODEL_RERUN_FOR_MODEL_P",
        }
    )
    return out
