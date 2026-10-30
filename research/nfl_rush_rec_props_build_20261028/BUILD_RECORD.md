# BUILD RECORD — `NFL_RUSH_REC_PROPS_V1` (pre-outcome readings)

**Status: COMMITTED BEFORE ANY OUTCOME STATISTIC IS COMPUTED.** No screen
has been run. The construction code and screen script are not written yet;
they will implement exactly the readings below. Nothing here prices a
game, opens a clock, changes a registry entry, or claims freeze/adoption.
**Date:** Wed Oct 28, 2026 (CT) · **Author:** Grok Bot.

**Authority:** design `research/nfl_rush_rec_props_design_20261028/DESIGN_NFL_RUSH_REC_PROPS_V1.md`
(sha256 `d088676745914f11215352bbafcdbde5cd759d9d1e7d21d2c5ebaccfe222ad8c`);
owner build authorization and independent review (SOUND-WITH-FLAGS, six
flags) posted on PR #2916, comment 6486781392 (Oct 28, 2026, 10:07 PM CT).
Design §7 (ambiguity rule) governs everything recorded here.

## 1. Input hashes (all verified on the build box before this record)

| Input | sha256 |
| --- | --- |
| ps_2018.csv.gz | `15730d75271ec10affc412b50b22fc8e3d6ce8f442d377936f65bc0044ef15bf` |
| ps_2019.csv.gz | `d143b91c62380bed1587fe390e594d0e5555e8ebac81fcc7212ad7224115caf2` |
| ps_2020.csv.gz | `e23a81d6ed3c94bd2dd14a5ee3ed94584a69e67fdb985c1ba0de4ccbc5a2bdcc` |
| ps_2021.csv.gz | `a2fb266576a1bde5d7978005a5f6ccf83e3c023234da500d38cf6a14f40a01c8` |
| ps_2022.csv.gz | `2b7dca6814993b9fd6ad3d4fdc56131663311bbe83281126e1ac441620d824ba` |
| ps_2023.csv.gz | `b7590543f3c81dceb17d7577a1dce7b8ff1a9aacf0f562e3d7bbc7e60f37bc9b` |
| ps_2024.csv.gz | `629b77e0c88d361f8b5c4a850e7866013aa670b7a5a94b7f1d0c591adf18f971` |
| sp_2025.csv.gz (original, rebuild source only) | `c7401e321bdb369443f3280b9acd74ba6e16d82e710383bf1c01acabfebeac0b` |
| sp_2025_played_v2.csv.gz (rebuilt, §2) | `f2768ac1c71e5ed616307106df32ef8ad4fc7d548bb96600f6a616fb631f7b48` |
| eval_nfl_props_calibration_v1.py (incumbent, imported unmodified) | `66de56155e3c36f90c1f39c648b24e724328ec86056dee0e9adbed57281bc25b` |
| build_sp_2025_played_v2.py | `795f01e54f3c1f0ee2c105beeb3a2b26b7d27dcc128b19ebd3fb1ce5c0293b0b` |
| DESIGN_NFL_RUSH_REC_PROPS_V1.md | `d088676745914f11215352bbafcdbde5cd759d9d1e7d21d2c5ebaccfe222ad8c` |

All eight player files match `research/nfl_props_part2_20261018/SPEC_HASHES.txt`.
The screen script re-verifies every hash and refuses on mismatch.

## 2. sp_2025_played_v2 rebuild (done before this record)

Rebuilt with the repo's own `build_sp_2025_played_v2.py --src sp_2025.csv.gz`:
source 19,422 rows, kept 18,618, removed 804 (771 REG, 33 POST) — the B8
amendment's counts. **Disclosure:** under Python 3.13.5 / zlib 1.3.1 the
script's gzip bytes hashed `180e2129…06cf` (≠ pin), with decompressed CSV
content identical to the matching build; under Python 3.12.15 / zlib 1.3.2
the same script on the same source produced **`f2768ac1…f7b48` = the B8
pin exactly**. The pin-matching artifact is the one used. The mismatch is
compressor-version byte drift in gzip output only (decompressed sha256
`526603b1…9224` identical in both builds).

## 3. Review flags — readings

**F1 — r_N pooled moment equation (pinned).** Per market, over the
2018–2019 training rows (§4 R9), with n̂ the row's point-in-time expected
opportunities (design §3.1) and N its realized opportunities:

    r_N = Σ n̂²  /  Σ [ (N − n̂)² − n̂ ]

(the NB2 moment identity Var(N) = n̂ + n̂²/r_N, pooled as ratio of sums).
If the denominator is ≤ 0, N is Poisson (Var(N) = n̂). REC_YDS and
RECEPTIONS share population and opportunity (targets), so they compute
the same r_N independently.

σ² (design §3.3, already pinned there): mean over training rows with N > 0
of (Y − N·ê)² / N, with ê the row's point-in-time ê (§3.2) and Y the
market's yardage stat. Not used for RECEPTIONS.

**F2 — criterion 3, INC's gap.** INC's gap is computed on **INC's own
deciles**: rows sorted by INC's P(over) at the line proxy, split exactly
as the incumbent evaluator's `over_line_deciles` does
(`order[k*n//10:(k+1)*n//10]`), top = decile 10, bottom = decile 1 —
the measure that produced 71/60 and 63/54. M's gaps are computed the same
way on M's own sort. Leg 3 passes iff M_gap_top ≤ 0.05, M_gap_bottom ≤
0.05, M_gap_top ≤ INC_gap_top, and M_gap_bottom ≤ INC_gap_bottom.

**F3 — bootstrap seed.** The screen sets the imported evaluator's module
constant `SEED = 20261028` at runtime before any `boot()` call and asserts
it at each call; the pinned file (constant 20261017) is not edited. The
results file records the seed actually used.

**F4 — incumbent reproduction scope.** Design §1's headline incumbent
CRPS (19.46 / 18.33 / 1.282) come from the pre-B8 published run on the
original sp_2025 file; on the B8 file set exact reproduction of those
figures is scoped to 2020–2024 rows, and the paired in-screen legs
(INC vs M on identical rows) are unaffected.

**F5 — §3 readings.** (a) Share EWMA decays **per played game**: weight
0.5^(j/3), j = 0 for the player's most recent prior played game with his
current team, j = 1 the next, etc.; team weeks the player missed add no
decay. (b) Role-pool membership for S, E, P = **exactly G's pool**: the
incumbent `build()` qualified rows for that market in strictly earlier
weeks of the same season, else all of the previous season's qualified
rows (the incumbent `league_pool` rule). Over those pool rows:
S = mean of each row's realized share; E = Σ yards / Σ opportunities;
P = Σ receptions / Σ targets.

**F6 — naming note.** `config/nfl_family_registry_v2.json` registers
these markets RESEARCH_ONLY under NFL_PLAYER_EMPIRICAL. Not touched here;
any future §8 forward prereg must reconcile naming there.

## 4. Further readings (design §7), recorded before any outcome

- **R1 Opportunities:** RUSH_YDS = carries; REC_YDS, RECEPTIONS = targets.
- **R2 Rows/files:** the incumbent loader's rule (REG only, `f()` coercion,
  all eight pinned files). Team identity = `recent_team` (ps) / `team` (sp).
  A team-game = (season, week, team).
- **R3 Team V:** sum of the opportunity column over every loaded row of
  that team-game (all positions). A team-game with V = 0 yields no share
  observation and is counted in the report.
- **R4 V̂:** prior team-games = the player's current-row team's team-games
  in strictly earlier weeks of the same season. L = mean V over all
  team-games in strictly earlier weeks of the same season, else all
  team-games of the previous season.
- **R5 Trades (design §7 example):** ŝ uses only prior played games with
  the current-row team; with none, Σw = 0 and ŝ = S. ê and p̂ use all
  prior same-season played games.
- **R6 Prior alignment:** the player's prior games are the incumbent's
  (same loader order); the screen asserts, per row, that its own prior stat
  list equals the incumbent's `prior` list.
- **R7 Degenerate values:** μ_Y = max(n̂·ê, 1e-6) (the incumbent's floor);
  Var(Y) = n̂σ² + ê²(n̂ + n̂²/r_N) (Poisson term only if r_N is Poisson),
  floored at 1e-9; Gamma shape μ²/Var, scale Var/μ. n̂ floored at 1e-6.
- **R8 Receptions CDF:** P(R ≤ k) = Σ_n NB(n; r_N, n̂)·Binom.cdf(k; n, p̂),
  N summed up to the first n where P(N > n) < 1e-9 (scipy `nbinom(r,
  r/(r+n̂))`, or Poisson if r_N is Poisson).
- **R9 Training rows:** all 2018–2019 qualified rows (no week filter) for
  which G's pool is non-empty — the incumbent's own training-row rule.
- **R10 Grid, CRPS, line proxy, deciles:** the incumbent's (`GRID_LO −60`,
  `GRID_HI 700`, `crps()`, line = floor(median prior) + 0.5; yardage
  P(over) by interpolation, count P(over) = 1 − CDF[floor(line)]).
- **R11 Unpriceable:** any non-finite μ, variance, or CDF value. > 0.5%
  of a market's rows → that market NOT_EXECUTABLE.
- **R12 Integrity before any M score is read:** hashes; evaluator hash;
  the INC arm's n and mean CRPS (INC, B1, B2) equal the pinned evaluator's
  own `evaluate()` output on the same files; R6 alignment; r_N, σ² use
  2018–2019 rows only (asserted). Any failure → NOT_EXECUTABLE.
- **R13 Leg 4:** per scored season, mean CRPS(M) − mean CRPS(INC) ≤ 0.01 ×
  mean CRPS(INC).
- **R14 One declared run;** the results JSON and verdicts are committed as
  produced.
