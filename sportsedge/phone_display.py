"""Complete user-facing cards, derived only from evaluated runner outputs.

Presentation cannot grant eligibility, change prices, or infer model validation.
The original card remains the evidence record. Intake supplies identity only.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from math import isfinite
import re

from sportsedge.quote_freshness import (
    MAX_QUOTE_AGE_SECONDS,
    QUOTE_STALE, QUOTE_UNVERIFIED, is_fresh,
)
from sportsedge.research_estimate import RESEARCH_LABEL, valid_research_estimate

CANDIDATE_STATUSES = frozenset({
    "RESEARCH_POSITIVE_EV_UNVALIDATED", "RESEARCH_CANDIDATE_NOT_VALIDATED",
})
INTAKE_FIELDS = ("sport", "away", "home", "market", "side", "selection",
                 "player_name", "line", "period", "phase", "alternate",
                 "settlement_type", "kickoff", "commence_time", "book",
                 "quote_source", "book_quote_receipt_verified")
SCREENSHOT_UNATTESTED = "OWNER_SCREENSHOT_QUOTE_NOT_ATTESTED"
RECEIPT_UNATTESTED = "QUOTE_RECEIPT_NOT_ATTESTED"
RESEARCH_STATUS = "RESEARCH ONLY"


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


def _quote_hold(row, source):
    """Name WHY a quote is not current. Unattested is not the same as stale."""
    freshness = row.get("quote_freshness")
    code = freshness.get("code") if isinstance(freshness, dict) else None
    if code == QUOTE_UNVERIFIED:
        screenshot = (str(source.get("quote_source") or "").upper() == "OWNER_DK_SCREENSHOT"
                      or str(row.get("quote_source") or "").upper() == "OWNER_DK_SCREENSHOT")
        return "UNATTESTED", (SCREENSHOT_UNATTESTED if screenshot else RECEIPT_UNATTESTED)
    if code == QUOTE_STALE:
        age = _number(freshness.get("age_seconds"))
        limit = freshness.get("max_age_seconds")
        age_text = f"{age:.0f}s" if age is not None else "unknown age"
        return "STALE", f"QUOTE_STALE: quote age {age_text} exceeds {limit}s; refresh required"
    if code:
        return "INVALID", f"{code}: quote timestamp unusable; refresh required"
    return "UNKNOWN", "Current quote required"


_QUOTE_FIELDS = ("odds_american", "dk_odds", "price", "price_american",
                 "american_odds", "odds", "decimal_odds", "book_price")
_CAPTURE_FIELDS = ("captured_at", "quote_captured_at", "quote_retrieved_at",
                   "retrieved_at", "quote_timestamp", "observed_at")


def _has_quote_field(row, source):
    """Any quote-bearing field on the row or its intake (not fair/model odds)."""
    for obj in (row, source):
        for key, value in obj.items():
            k = str(key).lower()
            if k.startswith("fair") or value is None:
                continue
            if k in _QUOTE_FIELDS or "odds" in k or "price" in k:
                return True
    return False


def _has_capture_time(*objs):
    return any(isinstance(obj, dict) and obj.get(k) not in (None, "")
               for obj in objs for k in _CAPTURE_FIELDS)


def _research_quote_ok(row, source):
    """180s limit kept (t211u/t212u): a research estimate may show only when
    the quote is fresh, or is an owner screenshot that is truly unattested
    (no recorded age AND no recorded capture time).  A recorded age over the
    limit, a non-finite age, a capture time without a valid fresh verdict, a
    stale/invalid code, or missing freshness on any quote-bearing row blocks."""
    freshness = row.get("quote_freshness")
    if freshness is None:
        return not _has_quote_field(row, source)
    if not isinstance(freshness, dict):
        return False
    raw_age = freshness.get("age_seconds")
    if raw_age is not None and _number(raw_age) is None:
        return False  # NaN/inf/garbage age: refuse, never treat as unattested
    if is_fresh(freshness):
        return raw_age is None or _number(raw_age) <= MAX_QUOTE_AGE_SECONDS
    if raw_age is not None:
        return False
    if _has_capture_time(freshness, row, source):
        return False  # a capture time exists but no valid fresh age: refuse
    if freshness.get("code") != QUOTE_UNVERIFIED:
        return False
    return (str(source.get("quote_source") or "").upper() == "OWNER_DK_SCREENSHOT"
            or str(row.get("quote_source") or "").upper() == "OWNER_DK_SCREENSHOT")


def _disposition(row, min_ev, source=None):
    source = source if isinstance(source, dict) else {}
    status = str(row.get("status") or "MISSING_STATUS")
    probability, ev, anchored = _metrics(row)
    priced = probability is not None and ev is not None
    if status.startswith("BLOCKED") or status in {"NO_MODEL_OR_MARKET", "NO_ENGINE", "NO_QUOTE", "MISSING_STATUS"}:
        # A real engine estimate may ride on a blocked row as a research
        # annex. The blocker name is kept; no EV, never eligible/PLAY.
        if (not status.startswith("BLOCKED") and valid_research_estimate(row) is not None
                and _research_quote_ok(row, source)):
            return (RESEARCH_STATUS, "research",
                    f"{RESEARCH_LABEL} · blocker kept: {row.get('reason') or status}")
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
        kind, detail = _quote_hold(row, source)
        screenshot = detail == SCREENSHOT_UNATTESTED
        if (kind == "UNATTESTED" and screenshot and not anchored and probability is not None
                and _research_quote_ok(row, source)):
            # The engine priced the row; only the quote's capture time is
            # unattested. Show the estimate as research, with no EV.
            return (RESEARCH_STATUS, "research",
                    f"{RESEARCH_LABEL} · {detail}: no attested capture time, "
                    "estimate only, no EV, never PLAY")
        return "REFRESH REQUIRED", "stale", detail
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


IMPOSSIBLE_TOTAL = "PROBABILITY_TOTAL_IMPOSSIBLE"
_SIGNED_LINE_MARKETS = ("SPREAD", "RUN_LINE", "RUNLINE", "PUCK_LINE", "HANDICAP", "ATS")


def _is_signed_line_market(market):
    """Spread-like markets, whatever the spacing/case/punctuation:
    'Run Line', 'puck-line', 'Point Spread', 'RUNLINE', 'ATS'."""
    tokens = re.sub(r"[^A-Z0-9]+", " ", str(market or "").upper()).split()
    joined = "_".join(tokens)
    return (any(t in {"SPREAD", "SPREADS", "HANDICAP", "ATS", "RUNLINE", "PUCKLINE"} for t in tokens)
            or "RUN_LINE" in joined or "PUCK_LINE" in joined)


def _line_value(line):
    if line is None:
        return None
    value = _number(line)
    return value if value is not None else ("INVALID", str(line))


def _complementary(a, b):
    """Two displayed selections are disjoint outcomes of one contract when they
    are different sides of the same game/market/player at the same line, or --
    for signed-line (spread-like) markets only -- at exactly opposite lines.
    abs(line) is never used, so different lines are never merged."""
    la, lb = _line_value(a.get("line")), _line_value(b.get("line"))
    signed = _is_signed_line_market(a.get("market"))
    if signed:
        # A -3 / B +3 are one contract; A +3 / B +3 are two different contracts.
        return isinstance(la, float) and isinstance(lb, float) and la == -lb
    return la == lb


def _refuse_impossible_totals(selections, push_masses):
    """Disjoint sides whose displayed probabilities plus push mass exceed 1,
    or two copies of one selection that disagree, are ALL refused -- never
    renormalised."""
    groups = defaultdict(list)
    for index, sel in enumerate(selections):
        if sel.get("probability") is None:
            continue
        groups[(sel.get("game"), sel.get("market"), sel.get("player_name"))].append(index)
    refused = {}
    for members in groups.values():
        for i, x in enumerate(members):
            for y in members[i + 1:]:
                a, b = selections[x], selections[y]
                if str(a.get("selection")) == str(b.get("selection")):
                    if (_line_value(a.get("line")) == _line_value(b.get("line"))
                            and a["probability"] != b["probability"]):
                        refused[x] = refused[y] = "duplicate selection disagrees"
                    continue
                if not _complementary(a, b):
                    continue
                push = max(push_masses[x], push_masses[y])
                total = a["probability"] + b["probability"] + push
                if total > 1 + 1e-6:
                    msg = f"sides plus push sum {total:.4f} > 1"
                    refused[x] = refused[y] = msg
    for index, msg in refused.items():
        sel = selections[index]
        sel["probability"] = None
        sel["estimated_ev"] = None
        sel["fair_odds"] = None
        sel["status"] = "BLOCKED"
        sel["research_only_estimate"] = False
        sel["reason"] = f"{IMPOSSIBLE_TOTAL}: {msg}; refused, not renormalised"
    return set(refused)


def _push_mass(row, estimate):
    for obj in (estimate, row.get("independent_projection"), row):
        if isinstance(obj, dict) and obj.get("push_p") is not None:
            value = _number(obj.get("push_p"))
            return value if value is not None and value >= 0 else 1.0  # bad push => refuse
    return 0.0


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
    dimensions = []
    push_masses = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or row.get("input_index", index) != index:
            raise ValueError("EVALUATED_ROW_ORDER_MISMATCH")
        source = intake[index] if intake is not None else {}
        if not isinstance(source, dict):
            raise ValueError("SELECTION_INTAKE_ROW_NOT_OBJECT")
        label, bucket, reason = _disposition(row, floor, source)
        if str(row.get("status") or "") in {"BLOCKED_INVALID", "BLOCKED_IL_COLLEGE", "BLOCKED_STARTED"}:
            bucket = "rejected"
        probability, ev, anchored = _metrics(row)
        research = bucket == "research"
        estimate = valid_research_estimate(row) if research else None
        if estimate is not None:
            probability = _number(estimate.get("probability"))
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
        dimensions.append((dimension, bucket))
        push_masses.append(_push_mass(row, estimate) if bucket in {"priced", "research"} else 0.0)
        selections.append({
            "input_index": index, "game": game, "sport": sport, "market": market,
            "kickoff": row.get("kickoff_utc") or source.get("kickoff") or source.get("commence_time"),
            "selection": row.get("selection") or source.get("side") or source.get("selection") or "Selection unavailable",
            "player_name": row.get("player_name") or source.get("player_name"),
            "line": row.get("line", source.get("line")),
            "odds": _number(row.get("odds_american", row.get("dk_odds"))),
            "status": label, "reason": reason,
            "probability": probability if bucket in {"priced", "research"} and not anchored else None,
            "estimated_ev": ev if bucket == "priced" and not anchored else None,
            "fair_odds": (_number(estimate.get("fair_american")) if estimate is not None
                          else _number((row.get("independent_projection")
                                        if isinstance(row.get("independent_projection"), dict)
                                        else row).get("fair_american"))
                          if bucket in {"priced", "research"} and not anchored else None),
            "source_status": row.get("status"),
            "research_only_estimate": research,
            "eligible": False,
        })
    refused = _refuse_impossible_totals(selections, push_masses)
    # Family counts are rebuilt from the FINALIZED displayed selections, after
    # refusal: a refused market contributes 0 priced/research rows.
    families = defaultdict(Counter)
    for index, (dimension, bucket) in enumerate(dimensions):
        families[dimension]["blocked" if index in refused else bucket] += 1
    ledger = [{**dict(zip(("sport", "market", "period", "phase", "alternate", "settlement_type"), key)),
               **{k: counts[k] for k in ("priced", "research", "blocked", "rejected", "stale")},
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
    # The research column/legend appear only when a research row exists, so
    # a card without research rows renders exactly as before.
    has_research = any(f["research"] for f in coverage["families"])
    lines += ["### Board coverage", "", "Counts describe this submitted board; the full DraftKings catalog has not been verified.", ""]
    if has_research:
        lines += ["Research only = real unvalidated engine estimate shown for research; never eligible, never PLAY, no EV, not validation.", "",
                  "| Sport / market / period / phase / alternate / settlement | Priced | Research only | Blocked | Rejected | Refresh |",
                  "| --- | ---: | ---: | ---: | ---: | ---: |"]
    else:
        lines += ["| Sport / market / period / phase / alternate / settlement | Priced | Blocked | Rejected | Refresh |",
                  "| --- | ---: | ---: | ---: | ---: |"]
    for family in coverage["families"]:
        name = " / ".join(str(family[k]) for k in ("sport", "market", "period", "phase", "alternate", "settlement_type"))
        research = f" {family['research']} |" if has_research else ""
        lines.append(f"| {_safe(name)} | {family['priced']} |{research} {family['blocked']} | {family['rejected']} | {family['stale']} |")
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
