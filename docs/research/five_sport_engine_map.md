# Five-sport engine map

Target: every sport has a phone card. A market prices only with a frozen owner
that passed a pre-registered holdout. Everything else is `NO_MODEL` or context.

| Sport | Phone issue | Live engine | Prices tonight |
|---|---|---|---|
| MLB | `[MLB LINES]` | V7 + Gamma-Poisson | ML, RL, totals, team totals |
| NFL | `[NFL LINES]` | Attempt 9 | half-point totals only |
| NHL | `[NHL LINES]` | rate v1 passed holdout, not promoted | all `NO_MODEL` until #1249 promotion |
| NBA | `[NBA LINES]` (this PR) | in-tree, no freeze | all `NO_MODEL` |
| CFB | `[CFB LINES]` (this PR) | paused Sep 23 / UNFROZEN | all `NO_MODEL` |

## What still needs an engine (not a guess)

- NFL moneyline / 3 / 7 / integer totals — discrete v1 **failed** 2025; v2 new window
- NFL / MLB / NHL / NBA / CFB player props — charters only
- NHL goal/point props — no model
- NBA ML / spread / total — needs frozen pace-efficiency owner + one holdout
- CFB — needs a new freeze, not a restart of the paused candidate on the same window
- MLB starters v2 — August passed small; bootstrap straddled 0; not promoted
- Weather / ump / bullpen / inactives — auto **context**, not model
