"""Chronological out-of-sample backtest harness. Research only.

Isaac's bar (2026-10-11): every new factor must PROVE it improves
chronological out-of-sample performance versus BOTH the existing model
and a market baseline before entering production pricing. No factor is
added on vibes.

This package is the measurement foundation for that bar. It provides
strict point-in-time train/test splitting (no lookahead), historical
game-outcome collection from free public sources only, proper scoring
metrics, a backtest runner, and a PASS/FAIL report.

Market-baseline limitation: Isaac does not use the Odds API, so there is
no complete historical market baseline. Archived or manually recorded
closing prices may be supplied as the market baseline where they exist;
everywhere else the baseline leg is explicitly flagged MISSING and the
verdict is conditional. Market prices are never invented.

All outputs are research_only. No betting authority, no staking.
"""
from .splits import walk_forward_splits, fixed_split, Split, SplitError
from .outcomes import (
    OutcomeError,
    fetch_football_scoreboard,
    parse_completed_football_games,
    fetch_mlb_schedule,
    parse_completed_mlb_games,
    settle_game,
)
from .metrics import (
    MetricError,
    brier_score,
    log_loss,
    calibration_bins,
    hit_rate_at_thresholds,
    summarize,
)
from .runner import RunnerError, run_backtest, compare_models
from .report import (
    ReportError,
    evaluate,
    to_markdown,
    to_json,
    summarize_actionability,
    actionability_to_json,
    actionability_to_markdown,
    PRICED_STATUSES,
    WATCH_STATUS_PREFIX,
)
from . import market_baseline
from .elo import (
    EloError,
    EloRatings,
    EloBaseline,
    make_elo_price_fn,
    naive_price_fn,
    SPORT_PARAMS,
    INIT_RATING,
)

__all__ = [
    "Split",
    "SplitError",
    "walk_forward_splits",
    "fixed_split",
    "OutcomeError",
    "fetch_football_scoreboard",
    "parse_completed_football_games",
    "fetch_mlb_schedule",
    "parse_completed_mlb_games",
    "settle_game",
    "MetricError",
    "brier_score",
    "log_loss",
    "calibration_bins",
    "hit_rate_at_thresholds",
    "summarize",
    "RunnerError",
    "run_backtest",
    "compare_models",
    "ReportError",
    "evaluate",
    "to_markdown",
    "to_json",
    "summarize_actionability",
    "actionability_to_json",
    "actionability_to_markdown",
    "PRICED_STATUSES",
    "WATCH_STATUS_PREFIX",
    "market_baseline",
    "EloError",
    "EloRatings",
    "EloBaseline",
    "make_elo_price_fn",
    "naive_price_fn",
    "SPORT_PARAMS",
    "INIT_RATING",
]
