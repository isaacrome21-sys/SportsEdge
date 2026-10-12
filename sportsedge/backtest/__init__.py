"""Backtest harness package.

On origin/main this package currently holds the Kaggle NBA baseline
loader only; the full harness (runner, metrics, market_baseline, ...)
lives on feat/backtest-harness-20261011 and feat/market-baseline-20261011
and merges in separately. See
sportsedge/backtest/kaggle_nba_baseline.py for the integration note.
"""

from sportsedge.backtest.kaggle_nba_baseline import KaggleNbaBaseline

__all__ = ["KaggleNbaBaseline"]
