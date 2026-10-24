"""Complete user-facing cards, derived only from evaluated runner outputs.

Presentation cannot grant eligibility, change prices, or infer model validation.
The original card remains the evidence record. Intake supplies identity only.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from math import isfinite
import re

from sportsedge.quote_freshness import is_fresh
from sportsedge.handicap_explanations import handicap_explanation

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
    projection = row.get("independent_projection")
    projection = projection if isinstance(projection, dict) else {}
    provenance = row.get("pricing_provenance")
    provenance = provenance if isinstance(provenance, dict) else {}
    anchored = (row.get("pricing_lane") == "LANE_B_ANCHORED"
                or provenance.get("lane") == "MARKET_ANCHORED"
                or projection.get("uses_sportsbook_price_in_projection") is True)
    source = projection if projection and not anchored else row
    probability = _number(source.get("estimate_p", source.get("model_probability")))
    ev = _number(source.get("ev_per_dollar"))
    if probability is not None and not 0 <= probability <= 1:
        probability = None
    return probability, ev, anchored


def _blended(row, sport):
    """Market-blended view (Lane B: DK line + 15% of the model's gap).

    CFB raw matchup projections disagree with DK by 7-15 points on half a
    slate (+20-70% "EV"). Owner ruling Oct 24 2026: rank CFB by the
    market-blended EV instead. Display only; Lane A stays on the record.
    """
    if sport != "CFB":
        return None
    lanes = row.get("pricing_lanes")
    lane_b = lanes.get("lane_b_anchored") if isinstance(lanes, dict) else None
    if not isinstance(lane_b, dict) or lane_b.get("status") == "LANE_B_UNAVAILABLE":
        return None
    p = _number(lane_b.get("estimate_p"))
    ev = _number(lane_b.get("ev_per_dollar"))
    if p is None or ev is None:
        return None
    return {"probability": p, "ev": ev,
            "fair_odds": _number(lane_b.get("fair_american")),
            "weight": (lane_b.get("anchor") or {}).get("weight")}


def _disposition(row, min_ev):
    status = str(row.get("status") or "MISSING_STATUS")
    probability, ev, anchored = _metrics(row)
    priced = probability is not None and ev is not None
    if status.startswith("BLOCKED") or status in {"NO_MODEL_OR_MARKET", "NO_ENGINE", "NO_QUOTE", "MISSING_STATUS"}:
        return "BLOCKED", "blocked", row.get("reason") or status
    if (row.get("independent_projection") is not None
            and not isinstance(row.get("independent_projection"), dict)):
        return "BLOCKED", "blocked", "INDEPENDENT_PROJECTION_MALFORMED"
    provenance = row.get("pricing_provenance")
    if provenance is not None and (
        not isinstance(provenance, dict)
        or provenance.get("lane") not in {"INDEPENDENT", "MARKET_ANCHORED"}
    ):
        return "BLOCKED", "blocked", "PROVENANCE_UNDETERMINED"
    if not priced:
        return "BLOCKED", "blocked", row.get("reason") or "Usable probability and EV unavailable"
    # Explicit freshness evidence is authoritative. A legacy quote_status
    # string must never override an explicit stale/invalid/future verdict.
    freshness = row.get("quote_freshness")
    fresh = (is_fresh(freshness) if freshness is not None
             else row.get("quote_status") == "RECENT_CAPTURED_QUOTE")
    if not fresh or status == "WATCH_QUOTE_NOT_CURRENT":
        return "REFRESH REQUIRED", "stale", "Current quote required"
    if anchored:
        return "WATCH", "priced", "Independent pricing unavailable for this row"
    notes = row.get("context_notes")
    if notes is not None and not isinstance(notes, (list, tuple)):
        return "WATCH", "priced", "CONTEXT_METADATA_MALFORMED"
    if any("NO_FETCH_MANUAL_MODE" in str(note) for note in (notes or [])):
        return "WATCH", "priced", "Verified event and team inputs required"
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
    analyses = card.get("handicap_explanations")
    if analyses is not None and (not isinstance(analyses, list)
                                 or len(analyses) != len(rows)):
        raise ValueError("HANDICAP_EXPLANATION_COUNT_MISMATCH")
    floor = _number(card.get("min_ev", 0.02))
    if floor is None or not 0 <= floor <= 0.15:
        raise ValueError("INVALID_EDGE_FLOOR")
    selections = []
    families = defaultdict(Counter)
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or row.get("input_index", index) != index:
            raise ValueError("EVALUATED_ROW_ORDER_MISMATCH")
        source = intake[index] if intake is not None else {}
        if not isinstance(source, dict):
            raise ValueError("SELECTION_INTAKE_ROW_NOT_OBJECT")
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
            # Stale-quote rows still carry the model's own probability and
            # fair price: show them (EV is at the SUBMITTED price and is only
            # a guide until the line is re-checked). Status stays REFRESH.
            "probability": probability if bucket in {"priced", "stale"} and not anchored else None,
            "estimated_ev": ev if bucket in {"priced", "stale"} and not anchored else None,
            "fair_odds": _number((row.get("independent_projection")
                                  if isinstance(row.get("independent_projection"), dict)
                                  else row).get("fair_american")) if bucket in {"priced", "stale"} and not anchored else None,
            "source_status": row.get("status"),
            "blended": _blended(row, sport) if bucket in {"priced", "stale"} else None,
            "handicap": (analyses[index] if analyses is not None
                          and isinstance(analyses[index], dict)
                          and analyses[index].get("input_index") == index
                          else None),
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


def _parsed_utc(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def build_current_value_screens(card, *, max_rows=20, now=None):
    """Rank positive *independent* research prices, with no historical clock.

    This is deliberately separate from PLAY/OFFICIAL promotion. A fresh quote
    and a positive raw estimated EV can establish a *screen*, not establish
    that the model is calibrated or that the bettor should stake a wager.
    """
    view = build_phone_card(card)
    as_of = _parsed_utc(card.get("as_of_utc"))
    final_now = now or datetime.now(timezone.utc)
    if (not isinstance(final_now, datetime) or final_now.tzinfo is None
            or final_now.utcoffset() is None):
        raise ValueError("VALUE_SCREEN_FINALIZATION_CLOCK_REQUIRED")
    final_now = final_now.astimezone(timezone.utc)
    results, exclusions = [], Counter()
    raw_rows = card["evaluated_rows"]
    for source, row in zip(view["selections"], raw_rows):
        status = str(row.get("status") or "MISSING_STATUS")
        if (status.startswith("BLOCKED") or status in
                {"NO_MODEL_OR_MARKET", "NO_ENGINE", "NO_QUOTE", "MISSING_STATUS"}):
            exclusions["BLOCKED_OR_UNPRICED"] += 1
            continue
        if status not in CANDIDATE_STATUSES | {
                "PASS", "BELOW_THRESHOLD", "WATCH_BELOW_EV_FLOOR", "PRICE_CAP", "WATCH_PRICE_CAP"}:
            exclusions["NONCANONICAL_RESEARCH_PRICE_STATUS"] += 1
            continue
        if status == "BLOCKED_IL_COLLEGE":
            exclusions["ILLINOIS_COLLEGE_PROHIBITION"] += 1
            continue
        p, reported_ev, anchored = _metrics(row)
        provenance = row.get("pricing_provenance")
        if anchored or (not isinstance(provenance, dict)
                        or provenance.get("lane") != "INDEPENDENT"):
            exclusions["NO_INDEPENDENT_PROJECTION"] += 1
            continue
        independent_projection = row.get("independent_projection")
        if (isinstance(independent_projection, dict) and
                independent_projection.get("paired_market_status") !=
                "EXACT_DK_TWO_SIDED_NO_VIG_RESEARCH"):
            exclusions["OPPOSITE_SIDE_QUOTE_NOT_VERIFIED"] += 1
            continue
        notes = row.get("context_notes")
        if notes is not None and not isinstance(notes, (list, tuple)):
            exclusions["LIVE_CONTEXT_METADATA_MALFORMED"] += 1
            continue
        if any("NO_FETCH_MANUAL_MODE" in str(note) for note in (notes or [])):
            exclusions["LIVE_CONTEXT_NOT_VERIFIED"] += 1
            continue
        if p is None:
            exclusions["NO_MODEL_PROBABILITY"] += 1
            continue
        freshness = row.get("quote_freshness")
        if not is_fresh(freshness):
            exclusions["NO_VERIFIED_CURRENT_QUOTE"] += 1
            continue
        # The quote's original freshness was calculated at model-as-of.
        # Final card rendering may happen minutes later. Reapply the 180s
        # limit against the real finalization clock without inventing a
        # second capture or treating a frozen snapshot as a live offer.
        age_at_capture = freshness.get("age_seconds")
        if (as_of is None or not isinstance(age_at_capture, (int, float))
                or isinstance(age_at_capture, bool) or not isfinite(age_at_capture)
                or age_at_capture < 0):
            exclusions["QUOTE_FINAL_FRESHNESS_NOT_PROVABLE"] += 1
            continue
        total_age = age_at_capture + (final_now - as_of).total_seconds()
        if total_age < 0 or total_age > 180:
            exclusions["QUOTE_EXPIRED_BEFORE_FINAL_CARD"] += 1
            continue
        kickoff = _parsed_utc(source.get("kickoff"))
        if kickoff is None or final_now >= kickoff:
            exclusions["PREGAME_CLOCK_UNVERIFIED_OR_STARTED"] += 1
            continue
        price = source.get("odds")
        if price is None or -100 < price < 100 or price < -165:
            exclusions["MISSING_QUOTE_OR_PRICE_CAP"] += 1
            continue
        decimal_odds = 1 + (100 / -price if price < 0 else price / 100)
        # A model's stored EV can refer to an earlier bookmaker price.
        # Reprice from the actual current quote on *every* card render.
        ev = p * decimal_odds - 1
        if ev <= 0:
            exclusions["NO_POSITIVE_ESTIMATED_EV"] += 1
            continue
        explanation = source.get("handicap") or {}
        factors = explanation.get("evidence") or []
        estimated_breakeven = (-price / (100 - price) if price < 0
                               else 100 / (100 + price))
        screen = (explanation.get("research_price_screen") or
                  handicap_explanation(row).get("research_price_screen") or {})
        results.append({
            "game": source["game"], "sport": source["sport"],
            "market": source["market"], "selection": source["selection"],
            "player_name": source.get("player_name"), "line": source.get("line"),
            "odds": price, "model_estimate_p": p,
            "book_raw_breakeven_p": round(estimated_breakeven, 6),
            "quote_age_at_finalization_seconds": round(total_age, 3),
            "raw_estimated_ev": ev,
            "original_model_reported_ev": reported_ev,
            "ev_repriced_at_current_quote": True,
            "prior_ev_differs_from_current_quote": (
                reported_ev is not None and abs(reported_ev - ev) > .01),
            "research_playable_to": screen.get("research_playable_to_positive_ev"),
            "supporting_factors": [x for x in factors if x.get("direction") == "SUPPORTS"],
            "opposing_factors": [x for x in factors if x.get("direction") == "OPPOSES"],
            "coverage_warning": (None if factors else "MATCHUP_EXPLANATION_NOT_YET_SOURCED"),
            "card_status": source["status"],
            "status": "CURRENT_MODEL_VALUE_SCREEN_NOT_VERIFIED_PLAY",
            "can_be_official_play": False,
        })
    results.sort(key=lambda x: -x["raw_estimated_ev"])
    return {"schema": "SPORTSEDGE_CURRENT_VALUE_SCREEN_V1",
            "basis": "PREGAME_FRESH_INDEPENDENT_MODEL_VS_BOOK_ONLY",
            "finalized_at_utc": final_now.isoformat(),
            "max_quote_age_seconds": 180,
            "historical_tests_required_to_display": False,
            "verified_plays": 0,
            "unverified_model_value_screens": results[:max_rows],
            "total_positive_screens": len(results),
            "exclusions": dict(sorted(exclusions.items()))}


def render_phone_card(card, *, run_url="", intake_at="", now=None):
    view = build_phone_card(card)
    current = build_current_value_screens(card, now=now)
    coverage = view["coverage"]
    lines = ["## SportsEdge · RUN IT", "",
             f"Snapshot: {_safe(view['as_of_utc'])}",
             f"{coverage['input_rows']} selections · {coverage['distinct_market_families']} market families on this board.",
             ""]
    lines += ["### Current priced value screens · NOT verified plays", "",
              "Ranked from independently priced pregame quotes. Quotes expire after 180 seconds; refresh before wagering. Model accuracy is not implied.", "",
              "| Sport | Matchup / selection | Book | Model p | Raw EV | Estimated playable-to | Matchup case |",
              "| --- | --- | ---: | ---: | ---: | ---: | --- |"]
    for entry in current["unverified_model_value_screens"]:
        bet = " ".join(str(v) for v in (entry.get("player_name"), entry["market"], entry["selection"], entry.get("line")) if v is not None)
        why = "; ".join(str(x.get("name")) + " " + str(x.get("value"))
                        for x in entry["supporting_factors"])
        if not why:
            why = "Matchup factors not yet source-backed"
        lines.append(f"| {_safe(entry['sport'])} | {_safe(entry['game'])}: {_safe(bet)} | "
                     f"{_price(entry['odds'])} | {entry['model_estimate_p']*100:.1f}% | "
                     f"{entry['raw_estimated_ev']*100:+.1f}% | "
                     f"{_price(entry['research_playable_to'])} | {_safe(why)} |")
    if not current["unverified_model_value_screens"]:
        lines.append("| — | No fresh independent positive-EV selection on this submitted board | — | — | — | — | — |")
    lines += ["", f"Last verified screen: {_safe(current['finalized_at_utc'])} UTC · Priced screens: {current['total_positive_screens']} · Verified PLAYs: 0 (this surface has no promotion authority).", ""]
    def _rank_ev(r):
        b = r.get("blended")
        return b["ev"] if b else r.get("estimated_ev")

    def _rank_p(r):
        b = r.get("blended")
        return b["probability"] if b else r["probability"]

    def _rank_fair(r):
        b = r.get("blended")
        return b["fair_odds"] if b else r["fair_odds"]

    stale_ranked = sorted(
        (r for r in view["selections"]
         if r["status"] == "REFRESH REQUIRED" and _rank_ev(r) is not None
         and _rank_ev(r) > 0),
        key=_rank_ev, reverse=True)
    if stale_ranked:
        lines += ["### Model value at the SUBMITTED prices · re-check line before betting", "",
                  "Ranked by EV, highest first. CFB rows use the MARKET-BLENDED price (DK line plus 15% "
                  "of the model's disagreement); raw model gaps are too noisy to bet directly.", "",
                  "| # | EV | Game | Selection | DK (submitted) | Model p | Model fair |",
                  "| ---: | ---: | --- | --- | ---: | ---: | ---: |"]
        for rank, r in enumerate(stale_ranked[:30], 1):
            name = " ".join(str(x) for x in (r.get("player_name"), r["market"], r["selection"]) if x)
            if r.get("line") is not None and str(r["line"]) not in str(r["selection"]):
                name += " " + str(r["line"])
            lines.append(f"| {rank} | {100*_rank_ev(r):+.1f}% | {_safe(r['game'])} | {_safe(name)} | "
                         f"{_price(r['odds'])} | {100*_rank_p(r):.1f}% | {_price(_rank_fair(r))} |")
        lines.append("")
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
        described = [r for r in rows if r.get("handicap") and
                     r["handicap"].get("evidence")]
        if described:
            lines += ["", "**Matchup evidence (research; not independently verified)**"]
            for r in described:
                h = r["handicap"]
                parts = [f"{e['name']}={e['value']} ({e['direction'].lower()}; {e['source']})"
                         for e in h["evidence"]]
                lines.append(f"- {_safe(r['selection'])}: " +
                             _safe("; ".join(parts)))
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


def phone_card_pages(markdown, *, max_bytes=55000):
    """Bound GitHub comment size without dropping rows; repeat table context."""
    if max_bytes < 1000:
        raise ValueError("PHONE_PAGE_LIMIT_TOO_SMALL")
    pages, current = [], []
    heading, table, separator = "", "", ""
    size = 0
    for line in markdown.splitlines(keepends=True):
        needed = len(line.encode("utf-8"))
        if needed > max_bytes - 1000:
            raise ValueError("PHONE_ROW_EXCEEDS_PAGE_LIMIT")
        if current and size + needed > max_bytes - 200:
            pages.append("".join(current))
            context = [heading, "\n", table, separator] if line.startswith("|") else []
            current = [part for part in context if part]
            size = sum(len(part.encode("utf-8")) for part in current)
        current.append(line)
        size += needed
        if line.startswith("### "):
            heading, table, separator = line, "", ""
        elif line.startswith("| Selection /") or line.startswith("| Sport / market"):
            table = line
        elif line.startswith("| ---"):
            separator = line
    if current:
        pages.append("".join(current))
    if len(pages) <= 1:
        return pages
    return [f"## SportsEdge · page {i}/{len(pages)}\n\n" + page for i, page in enumerate(pages, 1)]
