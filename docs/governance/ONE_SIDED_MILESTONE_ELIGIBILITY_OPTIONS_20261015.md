# One-sided milestone eligibility — governance options (owner ruling required)

Status: **DECISION PACKAGE ONLY.** Nothing here changes code, gates, eligibility or
authority. Prepared 2026-10-15 (CT) against main `1a10b7ffd`.

## Question
DraftKings increasingly hangs player props **only** as milestone ladders ("X+" /
"N or fewer"), with no two-sided O/U pair (e.g. 2026-10-15 MLB Hits board). Can a
one-sided milestone quote ever carry an EV route, and under what conditions?

## What the code does today (evidence)
| Path | One-sided behaviour |
|---|---|
| `sportsedge/milestone_ladder_intake.py` | Converts X+ → Over(X−0.5), N-or-fewer → Under(N+0.5) with the REAL price and original capture time; never invents an opposite price; says a one-sided quote "can support an EV calculation against an independently estimated probability, but cannot establish a two-sided no-vig market". MLB admitted only for `PITCHER_MARKETS`; football only passing yards (#2264 comment, Oct 14). |
| `sportsedge/generic_card_pipeline.py::_candidate_economics` | Computes EV = p·(dec−1) − loss vs the raw price; labels `MODEL_CANDIDATE_ONE_SIDED`, `UNAVAILABLE_ONE_SIDED`; no shadow/PLAY. |
| `sportsedge/football_prop_extended_run_machine.py` | `one_sided_model_p_plus_offered_price_ev_enabled: True` — EV from model p vs offered price. |
| `sportsedge/football_prop_readiness.py` | Blocks with `{SPORT}_PROP_ONE_SIDED_OFFICIAL_FLOOR_POLICY_REQUIRED` — i.e. the code already names this as a missing owner policy. |
| `artifacts/prop_board_intake.py` | Refuses `BOARD_LINE_ONE_SIDED` outright. |
| Three-sport research bridge | `EXACT_PAIRED_DK_QUOTE_REQUIRED`. |

So the repo is **already inconsistent**: two paths compute one-sided EV for research,
two refuse at intake, and readiness names a policy that does not exist.

## Why a pair matters
With a pair, the no-vig fair probability is a market benchmark the model must beat.
With one side only, the hold cannot be removed: the implied probability is the fair
probability **plus an unknown hold share** (milestone ladders typically carry more
hold than O/U mains, and the hold is not split symmetrically). The model must then
clear the raw break-even, which is strictly harder — that part is conservative.
What is lost is the **market comparator** for validation (Brier/log-loss vs no-vig
market cannot be computed per row).

## Options
- **A. Never.** One-sided forms stay research-only display forever. Simplest; as
  two-sided boards disappear, the routable surface shrinks to near zero.
- **B. Research EV only (status quo, made consistent).** All paths compute EV vs raw
  price, label `UNAVAILABLE_ONE_SIDED`, never PLAY. Unify the four divergent paths
  (also item-6 defect "two divergent milestone-refusal code paths").
- **C. Eligible under a family-specific floor (recommended path to evaluate).** A
  family may route one-sided only if ALL hold: (1) the family is independently
  validated on its own terms (calibration vs outcomes, not vs market); (2) a
  preregistered **hold floor**: model p must exceed raw implied p by a margin fixed
  in advance per family (covers the unknown hold); (3) forward record graded at the
  raw offered price, correlated stacks as one position; (4) -165 cap unchanged;
  (5) the market comparator for validation uses rungs where a pair **was** captured,
  never synthesized complements.
- **D. Synthesize the complement** from neighbouring rungs or a hold assumption.
  **Not recommended** — violates "never manufacture quotes/probabilities".

## Recommendation (for the owner's one-word ruling)
**Rule B now; C is allowed only per family after validation and a preregistered
floor. D is forbidden.** No family currently qualifies for C (zero families validated).

## If ruled B — concrete follow-up (Grok lane)
RED tests that all four paths produce the same named state for an identical
one-sided row, then one shared one-sided classifier. No eligibility change.
