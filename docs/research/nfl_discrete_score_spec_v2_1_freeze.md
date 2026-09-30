# NFL discrete v2.1 — family B frozen (2021–2024)

Research only. Attempt 9 stays the live `.5` owner. No phone-card pricing.

## Reproducible fit

- Source bytes: `data/nfl_discrete_v2/scores_2021_2024_reg.json`
  (also shipped as `scores_2021_2024_reg.json.gz.b64`; the fit decodes that and checks sha256 `90a2ed9d…`).
- Rows are `[season, week, home_score, away_score]` for 1087 REG games, 2021–2024 only.
- Regenerator: `sportsedge/sports/nfl/discrete_v2_fit.py`
- Test `test_fit_rebuilds_freeze_sha` rebuilds the JSON and matches `artifact_sha256`.
- Any season other than 2021–2024 fails the fit loader.

## Locked evaluator (before W4)

- `config/nfl_discrete_v2_eval_freeze.json`
- Mapping: `home = (total + margin) / 2`, `away = (total - margin) / 2`, clip (0.5, 70)
- Gates are read from that JSON, not from code constants:
  Brier vs 0.5400183992640294; slope 0.70–1.30; intercept ±0.10;
  P(|margin| ∈ {3,7,10}) and P(total = k) for k=40..51 within 3pp;
  n < 80 → INSUFFICIENT.
- Holdout windows: W4–W12 if the SHA is on main before first W4 kickoff, else W5–W13.
  Active window is `holdout.active`. Evaluator rejects 2025 and W1–W3.
- Code: `sportsedge/sports/nfl/discrete_v2_eval.py`
