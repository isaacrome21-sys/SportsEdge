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
                 reliability: float = 0.6, names: Mapping[str, str] | None = None) -> list[dict[str, Any]]:
    results = [r for r in (payload.get("results") or []) if isinstance(r, Mapping)]
    out: list[dict[str, Any]] = []
    for row in results:
        opposite = _opposite(row, results)
        cond, push = _conditional_and_push(row)
        odds = row.get("american_odds")
        guard_reason = empirical_guard_reason(row, cond)
        raw_paths = row.get("mc_paths", 0)
        n_paths = raw_paths if isinstance(raw_paths, int) and not isinstance(raw_paths, bool) and raw_paths >= 0 else 0
        base = {
            "game_id": row.get("game_id"), "market": row.get("market"), "entity_id": row.get("entity_id"),
            "entity_name": (names or {}).get(str(row.get("entity_id")), ""),
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
    return build_mlb_scored_card(apply_same_game_guard(out))


# --- Same-game script guard -------------------------------------------------
# Presentation-only: never changes a probability. It stops one card from telling
# two opposite stories about the same game (e.g. game Over + pitcher Outs Over),
# and from listing the same team twice (ML + run line) as independent edges.
SCRIPT_CONFLICT_REASON = "SAME_GAME_SCRIPT_CONFLICT"
SAME_SIDE_STACK_REASON = "SAME_SIDE_STACK"
_HIGH_RUNS_OVER = frozenset({
    "TOTALS", "TEAM_TOTALS", "F5_TOTALS", "F5_TEAM_TOTALS",
    "PITCHER_HITS_ALLOWED", "PITCHER_ER", "PITCHER_BB", "PITCHER_HITS_WALKS_ER",
    "EITHER_PITCHER_HITS_ALLOWED", "EITHER_PITCHER_ER", "EITHER_PITCHER_BB",
    "HITS", "TOTAL_BASES", "RBI", "RUNS", "HOME_RUNS", "HITS_RUNS_RBIS", "RUNS_RBIS",
    "EXTRA_BASE_HITS", "SINGLES", "DOUBLES",
})
# Over on these means the pitcher went deep or dominated -> fewer runs.
_LOW_RUNS_OVER = frozenset({"PITCHER_OUTS", "PITCHER_K"})
_SIDE_MARKETS = frozenset({"MONEYLINE", "RUN_LINE"})


def run_script_direction(row: Mapping[str, Any]) -> int:
    """+1 = needs runs, -1 = needs a quiet game, 0 = not a run-environment bet."""
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


def _demote(row: dict[str, Any], reason: str, keeper: Mapping[str, Any]) -> None:
    row["status"] = "PASS"
    codes = tuple(row.get("presentation_reason_codes") or ())
    if reason not in codes:
        row["presentation_reason_codes"] = codes + (reason,)
    row["guard_kept_instead"] = _selection(keeper)


def apply_same_game_guard(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_game: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if row.get("status") == "ACTIONABLE":
            by_game.setdefault(str(row.get("game_id")), []).append(row)
    for game_rows in by_game.values():
        # 1) One run script per game: keep the direction holding the best-EV row.
        scripted = [r for r in game_rows if run_script_direction(r)]
        if {run_script_direction(r) for r in scripted} == {1, -1}:
            keeper = max(scripted, key=_ev)
            keep_dir = run_script_direction(keeper)
            for r in scripted:
                if run_script_direction(r) != keep_dir:
                    _demote(r, SCRIPT_CONFLICT_REASON, keeper)
        # 2) One side bet per team: ML and run line on the same team are one bet.
        sides = [r for r in game_rows if r.get("status") == "ACTIONABLE"
                 and str(r.get("market") or "").upper() in _SIDE_MARKETS]
        for team in {str(r.get("side") or "").upper() for r in sides}:
            same = [r for r in sides if str(r.get("side") or "").upper() == team]
            if len(same) > 1:
                keeper = max(same, key=_ev)
                for r in same:
                    if r is not keeper:
                        _demote(r, SAME_SIDE_STACK_REASON, keeper)
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
