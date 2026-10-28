"""Sport adapters: market-name and team-name mapping only.

An adapter never parses a line and never prices anything. It answers two
questions for the shared parser: "what canonical market is this label?" and
"which team is this text?". Canonical market names are each sport's existing
names, so downstream engines see exactly what they saw before.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass(frozen=True)
class MarketSpec:
    market: str
    family: str                         # moneyline | spread | total | team_total | prop | yes_no
    sides: tuple[str, str]
    needs_line: bool
    subject: str | None = None          # None | "team" | "player"
    swap: bool = False                  # entered prices are (side_b, side_a)
    fixed_line: float | None = None     # line for markets entered without one


def _key(text: str) -> str:
    return re.sub(r"[^a-z0-9+]", "", str(text).lower())


ML = ("moneyline", ("AWAY", "HOME"), False)
SPREAD = ("spread", ("AWAY", "HOME"), True)
TOTAL = ("total", ("OVER", "UNDER"), True)


def _spec(name: str, kind: tuple, **kw) -> MarketSpec:
    family, sides, needs = kind
    return MarketSpec(name, family, sides, needs, **kw)


def _ou(name: str, subject: str) -> MarketSpec:
    fam = "team_total" if subject == "team" else "prop"
    return MarketSpec(name, fam, ("OVER", "UNDER"), True, subject=subject)


@dataclass
class SportAdapter:
    sport: str
    markets: dict[str, MarketSpec]
    resolve: Callable[[str], str] = field(default=lambda text: " ".join(str(text).split()))

    def market(self, label: str) -> MarketSpec | None:
        return self.markets.get(_key(label))

    def team(self, text: str) -> str:
        from .intake import SharedIntakeError
        try:
            return self.resolve(text)
        except SharedIntakeError:
            raise
        except ValueError as exc:
            raise SharedIntakeError(str(exc)) from exc


def _table(rows: dict[str, MarketSpec]) -> dict[str, MarketSpec]:
    out: dict[str, MarketSpec] = {}
    for labels, spec in rows.items():
        for label in labels.split("|"):
            out[_key(label)] = spec
    return out


def _nfl_team(text: str) -> str:
    from sportsedge.nfl_team_aliases import resolve_team
    return resolve_team(text)


def _nba_team(text: str) -> str:
    from sportsedge.sports.nba.lines_card import team_abbr
    return team_abbr(text)


_NFL_PROPS = {
    "passattempts|passingattempts": "pass_attempts",
    "completions": "completions",
    "passyards|passingyards": "passing_yards",
    "passtds|passingtouchdowns": "pass_tds",
    "interceptions|ints": "interceptions",
    "rushattempts|rushingattempts|carries": "rush_attempts",
    "rushyards|rushingyards": "rushing_yards",
    "receptions|catches": "receptions",
    "receivingyards|recyards": "receiving_yards",
    "rushreceivingyards|rushrec": "rush_receiving_yards",
    "receivingtds": "receiving_tds",
    "rushingtds": "rushing_tds",
    "anytimetds|anytimetd|attd": "anytime_tds",
}

NFL = SportAdapter("NFL", _table({
    "ml|moneyline": _spec("moneyline", ML),
    "spread|rl|line": _spec("spread", SPREAD),
    "total|ou": _spec("total", TOTAL),
    "teamtotal|tt|team_total": _ou("team_total", "team"),
    **{labels: _ou(name, "player") for labels, name in _NFL_PROPS.items()},
}), _nfl_team)

CFB = SportAdapter("CFB", _table({
    "ml|moneyline": _spec("MONEYLINE", ML),
    "spread|sp|line": _spec("SPREAD", SPREAD),
    "total|ou": _spec("TOTAL", TOTAL),
    "teamtotal|tt": _ou("TEAM_TOTAL", "team"),
}))

# CBB mirrors the CFB table exactly: the canonical names (MONEYLINE /
# SPREAD / TOTAL / TEAM_TOTAL) are the ones the CBB forward runners
# consume from the shared parser's output (games_from_board). Team
# names use the default resolver — DK display names pass through
# whitespace-normalized. There is deliberately NO DK-name alias table:
# the admitted crosswalk (PR #2898) does not map DK names, and identity
# is fixture-supplied, never name-derived. The intake wrapper that
# enforces the CBB-specific rules (strict unknown labels, comment
# event ids, the Illinois exclusion) is sportsedge/cbb_lines_intake.py.
CBB = SportAdapter("CBB", _table({
    "ml|moneyline": _spec("MONEYLINE", ML),
    "spread|sp|line": _spec("SPREAD", SPREAD),
    "total|ou": _spec("TOTAL", TOTAL),
    "teamtotal|tt": _ou("TEAM_TOTAL", "team"),
}))

def _period_total(name: str) -> MarketSpec:
    return MarketSpec(name, "period_total", ("OVER", "UNDER"), True)


def _period_team_total(name: str) -> MarketSpec:
    return MarketSpec(name, "team_period_total", ("OVER", "UNDER"), True,
                      subject="team")


# NBA period totals (prereg draft PR #2843 §2/§4.2): game and team totals
# for the four quarters and two halves. The canonical names encode the
# window, following the FIRST_FIVE_* precedent; the prereg subfamily of
# each name is derived in sportsedge/nba_period_lines_intake.py.
_NBA_PERIODS = {
    "q1total": _period_total("Q1_TOTAL"),
    "q2total": _period_total("Q2_TOTAL"),
    "q3total": _period_total("Q3_TOTAL"),
    "q4total": _period_total("Q4_TOTAL"),
    "1htotal|firsthalftotal": _period_total("FIRST_HALF_TOTAL"),
    "2htotal|secondhalftotal": _period_total("SECOND_HALF_TOTAL"),
    "q1tt|q1teamtotal": _period_team_total("Q1_TEAM_TOTAL"),
    "q2tt|q2teamtotal": _period_team_total("Q2_TEAM_TOTAL"),
    "q3tt|q3teamtotal": _period_team_total("Q3_TEAM_TOTAL"),
    "q4tt|q4teamtotal": _period_team_total("Q4_TEAM_TOTAL"),
    "1htt|1hteamtotal|firsthalfteamtotal": _period_team_total("FIRST_HALF_TEAM_TOTAL"),
    "2htt|2hteamtotal|secondhalfteamtotal": _period_team_total("SECOND_HALF_TEAM_TOTAL"),
}

NBA = SportAdapter("NBA", _table({
    "ml|moneyline": _spec("MONEYLINE", ML),
    "spread|sp|ps": _spec("SPREAD", SPREAD),
    "total|ou|o/u": _spec("TOTAL", TOTAL),
    **_NBA_PERIODS,
}), _nba_team)

NHL = SportAdapter("NHL", _table({
    "ml|moneyline": _spec("MONEYLINE", ML),
    "pl|puck|puckline|spread": _spec("PUCK_LINE", SPREAD),
    "total|ou": _spec("TOTAL", TOTAL),
}))

MLB = SportAdapter("MLB", _table({
    "ml|moneyline": _spec("MONEYLINE", ML),
    "rl|runline|spread": _spec("RUN_LINE", SPREAD),
    "total|ou|gametotal": _spec("GAME_TOTAL", TOTAL),
    "f5ml|first5ml|f5moneyline": _spec("FIRST_FIVE_MONEYLINE", ML),
    "f5rl|first5rl|f5runline": _spec("FIRST_FIVE_RUN_LINE", SPREAD),
    "f5total|first5total": _spec("FIRST_FIVE_TOTAL", TOTAL),
    "tt|teamtotal": _ou("TEAM_TOTAL", "team"),
    "yrfi": MarketSpec("FIRST_INNING_TOTAL", "yes_no", ("OVER", "UNDER"), False, fixed_line=0.5),
    "nrfi": MarketSpec("FIRST_INNING_TOTAL", "yes_no", ("OVER", "UNDER"), False, swap=True, fixed_line=0.5),
    "k|ks|strikeouts": _ou("PITCHER_STRIKEOUTS", "player"),
    "outs": _ou("PITCHER_OUTS", "player"),
    "hits": _ou("BATTER_HITS", "player"),
    "tb|totalbases": _ou("BATTER_TOTAL_BASES", "player"),
}))

ADAPTERS = {a.sport: a for a in (MLB, NFL, CFB, NBA, NHL, CBB)}


def adapter_for(sport: str) -> SportAdapter:
    try:
        return ADAPTERS[str(sport).upper()]
    except KeyError as exc:
        raise ValueError(f"UNKNOWN_SPORT:{sport}") from exc
