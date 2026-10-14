# Pre-pricing factor-ingestion stage

Runs **before any market is priced** for a game in the phone `RUN IT` runner
(`artifacts/run_it_full.py`). Isaac's directive: "run it need to pull all that
info and take those into account — injuries, weather, everything."

## What it does

Per game (sport/away/home/kickoff), the stage pulls from free public endpoints
only, applies **only verified** adjustments to the score means, and emits a
per-game factor-coverage audit on every research card:

| # | Factor | Source (free, no keys) | Adjustment |
|---|--------|------------------------|------------|
| 1 | Injuries/inactives + QB/participation | ESPN injuries, via the **canonical** `free_models.injury_rows` / `injury_points` path (no second fetch) | `home_injury_pts` / `away_injury_pts` (existing contract: NFL QB out/doubtful −1.5, NBA −0.3, else −0.15, cap 2.5) |
| 2 | Weather (outdoor venues) | **Archived evidence first** (`SPORTSEDGE_WEATHER_EVIDENCE_V1`); else free live Open-Meteo (no key) | `weather_total_adj` via the shared declared table (`declared_weather_total_adj`: 18+ mph → −0.8, 13+ → −0.4, 70%+ precip → −0.4, MLB ×0.3), split half per team |
| 3 | MLB probable pitchers | MLB StatsAPI `schedule?hydrate=team,probablePitcher` + season pitching line | `home_pitcher_adj` / `away_pitcher_adj`: declared bounded starter suppression, `−(4.30−ERA)×(IP/GS÷9)`, capped ±1.25 runs. Semantics: each key shifts that team's **own offense** for the **opposing** starter (good opposing starter → negative). |
| 4 | Rest/travel | ESPN team schedules (verified rest days) | `rest_diff_adj` (new context key, NFL/CFB/MLB): declared `0.12×rest-diff` pts (±0.6), MLB `0.05×` (±0.25); applied `home += adj/2`, `away −= adj/2`. Travel distance: NOT_WIRED (venue-history pipeline not built). |

## Sourcing rule (Isaac, Oct 11)

**Keyed APIs (odds, weather) are NEVER called directly by this stage.** Keys
(`SPORTSEDGE_ODDS_API_KEY[_2/_3/_4]`, weather) live ONLY as GitHub Actions
secrets, run Actions-side via `${{ secrets.* }}`, and arrive as **archived
evidence** on the data branch. The stage reads archived evidence plus free
public endpoints live (ESPN, MLB StatsAPI, Open-Meteo — zero keys, zero paid
services, zero infra for Isaac; his flow stays "send lines, get cards").

Weather resolution order:
1. Row carries `weather_evidence` → strict admission (`admit_weather_evidence`):
   exact contract, kickoff binding ±6h, retrieved ≤ now, retrieved ≤ kickoff,
   age ≤ 36h, numeric in-range forecast. **A stale/defective archive fails
   exactly like missing data — MISSING, never silently used, never silently
   replaced by the live path.**
2. No archive → free live Open-Meteo via existing `provider.weather` (no key).

Market-odds-as-features is a **rejected method**, never a MISSING audit item
(it is noted here once, not per-card).

## Fail-closed: critical factors

| Critical factor | Sports | Missing/unverifiable → |
|---|---|---|
| QB identity (verified ESPN injury payload + out/doubtful QB extraction; positive starter confirmation unavailable from free ESPN — stated in audit) | NFL, CFB | `BLOCKED_PREPRICING_QB_IDENTITY_UNVERIFIED` |
| Probable pitcher (both teams, usable season line ≥5 GS or ≥25 IP) | MLB | `BLOCKED_PREPRICING_PITCHER_UNCONFIRMED` |
| Unique future ESPN fixture | all | `BLOCKED_PREPRICING_FIXTURE_UNVERIFIED` |

**QB identity, Form 2 (CFB only; owner ruling Oct 13, 2026, issue #2154).**
QB_IDENTITY_EVIDENCE has two forms. Form 1 is the injury payload above —
the only form that speaks to availability. For a CFB team whose feed
status is `TEAM_NOT_IN_INJURY_FEED`, Form 2 (`DEPTH_ROSTER_COMPOSITE`)
may satisfy the **identity limb only**: an ESPN roster snapshot
(asserted-complete `?limit=1000` pull) binds membership by athlete ID,
a receipted pre-kickoff OurLads depth-chart snapshot supplies the QB
ordering, and the named QB1 (name + jersey) must resolve to exactly
one athlete ID on that team's roster. Form 2 is a research-stage
evidence path, **not** proof of availability or a clean injury report:
availability stays explicitly `AVAILABILITY_UNVERIFIED_NO_TEAM_INJURY_REPORT`,
injury points are exactly 0.0, and every Form 2 failure (missing,
stale, ambiguous, absent, incomplete roster, hash mismatch) fails
closed to the block above with its own status recorded
(`QB_IDENTITY_SATISFIED_FORM2_DEPTH_ROSTER_COMPOSITE` on a pass).
Implementation + disposition switch (`FORM2_PROCEEDS_WITH_AVAILABILITY_LABEL`):
`sportsedge/prepricing/qb_identity_evidence.py`. Bundles reach the stage
only through the runtime adapter (`sportsedge/prepricing/qb_form2_bundle_loader.py`,
runner flags `--form2-bundles-dir` + `--form2-manifest-sha256`): the
adapter reads the local archive root exclusively through
`qb_evidence_archive`'s IO and admits nothing without the caller's
external manifest pin (the receipt-v2 chain alone proves only
self-consistency); admitted bundles are pinned-manifest-anchored,
chain-verified (sealed assertions included), intake-matched, and
exclusions are audited on the card as `qb_form2_bundle_loader_audit`;
the adapter never fetches.

A blocked game carries **zero** partial adjustments. This closes the exact
Oct-11 failure: Lamar-out (QB-blind) and Skubal/Misiorowski (pitcher-blind)
can no longer be silently priced.

Manual `--no-fetch` mode: the stage audits without blocking
(`enforce_blocks=False`; factors report MISSING with `MANUAL_MODE_...`
reasons), preserving the explicit manual-only research path. Explicit
row-level `context` overrides win over stage values; collisions are noted in
`manual_context_overrides` in the audit.

## Audit taxonomy

Per-game `FactorRecord`s enumerate the factor library
(`model_factors_reference.md`): universal factors
(team_strength_ratings, recent_form, home_advantage, rest_schedule, travel,
pace_tempo, lineups_usage, advanced_metrics, situational, weather_venue) plus
sport-specific (NFL: qb_specific, efficiency_epa, key_numbers,
turnover_special_teams; CFB: qb_specific, talent_portal, key_numbers; NBA:
four_factors, rest_back_to_back, rotations_matchups; MLB: starting_pitcher,
bullpen, park_factors, umpire, opponent_adjusted_offense). NHL/Soccer omitted
(out of scope). Motivation spots / news speed / officiating tendencies stay
NOT_WIRED per standing rule. Statuses: USED (with source) / MISSING (explicit
reason) / NOT_WIRED / NOT_APPLICABLE. **Coverage is not validation.**

Card output: `card["prepricing_factor_audit"]`
(`SPORTSEDGE_PREPRICING_FACTOR_AUDIT_V1`) with per-`input_index` entries;
blocked rows carry their own `prepricing_audit`; priced game rows carry a
`prepricing_stage` summary. Stage fetch receipts join `source_receipts`.

## Merge-dedup notes (read at merge time)

- **Parallel branch `feat/team-half-participation-20261011`** (worktree
  `~/workspace/sportsedge-participation`): as of this build it contains the
  team-half wire-in only — its `team_half_pricing.py` has **no**
  pitcher/QB/participation logic yet (verified by grep). **This stage is the
  single orchestration point.** When participation adjustments land in
  `team_half_pricing`, they MUST consume this stage's verified adjustments
  (call `stage_games` / `mlb_pitcher_adjustments` / `injury_rows`) rather than
  inventing a second fetch + adjustment path. `price_team_or_half` should
  accept the stage's `FactorReport` adjustments as input.
- `free_models.py` changes in this branch (keep all three):
  1. `injury_rows()` extracted from `injury_points()` — same fetch path,
     receipts, and team-group binding; `injury_points` return contract
     unchanged.
  2. `declared_weather_total_adj()` — single declared table shared by
     `provider.weather` and archived evidence.
  3. `rest_diff_adj` added to `CONTEXT_KEYS` (NFL/CFB/MLB) and applied in
     `calculate()`; `schedule()` hardened to fail closed on malformed payloads.
- Known double-fetch: the stage and the engine each build a `PublicContext`
  (same getter, separate caches). Merge-time optimization: share one provider
  instance between `stage_games` and `engine.run`.

## Validation

- `tests/test_prepricing_ingestion.py`: 17 tests, recorded fixtures only —
  verified pulls, audit emission, all three downgrade paths, stale-archive
  rejection, verified-only application, manual-mode behavior, user-override
  precedence.
- Harness (cwd `~/workspace/sportsedge-backtest`, script
  `/tmp/validate_prepricing_harness.py`): MLB probable-pitcher factor,
  2026-09-01..10, n=474 walk-forward out-of-sample —
  **CONDITIONAL_PASS** (Brier 0.2425 vs 0.2465; log-loss 0.6781 vs 0.6861;
  market-baseline leg MISSING — no Odds API by Isaac's choice, so this is the
  ceiling, not a promotion). Point-in-time clean: probables retained by
  StatsAPI for completed games; ERA-to-date from gameLog strictly before game
  date (no lookahead).
- **Not yet validated:** NFL/CFB QB-participation factor (ESPN injuries feed
  has no point-in-time archive — historical QB-out states unavailable);
  rest/weather adjustments (directional only, pending harness runs with
  archived weather evidence); bullpen, park factors, travel (NOT_WIRED).

## Known limitations

- QB "identity" = verified out/doubtful extraction; free ESPN cannot
  positively confirm the starter — stated in every audit.
- CFB QB-out counts 0.15 under the existing `injury_points` contract (only
  NFL QBs get 1.5) — inherited, flagged for harness review.
- Stage covers game markets (ML/SPREAD/TOTAL) only; player props keep their
  existing pricing/audit.
- All numeric adjustments are declared heuristics, NOT calibrated edges; each
  must earn production status through the backtest harness per Isaac's bar.
