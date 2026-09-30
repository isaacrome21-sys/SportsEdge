# NFL discrete v2.1 — family B frozen (2021–2024)

Research only. Attempt 9 stays the live `.5` owner. No phone-card pricing.

## Reproducible fit

- Source bytes: `data/nfl_discrete_v2/games_2021_2024_reg.csv`
- `source_sha256` is the sha256 of those exact bytes.
- Regenerator: `sportsedge/sports/nfl/discrete_v2_fit.py`
- Test `test_fit_rebuilds_freeze_sha` rebuilds the JSON and matches `artifact_sha256`.
- Seasons other than 2021–2024 REG fail the fit loader.

## Locked evaluator (before W4)

- `config/nfl_discrete_v2_eval_freeze.json`
- Mapping: `home = (total + margin) / 2`, `away = (total - margin) / 2`, clip (0.5, 70)
- Gates: Brier vs 0.5400183992640294; slope 0.70–1.30; intercept ±0.10;
  P(|margin| ∈ {3,7,10}) and P(total = k) for k=30..60 within 3pp;
  n < 80 → INSUFFICIENT.
- Code: `sportsedge/sports/nfl/discrete_v2_eval.py`

Holdout is 2026 REG W4–W12 if this freeze is on main before first W4 kickoff.
