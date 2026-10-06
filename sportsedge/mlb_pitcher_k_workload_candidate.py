"""Research-only workload bundle for the preregistered MLB pitcher-K candidate.

This module deliberately does not price a market or alter production features. It
compresses already-fetched strictly-prior pitching game-log rows into an immutable
workload/skill bundle that can later be evaluated on untouched PIT data.
"""
from __future__ import annotations

from statistics import fmean
from typing import Any, Mapping, Sequence

AUTHORITY = "RESEARCH_ONLY_NOT_MODEL_INPUT_NOT_DEPLOYED"
MIN_STARTS = 5
MAX_STARTS = 10


class PitcherKWorkloadCandidateError(ValueError):
    pass


def _nonnegative_int(value: Any, name: str) -> int:
    if isinstance(value, bool):
        raise PitcherKWorkloadCandidateError(f"{name} must be an integer")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise PitcherKWorkloadCandidateError(f"{name} must be an integer") from exc
    if number < 0 or not number.is_integer():
        raise PitcherKWorkloadCandidateError(f"{name} must be a nonnegative integer")
    return int(number)


def _outs_from_ip(value: Any) -> int:
    text = str(value or "").strip()
    if not text:
        raise PitcherKWorkloadCandidateError("inningsPitched missing")
    if "." not in text:
        return int(text) * 3
    whole, frac = text.split(".", 1)
    if frac not in {"0", "1", "2"}:
        raise PitcherKWorkloadCandidateError("inningsPitched uses invalid baseball notation")
    return int(whole) * 3 + int(frac)


def _stat_row(raw: Mapping[str, Any], index: int) -> dict[str, int]:
    stat = raw.get("stat") if isinstance(raw.get("stat"), Mapping) else raw
    if not isinstance(stat, Mapping):
        raise PitcherKWorkloadCandidateError(f"row {index} missing stat object")
    if _nonnegative_int(stat.get("gamesStarted", 0), f"row {index}.gamesStarted") < 1:
        raise PitcherKWorkloadCandidateError(f"row {index} is not a start")
    bf = _nonnegative_int(stat.get("battersFaced"), f"row {index}.battersFaced")
    pitches = _nonnegative_int(stat.get("numberOfPitches"), f"row {index}.numberOfPitches")
    strikeouts = _nonnegative_int(stat.get("strikeOuts"), f"row {index}.strikeOuts")
    outs = _outs_from_ip(stat.get("inningsPitched"))
    if bf <= 0 or pitches <= 0 or outs < 0 or outs > 27 or strikeouts > bf:
        raise PitcherKWorkloadCandidateError(f"row {index} has impossible workload values")
    return {
        "batters_faced": bf,
        "number_of_pitches": pitches,
        "strikeouts": strikeouts,
        "outs": outs,
    }


def build_workload_bundle(prior_starts: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Build a fixed, outcome-blind candidate bundle from 5-10 prior starts.

    The input order is preserved so a later preregistered evaluator can choose a
    temporal weighting rule without refetching or reconstructing history.
    """
    if isinstance(prior_starts, (str, bytes)) or not isinstance(prior_starts, Sequence):
        raise PitcherKWorkloadCandidateError("prior_starts must be a sequence")
    if not MIN_STARTS <= len(prior_starts) <= MAX_STARTS:
        raise PitcherKWorkloadCandidateError(
            f"candidate requires {MIN_STARTS}..{MAX_STARTS} strictly-prior starts"
        )
    rows = [_stat_row(row, i) for i, row in enumerate(prior_starts)]
    bfs = [row["batters_faced"] for row in rows]
    pitches = [row["number_of_pitches"] for row in rows]
    ks = [row["strikeouts"] for row in rows]
    outs = [row["outs"] for row in rows]
    k_per_bf = [k / bf for k, bf in zip(ks, bfs)]
    pitches_per_bf = [p / bf for p, bf in zip(pitches, bfs)]
    return {
        "schema": "MLB_PITCHER_K_WORKLOAD_CANDIDATE_V1",
        "authority": AUTHORITY,
        "source_contract": "STRICTLY_PRIOR_PITCHING_GAMELOG_ROWS",
        "start_count": len(rows),
        "history": rows,
        "summary": {
            "recent_mean_batters_faced": fmean(bfs),
            "recent_mean_number_of_pitches": fmean(pitches),
            "recent_mean_outs": fmean(outs),
            "recent_mean_k_per_batter_faced": fmean(k_per_bf),
            "recent_mean_pitches_per_batter_faced": fmean(pitches_per_bf),
        },
        "deployment": False,
        "model_p_eligible": False,
    }
