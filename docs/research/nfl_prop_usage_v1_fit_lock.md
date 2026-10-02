# NFL prop usage V1 — executable fit/validation lock

This file operationalizes the already-frozen #1250 usage-first architecture
without scoring the 2025 holdout.

The candidate is intentionally fixed rather than hyperparameter-searched. It
models yardage as volume × efficiency:

- QB passing yards = attempts × completion rate × yards/completion.
- QB/RB rushing yards = carries × yards/carry.
- RB/WR/TE receiving yards = targets × catch rate × yards/reception.

Every primitive uses only strictly-prior player appearances. The most recent
eight appearances are exponentially weighted at 0.85 per game and shrunk
toward the previous regular season's position mean with the fixed pseudo-sample
strengths in the JSON lock. No sportsbook line or price is available to fit.

The 2025 validation uses DraftKings-only paired over/under snapshots from the
immutable public archive pinned in the lock. The grade line is the last
pre-kickoff snapshot no more than 15 minutes before kickoff. Regular-season
weeks 1–18 only are eligible.

Eligibility requires official NFL gamebook Not Active ground truth. QB passing
yards additionally requires a timestamped nflverse QB rank-1 depth observation
strictly before the market snapshot. Missing or unparseable eligibility
evidence emits zero rows. Postgame participation is never used to decide who
was eligible.

The pre-existing #1250 gates are operationalized as:
- pooled 10-bin equal-width ECE of P(over) versus observed over <= 0.06;
- pooled candidate Brier no worse than a position/market baseline fit only on
  2021–2024;
- zero emitted rows when the official Not Active list is missing.

The 2025 window is one-look. Failure spends it; there is no retune or second
look. Passing still grants no promotion or bettor-facing authority.
