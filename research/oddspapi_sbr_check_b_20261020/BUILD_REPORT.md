# Check B — NBA/SBR archive numeric comparison (research-only draft)

**Base at branch creation:** `647f6cd404adf7b23a86eb3689a53b004dd5d084`  
**Branch:** `feat/oddspapi-sbr-check-b-dryrun-20261020`  
**Authority:** NONE. This is a **numeric dry-run**, not an admission verdict, true historical close, certification of an SBR record, or model/PLAY gate.

## Source for exact numbers

Rocky/Muse's GitHub issue #2447 comment (`AGENT / TIME 2026-10-20 ~23:31 CT`, issuecomment `6308060982`) transcribes `ADMISSION_PROTOCOL_DRAFT.md` §3 from Rocky's non-repo workspace, under owner-delegated automatic-admission-upon-proof ruling. Original draft has **not been committed into this repository**, so the original document's hash is not independently verifiable here. This is a **faithful research implementation of the posted numbers**; no unpinned draft or user-supplied flag confers source admission.

### B exact numeric bars (NBA x market x DraftKings)

1. Stratified sample **at least 200 distinct games, across at least 4 seasons**, with the final-week set of the most recent complete season.
2. Moneyline: absolute American-odds difference **≤10 for at least 97%** of prelisted quote comparisons.
3. Spread and total: **exactly the same posted numeric line in at least 95%**, within **0.5 points in at least 99%**, and **zero games** with absolute line difference **>1.0 point**.
4. Bookmaker identity must be explicitly recognizable as DraftKings on BOTH SBR and OddsPapi observations; wrong/unidentified is a **failure**, never excluded.
5. Missing source closes are **failures in the original comparison denominator**, never removed. Any official-schedule final-week fixture omitted from submitted records adds a failing denominator entry and fails final-week completeness.
6. No self-reported `B_passed`, `owner_approved`, `ADMITTED` or altered numeric thresholds accepted by parser.
7. Market buckets are separate. Inputs require exactly one deterministic canonical comparison side per game (home ML, home spread, total OVER); duplicate game IDs refuse, and results disclose original per-season sample sizes. This is **not a claim of paired two-sided price completeness**.

## Implementation

New additive `sportsedge/oddspapi_sbr_check_b_dryrun.py`: one offline function `inspect_sbr_check_b_dryrun`, schema `ODDSPAPI_SBR_NBA_CHECK_B_DRYRUN_V1`, exact decimal (nonfloat-binary comparison) thresholds, safe reason codes, four-season and claimed final-week set counts, fixed denominator, strictly explicit bookmaker identity. Uses only caller-provided **synthetic/unverified** quote values and manifest hashes. No API requests, no keys, no account access, no backfill, no runtime writer, no config changes.

**Every possible successful function return still has:** `status: NOT_ADMITTED_UNPINNED_B_DRYRUN`, `admission: NOT_ADMITTED`, `source_eligible: false`, `play_authority: false`, `true_close_proven: false`. Both schedule and archive SHA fields are only syntactic shape evidence and marked `independently_authenticated: false`. **Passing a numeric threshold against user-supplied records is never validation of the records.**

Original §3 other checks remain separate: Check A ±30-minute matching/exact line/±10 at ≥95% (with all-timestamps and no-poststart qualifiers), Check C MLB ALCS G6 reproduction and ≥200 SBR MLB games, Check D 100% strictly pre-actual-first-play + ≥95% within six hours + consistent timezone on ten tightest A pairs, Check E ≥90% sampled-window coverage. These are not silently satisfied by B.

## Exact Git blobs at writing

- `sportsedge/oddspapi_sbr_check_b_dryrun.py`: `55bc588d854edf4b1d8ca519965db969e93cbde5`
- `tests/test_oddspapi_sbr_check_b_dryrun.py`: `4ecea706e0e7a76691f9c5c3db7f9f5805c04af7`

Tests authored: **18 pytest test functions** (some parameterized): 200/4, 194/200 vs 193/200 ML, +10/+11, 190/200 exact and 198/200 within half, any >1.0 failure, missing close retained in denominator, missing final-week fixtures, wrong/missing book, 199 observations, only three seasons, duplicate rows, false owner pass fields, invalid line/season, determinism.

**Execution honesty:** no independent targeted pytest result is claimed. Reviewer must run `python -m pytest tests/test_oddspapi_sbr_check_b_dryrun.py -q` on exact head (standard nine PR workflows may not run this test). The verifier must independently reconcile §3 values against the original versioned file or an approved commit/hash before any production admission implemention. Another independent reviewer must verify actual source/cohort and close data, beyond a passing synthetic arithmetic suite.

## Coordination / merge

- Claimed by ChatGPT in #2447 after Rocky supplied governing draft thresholds; Grok's earlier repo-only `B NOT LOCATED` was accurate at the time and not contradicting Rocky's later external document.
- Rocky owns independent verification/merger. ChatGPT may carry out mechanical merges ONLY for specifically approved exact heads with current-updated-branch green CI and GitHub protections; never self-approve this branch.
- Frozen V8 policy `config/mlb_v8_oddspapi_evidence_contract.json` remains byte-identical; #2436 and #2446 remain separately owned (structural and A/D).
