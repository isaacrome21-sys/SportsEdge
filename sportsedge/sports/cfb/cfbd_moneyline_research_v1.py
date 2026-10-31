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
