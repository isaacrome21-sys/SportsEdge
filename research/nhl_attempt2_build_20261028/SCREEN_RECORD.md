# NHL attempt-2 — design screen adjudication: NOT_EXECUTABLE (2026-10-28)

**Construction:** NHL_ATTEMPT2_V1 (PR #2839 design,
`research/activation_designs_20261027/NHL_SIDES_TOTALS_DESIGN.md`).
**Question put to this build:** run the design screen exactly as the
design specifies. **Answer: the design specifies no screen that is
runnable on 2026-10-28, and no historical screen at all.** The design's
only two evaluations are a locked future one-shot (Stage A) and a
forward market validation whose window has not opened (Stage B).
Inventing a historical backtest with seasons/baselines/criteria of
this build's choosing would be a criterion invention, and is refused.
What the design says is actually owed before Stage B's window opens —
"construction code + fit are build work owed before Stage B's window
opens Dec 1" (design, Blockers) — is delivered in BUILD_RECORD.md
beside this record.

## Stage A — cited verbatim, not touched, not runnable by this build

The design (Stage A paragraph, quoted in full):

> "Stage A (accuracy, locked Sep 29, 2026 — cited, not amended). The
> home-ice v2 pre-lock (`docs/research/nhl_home_ice_v2_prelock.md`):
> fit = 2024–25 regular season, regulation goals only, home-ice free;
> validate ONCE on 2026–27 regular-season games Oct 8 – Nov 30, 2026;
> score moneyline |gap| and Brier vs coin and vs the 2024–25 home-win
> rate, puck line −1.5 |gap|, totals 5.5/6.5 |gap| and Brier; October
> numbers are a first read only; the one-shot verdict is
> November 30, 2026 on the pre-lock's own pass line. This draft
> changes none of that. If Stage A fails, Stage B below does not run
> and this construction returns to design."

Gap: today is 2026-10-28. The validation window (Oct 8 – Nov 30, 2026)
is still open and the verdict date is in the future; the pre-lock's
own terms are validate-ONCE with October as a first read only. Running
any part of it now — early, partially, or on substituted data — would
break the one-shot discipline and re-litigate a locked protocol.
**State: NOT RUN — pending on the calendar, verdict Nov 30, 2026,
under the pre-lock's own act, not this build.**

## Stage B — the design's market validation; window not open

The design (Stage B validation protocol, quoted in full):

> "Precondition: Stage A verdict = PASS on Nov 30, 2026, and NHL
> capture flowing under the restart pack. Window: Dec 1, 2026 –
> Jan 31, 2027 regular-season games with paired DK captures (ML, puck
> line, total from the FINAL write). Candidate: attempt-2 v1 as
> specified above, fitted only on games before Dec 1 (MoneyPuck
> design fit) and updated strictly forward. Comparators on identical
> games: (a) the public boxscore baseline's probabilities; (b) DK
> closing no-vig probabilities. Primary metrics: log loss on
> moneyline; log loss on the total (distribution evaluated at the
> offered line). PASS = candidate beats BOTH comparators on moneyline
> log loss AND does not lose to either on totals log loss, paired
> one-sided significance at alpha = 0.05 / k, moneyline calibration
> slope within [0.8, 1.25]. One look, Feb 1, 2027. Puck line is scored
> and reported, not gated (its |gap| discipline lives in Stage A).
> CLV/ROI graded and reported; not gates."

Verdict per criterion, as of 2026-10-28:

| # | Criterion (design text) | State |
|---|---|---|
| 1 | Moneyline log loss beats BOTH comparators (public boxscore baseline; DK closing no-vig), paired one-sided at alpha = 0.05 / k | NOT RUNNABLE — window Dec 1, 2026 – Jan 31, 2027 has not opened; no paired DK FINAL captures for it exist |
| 2 | Totals log loss does not lose to either comparator | NOT RUNNABLE — same window, same captures |
| 3 | Moneyline calibration slope within [0.8, 1.25] | NOT RUNNABLE — same window |
| — | Precondition: Stage A verdict = PASS on Nov 30, 2026 | UNMET BY CALENDAR — verdict lands Nov 30, 2026 |

## No historical screen exists in the design — and the admission bars inventing one

The design names no backtest seasons, baselines, or pass criteria for
attempt-2 v1 outside Stages A and B above. Two standing bars confirm
that gap is deliberate, not an oversight this build may fill:

- Admission record section 8: "Backtests and fits run on this data
  are **design evidence only**; seasons a future construction is
  designed with can never later be presented as untouched validation,"
  and "Verification for NHL attempt 2 accrues **forward only**, from
  admitted pregame captures, under its own preregistration (Stage B
  window Dec 1, 2026 – Jan 31, 2027 per PR #2839, gated on the
  Nov 30, 2026 Stage A verdict)."
- Admission record section 4.1: the Stage B fit "sits entirely inside
  the 2026-27 season and therefore inside one disclosed vintage." A
  historical screen fitted on seasons ≤ 2025 would run on
  undisclosed-legacy xG — the exact pooling the vintage rule exists to
  refuse — for a construction whose declared fit never touches it.

**Overall screen verdict: NOT_EXECUTABLE on 2026-10-28.** Exact gap:
(a) Stage A is locked, one-shot, and its verdict date (Nov 30, 2026)
is future; (b) Stage B's window (Dec 1, 2026 – Jan 31, 2027), its
market captures, and its Stage A precondition do not yet exist;
(c) the design specifies no historical screen, and the admission's
forward-only law bars presenting one as validation. Family state is
unchanged: DESIGN ONLY, nothing frozen, no clock started, VERIFIED 0.
The next governed acts are the Stage A verdict (Nov 30, 2026), the
attempt-2 freeze package (which pins the freeze-owed constants listed
in BUILD_RECORD.md), and Stage B's one look on Feb 1, 2027.
