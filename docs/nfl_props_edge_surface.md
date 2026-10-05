# NFL props edge surface

SportsEdge's NFL props edge surface is a presentation and research layer over the existing governed football prop run output. It borrows useful product ideas from modern betting-research boards—model probability, fair price, sportsbook price, edge, sortable scores, featured rows, projections, and role what-if views—without copying an external site's code, branding, or proprietary ranking formula.

## What the board exposes

For each available player-market row the surface can expose:

- player, market, side and line
- settled model probability (`model_p / (1 - push_p)`)
- model fair American price derived only from SportsEdge Model_P
- offered sportsbook price and its break-even probability
- SportsEdge's existing no-vig market probability when a paired market exists
- SportsEdge's existing edge, EV and Kelly outputs
- quote freshness and price state
- an additive 0-100 SportsEdge research score and letter grade
- an optional projection and projection-vs-line difference when an upstream projection is supplied
- optional sharp/whale/liquidity metadata for display only

The score is intentionally transparent and SportsEdge-owned. It is not intended to reproduce another product's proprietary score. Current weights are edge 35%, EV 25%, model conviction 15%, role certainty 10%, data quality 10%, and quote freshness 5%. Sharp/public/capper context is excluded from the score.

## Views

`all_priced` shows every fresh priced model row, including negative-edge rows. `all_projections` shows every row with Model_P even when pricing is missing or stale. `featured` is governance-aware and requires the underlying row to already be `official_eligible=True`; this layer cannot promote a row. `research_featured` is an explicit non-authoritative shortlist for analysis while evidence/promotion gates remain blocked.

Example:

```python
from sportsedge.sports.nfl.prop_edge_surface import build_props_edge_board

board = build_props_edge_board(
    run_payload,
    view="all_priced",
    market="receptions",
    sort_by="score",
    teams=["KC", "IND"],
)
```

A compact top-picks view is available through `top_prop_picks`. Its default is governed/official eligibility. Research-only top picks require `research_only=True` and do not change eligibility.

## CLI

```bash
python scripts/build_nfl_props_edge_board.py \
  artifacts/nfl_prop_run.json \
  artifacts/nfl_props_edge_board.json \
  --view all_priced \
  --market receptions \
  --sort score
```

`--team` is repeatable. Both governed Featured thresholds and research Featured thresholds can be supplied independently.

## Sharp-money context

`sharp_context_by_key` can attach context such as exchange prices, liquidity, large observed orders, ticket/handle splits, or line-movement annotations to the matching row. The normalized context is stamped with:

- `promotion_authority=False`
- `used_in_model_probability=False`
- `used_in_score=False`

This preserves the SportsEdge rule that contextual/capper information can inform review but cannot create Model_P or vote a wager into OFFICIAL status.

## What-if role scenarios

`apply_role_scenario` supports a UI-style what-if view for targets, carries, pass attempts, or another explicit role variable when the row already contains a projection. It scales only that projection for research. Because that shortcut is not a full rerun of Engine A/B/C, the returned scenario deliberately clears Model_P, fair price, edge, EV, Kelly, score, and official eligibility and stamps the row `RESEARCH_SCENARIO`.

A scenario can become a priced Model_P only by feeding the changed role assumption back through the proper football simulation and validation path.

## Governance boundary

This module is downstream of the model and market-economics machinery. It does not:

- create or alter Model_P
- resimulate football paths
- devig a market
- invent the missing side of a one-sided market
- alter model artifacts or source hashes
- change Truth Gate, promotion, eligibility, staking, or OFFICIAL authority

One-sided scorer offers may display model fair price and existing EV when the run machine produced them, but the surface does not invent a no-vig market probability or edge.

As of this implementation, existing repository governance still controls whether NFL prop rows are promotable. If the underlying run is blocked for promotion evidence, the board remains a research surface and the governed `featured` view will correctly remain empty.
