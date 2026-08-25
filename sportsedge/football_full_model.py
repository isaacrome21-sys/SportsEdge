"""Stage-0 football full-model orchestration primitives.

Coverage is declared from config before acquisition. Provider responses can only
set acquisition state on pre-existing slots; they never define the market grid.
The run/card status is delegated to the shared sport-agnostic state contract.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import json
from pathlib import Path
from typing import Iterable

from sportsedge.core.run_state import SlotState, classify_acquisition, summarize_run


@dataclass(frozen=True)
class FootballMarketSlot:
    game_id: str
    sport: str
    family: str
    market: str
    required_engines: tuple[str, ...]
    acquisition: str
    engine: str = "INPUT_MISSING"
    decision: str | None = None

    def with_engine(self, engine: str) -> "FootballMarketSlot":
        return replace(self, engine=str(engine), decision=None)

    def with_decision(self, decision: str | None) -> "FootballMarketSlot":
        return replace(self, decision=None if decision is None else str(decision))


def _load_surface(surface_path: str | Path) -> dict:
    data = json.loads(Path(surface_path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("FOOTBALL_SURFACE_NOT_OBJECT")
    markets = data.get("markets")
    sports = data.get("sports")
    if not isinstance(markets, list) or not markets:
        raise ValueError("FOOTBALL_SURFACE_MARKETS_REQUIRED")
    if not isinstance(sports, list) or not sports:
        raise ValueError("FOOTBALL_SURFACE_SPORTS_REQUIRED")
    return data


def build_declared_market_grid(
    *,
    game_id: str,
    sport: str,
    surface_path: str | Path,
    provider_supported_markets: Iterable[str],
    request_succeeded: bool,
    offered_markets: Iterable[str],
) -> list[FootballMarketSlot]:
    """Build one slot per declared market before applying provider availability."""
    data = _load_surface(surface_path)
    sport_name = str(sport).strip().upper()
    if sport_name not in {str(x).strip().upper() for x in data["sports"]}:
        raise ValueError(f"UNSUPPORTED_FOOTBALL_SPORT:{sport_name}")
    if not str(game_id).strip():
        raise ValueError("GAME_ID_REQUIRED")

    supported = {str(x).strip() for x in provider_supported_markets}
    offered = {str(x).strip() for x in offered_markets}
    unknown_offers = offered - {str(row.get("market", "")) for row in data["markets"] if isinstance(row, dict)}
    if unknown_offers:
        raise ValueError(f"PROVIDER_RETURNED_UNDECLARED_MARKET:{sorted(unknown_offers)[0]}")

    rows: list[FootballMarketSlot] = []
    seen: set[str] = set()
    for raw in data["markets"]:
        if not isinstance(raw, dict):
            raise ValueError("FOOTBALL_SURFACE_MARKET_NOT_OBJECT")
        market = str(raw.get("market", "")).strip()
        family = str(raw.get("family", "")).strip()
        engines = tuple(str(x).strip() for x in raw.get("engines", ()))
        if not market or not family or not engines:
            raise ValueError("FOOTBALL_SURFACE_MARKET_INVALID")
        if market in seen:
            raise ValueError(f"DUPLICATE_DECLARED_MARKET:{market}")
        seen.add(market)
        provider_supported = market in supported
        acquisition = classify_acquisition(
            provider_supported=provider_supported,
            request_succeeded=bool(request_succeeded),
            offer_found=market in offered,
        )
        rows.append(FootballMarketSlot(
            game_id=str(game_id),
            sport=sport_name,
            family=family,
            market=market,
            required_engines=engines,
            acquisition=acquisition,
        ))
    return rows


def finalize_football_run(slots: Iterable[FootballMarketSlot]):
    """Return shared run/card health after engine and decision states are attached."""
    materialized = list(slots)
    return summarize_run(
        SlotState(
            game_id=row.game_id,
            market=row.market,
            acquisition=row.acquisition,
            engine=row.engine,
            decision=row.decision,
        )
        for row in materialized
    )
