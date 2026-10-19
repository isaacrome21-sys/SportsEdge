# MLB Pitcher Early-Exit Component V1 — Case-Check Record

**Status: RESEARCH ONLY. Not wired into any runner, card path, or the
frozen forward protocol. Zero card pricing impact. No PLAY eligibility is
created by anything in this record.**

- Preregistration: `docs/MLB_PITCHER_EARLY_EXIT_PREREG_V1.md`,
  sha256 `d9b276a4fed20f025a39604ae00004a32a28b6138104a5aee2cd9276ddd206d6`,
  committed alone (commit `6f2217716`) on branch
  `research/mlb-pitcher-early-exit-v1-20261018` **before** any component or
  scoring code existed.
- Component: `sportsedge/mlb_pitcher_early_exit.py`
  (`mlb_pitcher_early_exit_v1`).
- Scoring: `scripts/build_mlb_pitcher_early_exit_case_check.py`; full
  machine-readable results:
  `research/mlb_pitcher_early_exit_v1_20261018/case_check_results.json`.
- Data: MLB StatsAPI (free, public), fetched 2026-10-19T03:38:07Z. Cache
  artifacts (aggregated starts tables are the operative inputs):

  | artifact | sha256 |
  |---|---|
  | gamelog_2026_607192.json | `e4e703f3c9f1dee34f1ca0d461213f7024877a85cdd0b2e7f3f65639ba834371` |
  | gamelog_2026_675660.json | `1f6baa4b6b425f9af385ddb406bbd93d061751a25fb8b2750c4ef64cd5c3ca40` |
  | starts_2023.csv | `be0563618a519e6bf751f00b605c1049a92c5ad052cd8a15844116d9a17c9937` |
  | starts_2024.csv | `3a13c674c9977c117ac30a1c1a7798f11605c1f487cea312a48466aa41857973` |
  | starts_2025.csv | `5d7d29968cbe3c8e0f453204750ed41d2234a372737cab88ec77e103c4dcd956` |

## Verdict: CASE_CHECK_PASS (n = 2 — a case check, NOT validation)

Under the frozen bar of preregistration §8:

- Summed log score, existing engine tails: **−∞**
- Summed log score, early-exit component: **−5.0889**
- Component assigned nonzero mass to both realized exit bands
  (C = 4: 0.15713; C = 1: 0.026829).

**Read the −∞ honestly.** On the Drohan case the existing tails assign
literal zero mass to the realized outcome (no prior start in his pool had
exactly 1 K, and the engine's Jeffreys settlement smoothing puts no mass
on unobserved interior values), so that leg is decided by a support hole,
not by a close call. The Glasnow leg is a genuine finite improvement
(+0.4566 log), and the descriptive CRPS — finite for both distributions —
also favors the component on **both** cases. None of this is validation
evidence: n = 2, on the two losses that motivated the component. See
preregistration §9 for what promotion would still require.

## Fingerprint gate (preregistration §3) — PASSED before scoring

Both case pools were reconstructed as the pitcher's 12 most recent games
started strictly before 2026-10-15 (MLB StatsAPI gameLog, season 2026),
and all **nine** model probabilities recorded on the Oct 15 cards were
reproduced exactly via p = (0.5 + count) / 13:

- Glasnow: K O6.5 #{K≥7} = 10 ✓ · Outs O14.5 #{outs≥15} = 10 ✓ ·
  BB U2.5 #{BB≤2} = 9 ✓ · HA U3.5 #{H≤3} = 7 ✓ · ER O1.5 #{ER≥2} = 8 ✓
- Drohan: K O2.5 #{K≥3} = 10 ✓ · Outs O7.5 #{outs≥8} = 12 ✓ ·
  HA O2.5 #{H≥3} = 12 ✓ · ER O0.5 #{ER≥1} = 12 ✓

Reconstructed pools (date, outs, K, H, R, ER, BB, pitches):

- **Glasnow** (λ = ΣK/Σouts = 92/204 = 0.45100 K/out): 2026-04-04 (18, 9),
  04-10 (18, 7), 04-17 (21, 7), 04-23 (24, 9), 04-29 (17, 9), 05-06 (3, 2),
  08-25 (15, 7), 08-30 (21, 6), 09-05 (18, 8), 09-12 (12, 7), 09-18 (18, 10),
  09-24 (19, 11). [outs, K shown; full lines in the results JSON.]
- **Drohan** (λ = 61/183 = 0.33333 K/out): 2026-07-06 (18, 2), 07-11 (19, 6),
  07-18 (18, 9), 07-24 (18, 6), 07-31 (18, 7), 08-07 (15, 4), 08-13 (16, 5),
  08-23 (15, 5), 08-29 (15, 6), 09-04 (12, 5), 09-12 (11, 4), 09-24 (8, 2).

## Historical exit model (2023–2025, frozen construction)

14,574 regular-season starts (2023: 4,860 · 2024: 4,854 · 2025: 4,860).
Starters with numberOfPitches missing: **0**. League K rate
λ_lg = 0.30995 K/out.

| State | Rule (in order) | Starts | Weight |
|---|---|---|---|
| HOOK | runs allowed ≥ 5 | 2,662 | 0.18265 |
| LEASH | else pitches ≤ 65 | 1,095 | 0.07513 |
| NORMAL | else | 10,817 | 0.74221 |

Exit-band masses, completed innings C = floor(outs/3):

| C | HOOK | LEASH |
|---|---|---|
| 1 | 0.02780 | 0.28858 |
| 2 | 0.07325 | 0.23562 |
| 3 | 0.18032 | 0.18721 |
| 4 | 0.30841 | 0.15342 |
| **1–4 total** | **0.58978** | **0.86484** |

Sanity checks (preregistration §7): (a) nonzero early-exit mass under both
scenarios — **yes** (0.5898 hook, 0.8648 leash). (b) Mixture P(C ∈ 1–4) =
0.28688 vs pooled empirical 0.28688 — equal, as the preregistration's
identity requires; code-correctness check passes. (c) Per-band masses are
the table above. (Exit masses are λ-independent; for the league-average
profile λ = λ_lg the implied probability that a start ends in innings 1–4
is 0.28688 under the mixture.)

## Case scores

### Case A — Unit #3, Tyler Glasnow (HOOK), realized K = 6, exit 13 outs (C = 4)

| Distribution | P(K = 6) | Log score | CRPS (descriptive) |
|---|---|---|---|
| Existing engine tails | 0.076923 (= 1/13) | −2.5649 | 1.1893 |
| Early-exit component | 0.121435 | **−2.1084** | **0.8364** |

Component exit-band mass at realized band C = 4: **0.15713**.

### Case B — Unit #4, Shane Drohan (LEASH), realized K = 1, exit 3 outs (C = 1)

| Distribution | P(K = 1) | Log score | CRPS (descriptive) |
|---|---|---|---|
| Existing engine tails | **0.000000** | **−∞** | 2.9024 |
| Early-exit component | 0.050767 | **−2.9805** | **2.7260** |

Component exit-band mass at realized band C = 1: **0.026829**.

## Preserved records — untouched

- The frozen protocol
  `config/research/mlb_pitcher_k_forward_validation_v1.json` is unmodified;
  protocol state remains 5 recorded / 4 graded (1–3, −2.06u).
- The graded records for units #3 and #4 stand exactly as graded on
  Oct 15–17 (`operative_run_20261015_evening/GRADE_AND_REVIEW_RERUN.md`,
  `operative_run_20261015_night/GRADE_AND_REVIEW.md`). Unit #5 (Martinez)
  remains VOID per owner ruling and was not scored.
- The existing engine (`sportsedge/pitcher_joint_engine.py`) is unmodified;
  its tails remain in place for comparison and for the protocol.
