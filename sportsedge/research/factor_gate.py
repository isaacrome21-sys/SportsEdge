"""Forward selection with a minimum-gain gate and test-set ablations for factors.

Technique adapted from the public nfl-prediction project
(sujaynadkarni/nfl-prediction): a candidate factor is admitted only when it
improves validation Brier by MORE than a fixed minimum gain (noise floor),
then re-checked with per-factor ablations on the untouched test set. The
minimum gain replaces vibes with an explicit, auditable bar, and the ablation
table shows whether validation gains survive on unseen games.

This is a research-only protocol layer over probability records. It touches no
production pricing path and grants no betting authority.

Workflow:
  1. Build variant record sets on VALIDATION games (base model, base+factor...).
  2. select_candidates(...) admits only gain > min_gain factors.
  3. On TEST games, ablation_table(...) reports each kept factor's test gain.
  4. Rejected factors can be re-tested later via retest_rejected(...) as new
     seasons arrive (the "rejected-factor watch"), never silently promoted.

Research only. No betting authority.
"""
from __future__ import annotations

from math import isfinite
from typing import Mapping, Sequence

FACTOR_GATE_VERSION = "factor_gate_v1"


class FactorGateError(ValueError):
    pass


def _checked(records: Sequence[Mapping], *, label: str) -> list[tuple[str, float, float]]:
    if not isinstance(records, Sequence) or isinstance(records, (str, bytes)) or not records:
        raise FactorGateError(f"FACTOR_GATE_EMPTY_RECORDS:{label}")
    out: list[tuple[str, float, float]] = []
    seen: set[str] = set()
    for i, rec in enumerate(records):
        if not isinstance(rec, Mapping):
            raise FactorGateError(f"FACTOR_GATE_RECORD_NOT_OBJECT:{label}:{i}")
        try:
            game_id = str(rec["game_id"])
            p = float(rec["model_p"])
            y = float(rec["outcome"])
        except (KeyError, TypeError, ValueError) as exc:
            raise FactorGateError(f"FACTOR_GATE_RECORD_MALFORMED:{label}:{i}") from exc
        if not game_id:
            raise FactorGateError(f"FACTOR_GATE_GAME_ID_MISSING:{label}:{i}")
        if game_id in seen:
            raise FactorGateError(f"FACTOR_GATE_DUPLICATE_GAME_ID:{label}:{game_id}")
        seen.add(game_id)
        # Degenerate p=0/1 fails closed: absolute certainty is overconfidence,
        # and Brier selection must not reward it.
        if not (0.0 < p < 1.0) or not isfinite(p):
            raise FactorGateError(f"FACTOR_GATE_PROBABILITY_INVALID:{label}:{i}")
        if y not in (0.0, 0.5, 1.0) or not isfinite(y):
            raise FactorGateError(f"FACTOR_GATE_OUTCOME_INVALID:{label}:{i}")
        out.append((game_id, p, y))
    return out


def brier_score(pairs: Sequence[tuple[float, float]]) -> float:
    """Mean squared error of (model_p, outcome) pairs. Lower is better."""
    if not pairs:
        raise FactorGateError("FACTOR_GATE_BRIER_NO_PAIRS")
    return sum((p - y) ** 2 for p, y in pairs) / len(pairs)


def _aligned(
    base: list[tuple[str, float, float]],
    variant: list[tuple[str, float, float]],
    *,
    variant_label: str,
) -> tuple[list[tuple[float, float]], list[tuple[float, float]], int]:
    """Intersect variant coverage with base on game_id. Fail closed on empty overlap."""
    base_by_game = {g: (p, y) for g, p, y in base}
    base_pairs: list[tuple[float, float]] = []
    variant_pairs: list[tuple[float, float]] = []
    for g, p, y in variant:
        if g in base_by_game:
            pb, yb = base_by_game[g]
            if y != yb:
                raise FactorGateError(f"FACTOR_GATE_OUTCOME_MISMATCH:{variant_label}:{g}")
            base_pairs.append((pb, yb))
            variant_pairs.append((p, y))
    if not base_pairs:
        raise FactorGateError(f"FACTOR_GATE_NO_COMMON_COVERAGE:{variant_label}")
    return base_pairs, variant_pairs, len(base_pairs)


def marginal_gain(
    base_records: Sequence[Mapping],
    variant_records: Sequence[Mapping],
    *,
    variant_label: str = "variant",
) -> dict:
    """Brier gain of variant over base on common coverage. Positive = variant better."""
    base = _checked(base_records, label="base")
    variant = _checked(variant_records, label=variant_label)
    base_pairs, variant_pairs, n = _aligned(base, variant, variant_label=variant_label)
    base_brier = brier_score(base_pairs)
    variant_brier = brier_score(variant_pairs)
    return {
        "n_common": n,
        "base_brier": base_brier,
        "variant_brier": variant_brier,
        "gain": base_brier - variant_brier,
    }


def _validate_gate_args(
    records_by_variant: Mapping[str, Sequence[Mapping]],
    *,
    base: str,
    candidates: Sequence[str],
    min_gain: float,
) -> None:
    if not isinstance(records_by_variant, Mapping) or base not in records_by_variant:
        raise FactorGateError("FACTOR_GATE_BASE_VARIANT_MISSING")
    if not candidates:
        raise FactorGateError("FACTOR_GATE_NO_CANDIDATES")
    if len(set(candidates)) != len(candidates):
        raise FactorGateError("FACTOR_GATE_DUPLICATE_CANDIDATES")
    for c in candidates:
        if c == base or c not in records_by_variant:
            raise FactorGateError(f"FACTOR_GATE_CANDIDATE_INVALID:{c}")
    if not isinstance(min_gain, (int, float)) or not isfinite(min_gain) or min_gain < 0:
        raise FactorGateError("FACTOR_GATE_MIN_GAIN_INVALID")


def select_candidates(
    records_by_variant: Mapping[str, Sequence[Mapping]],
    *,
    base: str,
    candidates: Sequence[str],
    min_gain: float,
) -> dict:
    """Admit factors whose VALIDATION Brier gain over base exceeds min_gain.

    Returns {"kept": [names ranked by gain desc], "dropped": [...],
             "details": {name: {...marginal_gain..., "kept": bool}}}.
    Strict inequality: gain must EXCEED min_gain; ties fail closed (dropped).
    """
    _validate_gate_args(records_by_variant, base=base, candidates=candidates, min_gain=min_gain)
    base_records = records_by_variant[base]
    details: dict[str, dict] = {}
    for name in candidates:
        result = marginal_gain(base_records, records_by_variant[name], variant_label=name)
        result["kept"] = result["gain"] > min_gain
        details[name] = result
    kept = sorted((n for n, d in details.items() if d["kept"]), key=lambda n: -details[n]["gain"])
    dropped = sorted((n for n, d in details.items() if not d["kept"]), key=lambda n: -details[n]["gain"])
    return {"kept": kept, "dropped": dropped, "details": details}


def ablation_table(
    test_records_by_variant: Mapping[str, Sequence[Mapping]],
    *,
    base: str,
    variants: Sequence[str],
) -> dict:
    """Per-factor TEST-set Brier gain over base, on common coverage.

    A factor that passed the validation gate but shows a negative test gain is
    reported honestly instead of hidden: "test_gain_positive" is False.
    """
    _validate_gate_args(
        test_records_by_variant, base=base, candidates=list(variants), min_gain=0.0
    )
    base_records = test_records_by_variant[base]
    details: dict[str, dict] = {}
    for name in variants:
        result = marginal_gain(base_records, test_records_by_variant[name], variant_label=name)
        result["test_gain_positive"] = result["gain"] > 0.0
        details[name] = result
    return {"variants": list(variants), "details": details}


def retest_rejected(
    new_records_by_variant: Mapping[str, Sequence[Mapping]],
    *,
    base: str,
    rejected: Sequence[str],
    min_gain: float,
) -> dict:
    """Re-run the selection gate for previously rejected factors on NEW data.

    The rejected-factor watch: nothing is promoted without re-passing the gate
    on fresh, untouched games. Thin wrapper over select_candidates.
    """
    return select_candidates(
        new_records_by_variant, base=base, candidates=list(rejected), min_gain=min_gain
    )
