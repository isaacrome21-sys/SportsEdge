"""Complete user-facing cards, derived only from evaluated runner outputs.

Presentation cannot grant eligibility, change prices, or infer model validation.
The original card remains the evidence record. Intake supplies identity only.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from math import isfinite
import re

from sportsedge.quote_freshness import is_fresh

CANDIDATE_STATUSES = frozenset({
    "RESEARCH_POSITIVE_EV_UNVALIDATED", "RESEARCH_CANDIDATE_NOT_VALIDATED",
})
INTAKE_FIELDS = ("sport", "away", "home", "market", "side", "selection",
                 "player_name", "line", "period", "phase", "alternate",
                 "settlement_type", "kickoff", "commence_time", "book")


def identity_rows(rows, default_sport=None):
    """Never copy intake probabilities, statuses, or validation assertions."""
    return [{**{k: row[k] for k in INTAKE_FIELDS if k in row},
             "sport": str(row.get("sport") or default_sport or "").upper()}
            for row in rows]


def _number(value):
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return value if isfinite(value) else None


def _metrics(row):
    # Never substitute the independent projection for a row priced in Lane B:
    # its status may have been calculated from a different probability.
    projection = row.get("independent_projection") or {}
    anchored = (row.get("pricing_lane") == "LANE_B_ANCHORED"
                or projection.get("uses_sportsbook_price_in_projection") is True)
    source = projection if projection and not anchored else row
    probability = _number(source.get("estimate_p", source.get("model_probability")))
    ev = _number(source.get("ev_per_dollar"))
    if probability is not None and not 0 <= probability <= 1:
        probability = None
    return probability, ev, anchored


def _disposition(row, min_ev):
    status = str(row.get("status") or "MISSING_STATUS")
    probability, ev, anchored = _metrics(row)
    priced = probability is not None and ev is not None
    if status.startswith("BLOCKED") or status in {"NO_MODEL_OR_MARKET", "NO_ENGINE", "NO_QUOTE", "MISSING_STATUS"}:
        return "BLOCKED", "blocked", row.get("reason") or status
    if not priced:
        return "BLOCKED", "blocked", row.get("reason") or "Usable probability and EV unavailable"
    fresh = (is_fresh(row.get("quote_freshness") or {})
             or row.get("quote_status") == "RECENT_CAPTURED_QUOTE")
    if not fresh or status == "WATCH_QUOTE_NOT_CURRENT":
        return "REFRESH REQUIRED", "stale", "Current quote required"
    if anchored:
        return "WATCH", "priced", "Independent pricing unavailable for this row"
    # Source/context/participation/deployment holds take precedence over EV.
    allowed = CANDIDATE_STATUSES | {"PRICE_CAP", "WATCH_PRICE_CAP", "BELOW_THRESHOLD", "WATCH_BELOW_EV_FLOOR"}
    if status not in allowed:
        return "WATCH", "priced", row.get("reason") or status
    projection = row.get("independent_projection")
    if isinstance(projection, dict) and projection.get("paired_market_status") != "EXACT_DK_TWO_SIDED_NO_VIG_RESEARCH":
        return "WATCH", "priced", "Verified opposite-side quote required"
    if ev < 0:
        return "PASS", "priced", "Negative estimated EV"
    odds = _number(row.get("odds_american", row.get("dk_odds")))
    if odds is None:
        return "BLOCKED", "rejected", "Valid quoted odds required"
    if odds < -165 or status in {"PRICE_CAP", "WATCH_PRICE_CAP"}:
        return "WATCH", "priced", "Above straight-bet price cap"
    if ev < min_ev:
        return "WATCH", "priced", "Below edge floor"
    # There is no promoted/validated adapter on this surface today. A raw
    # PLAY or validation boolean cannot create one through presentation.
    if row.get("lineup_status") == "PUBLIC_BOXSCORE_LINEUP_NOT_VERIFIED":
        return "WATCH", "priced", "Confirmed lineup required"
    reason = "Model verification pending"
    if row.get("pitcher_status") == "PROBABLE_STARTER_ONLY_NOT_CONFIRMED":
        reason += "; probable starter only"
    return "LEAN", "priced", reason


def build_phone_card(card):
    rows = card.get("evaluated_rows")
    if not isinstance(rows, list):
        raise ValueError("COMPLETE_EVALUATED_ROWS_REQUIRED")
    expected = (card.get("summary") or {}).get("rows", len(rows))
    if expected != len(rows):
        raise ValueError("EVALUATED_ROW_COUNT_MISMATCH")
    intake = card.get("selection_intake")
    if intake is not None and (not isinstance(intake, list) or len(intake) != len(rows)):
        raise ValueError("SELECTION_INTAKE_COUNT_MISMATCH")
    floor = _number(card.get("min_ev", 0.02))
    if floor is None or not 0 <= floor <= 0.15:
        raise ValueError("INVALID_EDGE_FLOOR")
    selections = []
    families = defaultdict(Counter)
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or row.get("input_index", index) != index:
            raise ValueError("EVALUATED_ROW_ORDER_MISMATCH")
        source = intake[index] if intake is not None else {}
        label, bucket, reason = _disposition(row, floor)
        if str(row.get("status") or "") in {"BLOCKED_INVALID", "BLOCKED_IL_COLLEGE", "BLOCKED_STARTED"}:
            bucket = "rejected"
        probability, ev, anchored = _metrics(row)
        game = row.get("game") or (
            f"{source['away']} @ {source['home']}" if source.get("away") and source.get("home") else "Event unavailable")
        sport = str(source.get("sport") or row.get("sport") or "UNKNOWN").upper()
        market = str(row.get("market") or source.get("market") or "UNKNOWN").upper()
        # Keep unknown dimensions unknown: absence does not prove full-game,
        # pregame, a standard line, or any settlement convention.
        dimension = (sport, market, str(source.get("period") or "UNSPECIFIED"),
                     str(source.get("phase") or "UNSPECIFIED"),
                     str(source.get("alternate", "UNSPECIFIED")),
                     str(source.get("settlement_type") or "UNSPECIFIED"))
        families[dimension][bucket] += 1
        selections.append({
            "input_index": index, "game": game, "sport": sport, "market": market,
            "kickoff": row.get("kickoff_utc") or source.get("kickoff") or source.get("commence_time"),
            "selection": row.get("selection") or source.get("side") or source.get("selection") or "Selection unavailable",
            "player_name": row.get("player_name") or source.get("player_name"),
            "line": row.get("line", source.get("line")),
            "odds": _number(row.get("odds_american", row.get("dk_odds"))),
            "status": label, "reason": reason,
            "probability": probability if bucket == "priced" and not anchored else None,
            "estimated_ev": ev if bucket == "priced" and not anchored else None,
            "fair_odds": _number((row.get("independent_projection") or row).get("fair_american")) if bucket == "priced" and not anchored else None,
            "source_status": row.get("status"),
        })
    ledger = [{**dict(zip(("sport", "market", "period", "phase", "alternate", "settlement_type"), key)),
               **{k: counts[k] for k in ("priced", "blocked", "rejected", "stale")},
               "rows": sum(counts.values())} for key, counts in sorted(families.items())]
    return {"schema": "SPORTSEDGE_PHONE_DISPLAY_V1", "as_of_utc": card.get("as_of_utc"),
            "selections": selections, "status_counts": dict(Counter(r["status"] for r in selections)),
            "coverage": {"scope": "OBSERVED_INTAKE_ONLY", "dk_catalog_complete": False,
                         "input_rows": len(rows),
                         "distinct_market_families": len({(k[0], k[1]) for k in families}),
                         "distinct_market_variants": len(families), "families": ledger}}


def _safe(value):
    # Quote data is untrusted Markdown content, not executable formatting.
    text = str(value if value is not None else "—")
    return re.sub(r"[\r\n\t|<>`*\[\]!]", " ", text).strip()


def _price(value):
    return "—" if value is None else f"{value:+g}"


def render_phone_card(card, *, run_url="", intake_at=""):
    view = build_phone_card(card)
    coverage = view["coverage"]
    lines = ["## SportsEdge · RUN IT", "",
             f"Snapshot: {_safe(view['as_of_utc'])}",
             f"{coverage['input_rows']} selections · {coverage['distinct_market_families']} market families on this board.",
             ""]
    groups = defaultdict(list)
    for row in view["selections"]:
        groups[(str(row.get("kickoff") or ""), row["sport"], row["game"])].append(row)
    for (kickoff, sport, game), rows in sorted(groups.items()):
        lines += [f"### {_safe(sport)} · {_safe(game)}", "", f"Start: {_safe(kickoff)}", "",
                  "| Selection / market | DK | Status | Est. probability | Est. fair | Est. EV | Reason |",
                  "| --- | ---: | --- | ---: | ---: | ---: | --- |"]
        for row in rows:
            p = "—" if row["probability"] is None else f"{100*row['probability']:.1f}%"
            ev = "—" if row["estimated_ev"] is None else f"{100*row['estimated_ev']:+.1f}%"
            name = " ".join(str(x) for x in (row.get("player_name"), row["market"], row["selection"]) if x)
            if row.get("line") is not None and str(row["line"]) not in str(row["selection"]):
                name += " " + str(row["line"])
            lines.append(f"| {_safe(name)} | {_price(row['odds'])} | {row['status']} | {p} | {_price(row['fair_odds'])} | {ev} | {_safe(row['reason'])} |")
        lines.append("")
    lines += ["### Board coverage", "", "Counts describe this submitted board; the full DraftKings catalog has not been verified.", "",
              "| Sport / market / period / phase / alternate / settlement | Priced | Blocked | Rejected | Refresh |",
              "| --- | ---: | ---: | ---: | ---: |"]
    for family in coverage["families"]:
        name = " / ".join(str(family[k]) for k in ("sport", "market", "period", "phase", "alternate", "settlement_type"))
        lines.append(f"| {_safe(name)} | {family['priced']} | {family['blocked']} | {family['rejected']} | {family['stale']} |")
    if run_url:
        lines += ["", f"Run receipt: {_safe(run_url)}"]
    return "\n".join(lines) + "\n"
