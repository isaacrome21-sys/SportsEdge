"""MySpariEdge-style presentation of SportsEdge's own MLB model output.

Input: the payload written by ``scripts/run_manual_mlb_snapshot.py`` — i.e. rows
priced by the SportsEdge engines (shared game / F5 / hitter / pitcher joint
engines via ``engine_registry``). This module never computes a probability of its
own: it reads the engine's ``model_p`` (kept as MODEL_CANDIDATE while deployment
is ineligible), pairs each row with its opposite side, and ranks through
``score_mlb_edge`` + ``build_mlb_scored_card``.

Labeled estimate_p for presentation. The Truth Gate / OFFICIAL path is untouched.
"""
from __future__ import annotations

from math import isfinite
from typing import Any, Mapping, Sequence

from .mlb_empirical_support import empirical_guard_reason
from .mlb_edge_score import ev_per_dollar, score_mlb_edge
from .mlb_scored_card import build_mlb_scored_card

MYSPARI_OWN_MODEL_VERSION = "MLB_MYSPARI_OWN_MODEL_V1"
LABEL = "SportsEdge engine model_p shown MySpariEdge-style · NOT Truth Gate · NOT OFFICIAL"
MANUAL_QUOTE_TTL_SECONDS = 6 * 3600.0
# Favorites priced beyond this are never shown as ACTIONABLE (Isaac's -165 ceiling).
MAX_FAVORITE_ODDS = -165
PRICE_CEILING_REASON = "PRICE_BEYOND_MAX_FAVORITE_-165"
_LINE_NEGATED = frozenset({"RUN_LINE", "F5_RUN_LINE"})
_OPPOSITE = {"AWAY": "HOME", "HOME": "AWAY", "OVER": "UNDER", "UNDER": "OVER", "YES": "NO", "NO": "YES"}


def _f(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if isfinite(out) else None


def _opposite(row: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    want_side = _OPPOSITE.get(str(row.get("side", "")).upper())
    line = _f(row.get("line"))
    want_line = -line if (line is not None and row.get("market") in _LINE_NEGATED) else line
    for other in rows:
        if other is row:
            continue
        if (str(other.get("game_id")), str(other.get("market")), str(other.get("entity_id"))) != (
            str(row.get("game_id")), str(row.get("market")), str(row.get("entity_id"))
        ):
            continue
        if str(other.get("side", "")).upper() != want_side:
            continue
        other_line = _f(other.get("line"))
        if (want_line is None) != (other_line is None):
            continue
        if want_line is not None and abs(other_line - want_line) > 1e-9:
            continue
        return other
    return None


def _conditional_and_push(row: Mapping[str, Any]) -> tuple[float | None, float]:
    """Recover the engine's non-push probability and push mass from the card row.

    The pipeline reports ``edge = model_p/(1-push) - no_vig_p`` and ``implied_probability``
    = no-vig p, so the conditional probability is their sum when both exist.
    """
    p = _f(row.get("model_p"))
    if p is None:
        return None, 0.0
    fair = _f(row.get("implied_probability"))
    edge = _f(row.get("edge"))
    if fair is not None and edge is not None:
        cond = fair + edge
        if 0.0 < cond < 1.0 and cond >= p - 1e-9:
            return cond, max(0.0, 1.0 - p / cond)
    return p, 0.0


def myspari_rows(payload: Mapping[str, Any], *, quote_age_seconds: float = 0.0,
                 quote_ttl_seconds: float = MANUAL_QUOTE_TTL_SECONDS,
                 reliability: float = 0.6, names: Mapping[str, str] | None = None,
                 team_sides: Mapping[str, str] | None = None) -> list[dict[str, Any]]:
    results = [r for r in (payload.get("results") or []) if isinstance(r, Mapping)]
    out: list[dict[str, Any]] = []
    for row in results:
        opposite = _opposite(row, results)
        cond, push = _conditional_and_push(row)
        odds = row.get("american_odds")
        guard_reason = empirical_guard_reason(row, cond)
        raw_paths = row.get("mc_paths", 0)
        n_paths = raw_paths if isinstance(raw_paths, int) and not isinstance(raw_paths, bool) and raw_paths >= 0 else 0
        entity_id = str(row.get("entity_id"))
        team_side = str((team_sides or {}).get(entity_id, "")).upper() or None
        base = {
            "game_id": row.get("game_id"), "market": row.get("market"), "entity_id": row.get("entity_id"),
            "entity_name": (names or {}).get(entity_id, ""), "team_side": team_side,
            "line": row.get("line"), "side": row.get("side"), "american_odds": odds,
            "engine_status": row.get("bet_status"), "engine_reason": row.get("reason"),
            "engine_version": row.get("engine_version"), "mc_paths": n_paths,
            "model_p_raw": row.get("model_p"), "push_p": push, "label": LABEL,
            "empirical_evidence": row.get("empirical_evidence"),
            "presentation_reason": guard_reason,
            "presentation_priced": cond is not None and guard_reason is None,
        }
        if cond is None or guard_reason:
            scored = score_mlb_edge(model_available=False, american_odds=odds)
        else:
            scored = score_mlb_edge(
                estimate_p=min(max(cond, 1e-6), 1 - 1e-6), american_odds=odds,
                opposite_odds=None if opposite is None else opposite.get("american_odds"),
                quote_age_seconds=quote_age_seconds, quote_ttl_seconds=quote_ttl_seconds,
                reliability=reliability, n_paths=n_paths, push_p=push,
            )
        scored_row = {k: getattr(scored, k) for k in scored.__dataclass_fields__}
        if guard_reason:
            scored_row["reason_codes"] = (guard_reason.split(":", 1)[0],)
        if push > 0 and scored_row.get("ev_per_dollar") is not None and row.get("model_p") is not None:
            scored_row["ev_per_dollar"] = ev_per_dollar(float(row["model_p"]), odds, push_p=push)
        price = _f(odds)
        if scored_row.get("status") == "ACTIONABLE" and price is not None and price < MAX_FAVORITE_ODDS:
            scored_row["status"] = "PASS"
            scored_row["presentation_reason_codes"] = (PRICE_CEILING_REASON,)
        out.append({**scored_row, **base})

    # Apply card-level eligibility (including the 2% model-return floor) before
    # same-game conflict selection so a row that cannot make the card cannot
    # suppress a row that can.
    scored = build_mlb_scored_card(out)
    return build_mlb_scored_card(apply_same_game_guard(scored))


# --- Same-game guard --------------------------------------------------------
# Presentation-only: never changes a probability. It blocks exact contract
# contradictions, duplicate team-outcome exposure, and a deliberately narrow
# one-team scoring conflict. The old global high-runs/low-runs narrative is not
# used: game totals and strikeout props, for example, may coexist.
SCRIPT_CONFLICT_REASON = "SAME_GAME_DIRECT_CONFLICT"
SAME_SIDE_STACK_REASON = "SAME_SIDE_STACK"
OPPOSITE_TEAM_OUTCOME_REASON = "OPPOSITE_TEAM_OUTCOME_CONFLICT"
TEAM_SCORING_CONFLICT_REASON = "SAME_TEAM_SCORING_CONFLICT"
_HIGH_RUNS_OVER = frozenset({
    "TOTALS", "TEAM_TOTALS", "F5_TOTALS", "F5_TEAM_TOTALS",
    "PITCHER_HITS_ALLOWED", "PITCHER_ER", "PITCHER_BB", "PITCHER_HITS_WALKS_ER",
    "EITHER_PITCHER_HITS_ALLOWED", "EITHER_PITCHER_ER", "EITHER_PITCHER_BB",
    "HITS", "TOTAL_BASES", "RBI", "RUNS", "HOME_RUNS", "HITS_RUNS_RBIS", "RUNS_RBIS",
    "EXTRA_BASE_HITS", "SINGLES", "DOUBLES",
})
_LOW_RUNS_OVER = frozenset({"PITCHER_OUTS", "PITCHER_K"})
_TEAM_OUTCOME_MARKETS = frozenset({"MONEYLINE", "RUN_LINE", "F5_MONEYLINE", "F5_RUN_LINE", "PITCHER_RECORD_WIN"})
_TEAM_SCORING_MARKETS = frozenset({"TEAM_TOTALS", "F5_TEAM_TOTALS"})
_PITCHER_RUN_ALLOWANCE_MARKETS = frozenset({"PITCHER_HITS_ALLOWED", "PITCHER_ER", "PITCHER_BB", "PITCHER_HITS_WALKS_ER"})
_PITCHER_RUN_SUPPRESSION_MARKETS = frozenset({"PITCHER_OUTS"})


def run_script_direction(row: Mapping[str, Any]) -> int:
    """Diagnostic only: +1 run-seeking, -1 run-suppressing, 0 neutral.

    This label is intentionally not used as a global card rule. It remains for
    diagnostics/backward compatibility; the active scoring rule below is team-
    bound and excludes strikeouts and game totals.
    """
    market = str(row.get("market") or "").upper()
    side = str(row.get("side") or "").upper()
    if market in {"NRFI", "YRFI"}:
        yes = side in {"YES", "", market}
        return (1 if yes else -1) * (1 if market == "YRFI" else -1)
    if side not in {"OVER", "UNDER"}:
        return 0
    sign = 1 if side == "OVER" else -1
    if market in _HIGH_RUNS_OVER:
        return sign
    if market in _LOW_RUNS_OVER:
        return -sign
    return 0


def _ev(row: Mapping[str, Any]) -> float:
    ev = _f(row.get("ev_per_dollar"))
    return -1e9 if ev is None else ev


def _is_actionable(row: Mapping[str, Any]) -> bool:
    return str(row.get("scored_status") or row.get("status") or "").upper() == "ACTIONABLE"


def _team_outcome_side(row: Mapping[str, Any]) -> str | None:
    """Return AWAY/HOME for team-outcome exposure, or None when it cannot be bound safely."""
    market = str(row.get("market") or "").upper()
    if market not in _TEAM_OUTCOME_MARKETS:
        return None
    side = str(row.get("side") or "").upper()
    if market == "PITCHER_RECORD_WIN":
        if side != "YES":
            return None
        team_side = str(row.get("team_side") or "").upper()
        return team_side if team_side in {"AWAY", "HOME"} else None
    return side if side in {"AWAY", "HOME"} else None


def _outcome_guard_rank(row: Mapping[str, Any]) -> tuple[int, float]:
    """Prefer stronger qualification evidence, then EV, when collapsing exposure."""
    try:
        score = int(row.get("confidence_score") or 0)
    except (TypeError, ValueError):
        score = 0
    return score, _ev(row)


def _demote(row: dict[str, Any], reason: str, keeper: Mapping[str, Any]) -> None:
    row["status"] = "PASS"
    if "scored_status" in row:
        row["scored_status"] = "PASS"
    codes = tuple(row.get("presentation_reason_codes") or ())
    if reason not in codes:
        row["presentation_reason_codes"] = codes + (reason,)
    row["guard_kept_instead"] = _selection(keeper)


def _direct_opposites(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    """True only when two rows are opposite sides of the same exact contract."""
    if str(left.get("game_id")) != str(right.get("game_id")):
        return False
    if str(left.get("market") or "").upper() != str(right.get("market") or "").upper():
        return False
    if str(left.get("entity_id")) != str(right.get("entity_id")):
        return False
    left_side = str(left.get("side") or "").upper()
    if _OPPOSITE.get(left_side) != str(right.get("side") or "").upper():
        return False
    left_line = _f(left.get("line"))
    right_line = _f(right.get("line"))
    market = str(left.get("market") or "").upper()
    want_right = -left_line if (left_line is not None and market in _LINE_NEGATED) else left_line
    if (want_right is None) != (right_line is None):
        return False
    return want_right is None or abs(right_line - want_right) <= 1e-9


def _team_side(row: Mapping[str, Any]) -> str | None:
    side = str(row.get("team_side") or "").upper()
    return side if side in {"AWAY", "HOME"} else None


def _other_team(side: str | None) -> str | None:
    return {"AWAY": "HOME", "HOME": "AWAY"}.get(str(side or "").upper())


def _team_scoring_direction(row: Mapping[str, Any]) -> int:
    """Direction for the runs scored by the team this row is bound to.

    +1 means more runs for that team, -1 means fewer. Strikeouts intentionally
    return 0: a K over can coexist with an over/game-over thesis and is not used
    by this narrow guard.
    """
    market = str(row.get("market") or "").upper()
    side = str(row.get("side") or "").upper()
    if side not in {"OVER", "UNDER"}:
        return 0
    sign = 1 if side == "OVER" else -1
    if market in _TEAM_SCORING_MARKETS:
        return sign
    if market in _PITCHER_RUN_ALLOWANCE_MARKETS:
        return sign
    if market in _PITCHER_RUN_SUPPRESSION_MARKETS:
        return -sign
    return 0


def _same_team_scoring_conflict(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    """Narrow conflict: one team's totals vs its own opposite period or opposing starter.

    Examples intentionally caught:
    - Padres full-game TT Over vs Padres F5 TT Under.
    - Yankees TT Over vs the opposing starter Outs Over.

    Game totals, YRFI/NRFI, hitter props, and pitcher strikeouts are not part of
    this rule. Unknown team binding fails neutral.
    """
    lm = str(left.get("market") or "").upper()
    rm = str(right.get("market") or "").upper()
    ls, rs = _team_side(left), _team_side(right)
    if ls is None or rs is None:
        return False

    ld, rd = _team_scoring_direction(left), _team_scoring_direction(right)
    if ld == 0 or rd == 0 or ld == rd:
        return False

    # Same team's full-game/F5 totals pointing opposite ways.
    if lm in _TEAM_SCORING_MARKETS and rm in _TEAM_SCORING_MARKETS:
        return ls == rs

    # A team's total against the opposing starter's run-sensitive prop.
    if lm in _TEAM_SCORING_MARKETS and (rm in _PITCHER_RUN_ALLOWANCE_MARKETS or rm in _PITCHER_RUN_SUPPRESSION_MARKETS):
        return rs == _other_team(ls)
    if rm in _TEAM_SCORING_MARKETS and (lm in _PITCHER_RUN_ALLOWANCE_MARKETS or lm in _PITCHER_RUN_SUPPRESSION_MARKETS):
        return ls == _other_team(rs)
    return False


def apply_same_game_guard(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_game: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if not _is_actionable(row):
            continue
        game_id = row.get("game_id")
        if game_id in {None, ""}:
            # Fail neutral rather than treating unrelated unknown games as one game.
            continue
        by_game.setdefault(str(game_id), []).append(row)

    for game_rows in by_game.values():
        # 1) Exact contract contradictions.
        for idx, left in enumerate(game_rows):
            if not _is_actionable(left):
                continue
            for right in game_rows[idx + 1:]:
                if not _is_actionable(right) or not _direct_opposites(left, right):
                    continue
                keeper = max((left, right), key=_ev)
                loser = right if keeper is left else left
                _demote(loser, SCRIPT_CONFLICT_REASON, keeper)
                if loser is left:
                    break

        # 2) Narrow team-scoring conflicts only. Prefer qualification score, then EV.
        for idx, left in enumerate(game_rows):
            if not _is_actionable(left):
                continue
            for right in game_rows[idx + 1:]:
                if not _is_actionable(right) or not _same_team_scoring_conflict(left, right):
                    continue
                keeper = max((left, right), key=_outcome_guard_rank)
                loser = right if keeper is left else left
                _demote(loser, TEAM_SCORING_CONFLICT_REASON, keeper)
                if loser is left:
                    break

        # 3) One team-outcome exposure per game across full game, F5, and pitcher W.
        # Pitcher W is included only when context has bound the pitcher to AWAY/HOME.
        outcomes = [r for r in game_rows if _is_actionable(r) and _team_outcome_side(r)]
        if len(outcomes) > 1:
            keeper = max(outcomes, key=_outcome_guard_rank)
            keep_team = _team_outcome_side(keeper)
            for r in outcomes:
                if r is keeper:
                    continue
                reason = SAME_SIDE_STACK_REASON if _team_outcome_side(r) == keep_team else OPPOSITE_TEAM_OUTCOME_REASON
                _demote(r, reason, keeper)
    return rows


def _selection(row: Mapping[str, Any]) -> str:
    market, side = str(row.get("market")), str(row.get("side"))
    who = row.get("entity_name") or ("" if str(row.get("entity_id")) == str(row.get("game_id")) else row.get("entity_id"))
    line = _f(row.get("line"))
    line_text = "" if line is None or market in {"MONEYLINE", "F5_MONEYLINE", "NRFI", "YRFI"} else (
        f" {line:+g}" if market in _LINE_NEGATED else f" {line:g}"
    )
    return " ".join(x for x in (str(who or ""), market.replace("_", " ").title(), side.title() + line_text) if x).strip()


def render_markdown(rows: Sequence[Mapping[str, Any]], *, header: str, notes: Sequence[str] = ()) -> str:
    def pct(v):
        return "—" if v is None else f"{100 * float(v):.1f}%"

    lines = [f"# {header}", "", f"_{LABEL}_", "",
             "| # | Game | Pick | Odds | Win p | Push p | Win p ex-push | Fair | Edge | EV/$ | Score | Status |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for i, r in enumerate(rows, 1):
        fair = r.get("fair_odds")
        ev = r.get("ev_per_dollar")
        odds = _f(r.get("american_odds"))
        odds_text = "—" if odds is None else f"{int(odds):+d}"
        fair_text = "—" if fair is None else f"{int(fair):+d}"
        ev_text = "—" if ev is None else f"{float(ev):+.3f}"
        guarded = bool(r.get("presentation_reason"))
        win_text = "—" if guarded else pct(r.get("model_p_raw"))
        push_text = "—" if guarded else pct(r.get("push_p"))
        status_text = str(r.get("scored_status"))
        if PRICE_CEILING_REASON in (r.get("presentation_reason_codes") or ()):
            status_text += " (price > -165)"
        if r.get("guard_kept_instead"):
            status_text += f" (same game: kept {r['guard_kept_instead']})"
        lines.append(
            f"| {i} | {r.get('game_id')} | {_selection(r)} | {odds_text} | {win_text} | "
            f"{push_text} | {pct(r.get('model_p'))} | {fair_text} | {pct(r.get('edge'))} | "
            f"{ev_text} | {r.get('confidence_score', 0)} | {status_text} |"
        )
    lines += ["", "_Win p = engine win probability; Push p = refund probability; Win p ex-push = Win p / (1 − Push p), "
              "the basis for Fair odds and Edge against the two-way no-vig price. EV/$ uses Win p with pushes refunded. "
              "Score is qualification-only (simulation sufficiency, quote freshness, push-mass quality); price, edge, EV and probability magnitude do not add Score points._"]
    blocked = [r for r in rows if r.get("scored_status") in {"BLOCKED", "NO_MODEL"}]
    if blocked:
        lines += ["", "## Engine did not price / not card-eligible", "_Includes stale or incomplete market pairs plus empirical estimates withheld by the presentation support guard; raw engine output is preserved in JSON._"]
        for r in blocked:
            presentation_reason = r.get("presentation_reason")
            engine_reason = r.get("engine_reason")
            reason_codes = r.get("reason_codes") or ()
            if presentation_reason:
                reason = presentation_reason
            elif r.get("model_p_raw") is None and engine_reason:
                reason = engine_reason
            elif reason_codes:
                reason = ", ".join(reason_codes)
            else:
                reason = engine_reason or "UNSPECIFIED_BLOCK"
            lines.append(f"- {_selection(r)}: {reason}")
    if notes:
        lines += ["", "## Notes", *[f"- {n}" for n in notes]]
    return "\n".join(lines) + "\n"
