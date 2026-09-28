# CFB confidence-score provenance audit — 2026-09-27

Status: research/governance evidence only. NOT Model_P. NOT Truth Gate. NOT OFFICIAL.

## Finding

The current repository field named `confidence` is **market-derived by construction**. It is not an independent measure of forecast certainty, source agreement, injury certainty, or model reliability.

Source: `sportsedge/sports/cfb/scorecard.py` on the audited branch:
https://github.com/isaacrome21-sys/SportsEdge/blob/cfb-postmortem-1066/sportsedge/sports/cfb/scorecard.py

The function computes:

- `settled = model_p / (1 - push_p)`
- `edge = settled - fair_market_p`
- `edge_component = clip(edge * 250, -25, 25)`
- `ev_component = clip(ev_per_dollar * 100, -15, 15)`
- `raw = 50 + edge_component + ev_component`
- then shrinks distance from 50 using Monte Carlo path count, **sportsbook quote** freshness, and push probability.

Therefore market no-vig probability and EV directly determine the displayed score. Quote age affects it; external-projection freshness does not.

## Boundary check

`run_machine.py` keeps sportsbook prices out of predictive features and builds the scorecard only after the model distribution is priced. This means the audited score formula does **not** demonstrate contamination of `estimate_p` itself.

Source:
https://github.com/isaacrome21-sys/SportsEdge/blob/cfb-postmortem-1066/sportsedge/sports/cfb/run_machine.py

The severity is therefore presentation/ranking semantics unless another code path uses `confidence` as selection or promotion authority. The CFB Truth Gate is a separate evidence evaluator and does not reference this score.

Source:
https://github.com/isaacrome21-sys/SportsEdge/blob/main/sportsedge/sports/cfb/truth_gate.py

## Week 4 linkage

The Sept. 26 manually displayed 81–94 research-conviction values are **UNVERIFIED as outputs of `scorecard.py`**. No archived artifact has yet been found that maps those nine chat-card scores to the repository function. Do not claim the scorecard formula caused the 1–2 top-three result until that artifact link is proven.

## Governance decision

1. Do not tune this formula to the nine Week 4 outcomes.
2. Do not interpret `confidence` as forecast confidence.
3. Before any rename or formula change, locate all consumers and tests.
4. Any replacement ranking score must be pre-registered and validated out of sample.
5. Preserve market-blind `estimate_p`; ticket/handle/RLM remain context-only.

## Proposed next check

Search all repository consumers of the `scorecard.confidence` field. If it is presentation-only, consider a future non-breaking semantic rename such as `market_value_quality_score`. If it gates selection/promotion anywhere, treat that as a separate governance defect and fail closed.
