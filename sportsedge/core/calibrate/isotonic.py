"""Dependency-free fold-safe isotonic calibration for football probabilities."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from collections.abc import Iterable


@dataclass
class _Block:
    lo: float
    hi: float
    weight: int
    mean: float


class FoldSafeIsotonicCalibrator:
    """Pool-adjacent-violators isotonic calibrator with explicit fold guard."""

    def __init__(self) -> None:
        self._blocks: list[_Block] | None = None

    def fit(
        self,
        scores: Iterable[float],
        outcomes: Iterable[float],
        *,
        fit_seasons: set[int] | frozenset[int],
        test_season: int,
    ) -> "FoldSafeIsotonicCalibrator":
        if int(test_season) in {int(s) for s in fit_seasons}:
            raise ValueError("CALIBRATOR_FIT_ON_TEST_FOLD")

        x = [float(v) for v in scores]
        y = [float(v) for v in outcomes]
        if len(x) != len(y) or not x:
            raise ValueError("CALIBRATOR_INPUT_LENGTH")
        if any(not isfinite(v) for v in x + y):
            raise ValueError("CALIBRATOR_NONFINITE")
        if any(v < 0.0 or v > 1.0 for v in x):
            raise ValueError("CALIBRATOR_SCORE_RANGE")
        if any(v < 0.0 or v > 1.0 for v in y):
            raise ValueError("CALIBRATOR_OUTCOME_RANGE")

        pairs = sorted(zip(x, y), key=lambda p: p[0])
        grouped: list[_Block] = []
        for score, outcome in pairs:
            if grouped and score == grouped[-1].hi:
                block = grouped[-1]
                new_weight = block.weight + 1
                block.mean = (block.mean * block.weight + outcome) / new_weight
                block.weight = new_weight
            else:
                grouped.append(_Block(lo=score, hi=score, weight=1, mean=outcome))

        blocks: list[_Block] = []
        for block in grouped:
            blocks.append(block)
            while len(blocks) >= 2 and blocks[-2].mean > blocks[-1].mean:
                right = blocks.pop()
                left = blocks.pop()
                weight = left.weight + right.weight
                blocks.append(
                    _Block(
                        lo=left.lo,
                        hi=right.hi,
                        weight=weight,
                        mean=(left.mean * left.weight + right.mean * right.weight) / weight,
                    )
                )

        self._blocks = blocks
        return self

    def transform(self, scores: Iterable[float]) -> list[float]:
        if self._blocks is None:
            raise ValueError("CALIBRATOR_NOT_FIT")
        values = [float(v) for v in scores]
        if any(not isfinite(v) or v < 0.0 or v > 1.0 for v in values):
            raise ValueError("CALIBRATOR_SCORE_RANGE")

        result: list[float] = []
        for value in values:
            chosen = self._blocks[-1].mean
            for block in self._blocks:
                if value <= block.hi:
                    chosen = block.mean
                    break
            result.append(min(1.0, max(0.0, float(chosen))))
        return result

    def fit_transform(
        self,
        scores: Iterable[float],
        outcomes: Iterable[float],
        *,
        fit_seasons: set[int] | frozenset[int],
        test_season: int,
    ) -> list[float]:
        scores_list = list(scores)
        self.fit(scores_list, outcomes, fit_seasons=fit_seasons, test_season=test_season)
        return self.transform(scores_list)
