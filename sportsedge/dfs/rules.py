from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SportRules:
    sport: str
    salary_cap: int
    slots: tuple[str, ...]
    max_hitters_per_team: int | None = None
    min_teams: int = 2


RULES: dict[str, SportRules] = {
    "MLB": SportRules(
        sport="MLB",
        salary_cap=50_000,
        slots=("P", "P", "C", "1B", "2B", "3B", "SS", "OF", "OF", "OF"),
        max_hitters_per_team=5,
    ),
    "NFL": SportRules(
        sport="NFL",
        salary_cap=50_000,
        slots=("QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX", "DST"),
    ),
    "CFB": SportRules(
        sport="CFB",
        salary_cap=50_000,
        slots=("QB", "RB", "RB", "WR", "WR", "WR", "FLEX", "SUPERFLEX"),
    ),
}


def get_rules(sport: str) -> SportRules:
    key = sport.upper()
    if key not in RULES:
        raise ValueError(f"DFS_UNSUPPORTED_SPORT:{sport}")
    return RULES[key]
