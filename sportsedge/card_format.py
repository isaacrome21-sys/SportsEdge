"""Research-card presentation standard (adopted Oct 2026 from the 4-account research).

Standard: one line per play — Play + line + price -> modeled probability -> EV%,
ranked by EV. The modeled probability is ALWAYS stated BEFORE any status or
recommendation language. The JSON card keeps every existing key (factor-coverage
audit, uncertainty flags); this module only adds a presentation layer.

Structural rule (Isaac, Oct 11): nothing gets padded to hit a target number of
bets. A card with zero playable edges is a VALID card and must render as one.

Research-only. HYPOTHETICAL. Not bets, no staking authority, nothing here is
called a verified edge.
"""
from __future__ import annotations

from math import isfinite

# Statuses the pipeline already assigns to priced selections that carry a
# modeled probability AND clear the EV floor. This set is DERIVED from the
# engine's own statuses — the formatter never invents a playable edge.
PLAYABLE_STATUSES = frozenset({
    "RESEARCH_EDGE",                    # free_models game rows >= min_ev
    "RESEARCH_CANDIDATE_NOT_VALIDATED", # three-sport bridge prop rows >= EV floor
})

SCHEMA = "SPORTSEDGE_RESEARCH_CARD_FORMAT_V1"


class CardFormatError(ValueError):
    pass


def _num(value):
    """Finite float or None. Degenerate probabilities are refused upstream;
    here they degrade to None (never invented)."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if isfinite(f) else None


def model_probability_of(row):
    """Independent-lane modeled probability for the selected side, or None.

    Prefers the independent (market-blind) lane: ``independent_projection`` on
    game rows, ``model_probability`` on priced prop rows. Degenerate values
    (p <= 0, p >= 1, non-finite) return None so the row is excluded from the
    ranked plays rather than silently priced.
    """
    ind = row.get("independent_projection")
    candidates = []
    if isinstance(ind, dict):
        candidates.append(ind.get("estimate_p"))
    candidates.append(row.get("model_probability"))
    candidates.append(row.get("estimate_p"))
    for cand in candidates:
        p = _num(cand)
        if p is not None and 0.0 < p < 1.0:
            return p
    return None


def ev_of(row):
    ev = _num(row.get("ev_per_dollar"))
    return ev


def uncertainty_flags(row):
    """Uncertainty/audit flags already on the row, surfaced on the card."""
    flags = []
    qs = row.get("quote_status")
    if qs:
        flags.append(str(qs))
    cq = row.get("context_quality")
    if cq:
        flags.append(str(cq))
    mv = row.get("model_validation")
    if mv:
        flags.append(str(mv))
    if row.get("market_anchor"):
        flags.append("MARKET_ANCHORED_UNVALIDATED")
    if isinstance(row.get("independent_projection"), dict):
        flags.append("INDEPENDENT_MARKET_BLIND")
    status = str(row.get("status") or "")
    if status and status not in PLAYABLE_STATUSES and "BLOCKED" not in status:
        flags.append(status)
    return flags


def play_label(row):
    parts = []
    sport = str(row.get("sport") or "").upper()
    if sport:
        parts.append(sport)
    player = row.get("player_name") or row.get("pitcher_name")
    game = row.get("game")
    selection = str(row.get("selection") or row.get("side") or "")
    if player:
        base = "%s — %s %s" % (game or "", str(player).strip(), selection.strip())
    else:
        base = "%s — %s" % (game or "", selection.strip())
    line = row.get("line")
    price = row.get("odds_american", row.get("dk_odds"))
    label = base.strip(" —")
    if line is not None and str(line).strip() not in ("", "None"):
        label += " %s" % line
    if price is not None:
        try:
            label += " @ %d" % int(price)
        except (TypeError, ValueError):
            label += " @ %s" % price
    return label


def extract_plays(card):
    """One play dict per priced selection, sorted by EV descending.

    Priced = row has a valid (non-degenerate) modeled probability. Blocked /
    degenerate rows are NOT plays; they are reported separately so the card
    can never pad its count.
    """
    plays, excluded = [], []
    for i, row in enumerate(card.get("evaluated_rows") or []):
        if not isinstance(row, dict):
            continue
        p = model_probability_of(row)
        ev = ev_of(row)
        status = str(row.get("status") or "MISSING_STATUS")
        if p is None or ev is None:
            reason = ("DEGENERATE_OR_MISSING_PROBABILITY"
                      if p is None else "MISSING_EV")
            excluded.append({"input_index": i, "status": status,
                             "reason": reason, "label": play_label(row)})
            continue
        playable = status in PLAYABLE_STATUSES
        plays.append({
            "input_index": i,
            "label": play_label(row),
            "sport": str(row.get("sport") or "").upper(),
            "market": str(row.get("market") or "").upper(),
            "model_p": p,
            "ev_per_dollar": ev,
            "ev_pct": round(ev * 100, 2),
            "status": status,
            "playable": playable,
            "flags": uncertainty_flags(row),
        })
    plays.sort(key=lambda r: (-r["ev_per_dollar"], r["label"]))
    return plays, excluded


def render_card_text(plays, excluded, *, meta):
    """The Edge Card text. Modeled probability precedes any status language
    on every line; a zero-edge card renders explicitly, never padded."""
    lines = [
        "THE EDGE CARD — SportsEdge research output (HYPOTHETICAL / RESEARCH ONLY)",
        "as of %s · %s priced selections evaluated" % (
            meta.get("as_of_utc", "unknown"), meta.get("rows", "?")),
        "No bets placed. No staking authority. Nothing here is a verified edge.",
        "",
    ]
    if plays:
        lines.append("PLAYS, ranked by EV (play + line + price → modeled probability → EV%%):")
        for n, pl in enumerate(plays, 1):
            flag = (" — " + "; ".join(pl["flags"])) if pl["flags"] else ""
            lines.append(
                "%2d. %s → model %.1f%% → EV %+.2f%%%s"
                % (n, pl["label"], pl["model_p"] * 100, pl["ev_pct"], flag))
        lines.append("")
    playable = [p for p in plays if p["playable"]]
    lines.append("PLAYABLE EDGES (above EV floor, research-only, NOT validated): %d of %d priced"
                 % (len(playable), len(plays)))
    if not playable:
        lines.append("NO EDGES TODAY — this is a valid card. Nothing padded to hit a target.")
    lines.append("")
    if excluded:
        lines.append("NOT PRICED (excluded with reason, never silently priced):")
        for ex in excluded:
            lines.append(" - %s — %s (%s)" % (ex["label"], ex["status"], ex["reason"]))
        lines.append("")
    counts = meta.get("factor_status_counts") or {}
    if counts:
        used = sum(v for k, v in counts.items()
                   if k not in ("NOT_WIRED", "MISSING_UNVERIFIED"))
        missing = sum(v for k, v in counts.items()
                      if k in ("NOT_WIRED", "MISSING_UNVERIFIED"))
        lines.append("FACTOR COVERAGE AUDIT: %d factor-slots verified-used, %d missing/not-wired "
                     "(coverage is NOT validation)." % (used, missing))
        lines.append("")
    lines.append("_research_only: probabilities are research estimates; edges are "
                 "unvalidated until the backtest harness passes them._")
    return "\n".join(lines)


def format_research_card(card):
    """Attach the presentation standard to a card dict. Returns
    ``{"plays": [...], "excluded": [...], "rendered_card": str}``."""
    plays, excluded = extract_plays(card)
    fc = card.get("factor_coverage") or {}
    meta = {
        "as_of_utc": card.get("as_of_utc"),
        "rows": (card.get("summary") or {}).get("rows"),
        "factor_status_counts": fc.get("status_counts"),
    }
    return {
        "schema": SCHEMA,
        "plays": plays,
        "excluded": excluded,
        "playable_count": sum(1 for p in plays if p["playable"]),
        "rendered_card": render_card_text(plays, excluded, meta=meta),
    }
