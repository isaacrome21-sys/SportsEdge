"""Freshness-aware input contract for MLB prop/NRFI pricing.

This layer describes evidence required by the candidate/distribution engines.
It deliberately keeps trends/BvP as contextual features and never treats them
as standalone probabilities or promotion evidence.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Mapping


class InputKind(str, Enum):
    LINEUP = "LINEUP"
    WEATHER = "WEATHER"
    PARK = "PARK"
    STATCAST = "STATCAST"
    WORKLOAD = "WORKLOAD"
    BULLPEN = "BULLPEN"
    FIRST_INNING = "FIRST_INNING"
    RECENT_FORM = "RECENT_FORM"
    BVP = "BVP"
    MARKET = "MARKET"


DEFAULT_TTL_SECONDS: dict[InputKind, int] = {
    InputKind.LINEUP: 20 * 60,
    InputKind.WEATHER: 60 * 60,
    InputKind.PARK: 7 * 24 * 60 * 60,
    InputKind.STATCAST: 48 * 60 * 60,
    InputKind.WORKLOAD: 12 * 60 * 60,
    InputKind.BULLPEN: 12 * 60 * 60,
    InputKind.FIRST_INNING: 48 * 60 * 60,
    InputKind.RECENT_FORM: 48 * 60 * 60,
    InputKind.BVP: 7 * 24 * 60 * 60,
    InputKind.MARKET: 10 * 60,
}


@dataclass(frozen=True)
class InputDatum:
    name: str
    value: float | str | bool
    kind: InputKind
    as_of_utc: str
    source: str

    def age_seconds(self, now_utc: datetime | None = None) -> float:
        now = now_utc or datetime.now(timezone.utc)
        ts = datetime.fromisoformat(self.as_of_utc.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return max(0.0, (now - ts.astimezone(timezone.utc)).total_seconds())

    def is_fresh(self, now_utc: datetime | None = None, ttl_overrides: Mapping[InputKind, int] | None = None) -> bool:
        ttl = dict(DEFAULT_TTL_SECONDS)
        if ttl_overrides:
            ttl.update(ttl_overrides)
        return self.age_seconds(now_utc) <= ttl[self.kind]


@dataclass(frozen=True)
class InputAudit:
    usable: bool
    missing: tuple[str, ...]
    stale: tuple[str, ...]
    present: tuple[str, ...]


def audit_required_inputs(
    inputs: Mapping[str, InputDatum],
    required: tuple[str, ...],
    *,
    now_utc: datetime | None = None,
) -> InputAudit:
    missing: list[str] = []
    stale: list[str] = []
    present: list[str] = []
    for name in required:
        datum = inputs.get(name)
        if datum is None:
            missing.append(name)
            continue
        present.append(name)
        if not datum.is_fresh(now_utc):
            stale.append(name)
    return InputAudit(not missing and not stale, tuple(missing), tuple(stale), tuple(present))


PITCHER_PROP_REQUIRED = (
    "pitcher_k_rate", "pitcher_bb_rate", "pitcher_xba", "pitcher_xwoba",
    "pitch_count_recent", "workload_limit", "opponent_k_rate_vs_hand",
    "opponent_whiff_rate_vs_hand", "confirmed_lineup",
)

HITTER_PROP_REQUIRED = (
    "confirmed_lineup", "projected_pa", "batter_contact_rate", "batter_xwoba",
    "opposing_pitcher_xba", "opposing_pitcher_hard_hit", "bullpen_xfip",
    "park_run_factor", "weather_run_factor",
)

NRFI_REQUIRED = (
    "home_pitcher_nrfi_rate", "away_pitcher_nrfi_rate",
    "home_offense_first_inning_woba", "away_offense_first_inning_woba",
    "home_offense_first_inning_runs_per_game", "away_offense_first_inning_runs_per_game",
    "confirmed_lineup", "park_run_factor", "weather_run_factor",
)

# Research/context only: never sufficient by themselves for a release.
CONTEXT_ONLY = (
    "recent_hit_rate", "recent_k_ladder_rate", "recent_hits_allowed_rate",
    "bvp_batting_average", "bvp_home_runs", "last7_bullpen_era",
)


def promotion_evidence() -> bool:
    return False
