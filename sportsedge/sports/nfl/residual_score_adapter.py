"""Research pricing adapter; never mutates a fitted M2 model or its score shape."""
from types import SimpleNamespace
from math import isfinite

from sportsedge.sports.nfl.market_anchored_residual import ResidualQuoteError, price_game


def price_m2_research(model, features, game, *, as_of):
    """Replay M2's original paired residuals at market and fair centers.

    Features and model training must satisfy their existing PIT contracts.
    No fitting, artifact writes, odds retrieval or promotion happens here.
    """
    from sportsedge.sports.nfl.m2 import derive_nfl_m2_score_distribution

    margin, total = model.predict(dict(features))
    saved_paths = []

    def grid_factory(home, away):
        # The frozen distribution function checks identity and residual presence.
        # A location-only view preserves the exact paired residual replay logic.
        view = SimpleNamespace(model_id=model.model_id,
            feature_contract=model.feature_contract, residual_pairs=model.residual_pairs,
            predict=lambda row: (home-away, home+away))
        if any(not all(isfinite(float(v)) for v in pair) for pair in view.residual_pairs):
            raise ResidualQuoteError("M2_RESIDUAL_NONFINITE")
        paths = derive_nfl_m2_score_distribution(view, dict(features))
        size = max(max(row['home_score'], row['away_score']) for row in paths)+1
        if size > 256:
            raise ResidualQuoteError("M2_SCORE_SUPPORT_OUT_OF_RANGE")
        grid = [[0.0]*size for _ in range(size)]
        for row in paths:
            grid[row['home_score']][row['away_score']] += 1.0/len(paths)
        saved_paths[:] = paths
        return grid

    prices = price_game(game, raw_model_margin=margin, raw_model_total=total,
                        as_of=as_of, score_grid_factory=grid_factory)
    return {'prices':prices, 'score_paths':saved_paths, 'research_only':True,
            'validated_markets':[], 'promotion_authority':False,
            'official_authority':False, 'staking_authority':False}
