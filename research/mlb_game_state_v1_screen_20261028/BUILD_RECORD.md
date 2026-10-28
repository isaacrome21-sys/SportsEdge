# MLB_GAME_STATE_V1 — build record

Construction and screen runner for the design in
`research/mlb_game_lines_successor_20261028/DESIGN.md` (PR #2887).
Design/screen scope only: no freeze, no forward rows, no validation
claim (the design reserves verification to the 2027 forward clock).

## Construction (as built)

Per game, per team, run means are built from plate-appearance state:

- **PA values** are run-expectancy deltas (RE24 form): for each PA,
  `v = runs_on_play + RE(state_after) − RE(state_before)`, with the RE
  matrix fitted on the fold's fit window only (same-outs pooled fallback
  for unobserved states). League mean PA value is ~0 by construction, so
  player values are deltas on the runs/PA scale.
- **Lineup/platoon**: each batting slot's expected delta is the batter's
  outcome-class profile (OUT/BB/HBP/1B/2B/3B/HR/ROE/FC/OTHER) for the
  (batting side, pitcher hand) cell, shrunk toward the league cell class
  shares, valued at fit-window class linear weights, with class shares
  scaled by the game's park component factors (pinned table, PR #2856)
  and renormalized.
- **Pitcher prevention**: a pitcher's value is the mean PA delta he
  ALLOWS (batter-perspective scale; elite < 0, poor > 0), shrunk toward
  the league mean for the batter's side. Per-PA run rate is additive:
  `rate = L_runs_pa + off_delta(batter) + allowed_delta(pitcher)`,
  floored at 0.02.
- **Starter/bullpen split** (the V1 Phase D lesson): the starter phase
  share φ comes from the machinery's expected starter innings; the
  bullpen phase uses the availability pool below.
- **Bullpen availability**: relievers with an appearance in the trailing
  14 days form the pool. Availability tiers from trailing-3-day workload:
  full weight (≤40 pitches and ≤2 appearances), half weight (≤65 pitches
  and ≤3 appearances), otherwise the next-man-up tier (league prevention
  + 0.010 runs/PA allowed, weight 0.5). Pool prevention is the
  availability-weighted mean of per-pitcher allowed deltas, mixed over
  pitcher hands by the machinery's bullpen hand shares.
- **Umpire**: home-plate umpire's shrunk historical runs/game as a
  log-multiplier on both teams' λ, capped at ±0.03. Totals-primary by
  construction (it scales the total, not the split).
- **Weather**: first-pitch-hour Open-Meteo Previous Runs `previous_day1`
  features (temperature, wind-out component vs the park's CF bearing,
  precipitation indicator) enter as a clamped (±0.25) log-multiplier on
  the total; coefficients fitted on fit-window games only. See
  `weather_pin_record.json`.
- **Calibration layer**: logistic regression on (1, λ_home − λ_away,
  λ_home + λ_away), fitted on fit-window scored games only, one layer per
  variant (full / control / each ablation), so every variant is priced
  through the same layer form. Team totals split the posterior λ by the
  fit-window home log-advantage. The fold's NB dispersion (fitted on fit
  totals) is reported in the fold diagnostics.

## Declared constants (one configuration; no tuning)

Machinery carried from V1 Phase D: K_SHRINK 20, KS_OUTS 150, KS_STARTS 5,
KBP_OUTS 180, MIN_STARTS 3, Elo K=20 with HFA grid-searched 0–60 by fit
log loss. State layer: KB_PA 250 (batter class-profile shrinkage,
pseudo-PAs), KP_PA 200 (pitcher prevention shrinkage, pseudo-PAs),
KU_GAMES 40 (umpire shrinkage, pseudo-games), UMP_CAP 0.03,
POOL_WINDOW_DAYS 14, availability tiers (40 pitches/2 apps full,
65 pitches/3 apps half), TIER_DELTA +0.010 runs/PA, tier weight 0.5,
WX_CLAMP 0.25, PA_RATE_FLOOR 0.02. Bootstrap: 2,000 paired game-level
replicates, seed 20261028. Folds: fit ≤2022→2023, ≤2023→2024, ≤2024→2025
(2026 excluded — Retrosheet 2026 not pinned).

## Named readings (design ambiguities resolved at build)

1. **Market-proxy source.** The design (§5.1) names
   `minmaxxxer/mlb-closing-odds-2025` (Hugging Face, CC BY 4.0) for the
   2025 consensus closes; that source governs. (PR #2888's SmartStake
   admission covers 2026 player props and supplies no 2025 MLB game
   closes.) The leg is labeled DESIGN-GRADE everywhere; it does not
   close gap G4 and no CLV claim is drawn from it.
2. **Score-disagreement games.** Retrosheet and StatsAPI run totals
   disagree on 0.45–0.95% of matched games per season (residuals
   predominantly ±1 run after the parser rules of PR #2900 plus two
   run-counting fixes: HR events carry fielder digits so the batter's
   run is not in the advance string, and an advance marked X whose
   parenthetical carries an error is not an out). Treatment: those games'
   PAs still update histories; the games are excluded from scored rows
   via the per-game `score_agree` flag in the PA dataset.
3. **Starter identity.** Retrosheet↔StatsAPI starter identity is a
   majority-vote map over date+order-matched games (≥2 votes; 605
   pitchers mapped). Unmapped or <3-start starters price at league
   prevention with the machinery's expected innings.
4. **Appearance alignment.** Bullpen workload aligns Retrosheet
   appearance order to StatsAPI boxscore lines when the counts match
   (pitches/outs from StatsAPI); on mismatch it falls back to Retrosheet
   pitch-sequence counts.
5. **Weather NO_DATA.** Roof parks (per the pull table) are
   weather-neutral by rule; unmapped venues (Gocheok Sky Dome, 2 games;
   Tokyo Dome, 2 games — both domed) and missing hours are NO_DATA →
   neutral term. Previous Runs serves wind/precipitation `previous_day1`
   only from 2024 onward (temperature is served for 2022–2023); the
   weather term is therefore inactive in the 2023/2024 folds and fitted
   on 1,763 fit-window rows for the 2025 fold. Observed actuals were
   never pulled or used.
6. **2025 relocations.** Athletics (Sacramento) and Tampa Bay
   (Steinbrenner Field) rows are flagged (`relocated`) and priced on
   their pinned component-table entries, the only declared table
   available; no relocation-specific factor was invented.
7. **Joint treatment.** Win probability flows through the single
   calibration layer over the two run means with shared context
   multipliers (weather × umpire); totals are scored on the posterior
   run means with the fold's NB dispersion reported alongside.

## Build-time correctness fixes (all before the single official run)

Three bugs were found by component diagnostics during the build and
fixed before the screen was run once, in its declared configuration:
(i) the DH pitcher's slot-0 start record was excluded from lineups,
dropping starting pitchers from the identity table — slot 0 is now
included (batting slots still filter 1–9); (ii) the V1-shaped control's
pitching ratio was inverted (L/pit for pit/L), which inverted the
control's λ differentials — verified fixed by the control's in-fit
correlation (+0.19) and the machinery OFF ratings' 1.0 correlation with
actual team runs; (iii) the pitcher-prevention sign: prev_value is a
mean delta ALLOWED on the batter-perspective scale and combines
additively — verified by component extremes (top batter deltas: Judge
+0.110, Alvarez +0.092, Freeman/Ohtani +0.079; class linear weights
OUT −0.26 / BB +0.31 / 1B +0.459 / 2B +0.782 / HR +1.413).
