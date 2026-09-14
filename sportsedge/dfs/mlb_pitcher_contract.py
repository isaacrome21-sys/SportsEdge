from __future__ import annotations

from typing import Mapping

MLB_PITCHER_PATH_ACCOUNTING_VERSION = "MLB_SP_ACCOUNTING_V2"


class MlbPitcherAccountingError(ValueError):
    """Raised when an MLB starter path can leak full-game outcomes into DFS scoring."""


def _numeric(sample: Mapping[str, object], key: str) -> float:
    value = sample.get(key)
    if isinstance(value, bool):
        return float(value)
    if not isinstance(value, (int, float)):
        raise MlbPitcherAccountingError(f"DFS_MLB_PITCHER_PATH_FIELD_INVALID:{key}")
    return float(value)


def _binary(sample: Mapping[str, object], key: str) -> float:
    value = _numeric(sample, key)
    if value not in (0.0, 1.0):
        raise MlbPitcherAccountingError(f"DFS_MLB_PITCHER_PATH_BINARY_INVALID:{key}:{value}")
    return value


def normalize_starter_path(sample: Mapping[str, object]) -> dict[str, float]:
    """Validate and normalize one simulated starting-pitcher path.

    The contract deliberately requires starter-exit state. H/BB/HBP/K/ER must be
    starter-scoped rather than copied from the opponent's full-game hitter totals.
    The DraftKings win flag is derived here from 5 IP + lead at exit + the lead
    surviving to the final; a supplied final-score win proxy cannot create +4 DK.
    """

    required = {
        "outs",
        "strikeouts",
        "earned_runs",
        "hits_allowed",
        "walks_allowed",
        "hbp_allowed",
        "starter_exit_batters_faced",
        "starter_exit_pitch_count",
        "starter_scoped_events",
        "lead_at_exit",
        "lead_preserved_to_final",
    }
    missing = sorted(key for key in required if key not in sample)
    if missing:
        raise MlbPitcherAccountingError(
            "DFS_MLB_PITCHER_PATH_ACCOUNTING_MISSING:" + ",".join(missing)
        )

    out = {
        str(key): float(value)
        for key, value in sample.items()
        if isinstance(value, (int, float, bool))
    }
    outs = _numeric(sample, "outs")
    strikeouts = _numeric(sample, "strikeouts")
    earned_runs = _numeric(sample, "earned_runs")
    hits = _numeric(sample, "hits_allowed")
    walks = _numeric(sample, "walks_allowed")
    hbp = _numeric(sample, "hbp_allowed")
    batters_faced = _numeric(sample, "starter_exit_batters_faced")
    pitch_count = _numeric(sample, "starter_exit_pitch_count")
    starter_scoped = _binary(sample, "starter_scoped_events")
    lead_at_exit = _binary(sample, "lead_at_exit")
    lead_preserved = _binary(sample, "lead_preserved_to_final")

    for key, value in (
        ("outs", outs),
        ("strikeouts", strikeouts),
        ("earned_runs", earned_runs),
        ("hits_allowed", hits),
        ("walks_allowed", walks),
        ("hbp_allowed", hbp),
        ("starter_exit_batters_faced", batters_faced),
        ("starter_exit_pitch_count", pitch_count),
    ):
        if value < 0:
            raise MlbPitcherAccountingError(f"DFS_MLB_PITCHER_PATH_NEGATIVE:{key}:{value}")

    if starter_scoped != 1.0:
        raise MlbPitcherAccountingError("DFS_MLB_PITCHER_PATH_NOT_STARTER_SCOPED")
    if abs(outs - round(outs)) > 1e-9:
        raise MlbPitcherAccountingError(f"DFS_MLB_PITCHER_PATH_OUTS_NOT_INTEGER:{outs}")
    if abs(batters_faced - round(batters_faced)) > 1e-9:
        raise MlbPitcherAccountingError(
            f"DFS_MLB_PITCHER_PATH_BF_NOT_INTEGER:{batters_faced}"
        )
    if strikeouts > outs:
        raise MlbPitcherAccountingError(
            f"DFS_MLB_PITCHER_PATH_K_EXCEEDS_OUTS:{strikeouts}:{outs}"
        )
    if strikeouts + hits + walks + hbp > batters_faced + 1e-9:
        raise MlbPitcherAccountingError(
            "DFS_MLB_PITCHER_PATH_EVENTS_EXCEED_BF:"
            f"{strikeouts + hits + walks + hbp}:{batters_faced}"
        )
    if pitch_count + 1e-9 < batters_faced:
        raise MlbPitcherAccountingError(
            f"DFS_MLB_PITCHER_PATH_PITCHES_LT_BF:{pitch_count}:{batters_faced}"
        )
    if lead_preserved and not lead_at_exit:
        raise MlbPitcherAccountingError("DFS_MLB_PITCHER_PATH_PRESERVED_WITHOUT_EXIT_LEAD")

    derived_win = float(outs >= 15.0 and lead_at_exit == 1.0 and lead_preserved == 1.0)
    supplied_win = sample.get("win_probability")
    if supplied_win is not None:
        supplied = _numeric(sample, "win_probability")
        if supplied not in (0.0, 1.0) or supplied != derived_win:
            raise MlbPitcherAccountingError(
                f"DFS_MLB_PITCHER_PATH_WIN_MISMATCH:{supplied}:{derived_win}"
            )
    out["win_probability"] = derived_win
    out["starter_exit_batters_faced"] = batters_faced
    out["starter_exit_pitch_count"] = pitch_count
    out["starter_scoped_events"] = 1.0
    out["lead_at_exit"] = lead_at_exit
    out["lead_preserved_to_final"] = lead_preserved
    return out


def validate_pitcher_expectation(stats: Mapping[str, object]) -> None:
    """Fail closed on mean pitcher projections that can hide an unqualified win.

    Marginal probabilities do not prove a joint win model, but requiring workload,
    hook and qualification components prevents a naked final-game win probability
    from entering the projection layer.
    """

    required = {
        "expected_batters_faced",
        "expected_pitch_count",
        "p_reach_5ip",
        "p_lead_at_exit",
        "p_lead_preserved_to_final",
    }
    missing = sorted(key for key in required if key not in stats)
    if missing:
        raise MlbPitcherAccountingError(
            "DFS_MLB_PITCHER_EXPECTATION_ACCOUNTING_MISSING:" + ",".join(missing)
        )

    bf = _numeric(stats, "expected_batters_faced")
    pitches = _numeric(stats, "expected_pitch_count")
    if bf <= 0 or pitches <= 0 or pitches < bf:
        raise MlbPitcherAccountingError(
            f"DFS_MLB_PITCHER_EXPECTATION_WORKLOAD_INVALID:{bf}:{pitches}"
        )
    probs = [
        _numeric(stats, "p_reach_5ip"),
        _numeric(stats, "p_lead_at_exit"),
        _numeric(stats, "p_lead_preserved_to_final"),
    ]
    if any(value < 0.0 or value > 1.0 for value in probs):
        raise MlbPitcherAccountingError("DFS_MLB_PITCHER_EXPECTATION_PROBABILITY_INVALID")

    win = float(stats.get("win_probability", 0.0) or 0.0)
    if win < 0.0 or win > 1.0:
        raise MlbPitcherAccountingError(
            f"DFS_MLB_PITCHER_EXPECTATION_WIN_PROBABILITY_INVALID:{win}"
        )
    if win > min(probs) + 1e-9:
        raise MlbPitcherAccountingError(
            "DFS_MLB_PITCHER_EXPECTATION_WIN_EXCEEDS_QUALIFICATION_COMPONENT"
        )
