"""Manual/hybrid MLB runner using the same joint engines as automatic mode.

Manual/hybrid controls where quotes come from; it does not change predictive logic.
Caller-supplied latest lines remain authoritative market inputs. Predictive features
are either built automatically from MLB StatsAPI or supplied as an explicit frozen
snapshot, then the same unified card pipeline is used.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Mapping, Sequence, Callable
from urllib.request import urlopen

from .edge_floors import DEFAULT_EDGE_FLOOR_CONFIG
from .live_slate import LiveGame
from .mlb_generic_features import MLBGenericHistorySource
from .mlb_joint_mode_bridge import build_feature_rows_for_quotes
from .unified_card import UnifiedCardResult, run_unified_card


def run_manual_hybrid_joint_mlb(
    *,
    games: Sequence[LiveGame],
    quotes: Sequence[Mapping[str, Any]],
    target_date: date,
    feature_rows: Sequence[Mapping[str, Any]] | None = None,
    now: datetime | None = None,
    opener: Callable = urlopen,
    registry_path: str = "config/deployments.json",
    require_confirmed_lineup: bool = True,
    edge_floor_config_path: str = DEFAULT_EDGE_FLOOR_CONFIG,
    kelly_multiplier: float = 0.25,
) -> list[UnifiedCardResult]:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    game_list = list(games); quote_list = list(quotes)
    if feature_rows is None:
        source = MLBGenericHistorySource(opener=opener, retrieved_at=current)
        resolved = build_feature_rows_for_quotes(
            games=game_list, quotes=quote_list, source=source, target_date=target_date,
        )
    else:
        resolved = [dict(row) for row in feature_rows]
    return run_unified_card(
        games=game_list, feature_rows=resolved, quotes=quote_list,
        ingestion_now=current, finalization_now=current, registry_path=registry_path,
        require_confirmed_lineup=require_confirmed_lineup,
        edge_floor_config_path=edge_floor_config_path, kelly_multiplier=kelly_multiplier,
    )
