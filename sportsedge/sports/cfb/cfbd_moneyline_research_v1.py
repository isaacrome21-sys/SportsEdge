"""Research-only CFBD /lines moneyline pairs, never authenticated DK quotations.

This normalizer is opt-in via the ml_research_YEAR cache family. It retains
same-provider raw home/away pairs without choosing a favorable book or
converting missing prices to synthetic -110 values. Historical CFBD records
do not establish the quote capture time, DraftKings execution, or CLV.
"""
from __future__ import annotations

import math
import re
from typing import Any

SCHEMA = "CFB_CFBD_MONEYLINE_RESEARCH_V1"
SOURCE = "CFBD_REST_LINES"
PRICE_FIELDS = ("homeMoneyline", "awayMoneyline")
_INTEGER_TEXT = re.compile(r"[+-]?[0-9]+")


def american_odds(value: Any) -> int | None:
    """Accept only finite integral American prices with magnitude >= 100."""
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        value = value.strip()
        if not _INTEGER_TEXT.fullmatch(value):
            return None
        try:
            price = int(value)
        except ValueError:
            return None
    elif isinstance(value, (int, float)):
        try:
            if not math.isfinite(value) or not float(value).is_integer():
                return None
            price = int(value)
        except (OverflowError, TypeError, ValueError):
            return None
    else:
        return None
    return price if abs(price) >= 100 else None


def _game_key(game: dict) -> str:
    raw = game.get("id")
    if isinstance(raw, bool) or not isinstance(raw, (int, str)):
        raise ValueError("CFB_ML_RESEARCH_GAME_ID_REQUIRED")
    value = str(raw)
    if not value.isascii() or not value.isdecimal() or int(value) <= 0:
        raise ValueError("CFB_ML_RESEARCH_GAME_ID_REQUIRED")
    return str(int(value))


def normalize_moneyline_research(games: list[dict] | None) -> dict:
    """Preserve every distinct valid provider pair; fail closed on ambiguity.

    No market is priced or admitted here. In particular, the nested result
    intentionally has no `home_ml`/`moneyline` top-level key: downstream
    research must explicitly review/admit a new data source and quote clock.
    """
    out: dict[str, dict] = {}
    for game in games or []:
        if not isinstance(game, dict):
            raise ValueError("CFB_ML_RESEARCH_GAME_MAPPING_REQUIRED")
        gid = _game_key(game)
        if gid in out:
            raise ValueError("CFB_ML_RESEARCH_GAME_DUPLICATE")
        lines = game.get("lines", [])
        if lines is None:
            lines = []
        if not isinstance(lines, list):
            raise ValueError("CFB_ML_RESEARCH_LINES_LIST_REQUIRED")
        pairs_by_provider: dict[str, dict] = {}
        saw_price_field = False
        rejected_rows = 0
        conflict = False
        for line in lines:
            if not isinstance(line, dict):
                raise ValueError("CFB_ML_RESEARCH_LINE_MAPPING_REQUIRED")
            if not any(key in line for key in PRICE_FIELDS):
                continue
            saw_price_field = True
            provider = line.get("provider")
            home = american_odds(line.get("homeMoneyline"))
            away = american_odds(line.get("awayMoneyline"))
            if not isinstance(provider, str) or not provider.strip() or home is None or away is None:
                rejected_rows += 1
                continue
            canonical = provider.strip()
            pair = {
                "provider": canonical,
                "provider_raw": provider,
                "home_american": home,
                "away_american": away,
            }
            prior = pairs_by_provider.get(canonical)
            if prior is not None and (
                prior["home_american"] != home or prior["away_american"] != away
            ):
                conflict = True
                continue
            pairs_by_provider[canonical] = pair
        pairs = (
            [pairs_by_provider[name] for name in sorted(pairs_by_provider, key=str.casefold)]
            if not conflict else []
        )
        status = (
            "CONFLICTING_PROVIDER_PRICE" if conflict else
            "UNVERIFIED_RAW_PAIRS" if pairs else
            "NO_VALID_MONEYLINE_PAIR" if saw_price_field else
            "NO_MONEYLINE_FIELDS"
        )
        out[gid] = {
            "schema": SCHEMA,
            "source": SOURCE,
            "game_id": gid,
            "home_team": game.get("homeTeam"),
            "away_team": game.get("awayTeam"),
            "game_start_unverified": game.get("startDate"),
            "status": status,
            "pairs": pairs,
            "rejected_raw_rows": rejected_rows,
            "source_fields": list(PRICE_FIELDS),
            "quote_timestamp": None,
            "original_response_receipt": None,
            "authenticated_draftkings": False,
            "market_admitted": False,
            "clv_authority": False,
            "betting_authority": False,
        }
    return out

def summarize_raw_coverage(records: dict) -> dict:
    """Count *raw unverified* provider pairs; never infer DK quote admission."""
    if not isinstance(records, dict):
        raise ValueError("CFB_ML_RESEARCH_COVERAGE_MAPPING_REQUIRED")
    status_counts = {
        "UNVERIFIED_RAW_PAIRS": 0,
        "NO_VALID_MONEYLINE_PAIR": 0,
        "NO_MONEYLINE_FIELDS": 0,
        "CONFLICTING_PROVIDER_PRICE": 0,
    }
    providers: dict[str, int] = {}
    pair_rows = 0
    for gid, row in records.items():
        if (not isinstance(row, dict) or row.get("schema") != SCHEMA
                or row.get("game_id") != str(gid)):
            raise ValueError("CFB_ML_RESEARCH_COVERAGE_ROW_SCHEMA")
        status = row.get("status")
        pairs = row.get("pairs")
        if status not in status_counts or not isinstance(pairs, list):
            raise ValueError("CFB_ML_RESEARCH_COVERAGE_ROW_STATUS")
        if bool(pairs) != (status == "UNVERIFIED_RAW_PAIRS"):
            raise ValueError("CFB_ML_RESEARCH_COVERAGE_ROW_CONFLICT")
        if (row.get("source") != SOURCE
                or row.get("source_fields") != list(PRICE_FIELDS)
                or row.get("authenticated_draftkings") is not False
                or row.get("market_admitted") is not False
                or row.get("clv_authority") is not False
                or row.get("betting_authority") is not False
                or row.get("quote_timestamp") is not None
                or row.get("original_response_receipt") is not None):
            raise ValueError("CFB_ML_RESEARCH_COVERAGE_UNVERIFIED_ONLY")
        status_counts[status] += 1
        seen_providers: set[str] = set()
        for pair in pairs:
            if not isinstance(pair, dict) or not isinstance(pair.get("provider"), str):
                raise ValueError("CFB_ML_RESEARCH_COVERAGE_PAIR_SCHEMA")
            provider = pair["provider"]
            home = pair.get("home_american")
            away = pair.get("away_american")
            raw_provider = pair.get("provider_raw")
            if (not provider.strip() or provider != provider.strip()
                    or not isinstance(raw_provider, str)
                    or raw_provider.strip() != provider
                    or type(home) is not int or type(away) is not int
                    or american_odds(home) != home
                    or american_odds(away) != away):
                raise ValueError("CFB_ML_RESEARCH_COVERAGE_PAIR_INVALID")
            if provider in seen_providers:
                raise ValueError("CFB_ML_RESEARCH_COVERAGE_PAIR_DUPLICATE")
            seen_providers.add(provider)
            providers[provider] = providers.get(provider, 0) + 1
            pair_rows += 1
    return {
        "schema": "CFB_CFBD_ML_RAW_COVERAGE_V1",
        "status": ("EMPTY_NO_SOURCE_OBSERVATIONS" if not records
                   else "RAW_FIELD_COVERAGE_ONLY_NOT_ADMITTED"),
        "games_seen": len(records),
        "games_with_raw_pairs": status_counts["UNVERIFIED_RAW_PAIRS"],
        "raw_provider_pair_rows": pair_rows,
        "raw_provider_counts": dict(sorted(providers.items())),
        "games_by_status": status_counts,
        "verified_draftkings_quote_games": 0,
        "source_quote_timestamps_verified": 0,
        "moneyline_market_admitted": False,
        "actual_roi_or_clv_authority": False,
    }
