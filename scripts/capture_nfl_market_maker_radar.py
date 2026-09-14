#!/usr/bin/env python3
"""Capture zero-authority NFL Pinnacle/DraftKings/FanDuel radar snapshots.

One poll intentionally assigns every observed book the same ``capture_id`` and
``captured_at``. None of the direct transports used here exposes a trustworthy
quote-update timestamp, so HTTP request ordering must never manufacture a leader.
Price leadership can only be observed across distinct polls.

The output schema is the existing ``analyze_market_maker_radar.py`` observation
schema. Raw provider bytes are content-addressed and preserved on the append-only
``data`` branch. This lane is Layer B HARD_MARKET context only and creates no
Model_P, Truth Gate, promotion, eligibility, staking, OFFICIAL, evidence-clock,
or wager-placement authority.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from scripts.normalize_fanduel_nfl_markets import (
    FanDuelNormalizationError,
    normalize as normalize_fanduel,
)
from scripts.normalize_pinnacle_nfl_markets import (
    PinnacleNormalizationError,
    normalize as normalize_pinnacle,
)
from scripts.probe_direct_market_feeds import PINNACLE_ROOT, _fetch
from scripts.probe_fanduel_football_market_shape import _content_page_url
from scripts.probe_pinnacle_football_market_shape import (
    FOOTBALL_SPORT_ID,
    _is_upcoming_nfl_game,
)
from sportsedge.draftkings_game_market_source import (
    DraftKingsGameMarketError,
    fetch_board as fetch_draftkings_board,
    normalize_board as normalize_draftkings_board,
)

UTC = timezone.utc
SPORT_KEY = "americanfootball_nfl"
LOOKAHEAD = timedelta(days=8)
BIND_TOLERANCE_SECONDS = 10 * 60
MARKETS = ("h2h", "spreads", "totals")
NFL_MASCOTS = {
    "49ers", "bears", "bengals", "bills", "broncos", "browns", "buccaneers",
    "cardinals", "chargers", "chiefs", "colts", "commanders", "cowboys",
    "dolphins", "eagles", "falcons", "giants", "jaguars", "jets", "lions",
    "packers", "panthers", "patriots", "raiders", "rams", "ravens", "saints",
    "seahawks", "steelers", "texans", "titans", "vikings",
}


class NFLRadarCaptureError(RuntimeError):
    pass


def _authority() -> dict[str, bool]:
    return {
        "model_p_input": False,
        "truth_gate_input": False,
        "promotion_authority": False,
        "eligibility_authority": False,
        "staking_authority": False,
        "official_authority": False,
        "production_registry_authority": False,
        "evidence_clock_authority": False,
        "wager_placement_authority": False,
    }


def _iso(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise NFLRadarCaptureError("NFL_RADAR_TIMESTAMP_NAIVE")
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_ts(value: Any) -> datetime:
    text = str(value or "").strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except Exception as exc:
        raise NFLRadarCaptureError("NFL_RADAR_TIMESTAMP_INVALID") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise NFLRadarCaptureError("NFL_RADAR_TIMESTAMP_NAIVE")
    return parsed.astimezone(UTC)


def canonical_team_id(name: Any) -> str:
    tokens = re.findall(r"[a-z0-9]+", str(name or "").lower())
    if not tokens or tokens[-1] not in NFL_MASCOTS:
        raise NFLRadarCaptureError(f"NFL_RADAR_TEAM_UNRECOGNIZED:{name}")
    return tokens[-1]


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _persist_raw(out_root: Path, provider: str, raw: bytes) -> dict[str, Any]:
    digest = _sha(raw)
    rel = Path("archive") / "market-maker-radar" / "raw" / provider / f"{digest}.json"
    target = out_root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if target.read_bytes() != raw:
            raise NFLRadarCaptureError("NFL_RADAR_RAW_HASH_COLLISION")
    else:
        target.write_bytes(raw)
    return {"provider": provider, "raw_sha256": digest, "raw_bytes": len(raw), "raw_relative_path": str(rel)}


def _participants(matchup: Mapping[str, Any]) -> tuple[str, str]:
    by_alignment = {
        str(item.get("alignment") or "").lower(): str(item.get("name") or "").strip()
        for item in matchup.get("participants") or []
        if isinstance(item, Mapping)
    }
    if set(by_alignment) != {"home", "away"}:
        raise NFLRadarCaptureError("NFL_RADAR_PINNACLE_PARTICIPANTS_INVALID")
    return by_alignment["away"], by_alignment["home"]


def _capture_pinnacle(
    *,
    captured_at: datetime,
    out_root: Path,
    opener: Callable[..., Any] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    kwargs = {"provider": "pinnacle"}
    if opener is not None:
        kwargs["opener"] = opener
    raw, payload, _, _ = _fetch(f"{PINNACLE_ROOT}/sports/{FOOTBALL_SPORT_ID}/matchups", **kwargs)
    raw_refs = [_persist_raw(out_root, "pinnacle", raw)]
    if not isinstance(payload, list):
        raise NFLRadarCaptureError("NFL_RADAR_PINNACLE_MATCHUPS_NOT_LIST")
    horizon = captured_at + LOOKAHEAD
    games = [
        item for item in payload
        if isinstance(item, Mapping)
        and _is_upcoming_nfl_game(item, now=captured_at)
        and _parse_ts(item.get("startTime")) <= horizon
    ]
    events: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for game in games:
        matchup_id = int(game["id"])
        try:
            away, home = _participants(game)
            market_url = f"{PINNACLE_ROOT}/matchups/{matchup_id}/markets/related/straight"
            raw_market, markets, _, _ = _fetch(market_url, **kwargs)
            ref = _persist_raw(out_root, "pinnacle", raw_market)
            raw_refs.append(ref)
            matchup = {
                "matchup_id": matchup_id,
                "home_team": home,
                "away_team": away,
                "start_time": game.get("startTime"),
            }
            normalized = normalize_pinnacle(
                matchup=matchup,
                markets=markets,
                captured_at=_iso(captured_at),
                raw_sha256=ref["raw_sha256"],
            )
            events.append(
                {
                    "book": "pinnacle",
                    "provider_event_id": matchup_id,
                    "home_team": home,
                    "away_team": away,
                    "commence_time": game.get("startTime"),
                    "raw_sha256": ref["raw_sha256"],
                    "quotes": normalized["quotes"],
                }
            )
        except Exception as exc:
            failures.append({"provider_event_id": matchup_id, "reason": str(exc)})
    if not events:
        raise NFLRadarCaptureError("NFL_RADAR_PINNACLE_NO_NORMALIZED_EVENTS")
    return events, raw_refs, failures


def _mapping_values(value: Any) -> list[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        return [item for item in value.values() if isinstance(item, Mapping)]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, Mapping)]
    return []


def _capture_fanduel(
    *,
    captured_at: datetime,
    out_root: Path,
    opener: Callable[..., Any] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    kwargs = {"provider": "fanduel"}
    if opener is not None:
        kwargs["opener"] = opener
    raw, payload, _, _ = _fetch(_content_page_url(), **kwargs)
    ref = _persist_raw(out_root, "fanduel", raw)
    if not isinstance(payload, Mapping):
        raise NFLRadarCaptureError("NFL_RADAR_FANDUEL_BOARD_NOT_OBJECT")
    attachments = payload.get("attachments")
    if not isinstance(attachments, Mapping):
        raise NFLRadarCaptureError("NFL_RADAR_FANDUEL_ATTACHMENTS_MISSING")
    competitions = _mapping_values(attachments.get("competitions"))
    nfl = [item for item in competitions if str(item.get("name") or "").strip() == "NFL"]
    if len(nfl) != 1:
        raise NFLRadarCaptureError("NFL_RADAR_FANDUEL_NFL_COMPETITION_NOT_UNIQUE")
    competition_id = nfl[0].get("competitionId")
    event_type_id = nfl[0].get("eventTypeId")
    if competition_id is None or event_type_id is None:
        raise NFLRadarCaptureError("NFL_RADAR_FANDUEL_NFL_COMPETITION_ID_MISSING")

    events_container = attachments.get("events")
    markets_container = attachments.get("markets")
    event_values = _mapping_values(events_container)
    market_values = _mapping_values(markets_container)
    horizon = captured_at + LOOKAHEAD
    events: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []

    for event in event_values:
        try:
            if event.get("competitionId") != competition_id or event.get("eventTypeId") != event_type_id:
                continue
            if event.get("inPlay") is True:
                continue
            event_id = int(event.get("eventId"))
            start = _parse_ts(event.get("openDate"))
            if start <= captured_at or start > horizon:
                continue
            name = str(event.get("name") or "").strip()
            if name.count(" @ ") != 1:
                continue
            related = [market for market in market_values if market.get("eventId") == event_id]
            sub_markets = {str(idx): market for idx, market in enumerate(related)}
            sub_page = {"attachments": {"events": {str(event_id): event}, "markets": sub_markets}}
            normalized = normalize_fanduel(
                event_page=sub_page,
                captured_at=_iso(captured_at),
                raw_sha256=ref["raw_sha256"],
            )
            selected = normalized["event"]
            events.append(
                {
                    "book": "fanduel",
                    "provider_event_id": event_id,
                    "home_team": selected["home_team"],
                    "away_team": selected["away_team"],
                    "commence_time": selected["start_time"],
                    "raw_sha256": ref["raw_sha256"],
                    "quotes": normalized["quotes"],
                }
            )
        except Exception as exc:
            failures.append({"provider_event_id": event.get("eventId"), "reason": str(exc)})
    if not events:
        raise NFLRadarCaptureError("NFL_RADAR_FANDUEL_NO_NORMALIZED_EVENTS")
    return events, [ref], failures


def _capture_draftkings(
    *,
    captured_at: datetime,
    out_root: Path,
    fetcher: Callable[..., Any] = fetch_draftkings_board,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    board = fetcher(SPORT_KEY)
    ref = _persist_raw(out_root, "draftkings", board.raw)
    rows = normalize_draftkings_board(board)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("provider_event_id") or "")].append(dict(row))
    events: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    horizon = captured_at + LOOKAHEAD
    for event_id, event_rows in grouped.items():
        if not event_id or not event_rows:
            continue
        first = event_rows[0]
        try:
            start = _parse_ts(first.get("commence_time"))
            if start <= captured_at or start > horizon:
                continue
            by_market = {market: [r for r in event_rows if r.get("market") == market] for market in MARKETS}
            if any(len(by_market[market]) != 2 for market in MARKETS):
                raise NFLRadarCaptureError("NFL_RADAR_DK_CORE_MARKETS_NOT_EXACT_PAIRS")
            events.append(
                {
                    "book": "draftkings",
                    "provider_event_id": event_id,
                    "home_team": first["home_team"],
                    "away_team": first["away_team"],
                    "commence_time": first["commence_time"],
                    "raw_sha256": ref["raw_sha256"],
                    "quotes": [row for market in MARKETS for row in by_market[market]],
                }
            )
        except Exception as exc:
            failures.append({"provider_event_id": event_id, "reason": str(exc)})
    if not events:
        raise NFLRadarCaptureError("NFL_RADAR_DK_NO_NORMALIZED_EVENTS")
    return events, [ref], failures


def _event_identity(event: Mapping[str, Any]) -> tuple[str, str, datetime]:
    away = canonical_team_id(event.get("away_team"))
    home = canonical_team_id(event.get("home_team"))
    if away == home:
        raise NFLRadarCaptureError("NFL_RADAR_EVENT_TEAMS_DUPLICATE")
    return away, home, _parse_ts(event.get("commence_time"))


def _canonical_event_id(away: str, home: str, start: datetime) -> str:
    return f"{SPORT_KEY}:{start.strftime('%Y-%m-%d')}:{away}@{home}"


def bind_events(
    *,
    pinnacle: Sequence[Mapping[str, Any]],
    draftkings: Sequence[Mapping[str, Any]],
    fanduel: Sequence[Mapping[str, Any]],
    tolerance_seconds: int = BIND_TOLERANCE_SECONDS,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    soft = {"draftkings": list(draftkings), "fanduel": list(fanduel)}
    bound: list[dict[str, Any]] = []
    coverage: list[dict[str, Any]] = []
    used: dict[str, set[str]] = {"draftkings": set(), "fanduel": set()}

    for pin in pinnacle:
        away, home, pin_start = _event_identity(pin)
        event_id = _canonical_event_id(away, home, pin_start)
        books: dict[str, Mapping[str, Any]] = {"pinnacle": pin}
        entry = {"event_id": event_id, "away_team_id": away, "home_team_id": home, "books": ["pinnacle"], "missing_books": [], "ambiguous_books": []}
        for book, candidates in soft.items():
            matches: list[Mapping[str, Any]] = []
            for candidate in candidates:
                try:
                    c_away, c_home, c_start = _event_identity(candidate)
                except NFLRadarCaptureError:
                    continue
                if c_away != away or c_home != home:
                    continue
                if abs((c_start - pin_start).total_seconds()) <= tolerance_seconds:
                    matches.append(candidate)
            if len(matches) == 1:
                provider_id = str(matches[0].get("provider_event_id") or "")
                if provider_id in used[book]:
                    entry["ambiguous_books"].append(book)
                    continue
                used[book].add(provider_id)
                books[book] = matches[0]
                entry["books"].append(book)
            elif len(matches) == 0:
                entry["missing_books"].append(book)
            else:
                entry["ambiguous_books"].append(book)
        coverage.append(entry)
        if len(books) >= 2:
            bound.append(
                {
                    "event_id": event_id,
                    "away_team_id": away,
                    "home_team_id": home,
                    "commence_time": _iso(pin_start),
                    "books": books,
                }
            )
    return bound, coverage


def _designation_for_quote(book: str, quote: Mapping[str, Any], event: Mapping[str, Any]) -> str:
    market = str(quote.get("market") or "")
    if book in {"pinnacle", "fanduel"}:
        designation = str(quote.get("designation") or "").lower()
        if market in {"h2h", "spreads"} and designation in {"home", "away"}:
            return designation
        if market == "totals" and designation in {"over", "under"}:
            return designation
        raise NFLRadarCaptureError("NFL_RADAR_PROVIDER_DESIGNATION_INVALID")
    outcome = str(quote.get("outcome") or "").strip()
    if market == "totals":
        low = outcome.lower()
        if low in {"over", "under"}:
            return low
        raise NFLRadarCaptureError("NFL_RADAR_DK_TOTAL_DESIGNATION_INVALID")
    team = canonical_team_id(outcome)
    if team == event["home_team_id"]:
        return "home"
    if team == event["away_team_id"]:
        return "away"
    raise NFLRadarCaptureError("NFL_RADAR_DK_TEAM_DESIGNATION_INVALID")


def build_observation_rows(
    *,
    bound_events: Sequence[Mapping[str, Any]],
    capture_id: str,
    captured_at: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for event in bound_events:
        for book, provider_event in event["books"].items():
            quotes = provider_event.get("quotes") or []
            for quote in quotes:
                if not isinstance(quote, Mapping):
                    continue
                market = str(quote.get("market") or "")
                if market not in MARKETS:
                    continue
                designation = _designation_for_quote(book, quote, event)
                outcome = (
                    event["home_team_id"] if designation == "home" else
                    event["away_team_id"] if designation == "away" else
                    "Over" if designation == "over" else "Under"
                )
                price = quote.get("american_price") if book in {"pinnacle", "fanduel"} else quote.get("price_american")
                point = quote.get("point")
                rows.append(
                    {
                        "capture_id": capture_id,
                        "sport_key": SPORT_KEY,
                        "event_id": event["event_id"],
                        "book": book,
                        "market": market,
                        "outcome": outcome,
                        "point": point,
                        "price_american": price,
                        "book_last_update": None,
                        "captured_at": captured_at,
                        "commence_time": event["commence_time"],
                        "timestamp_source": "CAPTURED_AT",
                        "provider_quote_timestamp_available": False,
                        "provider_event_id": provider_event.get("provider_event_id"),
                        "provider_commence_time": provider_event.get("commence_time"),
                        "raw_sha256": provider_event.get("raw_sha256"),
                        "designation": designation,
                        "model_p_authority": False,
                        "truth_gate_input": False,
                        "promotion_authority": False,
                        "eligibility_authority": False,
                        "staking_authority": False,
                        "official_authority": False,
                        "evidence_clock_authority": False,
                        "wager_placement_authority": False,
                    }
                )
    rows.sort(key=lambda row: (row["event_id"], row["market"], row["outcome"], row["book"]))
    return rows


def _poll_id(captured_at: str, raw_refs: Sequence[Mapping[str, Any]]) -> str:
    material = captured_at + "|" + "|".join(sorted(str(item.get("raw_sha256") or "") for item in raw_refs))
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]
    return f"nfl-{captured_at.replace(':', '').replace('-', '')}-{digest}"


def capture(
    *,
    out_root: Path,
    now: datetime | None = None,
) -> dict[str, Any]:
    captured_dt = (now or datetime.now(UTC)).astimezone(UTC)
    captured_at = _iso(captured_dt)
    providers: dict[str, Any] = {}
    raw_refs: list[dict[str, Any]] = []
    event_sets: dict[str, list[dict[str, Any]]] = {"pinnacle": [], "draftkings": [], "fanduel": []}

    for book, fn in (
        ("pinnacle", _capture_pinnacle),
        ("draftkings", _capture_draftkings),
        ("fanduel", _capture_fanduel),
    ):
        try:
            events, refs, failures = fn(captured_at=captured_dt, out_root=out_root)
            event_sets[book] = events
            raw_refs.extend(refs)
            providers[book] = {"state": "REACHABLE", "event_count": len(events), "failures": failures, "raw": refs}
        except Exception as exc:
            providers[book] = {"state": "BLOCKED", "reason": str(exc), "event_count": 0, "failures": [], "raw": []}

    poll_id = _poll_id(captured_at, raw_refs)
    bound, coverage = bind_events(
        pinnacle=event_sets["pinnacle"],
        draftkings=event_sets["draftkings"],
        fanduel=event_sets["fanduel"],
    ) if event_sets["pinnacle"] else ([], [])
    rows = build_observation_rows(bound_events=bound, capture_id=poll_id, captured_at=captured_at) if bound else []

    books_in_rows = {row["book"] for row in rows}
    if "pinnacle" not in books_in_rows or not ({"draftkings", "fanduel"} & books_in_rows):
        state = "BLOCKED"
    elif {"pinnacle", "draftkings", "fanduel"}.issubset(books_in_rows):
        state = "CAPTURED"
    else:
        state = "PARTIAL"

    rows_relative_path = None
    if rows:
        day = captured_dt.strftime("%Y/%m/%d")
        rel = Path("archive") / "market-maker-radar" / "nfl" / day / f"{poll_id}.ndjson"
        target = out_root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            raise NFLRadarCaptureError("NFL_RADAR_APPEND_ONLY_COLLISION")
        target.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
        rows_relative_path = str(rel)

    return {
        "contract": "NFL_DIRECT_MARKET_MAKER_RADAR_CAPTURE_V1",
        "state": state,
        "captured_at": captured_at,
        "capture_id": poll_id,
        "sport_key": SPORT_KEY,
        "poll_resolution_seconds": 300,
        "leadership_rule": "NO_WITHIN_POLL_LEADER_WITHOUT_DISTINCT_TRUSTWORTHY_PROVIDER_TIMESTAMPS",
        "bind_tolerance_seconds": BIND_TOLERANCE_SECONDS,
        "authority": _authority(),
        "providers": providers,
        "bound_event_count": len(bound),
        "coverage": coverage,
        "rows_written": len(rows),
        "rows_relative_path": rows_relative_path,
        "book_row_counts": {book: sum(1 for row in rows if row["book"] == book) for book in ("pinnacle", "draftkings", "fanduel")},
        "provider_required_not_captured": ["circa"],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-root", required=True)
    parser.add_argument("--status-out", required=True)
    parser.add_argument("--now", default=None)
    args = parser.parse_args(argv)
    now = _parse_ts(args.now) if args.now else None
    report = capture(out_root=Path(args.out_root), now=now)
    target = Path(args.status_out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({k: report.get(k) for k in ("state", "capture_id", "bound_event_count", "rows_written", "book_row_counts")}, sort_keys=True))
    return 0 if report["state"] in {"CAPTURED", "PARTIAL"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
