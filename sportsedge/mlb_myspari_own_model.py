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

from .mlb_edge_score import ev_per_dollar, score_mlb_edge
from .mlb_scored_card import build_mlb_scored_card

MYSPARI_OWN_MODEL_VERSION = "MLB_MYSPARI_OWN_MODEL_V1"
LABEL = "SportsEdge engine model_p shown MySpariEdge-style · NOT Truth Gate · NOT OFFICIAL"
MANUAL_QUOTE_TTL_SECONDS = 6 * 3600.0
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
        base = {
            "game_id": row.get("game_id"), "market": row.get("market"), "entity_id": row.get("entity_id"),
            "entity_name": (names or {}).get(str(row.get("entity_id")), ""),
            "line": row.get("line"), "side": row.get("side"), "american_odds": odds,
            "engine_status": row.get("bet_status"), "engine_reason": row.get("reason"),
            "engine_version": row.get("engine_version"), "mc_paths": row.get("mc_paths"),
            "model_p_raw": row.get("model_p"), "push_p": push, "label": LABEL,
        }
        if cond is None:
            scored = score_mlb_edge(model_available=False, american_odds=odds)
        else:
            scored = score_mlb_edge(
                estimate_p=min(max(cond, 1e-6), 1 - 1e-6), american_odds=odds,
                opposite_odds=None if opposite is None else opposite.get("american_odds"),
                quote_age_seconds=quote_age_seconds, quote_ttl_seconds=quote_ttl_seconds, reliability=reliability,
            )
        scored_row = {k: getattr(scored, k) for k in scored.__dataclass_fields__}
        if push > 0 and scored_row.get("ev_per_dollar") is not None and row.get("model_p") is not None:
            scored_row["ev_per_dollar"] = ev_per_dollar(float(row["model_p"]), odds, push_p=push)
        out.append({**scored_row, **base})
    return build_mlb_scored_card(out)


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
             "| # | Game | Pick | Odds | Model p | Fair | Edge | EV/$ | Score | Status |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for i, r in enumerate(rows, 1):
        fair = r.get("fair_odds")
        ev = r.get("ev_per_dollar")
        odds = _f(r.get("american_odds"))
        lines.append(
            f"| {i} | {r.get('game_id')} | {_selection(r)} | {'—' if odds is None else f'{int(odds):+d}'} | "
            f"{pct(r.get('model_p'))} | {'—' if fair is None else f'{int(fair):+d}'} | {pct(r.get('edge'))} | "
            f"{'—' if ev is None else f'{float(ev):+.3f}'} | {r.get('confidence_score', 0)} | {r.get('scored_status')} |"
        )
    blocked = [r for r in rows if r.get("scored_status") in {"BLOCKED", "NO_MODEL"}]
    if blocked:
        lines += ["", "## Engine did not price"]
        lines += [f"- {_selection(r)}: {r.get('engine_reason') or ', '.join(r.get('reason_codes') or ())}" for r in blocked]
    if notes:
        lines += ["", "## Notes", *[f"- {n}" for n in notes]]
    return "\n".join(lines) + "\n"
