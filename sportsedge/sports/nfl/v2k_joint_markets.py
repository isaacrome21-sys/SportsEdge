"""Research-only market derivation from V2K joint score paths.

One path set produces ML, spread, total, and team totals. Signed key-number
mass is measured, never forced. No Model_P / pricing / promotion authority.
"""
from __future__ import annotations

from collections import Counter
from typing import Iterable, Sequence

from .v2k_drive_core import SimulationResult

AUTHORITY = {
    "model_p": False,
    "pricing": False,
    "promotion": False,
    "staking": False,
    "run_it": False,
    "official": False,
    "untouched_readout": False,
    "development_validation_scoring": False,
}

SIGNED_KEYS = (-7, -3, 3, 7)


class V2KJointMarketError(ValueError):
    pass


def _require_fg(period: object) -> None:
    if str(period or "").strip().upper() != "FG":
        raise V2KJointMarketError("V2K_PERIOD_NOT_FULL_GAME")


def _three_way(values: Sequence[float]) -> dict[str, float]:
    if not values:
        raise V2KJointMarketError("V2K_SIMULATION_ROWS_EMPTY")
    n = float(len(values))
    return {
        "win": sum(v > 0 for v in values) / n,
        "loss": sum(v < 0 for v in values) / n,
        "push": sum(v == 0 for v in values) / n,
    }


def signed_key_mass(margins: Sequence[int]) -> dict[str, float]:
    if not margins:
        raise V2KJointMarketError("V2K_SIMULATION_ROWS_EMPTY")
    n = float(len(margins))
    counts = Counter(int(m) for m in margins)
    return {str(k): counts.get(k, 0) / n for k in SIGNED_KEYS}


def derive_v2k_full_game_markets(
    results: Iterable[SimulationResult],
    *,
    period: str,
    home_team: str,
    away_team: str,
    spread_line: float,
    total_line: float,
    home_team_total_line: float | None = None,
    away_team_total_line: float | None = None,
) -> dict[str, object]:
    _require_fg(period)
    rows = list(results)
    if not rows:
        raise V2KJointMarketError("V2K_SIMULATION_ROWS_EMPTY")
    if home_team == away_team:
        raise V2KJointMarketError("V2K_TEAM_IDENTITY_INVALID")

    homes = [int(r.home_score) for r in rows]
    aways = [int(r.away_score) for r in rows]
    margins = [h - a for h, a in zip(homes, aways)]
    totals = [h + a for h, a in zip(homes, aways)]
    if any(h + a != r.total or h - a != r.margin for h, a, r in zip(homes, aways, rows)):
        raise V2KJointMarketError("V2K_PATH_CONSERVATION_BROKEN")

    ml = _three_way([float(m) for m in margins])
    spread = _three_way([m + float(spread_line) for m in margins])
    total = _three_way([t - float(total_line) for t in totals])

    out: dict[str, object] = {
        "period": "FG",
        "n_paths": len(rows),
        "moneyline": {
            "home_win": ml["win"],
            "away_win": ml["loss"],
            "tie": ml["push"],
        },
        "spread": {
            "home_line": float(spread_line),
            "home_cover": spread["win"],
            "away_cover": spread["loss"],
            "push": spread["push"],
        },
        "total": {
            "line": float(total_line),
            "over": total["win"],
            "under": total["loss"],
            "push": total["push"],
        },
        "signed_key_mass": signed_key_mass(margins),
        "authority": dict(AUTHORITY),
        "home_team": home_team,
        "away_team": away_team,
    }
    if home_team_total_line is not None:
        tw = _three_way([h - float(home_team_total_line) for h in homes])
        out["home_team_total"] = {
            "line": float(home_team_total_line),
            "over": tw["win"],
            "under": tw["loss"],
            "push": tw["push"],
        }
    if away_team_total_line is not None:
        tw = _three_way([a - float(away_team_total_line) for a in aways])
        out["away_team_total"] = {
            "line": float(away_team_total_line),
            "over": tw["win"],
            "under": tw["loss"],
            "push": tw["push"],
        }
    return out
