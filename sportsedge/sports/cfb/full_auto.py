from __future__ import annotations

from typing import Any, Callable, Iterable, Mapping
from urllib.request import urlopen

from .auto_slate import build_cfb_auto_context_slate
from .context_autopull import ContextObservation
from .season_priors_provider_factory import build_cfbd_season_priors_provider_factory


def build_cfb_full_auto_slate(
    *,
    as_of: Any,
    cfbd_api_key: str,
    season: int | None = None,
    mode: str = "AUTO",
    min_lead_minutes: int = 0,
    horizon_minutes: int = 7 * 24 * 60,
    manual_observations_by_game: Mapping[str, Iterable[ContextObservation]] | None = None,
    opener: Callable = urlopen,
) -> dict[str, Any]:
    """Canonical CFB objective-context AUTO/HYBRID entry point.

    The operator supplies no game list. The FBS slate is discovered from CFBD,
    then objective weather, prior-only advanced metrics/matchups, season returning
    production, team talent and prior-season player-usage baselines are acquired.
    Prior-season usage is deliberately partial context, not a claim about current
    snaps/depth. Unsupported trusted classes remain explicit MISSING_PROVIDER;
    market/social data are never requested by this lane.
    """
    return build_cfb_auto_context_slate(
        as_of=as_of,
        cfbd_api_key=cfbd_api_key,
        season=season,
        mode=mode,
        min_lead_minutes=min_lead_minutes,
        horizon_minutes=horizon_minutes,
        provider_factory=build_cfbd_season_priors_provider_factory(cfbd_api_key=cfbd_api_key, opener=opener),
        manual_observations_by_game=manual_observations_by_game,
        opener=opener,
    )
