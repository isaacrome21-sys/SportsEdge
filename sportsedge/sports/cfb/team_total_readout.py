"""Full-game CFB team-total readout from the canonical joint score distribution.

This is market readout plumbing only. It does not change score simulation, fit a model,
or grant betting authority. The caller supplies the posted team-total line after the
joint distribution already exists.
"""
from __future__ import annotations

from math import isfinite
from typing import Any, Iterable, Mapping


class CFBTeamTotalReadoutError(ValueError):
    pass


def price_cfb_team_total(
    distribution: Iterable[Mapping[str, Any]],
    *,
    team_side: str,
    line: float,
) -> dict[str, float | str]:
    rows = [dict(row) for row in distribution]
    if not rows:
        raise CFBTeamTotalReadoutError("CFB_TEAM_TOTAL_DISTRIBUTION_EMPTY")

    side = str(team_side or "").strip().upper()
    if side not in {"HOME", "AWAY"}:
        raise CFBTeamTotalReadoutError(f"CFB_TEAM_TOTAL_SIDE_INVALID:{side}")

    try:
        total_line = float(line)
    except (TypeError, ValueError) as exc:
        raise CFBTeamTotalReadoutError("CFB_TEAM_TOTAL_LINE_INVALID") from exc
    if not isfinite(total_line) or total_line < 0:
        raise CFBTeamTotalReadoutError("CFB_TEAM_TOTAL_LINE_INVALID")

    key = "home_score" if side == "HOME" else "away_score"
    scores: list[float] = []
    for index, row in enumerate(rows):
        try:
            score = float(row[key])
        except (KeyError, TypeError, ValueError) as exc:
            raise CFBTeamTotalReadoutError(
                f"CFB_TEAM_TOTAL_SCORE_INVALID:{index}:{key}"
            ) from exc
        if not isfinite(score) or score < 0:
            raise CFBTeamTotalReadoutError(
                f"CFB_TEAM_TOTAL_SCORE_INVALID:{index}:{key}"
            )
        scores.append(score)

    n = float(len(scores))
    over = sum(score > total_line for score in scores) / n
    under = sum(score < total_line for score in scores) / n
    push = sum(score == total_line for score in scores) / n
    return {
        "team_side": side,
        "line": total_line,
        "over": over,
        "under": under,
        "push": push,
    }


__all__ = ["CFBTeamTotalReadoutError", "price_cfb_team_total"]
