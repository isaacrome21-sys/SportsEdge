"""Read-only fixture-specific DraftKings menu census for canonical RUN IT.

The October 13 operator menu enumeration is not a quote receipt or validated
model. This module deliberately cannot price, activate, or validate any market.
Unknown and omitted menus stay visible; observed-only != globally offered.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
import json
import math

DEFAULT_CENSUS = Path(__file__).resolve().parents[1] / "config" / "dk_inspected_menu_census_v1.json"
SCHEMA = "SPORTSEDGE_DK_INSPECTED_MENU_CENSUS_V1"
SNAPSHOT_SCHEMA = "SPORTSEDGE_DK_FIXTURE_MENU_SNAPSHOT_V1"
QUOTE_FIELDS = ("price_american", "quote_captured_at", "source_receipt")
LADDER_FORMS = frozenset({"X_PLUS_LADDER", "OR_FEWER_LADDER", "OVER_UNDER_LADDER"})
PRICE_FORMS = frozenset({"TWO_SIDED", "ALTERNATE"}) | LADDER_FORMS


class DKFixtureMenuError(ValueError):
    """Untrusted fixture snapshot cannot be safely parsed."""


def _timestamp(value: Any, name: str) -> datetime:
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise DKFixtureMenuError(name + "_INVALID") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise DKFixtureMenuError(name + "_TIMEZONE_REQUIRED")
    return dt.astimezone(timezone.utc)


def _required(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DKFixtureMenuError(name + "_REQUIRED")
    return value.strip()


def _odds(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return abs(value) >= 100
    return False


def _line(value: Any) -> bool:
    return (not isinstance(value, bool) and isinstance(value, (float, int))
            and math.isfinite(float(value)))


def load_census(path: str | Path = DEFAULT_CENSUS) -> dict:
    with open(path, encoding="utf-8") as f:
        source = json.load(f)
    if not isinstance(source, dict) or source.get("schema") != SCHEMA:
        raise DKFixtureMenuError("DK_CENSUS_SCHEMA_INVALID")
    if not isinstance(source.get("sports"), dict):
        raise DKFixtureMenuError("DK_CENSUS_SPORTS_REQUIRED")
    for sport, group in source["sports"].items():
        if sport not in {"MLB", "NFL", "CFB"} or not isinstance(group, dict):
            raise DKFixtureMenuError("DK_CENSUS_SPORT_INVALID")
        markets = group.get("markets")
        if not isinstance(markets, list) or not markets:
            raise DKFixtureMenuError("DK_CENSUS_MARKETS_REQUIRED")
        ids = [m.get("market_key") for m in markets if isinstance(m, dict)]
        if len(ids) != len(markets) or len(ids) != len(set(ids)):
            raise DKFixtureMenuError("DK_CENSUS_DUPLICATE_OR_MALFORMED")
    return source


def _form_compatible(expected: list, form: str) -> bool:
    if form in expected:
        return True
    # A native O/U ladder is separately identified from a single X+ rung,
    # but they may belong to the same observed player-stat family.
    return "OVER_UNDER_LADDER" in expected and form in LADDER_FORMS


def audit_dk_fixture_menu(snapshot: Mapping[str, Any],
                          *, census: Mapping[str, Any] | None = None) -> dict:
    """Audit fixture menu visibility without consuming prices or model results.

    No caller may interpret this output as a verified offered quote or a
    certification decision. It is pure observability in RUN IT's card.
    """
    if not isinstance(snapshot, Mapping) or snapshot.get("schema") != SNAPSHOT_SCHEMA:
        raise DKFixtureMenuError("DK_FIXTURE_SNAPSHOT_SCHEMA_INVALID")
    census = dict(census) if census is not None else load_census()
    sport = _required(snapshot.get("sport"), "SPORT").upper()
    if sport not in census.get("sports", {}):
        raise DKFixtureMenuError("DK_FIXTURE_SPORT_NOT_CATALOGED")
    event_id = _required(snapshot.get("event_id"), "EVENT_ID")
    book = _required(snapshot.get("book"), "BOOK").lower()
    if book != "draftkings":
        raise DKFixtureMenuError("DK_FIXTURE_BOOK_UNSUPPORTED")
    start = _timestamp(snapshot.get("scheduled_start"), "SCHEDULED_START")
    capture = _timestamp(snapshot.get("captured_at"), "CAPTURED_AT")
    raw_offers = snapshot.get("offers")
    absent = snapshot.get("observed_absent", [])
    if not isinstance(raw_offers, list) or not isinstance(absent, list):
        raise DKFixtureMenuError("DK_FIXTURE_OFFERS_OR_ABSENCE_INVALID")
    if not all(isinstance(x, str) and x for x in absent) or len(set(absent)) != len(absent):
        raise DKFixtureMenuError("DK_FIXTURE_ABSENCE_DUPLICATE_OR_INVALID")
    market_list = census["sports"][sport]["markets"]
    by_name = {m["market_key"]: m for m in market_list}
    observations, seen, dupes = [], set(), set()
    input_keys = set()
    for i, offer in enumerate(raw_offers):
        if not isinstance(offer, Mapping):
            observations.append({"input_index": i, "status": "REFUSED_MALFORMED_OFFER"})
            continue
        key = str(offer.get("market_key") or "").strip().upper()
        form = str(offer.get("form") or "").strip().upper()
        period = str(offer.get("period") or "").strip().upper()
        entity = str(offer.get("player_id") or offer.get("team_id") or "").strip()
        side = str(offer.get("selection") or "").strip().upper()
        line = offer.get("line")
        spec = by_name.get(key)
        out = {"input_index": i, "market_key": key, "form": form,
               "period": period, "status": "MENU_OBSERVATION_UNPRICED",
               "source_status": "OPERATOR_REPORTED_NOT_INDEPENDENTLY_VERIFIED",
               "model_status": "NOT_EVALUATED_BY_MENU_AUDIT"}
        if not key or not form or not period:
            out["status"] = "REFUSED_MALFORMED_OFFER"
        elif spec is None:
            out["status"] = "MARKET_UNCATALOGED"
        elif not _form_compatible(spec["forms"], form):
            out["status"] = "MARKET_FORM_NOT_REGISTERED"
        elif (spec["period"] not in {"FULL_GAME", "MULTI_PERIOD"}
              and spec["period"] != period):
            out["status"] = "MARKET_PERIOD_CONFLICT"
        elif (form in PRICE_FORMS and line is not None and not _line(line)):
            out["status"] = "MARKET_LINE_MALFORMED"
        elif form in LADDER_FORMS and line is None:
            out["status"] = "MILESTONE_LINE_REQUIRED"
        # A market could be both a quoted individual rung and a catalog tab.
        # Do not infer an offered price from presence in the menu.
        has_quote_fields = any(field in offer for field in QUOTE_FIELDS)
        if out["status"] == "MENU_OBSERVATION_UNPRICED" and has_quote_fields:
            if (not _odds(offer.get("price_american"))
                    or not offer.get("source_receipt")
                    or not offer.get("book_event_id")
                    or not offer.get("selection")
                    or not offer.get("quote_captured_at")):
                out["status"] = "QUOTE_EVIDENCE_INCOMPLETE"
            else:
                try:
                    qt = _timestamp(offer["quote_captured_at"], "QUOTE_CAPTURE")
                    if qt > capture or qt > start:
                        out["status"] = "QUOTE_NOT_PREGAME_OR_AFTER_SNAPSHOT"
                    else:
                        out["status"] = "QUOTE_REPORTED_RECEIPT_NOT_VERIFIED"
                        out["quote_captured_at"] = qt.isoformat()
                except DKFixtureMenuError:
                    out["status"] = "QUOTE_CAPTURE_INVALID"
        if capture > start and out["status"] == "QUOTE_REPORTED_RECEIPT_NOT_VERIFIED":
            out["status"] = "POST_START_SNAPSHOT_NO_PREGAME_AUTHORITY"
        if key:
            input_keys.add(key)
        # Duplicate identities cannot be silently coalesced across selections.
        ident = (key, form, period, entity, side, str(line))
        if ident in seen and out["status"] not in {"MARKET_UNCATALOGED", "REFUSED_MALFORMED_OFFER"}:
            out["status"] = "DUPLICATE_MARKET_OFFER"
            dupes.add(key)
        seen.add(ident)
        observations.append(out)
    conflict = sorted(input_keys.intersection(absent))
    if conflict:
        raise DKFixtureMenuError("DK_FIXTURE_OBSERVED_ABSENT_CONFLICT:" + ",".join(conflict))
    not_reported = sorted(set(by_name).difference(input_keys).difference(absent))
    statuses = {}
    for item in observations:
        statuses[item["status"]] = statuses.get(item["status"], 0) + 1
    return {
        "schema": "SPORTSEDGE_DK_FIXTURE_MENU_AUDIT_V1",
        "sport": sport, "event_id": event_id, "book": book,
        "scheduled_start": start.isoformat(), "captured_at": capture.isoformat(),
        "snapshot_after_start": capture > start,
        "catalog_entry_count": len(by_name),
        "observed_absent_on_this_fixture": sorted(absent),
        "not_reported_no_absence_proof": not_reported,
        "observations": observations,
        "status_counts": dict(sorted(statuses.items())),
        "duplicate_keys": sorted(dupes),
        "coverage_is_not_validation": True,
        "snapshot_is_not_proven_tradable_quote": True,
        "no_vig_without_true_two_sided_quote": "UNAVAILABLE",
        "model_probability_status": "NOT_COMPUTED",
        "promotion_eligible": False,
        "betting_authority": False,
    }
