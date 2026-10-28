# Admission record — MoneyPuck (NHL expected goals) for NHL attempt 2

**Status: SAMPLE-VERIFIED / ADMISSION PROPOSED — DESIGN + FORWARD-PRICING
INPUT FOR NHL ATTEMPT 2 — NO MODEL PROMOTED BY THIS RECORD — NO PLAY
ELIGIBILITY BY THIS RECORD ALONE.**
Prepared 2026-10-28 (retrieval 2026-10-28) for independent review.
This record admits nothing by itself: admission takes effect only if this
PR is merged after independent (Rocky) review. Even then, the data prices
nothing by itself — pricing use flows only through the NHL attempt-2
preregistration (draft PR #2839, `NHL_SIDES_TOTALS_DESIGN.md`) when that
preregistration is written and frozen under its own act. The Stage A
home-ice v2 accuracy verdict (locked Sep 29, 2026; verdict Nov 30, 2026)
does not consume this source and is not altered by this record.

This record closes the named blocker in the NHL restart pack (draft PR
#2847, `research/nhl_restart_20261027/NHL_RESTART_READINESS.md` §3.2/§3.3):
MoneyPuck was verified live with hash-pinned sample pulls but had **no
admission record and no collector anywhere in the tree**, while the
attempt-2 design names MoneyPuck shot-level xG as its foundation and
requires "an admission record (or a derived-xG route from official
play-by-play) owed before any fit under Stage B."

Every factual claim below carries an evidence state: **verified-by-pull**
(bytes were downloaded from the SportsEdge runtime and hash-checked) or
**documented-only** (stated by the provider's pages or another admitted
record; not reproduced here).

## 1. Source, provenance, and the verified surface

- **Source:** MoneyPuck — NHL analytics published by Peter Tanner at
  moneypuck.com, with data files served from peter-tanner.com. The data
  derives from the NHL's official play-by-play, scored by MoneyPuck's own
  expected-goals model (documented-only as to authorship/method beyond
  the about-page disclosure quoted in §4.1).
- **Access:** plain CSV / zip-of-CSV over static HTTPS. No API key, no
  account, no JavaScript. Free (owner's free-only law, Oct 27, 2026:
  satisfied — no purchase, no sign-up).

Verified endpoints (all verified-by-pull 2026-10-27 by the restart pack
and re-verified 2026-10-28 in preparing this record):

| Surface | URL pattern | Content |
|---|---|---|
| Season skaters | `peter-tanner.com/moneypuck/downloads/seasonPlayersSummary/skaters/{season}.zip` | zip of `{season}.csv`; one row per player-game-situation (157 cols) |
| Season goalies | `…/seasonPlayersSummary/goalies/{season}.zip` | zip of `{season}.csv`; one row per goalie-game-situation (39 cols), incl. `xGoals` faced |
| Season lines | `…/seasonPlayersSummary/lines/{season}.zip` | zip of `{season}.csv`; one row per line-game-situation (111 cols) |
| Game-by-game teams | `moneypuck.com/moneypuck/playerData/careers/gameByGame/all_teams.csv` | one row per team-game-situation (111 cols), seasons 2008 → current |
| Data dictionary | `peter-tanner.com/moneypuck/downloads/MoneyPuckDataDictionaryForPlayers.csv` | prose-headed column reference (15,040 B) |

Also on the downloads page (documented in the restart pack, not collected
by this admission): per-season shot-database zips (`shots_{season}.zip`),
one-row-per-season archives, and per-player career CSVs. Seasons for the
summary zips run 2008–2026, where the season label is the year the season
starts (2026 = the in-progress 2026-27 season).

Earlier in-repo guesses at a `seasonSummary/` URL pattern 404; the
`peter-tanner.com` paths above are the live ones (restart pack §3.2).

## 2. The snapshot discipline (binding on any use)

MoneyPuck's season-summary and game-by-game files are **cumulative
snapshots, rewritten in place**. A file pulled today states
season-to-date numbers as of today; there is no provider as-of archive.
The point-in-time property is therefore created by SportsEdge's own pull
discipline, fixed here before any use:

1. **The pin is the pull.** Every pull used for design or pricing is
   hash-pinned at pull time by the collector shipped with this record
   (`collect_moneypuck.py`); the manifest entry — pull timestamp (UTC),
   the site's `Last-Modified`/`ETag`, byte count, SHA-256, per-file row
   counts and gameDate range — is the vintage of record. Raw bytes are
   stored outside the repository; the repo stores hashes, manifests and
   code only (§5).
2. **Strictly-prior rows only.** Every game-by-game row carries
   `gameId`/`gameDate`. A feature for a game on date D may be built only
   from rows with `gameDate` **strictly before** D (same-day rows are
   excluded: a game is never a feature for itself, and same-day ordering
   is not guaranteed). The collector's `demo-prior` subcommand and its
   `strictly_prior_team_aggregate` implement and demonstrate the filter;
   §3 records a live demonstration.
3. **Snapshot aggregates are never backdated.** Season-to-date aggregate
   readings taken from a snapshot pulled on date P describe games
   through P. Offering them as features for a game before P is
   lookahead and a refusal (`LOOKAHEAD_RISK`). Retroactive
   point-in-time claims for dates before a snapshot's pull are
   forbidden, per the standing baseline contract.
4. **A changed vintage is refused, never substituted.** Re-pulling with
   `--expect` against a pinned hash refuses a different vintage as
   `SOURCE_CHANGED_AFTER_SNAPSHOT` and leaves the pinned bytes on disk
   untouched. In-season files regenerate roughly daily (observed
   `Last-Modified` on consecutive days, Oct 27–28, 2026); a
   current-season pull whose `Last-Modified` is more than 72 hours old
   is refused as `STALE_SNAPSHOT` rather than silently treated as
   current.
5. **xG vintage is pinned per pull** (§4.1). xG values from different
   model vintages are not one consistent series.

## 3. Reproducibility — pinned retrieval, hash-verified samples

Retrieval is by the committed script `collect_moneypuck.py` (stdlib
only). It streams each surface to a data dir outside the repo, verifies
the schema (required columns present, every `gameDate` a valid YYYYMMDD
date, season-summary files containing exactly the requested season),
refuses per §7, and writes the JSON manifest committed beside this
record as `sample_manifest.json`.

Sample pulls executed 2026-10-28 from the SportsEdge runtime with the
committed collector, stored outside the repo in the workspace data dir
(all row counts are data rows, header excluded):

| Surface | Season | Bytes | Data rows | gameDate range | SHA-256 |
|---|---|---|---|---|---|
| season_skaters | 2026 | 3,447,478 | 33,655 | 20260929 → 20261026 | `bd16f2ddef3dd62f082aef061feb49d891d3303042de959b00f4ad3ffb4a1a79` |
| season_skaters | 2025 | 23,609,057 | 236,060 | 20251007 → 20260416 | `358d4fe42277ddbd7489152cb0f0d1033abf2a9df305b77ac65a9cffeedb62d1` |
| season_goalies | 2026 | 83,943 | 1,965 | 20260929 → 20261026 | `235c25efeaa39467597c10d5fcde776adda9868cbee81d9aa68010b5eed2be2c` |
| season_goalies | 2025 | 573,442 | 13,830 | 20251007 → 20260416 | `ce6730b2d4e51096e90e6dd263e082c2d11567e90f666323c3a073a17361168d` |
| all_teams | all (2008–2026) | 127,505,574 | 234,090 | 20081004 → 20261026 | `3ac5ed95fbf072166ea59d2cf4e44a37e337e8c2122ba5f2fa55e56ec3cef1ab` |
| data_dictionary | — | 15,040 | — | — | `74c5a09f5eb5e12c03838c9efea0a84d9b33024193a1a29b9c67d998f5324a91` |

A `verify` run against the committed manifest recomputed every hash
from the stored bytes: **6/6 PIN_MATCH**. The 127 MB `all_teams.csv`
pull is tractable from this runtime (~85 s).

Three of these files were independently pinned a day earlier by the
restart pack (different agent, different pull): skaters 2026
`bd16f2ddef3dd62f…`, all_teams `3ac5ed95fbf072166ea5…`, dictionary
`74c5a09f5eb5e12c0…`. Agreement across independent pulls is recorded in
the manifest notes where it holds; any file whose bytes moved between
the two days is a different vintage by §2.4, not a discrepancy.

**Strictly-prior demonstration (verified-by-pull, 2026-10-28):**
`collect_moneypuck.py demo-prior --file all_teams.csv --team ANA
--date 20261020 --season 2026` — building Anaheim's features for its
Oct 20, 2026 game from the pinned `all_teams.csv`: **8 games used,
max gameDate used 20261019 (strictly before the target), 3 rows
excluded as same-day-or-later**, sums xGoalsFor 25.708 /
xGoalsAgainst 27.884 (actual goals 24 / 26). The same-day game itself
and the two later October games in the snapshot contribute nothing —
the filter, not the snapshot date, is what makes the feature lawful.
The demonstration is recorded in the manifest
(`strictly_prior_demonstration`).

## 4. Known limitations (read before designing on this)

### 4.1 The xG model was rebuilt for 2026-27 — vintage pinning is an admission condition

MoneyPuck's about page (read directly, 2026-10-28) states: *"This model
predicts the probability of each shot being a goal. The model was rebuilt
for the 2026-2027 NHL season to adapt to how the NHL now tracks shots
and other changes to the game. This model is trained on a random sample
of over 289,000 shots from the 2023-2024 to 2025-2026 seasons. It was
built using gradient boosting."* Its published AUC table: old model
0.784 overall vs new model 0.807 overall on the 2023-24 → 2025-26
evaluation seasons.

What the source does **not** disclose: whether the historical files
(seasons ≤ 2025, and pre-2026 rows of `all_teams.csv`) were re-scored
under the rebuilt model or still carry the prior model's values.
Accordingly:

- Every manifest entry records `xg_model_vintage`: `rebuilt_2026_27`
  for season-2026 files; `undisclosed_legacy` for seasons ≤ 2025;
  `mixed_file_see_record` for `all_teams.csv`, whose rows span both.
- **xG must not be pooled across the 2025/2026 season boundary** —
  in a rate fit, a validation, or an aggregate — without a declared
  cross-vintage treatment in the consuming preregistration. The
  attempt-2 Stage B fit (games before Dec 1, 2026) sits entirely inside
  the 2026-27 season and therefore inside one disclosed vintage.
- If MoneyPuck later discloses re-scoring (or rebuilds again), the
  vintage labels get amended by a new record; labels are never edited
  retroactively in a merged manifest.

### 4.2 Definitional differences vs the official NHL API

MoneyPuck is shot-derived. The official standings' goals-against counts
the shootout-deciding goal; shot-derived sources do not — expect ±1 GA
per shootout loss when joining MoneyPuck rows to official-API records
(restart pack §3.1, citing the in-repo NHL API admission doc). Attempt
2's regulation-first construction (PR #2839) must take its goal
conventions from one source consistently inside any single fit.

### 4.3 Other limitations

- **Team identity is abbreviation strings** (`playerTeam` /
  `opposingTeam`, e.g. `ANA`, `T.B`), with formatting that is not
  guaranteed identical across files. Joins to the official API or to
  DraftKings captures must go through an admitted crosswalk; name-only
  joins are refused by the program's standing rule.
- **Season files include late-September dates** (the 2026 file's
  earliest `gameDate` is 20260929 — preseason). Consumers apply their
  own competition windows; this record does not bless any row as
  regular-season.
- **Single point of failure.** If MoneyPuck is unreachable or stops
  regenerating, pulls refuse (`SOURCE_UNAVAILABLE` / `STALE_SNAPSHOT`)
  and the affected dates are `NO_DATA` on this source — never papered
  over with another source's numbers relabeled as MoneyPuck.
- **No as-of archive.** A missed pull cannot be backfilled: the file
  only ever shows the current vintage. Forward pricing under attempt 2
  therefore needs pulls scheduled ahead of the games they will price
  (§9.2), exactly like the CBB morning-of rule.

## 5. License and terms

- MoneyPuck's data page publicly offers the downloads, and its about
  page invites modeling on them ("Download our database of shots on our
  data page and have fun building your own model" — read directly,
  2026-10-28). No machine-readable license grant accompanies the files,
  and no redistribution right is granted or assumed.
- Accordingly — identical to the Torvik precedents (#2832, #2841):
  this repository stores **hashes, manifests and retrieval code only —
  no MoneyPuck data files are committed** — raw bytes live in a data
  dir under the workspace, outside the repo. MoneyPuck-derived
  artifacts stay internal research material; no republication of
  MoneyPuck tables on cards, posts, or public artifacts.
- No account was created and no payment made in preparing this record
  (free-only law).

## 6. Role admitted, and what stays unchanged

- **Admitted role:** MoneyPuck is admitted as a **design input and a
  forward-pricing input for NHL attempt 2** — the xG foundation its
  design (PR #2839) names. Pricing use exists only inside that
  construction's preregistration when written and frozen; this record
  is not a preregistration, freezes nothing, and starts no clock.
- **Unchanged:** the official NHL API collector's registered role
  (`pricing_input: false`, `scripts/collect_nhl_api.py`) is a separate
  source-role decision and is **not** modified by this record.
  Natural Stat Trick and Hockey-Reference remain unadmitted
  (documented-only context per the restart pack) — nothing here admits
  them by proximity.
- Attempt 1 is retired (NO EDGE, leakage) and stays retired; attempt 2
  is a new construction scored by version.

## 7. Refusals

`SOURCE_UNAVAILABLE` (fetch fails), `SEASON_NOT_PUBLISHED` (404 for the
requested season file), `SCHEMA_INVALID` (required columns absent,
malformed `gameDate`, zero rows, or a season-summary file containing a
season other than the one requested), `SOURCE_CHANGED_AFTER_SNAPSHOT`
(re-pull hash ≠ pinned/expected hash; pinned bytes left untouched),
`STALE_SNAPSHOT` (current-season surface whose `Last-Modified` is older
than the 72-hour in-season threshold), `LOOKAHEAD_RISK` (snapshot
aggregates offered for a date they postdate, or a strictly-prior filter
asked to speak about a date no row precedes), `MANIFEST_MISMATCH`
(a stored file's recomputed hash differs from the manifest during
`verify`).

## 8. What this admission does NOT do

- It does not create an NHL engine, preregistration, freeze, or forward
  clock, and it changes no threshold anywhere.
- Backtests and fits run on this data are **design evidence only**;
  seasons a future construction is designed with can never later be
  presented as untouched validation.
- Verification for NHL attempt 2 accrues **forward only**, from
  admitted pregame captures, under its own preregistration (Stage B
  window Dec 1, 2026 – Jan 31, 2027 per PR #2839, gated on the
  Nov 30, 2026 Stage A verdict).
- PAPER / research only: 0u, no staking, no wager execution.

## 9. Owner / reviewer decisions still required

1. Accept this admission (merge of this PR after Rocky review). On
   acceptance, NHL attempt 2's Stage B fit may proceed on this input.
2. **Pull cadence for the 2026-27 season:** wire scheduled pulls
   (e.g. each morning, America/Chicago) of the season-2026 surfaces +
   `all_teams.csv` so forward vintages exist before the games they
   will price — a missed date is permanently `NO_DATA` on this source
   (§4.3). This wiring is a follow-up act, not part of this PR.
3. Separately and unchanged: the attempt-2 preregistration itself
   (PR #2839 is a design draft, not frozen), and any NHL-API
   source-role decision (§6).
