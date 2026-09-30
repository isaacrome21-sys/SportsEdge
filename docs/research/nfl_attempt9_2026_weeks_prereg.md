# NFL Attempt 9 — 2026 weeks already played (pre-registered)

**Status:** window locked in writing before this look. Frozen Attempt 9 is checked
as-is. No coefficients, decay, feature recipe, or line-eligibility rules change
for this check.

## Window

**2026 NFL regular-season games with kickoff before 2026-09-30 05:00 UTC**
(end of Tuesday 2026-09-29 America/Chicago). Completed finals only.

This is the prospective test Attempt 9 was built for. 2025 remains the locked
final holdout and is not used here as a tuning set. 2021–2024 were used in the
feature search and are not re-used as a new validation window.

## Frozen owner (no edits)

- Runtime artifact: `artifacts/football/nfl_attempt9_runtime_v1.json`
- Probability wrapper: `artifacts/football/nfl_attempt9_model_p_v1.json`
- Features: last up to 10 prior games, exponential decay 0.85, both points-for
  and points-against (and nets). Prior-season games stay in the history stream
  so early 2026 weeks are defined by 2025 (and earlier) results.
- Minimum history: **5 prior games per team**. If either side is short,
  that game is **NO_MODEL**. There is no defense-blend or other invented fallback.
- Markets priced: non-integer spread and non-integer total only.
- **Integer spread/total:** `NO_MODEL` (`NFL_ATTEMPT9_MODEL_P_PUSH_MODEL_REQUIRED_FOR_INTEGER_LINE`).
- **Moneyline:** `NO_MODEL` (`UNSUPPORTED_V1_NO_TIE_MASS_MODEL`).
- Team totals, halves, quarters, alts, props: `NO_MODEL` on this card.

## One-shot rule

This 2026-weeks window is scored once for the frozen owner. A later candidate
that changes the specification does **not** get a second look at these same
weeks. Any fix is tuned on a different, newly pre-registered window, then this
2026 slice is re-checked at most once under that new spec.

## Authority

Card label remains `NOT Model_P / NOT Truth Gate / NOT OFFICIAL`.
Prices stay manual via the phone issue. Schedule, scores, and features are
model inputs and must be timestamped.
