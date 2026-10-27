# CFB converged-ratings successor: pre-freeze screen, October 26, 2026

**Verdict: FAILED for spreads and totals.** No viable score-only construction
was found in this single fixed research instantiation. This does **not**
adjudicate the unmeasured backup-QB feature or claim that the original
constructions-folder design file was available.

## Fixed instantiation

The original DESIGN ONLY file was not in this checkout or the searched saved
files. The implementation explicitly supplies research constants omitted from
the message, *not* purported owner-frozen values: score baseline 28/team,
ordinary home-field advantage 2.5 points (zero at neutral sites), last five
results per team, 3-game ridge prior, iterated opponent offense/defense
adjustments to 1e-10 tolerance, 500-iteration fail-stop, raw margin +/-24
point cap. Only FBS-vs-FBS completed games with kickoff +24h embargo
(unverified score-availability proxy) train the ratings. Predictions begin
Week 5 with at least three qualifying prior games for each team.

The raw predictions use **no market line**. A separate proposed post-freeze
market anchor has a hard 4-point disagreement limit and would require an
independently timestamped current entry quote (never the hindsight close),
but is **not used** in the viability screen and carries no pricing authority.
Historical point-in-time
backup-QB change receipts were unavailable: that signal is NOT EVALUATED;
no invented replacement-QB adjustments were entered.

## Preregistered viability rule for this experiment

The pooled OLS slope with intercept of (actual - published close) on
(raw model - published close) must be >= +0.10; beta must be positive in at
least 2 of 3 design seasons; pooled model MAE must be within 0.5 points of
the close on identical games. The screening implementation also refuses fewer
than 100 paired observations per season. These conditions are conjunctive,
separately for spread and total. No post-result cap, shrinkage or threshold
sweep is performed.

## Data and exclusion accounting

The input consists of SportsDataVerse `espn_cfb_betting` and
`cfb_schedules` CSV releases for 2023–2025, read as published. The source
documents a three-game 2023 CSV-versus-parquet divergence; no per-game winner
was manufactured. The stacked SDV integrity repairs are applied.

| Step | Game count |
| --- | ---: |
| Published betting rows | 2,835 |
| Scoreable published spread / total | 2,781 / 2,781 |
| Completed schedule rows, all divisions | 11,352 |
| FBS vs FBS results | 2,398 |
| FBS vs FBS before Week 5 (excluded) | 739 |
| Week 5+ insufficient released history (excluded) | 58 |
| Eligible projections | 1,601 |
| Flagged spread / total unavailable after projection | 2 / 2 |
| **Identical scored cohort per market** | **1,599** |

This is a selected, Week-5+ FBS/FBS population, **not** a 2,781-game full-slate
headline. Partial 2026 and biased historical 2012–2022 odds strata do not
enter the design screen.

Of 8,954 excluded non-FBS/FBS result rows, 210 lacked at least one division
label (54 missing home, 161 missing away, with 5 overlapping); the other
8,744 carry known FCS/II/III divisional labels. None of the source's
2,781 scoreable published-close rows has a missing division label.

## Measured result against the published close

| Metric | Spread | Total |
| --- | ---: | ---: |
| Paired games | 1,599 | 1,599 |
| Pooled residual beta | +0.036746 | +0.071880 |
| Raw model MAE (points) | 12.9211 | 13.2540 |
| Published-close MAE (points) | 12.1191 | 12.5216 |
| Model worse than close | +0.8019 | +0.7325 |
| Pooled beta >=0.10 | **FAIL** | **FAIL** |
| At least 2/3 seasons beta >0 | PASS | PASS |
| Accuracy <= close MAE +0.5 | **FAIL** | **FAIL** |
| 100+ observations/season | PASS | PASS |

| Season | n per market | Spread beta | Total beta |
| --- | ---: | ---: | ---: |
| 2023 | 531 | +0.089598 | -0.081614 |
| 2024 | 530 | +0.139881 | +0.225296 |
| 2025 | 538 | -0.139366 | +0.053924 |

An independent numerical recomputation using pandas sample covariance /
variance and absolute errors directly on the exported row-level predictions
reproduced pooled beta and both MAEs. The targeted suites returned **40
passed, 6 subtests passed**; 37 pre-existing NumPy timedelta deprecation
warnings from the parent evaluator, no failures. Ruff: clean for the three
new Python files.

## Reproduce and provenance

```bash
python scripts/collect_cfb_sdv_closes.py --seasons 2023-2025 --out-dir output/cfb_successor_20261026
python scripts/evaluate_cfb_converged_viability.py --data-dir output/cfb_successor_20261026 --out-dir output/cfb_successor_20261026
python -m pytest -q tests/test_cfb_converged_viability.py tests/test_cfb_sdv_closes.py
```

Source retrieval UTC: 2026-10-26T23:18:34Z; per-asset raw SHA-256 values are
retained in generated `provenance.json`. Joined result-file SHA-256:
`1177406214cb9dc83e0fea496d1361793c78f76eec60519196741025cc599caa`.
Published-close file SHA-256:
`9126e1fa1e54ce7bad0f92073da059904340defaa4bd7cf8add85dec99361331`.
The report also hashes the two predictive/evaluator source files.

**Authority and limitations:** the book/source provides neither historical
prices nor individual line-capture timestamps. Every comparison is vs
published close, *never verified CLV*, and no ROI claim is derived from
assumed -110 odds. Score result-publication timestamps likewise do not exist;
kickoff +24h is only a conservative, unverified research proxy.

These historical rows cannot start a prospective clock. No Model_P, pricing,
EV, card, Truth Gate, promotion, bet, stakes or OFFICIAL authority is
created. CFB production weight remains **0%**. Do not retune and retry this
failed score-only specification as if it were a new independent signal.
The proposed backup-QB construction is independently blocked until source-
bound, timestamped, historical as-of change data and its own prior-frozen
specification are available.
