"""Regular-season OT regimes for the isolated possession challenger.

No production/holdout authority. Source notes and limits are recorded in
NFL_CHALLENGER_OT_AND_SEED_PROTOCOL_20260920.md.
"""
from dataclasses import dataclass
from numbers import Integral


@dataclass(frozen=True)
class ChallengerOTRules:
    regime_id: str
    period_seconds: int
    opening_td_ends_game: bool


def regular_season_ot_rules(season: int) -> ChallengerOTRules:
    if isinstance(season, bool) or not isinstance(season, Integral) or not 2016 <= season <= 2026:
        raise ValueError("CHALLENGER_REGULAR_SEASON_OT_REGIME_UNSUPPORTED")
    if season == 2016:
        return ChallengerOTRules("REG_2016", 900, True)
    if season <= 2024:
        return ChallengerOTRules("REG_2017_2024", 600, True)
    return ChallengerOTRules("REG_2025_2026", 600, False)
