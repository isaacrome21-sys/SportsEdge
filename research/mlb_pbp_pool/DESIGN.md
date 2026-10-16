# MLB Plate-Appearance (PA) Play-by-Play Pool — Stage 1 Design

**Status:** stage 1 (foundation only). This package builds the verified,
PIT-disciplined plate-appearance pool that the Plate Appearance gates
(`sportsedge/mlb_plate_appearance_gates.py`, matrix M49) name as
`PLATE_APPEARANCE_PBP_POOL_UNBUILT`, and that the HR, H+R+RBI,
per-inning-runs and exotics engines are all gated on. **No engine is
built here, nothing prices, and no gate changes state.** The M49 gate
also names a second, independent blocker —
`PLATE_APPEARANCE_SELECTION_SET_UNVERIFIED` (DraftKings' exact
selection lists) — which is catalog work, not pool work, and remains
open after this stage.

## Source decision

**Chosen: MLB StatsAPI play-by-play** —
`GET https://statsapi.mlb.com/api/v1/game/{gamePk}/playByPlay`
(no key, no cost), with the StatsAPI schedule endpoint for game
enumeration and the StatsAPI box-score endpoint for reconciliation.

Why this source:

- It is the repo's established MLB source (schedules, box scores,
  probable pitchers) and carries the system's **canonical player
  IDs** — every other MLB lane keys on StatsAPI person IDs, so pool
  rows join without a crosswalk.
- It is **uniform across 2024, 2025 and 2026**, including the
  in-progress 2026 season; one construction serves all three.
- Each play carries the full PA resolution: batter, pitcher, raw
  event type, RBI, running score, outs, and per-runner movement
  (including which runners scored) — everything the schema below
  needs, with no inference from summaries.

Terms: StatsAPI responses carry an MLB Advanced Media copyright
notice. The pool stores **derived factual event records** (who batted,
against whom, the outcome class, runs and RBI) for internal research;
raw feeds are cached only in build scratch and are not redistributed.
No API key, account, or payment is involved.

Alternatives considered and rejected for stage 1:

- **Retrosheet event files** (via Chadwick tooling): the historical
  gold standard and license-clean (Retrosheet data is provided free
  of charge under its stated terms, with an attribution notice and
  no warranty). Rejected for stage 1 because (a) Retrosheet player
  IDs differ from StatsAPI IDs and would force a Chadwick-register
  crosswalk into the foundation itself, (b) the 2026 file is only
  published after the season, so one construction could not cover
  all three seasons, and (c) parsing/tooling cost buys nothing the
  feed does not already carry. Retrosheet remains the natural
  independent cross-check for a later stage.
- **Baseball Savant / Statcast**: pitch-level tracking, already used
  elsewhere in the repo for a different layer. PA outcomes would
  have to be reconstructed from final-pitch rows and it carries no
  cleaner RBI / scoring-runner attribution than the feed. Not a PA
  pool source.

## What counts as a plate appearance (the load-bearing rule)

`allPlays` is **not** a PA list. Baserunning plays that occur during
someone else's plate appearance — a caught stealing or pickoff that
ends a half-inning, for example — appear as their own `allPlays`
entries, carry `result.type == "atBat"` and even
`about.isComplete == True`, with the *current batter* named in the
matchup. Counting them inflates PA totals (verified on game 776372:
feed-complete plays 37 vs box-score PA 36 for the away team).

A play is a pool PA iff **all** of the following hold:

1. `result.type == "atBat"`,
2. `about.isComplete` is true,
3. the matchup batter appears in the play's `runners` list (a real
   PA resolution always resolves the batter's own runner record —
   hit, walk, HBP, out, error, fielder's choice, interference).

Rule (3) is the semantic test; rule (1)+(2) alone are provably
wrong. Incomplete plays (a PA interrupted by a third out on the
bases, a rain ending) are **not** PAs — the box score does not count
them — and are excluded, counted, and reported. The builder then
reconciles pool PA against the official box score for **every**
game (next section); the rule is not trusted until it survives all
7,290 games.

Two feed facts verified over the full corpus (7,288 games with
plays, 550,618 entries), which the construction relies on:

- `about.atBatIndex` is **exactly the play's position** in
  `allPlays` — `0..n-1`, no gaps, no duplicates, in every game. It
  is retained on pool rows as traceability only; it carries no
  information beyond feed order, and pool rows are keyed by
  `pa_index`, not by it.
- Every `allPlays` entry's score delta equals the number of its
  own runners whose movement ends at `"score"` — PA entries and
  non-PA entries alike, with zero violations. Scoring attribution
  at the entry level is therefore exact; the only question is
  which entries are PAs.

## Runs that score on non-PA plays (orphan runs)

A run can score on a play that is not a plate appearance: a wild
pitch with a runner on third, a balk, a throw on a caught-stealing
attempt. The feed records these as their own entries (23 across
the three seasons), the run belongs to **no** plate appearance,
and it is never an RBI. Empirically these entries never fall
inside the *following* PA's window — in the majority pattern the
play closes the half-inning during an interrupted PA whose
resolution is not the adjacent entry — so attaching the run to a
neighbouring PA row would mis-attribute it, and team-total
reconciliation could not detect the error (totals are invariant
under which row carries the run).

The pool therefore keeps PA rows pure — `runs_scored_on_play`
counts only runs scored on that PA's own resolution — and carries
orphan runs in a per-season side table
(`pool_orphans_<season>.jsonl.gz`): one row per non-PA scoring
play with `game_id`, dates, feed `play_index`, `inning`, `half`,
`batting_team_id`, `event_type`, `runs`, and
`scoring_runner_ids`. Nothing is lost: per-inning runs add the
side table by (`game_id`, `inning`, `half`), and a player's runs
scored are his appearances in either file's
`scoring_runner_ids`. Reconciliation checks team runs as
PA-resolution runs + orphan runs == box-score runs, for every
game.

## Schema — one row per plate appearance

Emitted as JSON Lines, one file per season, rows sorted by
(`game_date`, `game_id`, `pa_index`). Field names are stable; stage 2
engines code against this table.

| field | meaning |
|---|---|
| `game_id` | StatsAPI gamePk |
| `season` | MLB season year |
| `game_date` | game date (America/New_York) of the first PA's start — the PIT target key |
| `game_completed_date` | date (America/New_York) of the final play's end — the PIT availability key |
| `game_type` | `"R"` (regular season; stage 1 scope) |
| `away_team_id`, `home_team_id` | StatsAPI team IDs |
| `pa_index` | 0-based ordinal of the PA among the game's pool PAs, feed order |
| `at_bat_index` | the feed's own `about.atBatIndex` (traceability; exceeds `pa_index` when non-PA plays intervene) |
| `inning`, `half` | inning number (≥1, extras included), `"top"` / `"bottom"` |
| `batting_team_id`, `fielding_team_id` | per half |
| `batter_id`, `pitcher_id` | StatsAPI person IDs (canonical) |
| `bat_side`, `pitch_hand` | `"L"`/`"R"`/`"S"` and `"L"`/`"R"` as recorded on the play |
| `batting_order_slot` | 1–9, derived (below) |
| `batter_pa_number` | 1-based ordinal of this PA among the batter's PAs in the game (1 = his first PA — the M49 population) |
| `pitcher_bf_number` | 1-based ordinal of this PA among batters faced by the pitcher in the game |
| `event_type` | StatsAPI raw `result.eventType`, unmodified |
| `outcome_class` | normalized class (mapping below) |
| `is_hit`, `is_home_run`, `is_walk`, `is_intent_walk`, `is_hit_by_pitch`, `is_strikeout`, `is_sac_fly`, `is_sac_bunt` | strict factual booleans from `event_type` (see below on what is *not* here) |
| `result_is_out` | the feed's `result.isOut` for the PA resolution |
| `rbi` | `result.rbi` (0–4) |
| `runs_scored_on_play` | number of runners (incl. the batter on a HR) whose movement ends at `"score"` on this PA |
| `scoring_runner_ids` | those runners' person IDs — credits each scorer with a run, which is what makes batter game-line *runs* derivable from the pool alone |
| `outs_after` | outs in the half-inning after this PA (`count.outs`) |
| `away_score_after`, `home_score_after` | running score after this PA |

**Batting-order slot derivation.** A team's completed PAs cycle
through the lineup in order, so the slot of its k-th PA (0-based) is
`(k mod 9) + 1`. This is a structural identity, not an estimate, and
the builder validates it against the box score for **every** PA: the
box score's per-player `battingOrder` code (`"100"`…`"900"` for the
nine starters, first digit = slot for every subsequent occupant)
must agree with the derived slot on 100% of rows. (The box score's
*team-level* `battingOrder` list is **not** slot-ordered and is never
used.)

**Deliberately absent:** no `is_on_base` boolean. Whether an error or
a fielder's choice settles as "on base" is a *market settlement*
question (part of the still-open selection-set verification), and the
pool stores facts, not settlement guesses. Downstream engines read
`outcome_class` + `event_type` and apply their own verified
settlement basis.

### Outcome-class mapping

`event_type` → `outcome_class` (exhaustive over the observed census;
the builder fails closed on any unmapped type):

| outcome_class | event types |
|---|---|
| `HIT_SINGLE` | single |
| `HIT_DOUBLE` | double |
| `HIT_TRIPLE` | triple |
| `HOME_RUN` | home_run |
| `WALK` | walk |
| `INTENT_WALK` | intent_walk |
| `HIT_BY_PITCH` | hit_by_pitch |
| `STRIKEOUT` | strikeout, strikeout_double_play, strikeout_triple_play |
| `SAC_FLY` | sac_fly, sac_fly_double_play |
| `SAC_BUNT` | sac_bunt, sac_bunt_double_play |
| `INTERFERENCE` | catcher_interf, batter_interf, fan_interf (StatsAPI truncates these codes) |
| `REACH_ON_ERROR` | field_error |
| `FIELDERS_CHOICE` | fielders_choice, fielders_choice_out |
| `OUT_IN_PLAY` | field_out, force_out, grounded_into_double_play, double_play, triple_play, other_out |

Boolean facts: `is_hit` = the four hit classes; `is_walk` includes
intentional walks (`is_intent_walk` separates them); the rest map
one-to-one from the table.

## PIT discipline

Every row is keyed by its game's dates. The availability rule for
any future feature construction is stated in terms of the pool's own
keys and is **fail-closed**:

> Pool game G may feed a feature for target game T only if
> `G.game_completed_date < T.game_date` (both America/New_York
> calendar dates, strict inequality).

Keying availability on *completion* date — not the game's start
date — is what makes suspended/resumed games safe: a game suspended
on Monday and completed on Wednesday contributes nothing to a
Tuesday target even though its first PA predates it. Same-date
games (doubleheaders) can never feed each other. There is no
timestamp rewriting and no partial-game state: a game enters the
pool whole, when final, or not at all.

## Integrity contract (enforced by the builder, every game)

A game enters the pool only if **all** checks pass; failures are
excluded and listed in `BUILD_REPORT.md` with the failed check:

1. **PA count** per team == box-score `plateAppearances`, and the
   component identity `PA == AB + BB + HBP + SF + SH + CI` holds
   against box-score components.
2. **Component totals** per team: pool Σ hits, Σ HR, Σ BB (incl.
   IBB), Σ K, Σ RBI each == the box-score team totals; Σ runs ==
   box-score runs with runs counted as PA-resolution runs plus
   orphan (non-PA) runs from the side table.
3. **Final score**: last pool row's running score == box-score
   runs for both teams.
4. **Slot agreement**: derived slot == box-score `battingOrder`
   code's slot digit for every PA.
5. **Outs progression**: within each half-inning, `outs_after` is
   non-decreasing, increments by 0–3 per PA, and never exceeds 3;
   every half-inning except a game-ending one (walk-off, shortened
   official game) ends at exactly 3.
6. **Score/RBI sanity**: `runs_scored_on_play == len(scoring_runner_ids)`,
   `rbi <= runs_scored_on_play`, scores monotone non-decreasing.
7. **Schema**: every row carries every field with the declared type
   and range (validated again by the test suite over the shipped
   sample and, via `--verify`, over the full artifact).

## Artifact placement

The full pool (548,938 PA rows + 23 orphan rows) is too large for this branch and for the
sandbox's text-only push path, so — per the repo's data-archive
pattern (Statcast snapshots and forward-capture archives live on
the **`data` branch**, written there by automation) — the artifacts
of record for stage 1 live in durable workspace storage at

```
~/workspace/sportsedge/mlb_pbp_pool_20261016/
    pool_2024.jsonl.gz   pool_2025.jsonl.gz   pool_2026.jsonl.gz
    pool_orphans_2024.jsonl.gz   pool_orphans_2025.jsonl.gz
    pool_orphans_2026.jsonl.gz
```

with SHA-256 (of the gzip bytes **and** of the uncompressed JSONL)
recorded in `MANIFEST.json` in this package. The builder is
deterministic (sorted rows, fixed JSON separators, gzip with
`mtime=0`), so anyone can rebuild from the StatsAPI source and
compare hashes byte-for-byte; `build_pbp_pool.py --verify` does
exactly that plus the full integrity contract against cached box
scores. No data-branch push is made from the sandbox in stage 1
(that branch's write path is Actions automation, as with Statcast);
the data-branch home when automation picks this up is
`data/mlb_pbp_pool/` on `data`, mirroring `data/mlb_forward_*`.

Build scratch (raw play-by-play responses, one file per game, plus
schedule snapshots) is cached under
`~/workspace/tmp/bt_data/pbp_cache/` following the existing
`boxscore_cache` precedent, which makes builds resumable: a re-run
fetches only what is missing. Box scores are read from the existing
shared `~/workspace/tmp/bt_data/boxscore_cache/` (read-only).

This branch ships: this design, the builder, a 30-game sample
excerpt of the pool with its box-score reconciliation fixture
(`sample/`), the manifest, and the build report.

## Readiness — what stage 2 gets from this pool

| downstream engine | pool now provides | still missing (not pool work) |
|---|---|---|
| Home-run props | per-PA HR outcomes by batter × pitcher, slot, PIT availability keys | the engine + its harness validation; park/context layers exist elsewhere |
| H + R + RBI props | hits and RBI on the batter's own PAs; **runs scored by the batter** via `scoring_runner_ids` on any PA — full batter game lines derivable from the pool alone | the engine + validation |
| Per-inning runs (incl. 1st inning, 2nd–9th) | runs per half-inning = Σ `runs_scored_on_play` grouped by (`inning`, `half`, batting team); PAs per half-inning (batters-to-plate) equally direct | the engines + validation |
| Plate-appearance markets (M49) | first-PA population = `batter_pa_number == 1`; opposing starter's first-PA-faced = those rows against the fielding team's first pitcher (`pitcher_bf_number` sequence) | `PLATE_APPEARANCE_SELECTION_SET_UNVERIFIED` — DK's exact selection lists / Grouped partition (catalog work); then the engine |
| Exotics (M50 forms) | PA-level outcomes with full game sequencing: first scoring PA (first team to score), per-inning scoring order, race-style derivations from running scores | form-specific selection sets (catalog work); then the engines |

Nothing in this stage touches a gate, a registry, or a pricing
path: the pool existing is the *prerequisite* the gates name, and
each engine still needs its own spec-first build and chronological
validation before any row can price.
