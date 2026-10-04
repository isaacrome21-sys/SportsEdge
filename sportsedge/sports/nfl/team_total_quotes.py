"""Fail-closed NFL team-total quote acquisition and diagnostic binding.

Sportsbook team-total lines are consumed only after the exact canonical
score-distribution handoff has been verified. This module remains diagnostic:
it cannot create Model_P, promotion, Truth Gate, OFFICIAL, or staking authority.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from math import isfinite
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from sportsedge.odds_keyring import fetch_with_key_failover
from sportsedge.sports.nfl.team_total_handoff import (
    price_verified_team_totals,
    verify_team_total_distribution_handoff,
)

_BASE = "https://api.the-odds-api.com/v4"
_SPORT = "americanfootball_nfl"
_PROVIDER_MARKET = "team_totals"
_DEFAULT_BOOK = "draftkings"
_DEFAULT_TTL_SECONDS = 180


class NFLTeamTotalQuoteError(ValueError):
    pass


def _dt(value: Any, error: str) -> datetime:
    raw = str(value or "").strip().replace("Z", "+00:00")
    if not raw:
        raise NFLTeamTotalQuoteError(error)
    try:
        out = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise NFLTeamTotalQuoteError(error) from exc
    if out.tzinfo is None or out.utcoffset() is None:
        raise NFLTeamTotalQuoteError(error)
    return out.astimezone(timezone.utc)


def _num(value: Any, error: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise NFLTeamTotalQuoteError(error) from exc
    if not isfinite(out):
        raise NFLTeamTotalQuoteError(error)
    return out


def _american_decimal(value: Any) -> float:
    odds = _num(value, "NFL_TEAM_TOTAL_PRICE_INVALID")
    if -100.0 < odds < 100.0:
        raise NFLTeamTotalQuoteError("NFL_TEAM_TOTAL_PRICE_INVALID")
    return 1.0 + (100.0 / abs(odds) if odds < 0 else odds / 100.0)


def _implied(value: Any) -> float:
    return 1.0 / _american_decimal(value)


def build_nfl_team_total_url(*, event_id: str, book_key: str = _DEFAULT_BOOK) -> str:
    event = str(event_id or "").strip()
    book = str(book_key or "").strip().lower()
    if not event or "/" in event:
        raise NFLTeamTotalQuoteError("NFL_TEAM_TOTAL_EVENT_ID_INVALID")
    if not book:
        raise NFLTeamTotalQuoteError("NFL_TEAM_TOTAL_BOOK_REQUIRED")
    params = {
        "regions": "us",
        "bookmakers": book,
        "markets": _PROVIDER_MARKET,
        "oddsFormat": "american",
        "dateFormat": "iso",
    }
    return f"{_BASE}/sports/{_SPORT}/events/{event}/odds?{urlencode(params)}"


def _http_fetch(url_without_key: str, key: str) -> Any:
    sep = "&" if "?" in url_without_key else "?"
    url = f"{url_without_key}{sep}{urlencode({'apiKey': key})}"
    with urlopen(
        Request(url, headers={"Accept": "application/json", "User-Agent": "SportsEdge-NFL-TeamTotals/1"}),
        timeout=20,
    ) as response:
        raw = response.read()
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise NFLTeamTotalQuoteError("NFL_TEAM_TOTAL_RESPONSE_JSON_INVALID") from exc


def fetch_nfl_team_total_event(
    api_keys: Sequence[str],
    *,
    event_id: str,
    book_key: str = _DEFAULT_BOOK,
    fetcher: Callable[[str, str], Any] = _http_fetch,
):
    base = build_nfl_team_total_url(event_id=event_id, book_key=book_key)
    result = fetch_with_key_failover(list(api_keys), lambda key: fetcher(base, key))
    if not isinstance(result.value, Mapping):
        raise NFLTeamTotalQuoteError("NFL_TEAM_TOTAL_EVENT_RESPONSE_NOT_OBJECT")
    return result


def _selected_book(event: Mapping[str, Any], book_key: str) -> Mapping[str, Any]:
    books = event.get("bookmakers")
    if not isinstance(books, list):
        raise NFLTeamTotalQuoteError("NFL_TEAM_TOTAL_BOOKMAKERS_REQUIRED")
    matches = [
        row for row in books
        if isinstance(row, Mapping)
        and str(row.get("key") or "").strip().lower() == book_key
    ]
    if len(matches) != 1:
        raise NFLTeamTotalQuoteError(f"NFL_TEAM_TOTAL_BOOK_COUNT_INVALID:{len(matches)}")
    return matches[0]


def _selected_market(book: Mapping[str, Any]) -> Mapping[str, Any]:
    markets = book.get("markets")
    if not isinstance(markets, list):
        raise NFLTeamTotalQuoteError("NFL_TEAM_TOTAL_MARKETS_REQUIRED")
    matches = [
        row for row in markets
        if isinstance(row, Mapping)
        and str(row.get("key") or "").strip().lower() == _PROVIDER_MARKET
    ]
    if len(matches) != 1:
        raise NFLTeamTotalQuoteError(f"NFL_TEAM_TOTAL_MARKET_COUNT_INVALID:{len(matches)}")
    return matches[0]


def parse_nfl_team_total_pairs(
    event: Mapping[str, Any],
    *,
    now: datetime,
    expected_event_id: str,
    book_key: str = _DEFAULT_BOOK,
    ttl_seconds: int = _DEFAULT_TTL_SECONDS,
) -> dict[str, Any]:
    current = _dt(now.isoformat(), "NFL_TEAM_TOTAL_NOW_INVALID")
    event_id = str(event.get("id") or "").strip()
    if event_id != str(expected_event_id or "").strip():
        raise NFLTeamTotalQuoteError("NFL_TEAM_TOTAL_EVENT_ID_MISMATCH")
    if str(event.get("sport_key") or "") not in ("", _SPORT):
        raise NFLTeamTotalQuoteError("NFL_TEAM_TOTAL_SPORT_KEY_MISMATCH")
    start = _dt(event.get("commence_time"), "NFL_TEAM_TOTAL_EVENT_START_INVALID")
    if current >= start:
        raise NFLTeamTotalQuoteError("NFL_TEAM_TOTAL_EVENT_NOT_PREGAME")

    book = _selected_book(event, str(book_key or "").strip().lower())
    market = _selected_market(book)
    observed = _dt(
        market.get("last_update") or book.get("last_update"),
        "NFL_TEAM_TOTAL_LAST_UPDATE_REQUIRED",
    )
    if observed > current:
        raise NFLTeamTotalQuoteError("NFL_TEAM_TOTAL_QUOTE_FROM_FUTURE")
    if observed >= start:
        raise NFLTeamTotalQuoteError("NFL_TEAM_TOTAL_QUOTE_NOT_PREGAME")
    if (current - observed).total_seconds() > int(ttl_seconds):
        raise NFLTeamTotalQuoteError("NFL_TEAM_TOTAL_QUOTE_STALE")

    home = str(event.get("home_team") or "").strip()
    away = str(event.get("away_team") or "").strip()
    if not home or not away or home == away:
        raise NFLTeamTotalQuoteError("NFL_TEAM_TOTAL_EVENT_TEAM_IDENTITY_INVALID")

    raw = market.get("outcomes")
    if not isinstance(raw, list):
        raise NFLTeamTotalQuoteError("NFL_TEAM_TOTAL_OUTCOMES_REQUIRED")

    grouped: dict[str, dict[str, dict[str, float]]] = {home: {}, away: {}}
    for row in raw:
        if not isinstance(row, Mapping):
            raise NFLTeamTotalQuoteError("NFL_TEAM_TOTAL_OUTCOME_INVALID")
        team = str(row.get("description") or "").strip()
        if team not in grouped:
            raise NFLTeamTotalQuoteError(f"NFL_TEAM_TOTAL_TEAM_UNRESOLVED:{team or 'MISSING'}")
        side = str(row.get("name") or "").strip().upper()
        if side not in {"OVER", "UNDER"}:
            raise NFLTeamTotalQuoteError(f"NFL_TEAM_TOTAL_SIDE_INVALID:{side or 'MISSING'}")
        if side in grouped[team]:
            raise NFLTeamTotalQuoteError(f"NFL_TEAM_TOTAL_DUPLICATE_SIDE:{team}:{side}")
        line = _num(row.get("point"), "NFL_TEAM_TOTAL_LINE_INVALID")
        if line < 0:
            raise NFLTeamTotalQuoteError("NFL_TEAM_TOTAL_LINE_INVALID")
        price = _num(row.get("price"), "NFL_TEAM_TOTAL_PRICE_INVALID")
        _american_decimal(price)
        grouped[team][side] = {"line": line, "price": price}

    pairs: dict[str, dict[str, Any]] = {}
    for label, team in (("home", home), ("away", away)):
        sides = grouped[team]
        if set(sides) != {"OVER", "UNDER"}:
            raise NFLTeamTotalQuoteError(f"NFL_TEAM_TOTAL_PAIRED_PRICE_REQUIRED:{label}")
        if abs(sides["OVER"]["line"] - sides["UNDER"]["line"]) > 1e-9:
            raise NFLTeamTotalQuoteError(f"NFL_TEAM_TOTAL_LINE_PAIR_MISMATCH:{label}")
        over_i = _implied(sides["OVER"]["price"])
        under_i = _implied(sides["UNDER"]["price"])
        hold_sum = over_i + under_i
        if hold_sum <= 0:
            raise NFLTeamTotalQuoteError("NFL_TEAM_TOTAL_DEVIG_INVALID")
        pairs[label] = {
            "team": team,
            "line": sides["OVER"]["line"],
            "over_price": sides["OVER"]["price"],
            "under_price": sides["UNDER"]["price"],
            "over_fair_market_p": over_i / hold_sum,
            "under_fair_market_p": under_i / hold_sum,
            "hold": hold_sum - 1.0,
        }

    return {
        "event_id": event_id,
        "book_key": str(book.get("key") or "").strip().lower(),
        "sportsbook": str(book.get("title") or book.get("key") or "").strip(),
        "observed_at": observed.isoformat(),
        "event_start_at": start.isoformat(),
        "home": pairs["home"],
        "away": pairs["away"],
    }


def build_verified_team_total_diagnostics(
    *,
    handoff: Mapping[str, Any],
    report: Any,
    event: Mapping[str, Any],
    now: datetime,
    book_key: str = _DEFAULT_BOOK,
    ttl_seconds: int = _DEFAULT_TTL_SECONDS,
) -> dict[str, Any]:
    """Verify score support first, then apply sportsbook team-total thresholds."""
    verified = verify_team_total_distribution_handoff(handoff, report=report)

    report_rows = [
        row for row in (
            report.to_dict().get("results", [])
            if hasattr(report, "to_dict")
            else dict(report).get("results", [])
        )
        if str(row.get("game_id") or "") == verified["game_id"]
    ]
    provider_ids = {str(row.get("provider_event_id") or "") for row in report_rows}
    if len(provider_ids) != 1 or "" in provider_ids:
        raise NFLTeamTotalQuoteError("NFL_TEAM_TOTAL_REPORT_EVENT_ID_INVALID")
    expected_event_id = next(iter(provider_ids))

    quotes = parse_nfl_team_total_pairs(
        event,
        now=now,
        expected_event_id=expected_event_id,
        book_key=book_key,
        ttl_seconds=ttl_seconds,
    )
    diagnostic = price_verified_team_totals(
        handoff=verified,
        report=report,
        home_total_line=float(quotes["home"]["line"]),
        away_total_line=float(quotes["away"]["line"]),
    )

    probs = diagnostic["probabilities"]
    rows = []
    for team_side in ("home", "away"):
        pair = quotes[team_side]
        model = probs[f"{team_side}_team_total"]
        for side in ("over", "under"):
            rows.append({
                "game_id": verified["game_id"],
                "market": f"{team_side.upper()}_TEAM_TOTAL",
                "team": pair["team"],
                "side": side.upper(),
                "line": pair["line"],
                "american_odds": pair[f"{side}_price"],
                "model_p": model[side],
                "push_p": model["push"],
                "fair_market_p": pair[f"{side}_fair_market_p"],
                "hold": pair["hold"],
                "book_key": quotes["book_key"],
                "sportsbook": quotes["sportsbook"],
                "quote_observed_at": quotes["observed_at"],
                "distribution_sha256": verified["distribution_sha256"],
                "handoff_sha256": verified["handoff_sha256"],
                "engine_status": "PRICED_DIAGNOSTIC",
                "bet_status": "BLOCKED",
                "official_eligible": False,
                "reason": "TEAM_TOTAL_MARKET_SPECIFIC_PROMOTION_EVIDENCE_REQUIRED",
            })

    return {
        "schema_version": "NFL_TEAM_TOTAL_QUOTE_DIAGNOSTIC_V1",
        "game_id": verified["game_id"],
        "event_id": expected_event_id,
        "book_key": quotes["book_key"],
        "quote_observed_at": quotes["observed_at"],
        "distribution_sha256": verified["distribution_sha256"],
        "handoff_sha256": verified["handoff_sha256"],
        "rows": rows,
        "authority": {
            "creates_model_p": False,
            "truth_gate": False,
            "official": False,
            "promotion": False,
            "staking": False,
            "changes_engine_state": False,
        },
    }


__all__ = [
    "NFLTeamTotalQuoteError",
    "build_nfl_team_total_url",
    "build_verified_team_total_diagnostics",
    "fetch_nfl_team_total_event",
    "parse_nfl_team_total_pairs",
]
