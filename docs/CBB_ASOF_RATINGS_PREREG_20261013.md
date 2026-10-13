# Pre-registration: CBB as-of team ratings walk-forward (2024-25)

Committed before the ratings code was run on data. **Governance flag:** this is a new pre-registration path and needs ChatGPT freeze-inventory registration. Research only. Market baseline MISSING. Lines are **NAIVE STAND-INS, not market lines**.

## Data
- Free ESPN men's college basketball `scoreboard?groups=50` (D1) for 2024-11-04 to 2025-03-16: ids, start, neutral site, scores.
- `summary` box scores: FGA, OREB, TO, FTA. Cached outside the repo (`/workspace/cbb_cache`).

## Point in time
- Slate = America/Chicago date. Cutoff = earliest tip on the slate.
- A game trains only if it is completed and start + 3h ≤ cutoff (conservative final buffer).
- Ordering is canonical (start, id), so input order cannot matter.

## Model (fixed; `sportsedge/sports/cbb/asof_ratings.py`)
- Possessions = FGA − OREB + TO + 0.475·FTA (team average of both sides per game).
- Home court: H = mean(home pts − away pts) over trainable **non-neutral** games, applied ±H/2. Neutral-site games get 0.
- 20 iterations of opponent adjustment:
  - offense ORtg_t = league eff + mean(game eff − opponent DRtg adj);
  - defense likewise;
  - pace likewise.
  - Each is shrunk toward 0 by n/(n + 5) (5 pseudo-games).
- Prediction: pace = league + pace_h + pace_a; pts = pace·(eff + O_t + D_opp)/100 ± H/2.
- Margin and total are Normal, with SDs = residual SDs of trainable games under the same fit.

## Illinois exclusion (ID-based, #2148)
- Games with any ESPN team id in `IL_COLLEGE_ESPN_IDS` are used as opponents in training, but are **excluded from scored/playable output** (BLOCKED ILLINOIS_COLLEGE_EXCLUDED at intake).
- They are excluded from evaluation.

## Evaluation
- Both teams need ≥ 5 trainable games. Slates need ≥ 200 trainable games.
- Stand-in lines (naive point estimates, labeled NAIVE_STANDIN):
  - spread = (home avg margin − away avg margin)/2 + H_home;
  - total = mean over both teams of (avg pts for + avg pts against).
- **Moneyline:** model P(home win) vs naive = trainable home-win rate (non-neutral) or 0.5 (neutral).
- **Spread / total:** model P(home covers stand-in) and P(over stand-in) vs naive 0.5. Pushes are dropped.
- Metrics: Brier for all three; log-loss for moneyline.

## Decision rule (fixed)
- PASS_RESEARCH iff model Brier < naive for moneyline, spread **and** total, and moneyline log-loss < naive.
- Otherwise FAIL. Single season; no tuning after results.
