# Scope-Extension Record — Retrosheet PA / Lineup / Umpire for MLB_GAME_STATE_V1

Date of pass: **2026-10-28** · Subject design: `research/mlb_game_lines_successor_20261028/DESIGN.md`
(PR #2887), §3 input 1 and input 3, §6 **step A** · Prior pin: PR #2856
(`research/retrosheet_park_factor_pin_20261027/PIN_RECORD.md`)

## Verdict: SCOPE_EXTENSION_ADMITTED

The PR #2856-pinned Retrosheet bytes **do** support plate-appearance-level
lineup reconstruction for the screen's fit windows, and the 2025 event zip
is now pinned by the same pattern. The design's pre-declared collapse
condition (§7: *"if step A finds the pinned Retrosheet bytes cannot
support lineup reconstruction at PA level … NO_VIABLE_SUCCESSOR until a
PA-level source is admitted"*) is **not** triggered. This packet is the
step-A record. It admits the Retrosheet event files at design/screen scope
for PA, lineup, and umpire features — nothing more: no validation credit,
no forward-clock credit, no play eligibility, and no change to the
park-factor pin's own scope or values.

**Umpire input (recorded separately, as the design requires): PRESENT_IN_PINNED_BYTES.**
`info,umphome` carries a Retrosheet person ID in **9,719 of 9,719 games**
(0 missing, 0 `(none)`), with 96 / 94 / 90 / 92 distinct home-plate umpires
in 2022 / 2023 / 2024 / 2025 — enough identity history for the design's
strictly-prior tendency computation from the same bytes. The design's
pre-declared umpire descope is therefore not triggered at the data step;
the class still has to earn its place through the §5.3 ablation at screen
time, unchanged.

## What was tested, and how

### 1. The pinned bytes, re-verified before any use

The three #2856 zips were re-pulled from retrosheet.org and matched
byte-for-byte (size + sha256) before a single record was read. The 2025
zip was pulled and pinned the same way. All four pins were then
re-verified a second time through this packet's own
`pull_retrosheet_events.py` on a fresh directory.

| File | URL | Bytes | sha256 | Pin origin |
|---|---|---|---|---|
| 2022eve.zip | https://www.retrosheet.org/events/2022eve.zip | 2,497,692 | `cce73b21bed02283eb70f95e18575f4c8b60b968c75f926530b43f35c85f4c61` | PR #2856 — re-verified MATCH |
| 2023eve.zip | https://www.retrosheet.org/events/2023eve.zip | 2,532,820 | `301e6d36afd58f3c2f9b3dfa546cb7953b24c90a4de57a69565ccc2f2a5eb8d1` | PR #2856 — re-verified MATCH |
| 2024eve.zip | https://www.retrosheet.org/events/2024eve.zip | 2,674,738 | `5dfd9ed678c9c619f6a216322922c99234c067d0ec15b12790546f620ced2fa4` | PR #2856 — re-verified MATCH |
| 2025eve.zip | https://www.retrosheet.org/events/2025eve.zip | 2,527,926 | `5ece2be6c8ec5b47b9d8d90f2ca533ceca7eee915c7e0997f9bd6d64b879303c` | **this packet (new pin)** |

Cross-check on game counts: this packet's census counts 2,430 + 2,430 +
2,429 = **7,289 games for 2022–2024 — exactly the count the #2856
derivation parsed from the same zips.** (2024 has 2,429 games: one
regular-season game was not played.)

### 2. Schema findings — the exact fields the reconstruction uses

Each annual zip holds 61 files: 30 event files (`{season}{TEAM}.EVA/.EVN`),
30 roster files (`{TEAM}{season}.ROS`), and `TEAM{season}` — identical
inventory in all four seasons, and the record-type set
(`id, version, info, start, play, sub, com, data, badj, radj`) is present
in every season (2025 adds four `padj` records; nothing is lost or
changed). Every game in every season has exactly 20 `start` records.

- **Lineup** — `start` / `sub` records: `player_id, "name", team
  (0 = visitor, 1 = home), batting slot (1–9; 0 = the pitcher under the
  DH), fielding position`. The as-played nine per team, in order, with
  every substitution carrying the slot it inherits.
- **Plate appearances** — `play` records: `inning, batting team, batter
  player_id, count, pitch sequence, event string`. The pitcher is *not*
  a play-record field; the pitcher of record is the fielding team's
  current position-1 player under `start`/`sub` defensive state — the
  standard Chadwick derivation.
- **Handedness** — roster `.ROS` records: `player_id, last, first, bats
  (L/R/B), throws (L/R), team, position`. Switch hitters carry
  `bats = B` (95 / 89 / 87 / 88 rostered per season) and are resolved per
  PA to the side opposite the pitcher of record's throwing hand — a
  declared convention of this record, applied uniformly.
- **Umpires** — `info,umphome,<person_id>` in every game's info block
  (`ump1b/ump2b/ump3b` likewise).

### 3. The worked proof

`reconstruct_proof.py` (this packet) reconstructs every game from the
pinned bytes. Three results, all reproduced from a fresh verified pull:

**(a) Full-coverage audit — all 9,719 games, 2022–2025.** 733,260 plate
appearances reconstructed. Every PA's batter **and** pitcher of record
resolves in the roster files with handedness: **0 unresolved batters, 0
unresolved pitchers.** Batting-order continuity — each team's successive
PAs must come from successive lineup slots (cyclically), with the single
legal exception of a batter whose PA was interrupted by a half-inning-
ending baserunning out leading off the next half-inning — holds across
**713,822 checked slot transitions with 0 violations.**

**(b) Independent cross-check — MLB StatsAPI (free, no key).** Three
sample games, one per season 2023/2024/2025 (HOU202303300,
LAN202403280, ANA202504040): the reconstruction's final score and
per-team PA totals match the StatsAPI linescore and play-by-play feed
**exactly, 3 of 3 games, both teams, both measures**
(`proof_results.json` carries the numbers).

**(c) Worked example.** ANA202504040 (CLE @ ANA, 2025-04-04): full
starting lineups reconstructed (slots, positions, handedness), the
game's 87 PAs enumerated with batter / pitcher-of-record / both
hands — switch hitters José Ramírez, Carlos Santana and Brayan Rocchio
resolved to bat left against RHP José Soriano — and home-plate umpire
`vondc901` read from `info,umphome`.

### 4. Parsing rules the proof forced (recorded so the build inherits them)

The first cross-check run overcounted PAs by 1–3 per game; the
discrepancies were traced play-by-play against the StatsAPI feed and
reduced to rules about the bytes, not about the model:

1. **`play` records with event exactly `NP` are substitution markers,
   not plays.** They name the outgoing batter when an announced pinch
   hitter is replaced before a pitch; no PA occurs. Skipping them is
   required for exact totals.
2. **A play record completes the PA unless every segment of its primary
   event is baserunning-only** (steals, caught stealings, pickoffs,
   wild pitches, passed balls, balks, defensive indifference). Base
   designators after the prefix may be digits *or* `H` — `SBH`,
   `CSH(2452)`, `POCSH(25)` are baserunning plays, and an error
   parenthetical may be truncated by the `/` modifier split
   (`PO1(E1/TH…`). An earlier classifier that required a digit after
   the prefix misread these; the audit's slot-continuity check is what
   exposed it (121 raw violations, all in this class, 0 after the rule
   was stated correctly).

### 5. Known anomalies, stated

- One 2025 roster record (`cortc001`, Carlos Cortes, ATH, OF) carries
  `throws = B`. He never appears at fielding position 1 in the 2025
  files, so the anomaly touches no plate appearance; a build consuming
  pitcher handedness should still refuse or declare a treatment for a
  non-L/R `throws` value rather than silently pass it through.
- 2024 contains 2,429 games, not 2,430 (see §1).
- The 2026 fold stays excluded, per the design, until Retrosheet 2026
  events are pinned as their own step.

## What this record does NOT do

- It does not build the construction, run the §5 screen, or touch step B
  (the Previous Runs weather pin) — step A only, as tasked.
- It does not admit the StatsAPI live feed (lineups + officials); that
  remains forward-clock precondition (iii), not a screen blocker.
- It does not change any park factor, frozen term, or threshold; the
  2025 park-relocation treatment (Athletics–Sacramento, Tampa
  Bay–Steinbrenner) remains a declared build-stage item in the design,
  untouched here.
- Data bytes are not committed (Retrosheet data, ~10 MB of zips);
  hashes + URLs + `pull_retrosheet_events.py` are the reproducible
  pointer, per the #2856 pattern.

## Freeze-coverage check

All paths in this packet were checked against
`config/freeze_reconciliation_registry_v1.json` with the repo's own
matcher (`scripts/reconcile_freeze_deltas.py::_covered_change`, all
bundles): **NOT GOVERNED** — no frozen terms, thresholds, or factor
values are touched.

*Research only. PAPER / 0u. Retrosheet data used free of charge from
retrosheet.org; attribution per Retrosheet's notice.*
