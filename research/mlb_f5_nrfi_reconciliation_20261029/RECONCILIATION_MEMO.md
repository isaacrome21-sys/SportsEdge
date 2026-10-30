# MLB F5 / NRFI reconciliation memo, 2026-10-29

Lane: grok (owner assignment t18u). **Read-only reconciliation.** This memo runs nothing, freezes nothing, amends nothing and creates no PLAY. PAPER / 0u.
All times are CT. Source timestamps were converted from UTC.

## 1. The #1580 production-parity confirmation: RECOVERED

- **Spec:** `docs/MLB_F5_NRFI_PRODUCTION_PARITY_2026.md`, merged in PR #1580 (`fa56de609`). The pass rules were frozen in it before the run.
- **Run:** owner issue #1581 "[MLB LINES] Research: 2026 F5 + NRFI production parity", opened Oct 4 9:50 PM CT.
- **Results:** posted by github-actions[bot] as comment 5987260253 on Oct 4 at 9:51 PM CT. The table below copies that comment verbatim; nothing was rerun.
- **Scope:** fixed candidate m30, no retuning. Eligible 2026 games: F5 = 2429, NRFI = 2429. The spec requires at least 1,000.

| Lane | Metric | Production | m30 | Rule | Met? |
|---|---|---:|---:|---|---|
| F5 | exact-score NLL | 5.4191 | 4.1927 | delta 95% CI entirely < 0 | Yes: delta -1.2264 [-1.4220, -1.0372] |
| F5 | W/T/L Brier | 0.6220 | 0.6187 | <= prod + 0.002 | Yes |
| F5 | O4.5 Brier | 0.2523 | 0.2503 | <= prod + 0.002 | Yes |
| NRFI/YRFI | log loss | 0.6979 | 0.6937 | delta 95% CI entirely < 0 | Yes: delta -0.0041 [-0.0068, -0.0016] |
| NRFI/YRFI | Brier | 0.2523 | 0.2503 | <= prod | Yes |
| NRFI/YRFI | 10-bin ECE | 0.0435 | 0.0189 | <= prod + 0.005 | Yes |

The bot's decision was **SHIP** on both lanes. Its own caveat reads: "A SHIP result authorizes only a separate production implementation with parity tests." That implementation is PR #1596 (`37cb99274`, Oct 4, "clean-port validated m30 F5 and NRFI/YRFI priors"). Main currently runs `mlb_first_inning_empirical_jeffreys_m30_v2` and the F5 source `..._LEAGUE_PRIOR_M30`.

**Upstream held-out study (#1578):** comment 5987117975, Oct 4 9:33 PM CT, spec `docs/MLB_F5_NRFI_TIGHTENING_PREREG.md` (#1577).
- Units: tune 2427, test 2430.
- F5: m30 SELECTED. 2025 NLL 5.5116 -> 4.1700; delta vs m0 -1.3416 [-1.5512, -1.1351].
- NRFI: direct_m30 SELECTED. 2025 log loss 0.7003 -> 0.6953; delta -0.0050 [-0.0072, -0.0028].
- Decision: "SHIP SEPARATELY".

**Flags. These are observations, not findings of error:**
- (a) In the #1581 table, F5 O4.5 Brier and NRFI Brier are identical for both models (0.2523 production, 0.2503 m30), to four decimals. These are different targets, so the identity could be a coincidence or a reporting/copy defect in the research script. Before anyone cites the Brier rows, check `scripts/research_mlb_f5_nrfi_production_parity.py` read-only. The decisive NLL and log-loss rows are not affected.
- (b) Neither study committed a result file. The issue comments are the only record, and both issues are still OPEN.
- (c) Neither study has a market leg. Under the Oct 27 law they establish model improvement only. **Neither F5 nor NRFI is VERIFIED.** The ladder lists every F5/first-inning family as PAPER with 0 graded picks.

**Rerun: not needed and not done.** If the Brier check in (a) finds a defect, a corrected run would need a new versioned spec. That spec would pin the script SHA, the same frozen rules, seed 20261005 and the 2026 eligible-game set, and it would be filed before the rerun. The old result stays on record.

## 2. `grok/mlb-f5-nrfi-prereg-20261013` (head `7cb99d154`) vs main (`43afcc170`) and current law

**What the branch holds:**
- It forked from main at `007f323f5` (Oct 13) and was never merged: 33 files, +5538/-49, 47 commits.
- Two preregistrations, both marked PRE-REGISTERED, NOT EVALUATED:
  - `docs/preregs/MLB_F5_INNING_EXPOSURE_NB_PREREG_20261013.md`: per-inning NB2 with starter/bullpen exposure.
  - `docs/preregs/MLB_NRFI_FIRST_INNING_STARTER_PREREG_20261013.md`: NB2 first inning with a starter index.
- Infrastructure:
  - `sportsedge/mlb_pregame_starter_adapter.py`, `sportsedge/sports/mlb/starter_capture.py` (1743 lines) and `sportsedge/mlb_pit_binding.py`. None of these exists on main.
  - Receipt-journal and clock hardening in `sportsedge/mlb_source.py` plus 10 shared callers.
  - A large adversarial test battery.
- Both preregistrations reserve the **2027 regular season** as an untouched evaluation window, run once after the season, with the implementation SHA-pinned before 2027-03-01.
- Their burned-window hygiene is consistent with current law: 2024 and 2025 are training-only.

**What would need to change before offering them as the 2027 forward-market preregistration:**

1. **Existing-model baseline is wrong or missing (law leg (a)).**
   - The NRFI B1 names `mlb_first_inning_team_rates_poisson_jeffreys_v1`, but production has been `..._jeffreys_m30_v2` since #1596. That was already true on Oct 4, before this prereg was written. B1 must be the current production m30 model, pinned by SHA.
   - The F5 preregistration's baselines are B1 (league empirical) and B2 (scaled full game), and neither is the existing model. It needs a baseline for the production m30 F5 distribution.
2. **Market leg is optional; it must be mandatory (law leg (b)).**
   - Both preregs say the DK baseline is used "if genuinely captured; else MISSING". Under the Oct 27 definition, a construction without a contemporaneous market comparison cannot be VERIFIED.
   - Each prereg needs a preregistered market criterion: de-vig method, the metric vs no-vig close (for example log-loss difference or CLV), its CI rule, and the minimum paired-row count, with INSUFFICIENT_DATA if it is not met.
   - It must also name the capture source and when quotes are snapped (strictly pregame, before first pitch).
   - `scripts/archive_mlb_additional_odds.py` on main handles F5_MONEYLINE, F5_RUN_LINE, F5_TOTALS and NRFI/YRFI. I did not verify that it produces DK rows on a schedule. That has to be confirmed before freezing.
3. **Promotion language predates the law.** "promotion requires the separate market and forward-evidence gates" must be replaced with:
   - the Oct 27 definition (VERIFIED = passes the preregistered window vs model AND market);
   - forward clocks report only;
   - the multiple-testing policy alpha = 0.05/k, with k counted at verdict time.
4. **Freeze conventions are missing.** Neither prereg has:
   - a SPEC_HASHES entry (sha256 of the spec and the implementation);
   - a version label;
   - a FREEZE_RECORD;
   - an exact-head independent review;
   - an owner merge as the recording act.
   - It also needs a one-look/anti-peeking clause: a failed look is recorded, and any successor is a new version.
   The Mar 1, 2027 SHA-pin date can stay as the deadline for the freeze act.
5. **Starter dependency is unmerged.**
   - Both candidates BLOCK any row without a verified pregame starter binding from `mlb_pregame_starter_adapter`, which is not on main.
   - The capture module is "offline, activation held". Without live starter capture in 2027, every row BLOCKS and the window is empty.
   - The starter stack must be reconciled to main (16 days of drift; `mlb_source.py` plus 10 shared callers will conflict) and independently reviewed, and live capture needs owner activation before 2027 opening day.
   - The prereg should state an exact BLOCKED-rate threshold above which the verdict is INSUFFICIENT_DATA.
6. **Smaller fixes:**
   - F5 §2 excludes 4.5-inning home-leading games. That should be checked against DK's actual F5 settlement rule, which is market-specific.
   - The training cutoff (Final before 2026-10-13T00:00Z) should cover through the 2026 World Series end, or say explicitly that the postseason is excluded. The preregs say regular season only, which is consistent.
   - The bootstrap is game-level. The program convention elsewhere is date- or block-clustered (#1580 used date-clustered). Pick one and justify it.

**Ownership:** the branch is grok-authored (my lane). No rocky/* or Lane A work is touched. The branch was left unchanged; this memo does not edit it.

## 3. Retrosheet gamePk / UTC check: claim CONFIRMED

Checked directly against the admitted, pinned 2025 file. `2025eve.zip` was re-downloaded from retrosheet.org and matched its pin: 2,527,926 bytes, sha256 `5ece2be6…303c`. Then I scanned all 2430 game records.

- **gamePk: absent.** The game key is the Retrosheet id (for example `ANA202504040`). No record carries an MLB gamePk.
  - The scope extension's `reconstruct_proof.py` builds a gamePk crosswalk only for three sample games.
  - That crosswalk joins on date plus home team and ignores `info,number`. 2025 has 28 doubleheaders (number 1/2 = 56 games), and on those the join can pick the wrong game.
  - A full crosswalk would need date + home + doubleheader number to StatsAPI schedule, with a uniqueness check.
- **UTC: absent.**
  - `info,starttime` is a local wall-clock string (for example `6:38PM`, present on 2430/2430 games) with no timezone field.
  - There is no completion or observed-at time.
  - `info,inputtime` is the scorer's data-entry time (for example 2025/06/28 09:11:34) with no zone.
- **Consequence:** as written, the first-inning PBP screen spec requires "exact gamePk" and "first-pitch/completion/observed-at UTC" per pack. Retrosheet alone cannot satisfy that.
  - It can satisfy the outcome and plate-appearance content (733,260 PAs over 2022–2025, zero unresolved batters or pitchers per `proof_results.json`).
  - The identifiers and UTC times would have to come from a StatsAPI crosswalk, or the spec would have to be amended. Either is an owner decision, not something taken here.
- **Market data:** no admitted source has historical DK first-inning K, batters-to-the-plate, F5 or NRFI quotes. SmartStake covers six player markets, 2026-03-21 to 2026-07-05 only. So the market leg for these families is **forward (2027) only**.

## 4. Recommendations (in order; none executed)

1. Do a read-only check of the identical Brier values in #1581 (flag a). Record the outcome as a comment or file; it changes no decision.
2. Commit the #1578/#1581 results into the repo as a results record that cites the comment ids. The numbers above are copied verbatim. Then let the owner close both issues. Neither step is taken here.
3. Draft v2 of both preregistrations on a new grok branch, applying changes 1–6 in §2. Do not edit the Oct 13 files: they are pre-registered text and stay as history.
4. Reconcile the starter-capture stack to main as its own PR, with an exact-head independent review and owner activation before 2027 opening day. Without it, the 2027 window is empty.
5. Confirm that F5/NRFI DK capture actually produces rows before any freeze. The freeze act (SPEC_HASHES + review + owner merge) must happen before 2027-03-01.
6. The first-inning K and batters-to-the-plate screen stays INSUFFICIENT_DATA / NO_MARKET_TEST unless the owner rules on a StatsAPI crosswalk or a spec amendment for the identifiers and UTC times.
