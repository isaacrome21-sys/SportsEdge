# AMENDMENT 1 — CBB_TORVIK_EFFICIENCY_V1: the PRIOR-SNAPSHOT input convention

**Status:** DRAFT — proposed amendment, submitted for independent review.
Not in force until cleared and merged. Nothing in this amendment is a
freeze, a screen result, or a counting authorization.

**Amends:** `CBB_SIDES_TOTALS_DESIGN_AND_PREREG_DRAFT.md` in this
directory (the `CBB_TORVIK_EFFICIENCY_V1` design screen), §1 input
definition, §2 fixture gate (Torvik leg), and §3 pin (a) / protocol —
**the input vintage convention only**. Every other term of the design
is unchanged (§5 below).

**Authority:** PR #2832 (Torvik archive admission), binding rule 4:
the archive file for a date *"may never be substituted from D−1 or
D+1 silently; any carry-forward must be declared in the consuming
design, with its own review."* This amendment is that declaration,
with its own review.

**Why it exists:** screen attempt 3
(`research/cbb_torvik_efficiency_screen_20261028/SCREEN_REPORT_ATTEMPT3.md`,
PR #2873) returned `NOT_EXECUTABLE — AS_OF_PREMISE_FAILURE`: the
design's premise that *"the archive file for D is the rating as of
the morning of D"* is **false on the pinned bytes**. The archive
files are end-of-day snapshots. Attempt 3 §6.1 named this amendment
as the governed unblock.

---

## 1. The convention (the whole amendment)

> **PRIOR-SNAPSHOT CONVENTION.** For games played on date D, the
> model's BartTorvik input is the archive file dated **D−1** — the
> last end-of-day snapshot strictly before D. Anywhere the design
> says "the morning-of file for the game date", it now means the
> prior-snapshot file for the game date. If the file dated D−1 does
> not exist on the admitted route, the fixture is **NO_DATA** —
> never substituted from D−2 or D (fail-closed, the design's
> existing missing-file rule shape).

Nothing else about the inputs changes: same admitted route (PR
#2832, mirror `andreweatherman/toRvik-data` at pinned commit
`46d1036443ca452fdd1c6cf25cf5dff50de68337`, path
`ratings/archive/by_date/ratings_archive_{YYYYMMDD}.csv`), same row
fields, same design.

## 2. Witness evidence (attempt 3, quoted verbatim)

From `SCREEN_REPORT_ATTEMPT3.md` §3 — the four witnesses, each
computed from the pinned archive bytes against the pinned substrate:

- **Duke, file 2014-11-14** (opener played ON 11-14: Presbyterian 44
  @ Duke 113): morning-of requires 0-0; file shows **1-0**.
- **Kentucky, file 2014-11-14** (Grand Canyon 45 @ Kentucky 85):
  requires 0-0; shows **1-0**.
- **Wisconsin, file 2014-11-14** (Northern Kentucky 31 @ Wisconsin
  62): requires 0-0; shows **1-0**.
- **Purdue, file 2023-03-12** (Big Ten final played ON 03-12; 28-5
  before, 29-5 after): requires 28-5; shows **29-5**.

And its fingerprint paragraph:

> Wisconsin's adj_d is 90.405 in the 2014-11-13 file (preseason,
> 0-0) and 89.118 in the 2014-11-14 file, while the 2014-11-15 file
> (a day Wisconsin did not play) sits at 89.133; Kentucky's adj_o
> 117.724 (11-13) → 117.434 (11-14) → 117.442 (11-15, idle); Duke's
> record across the three files 0-0 → 1-0 → 2-0. Conclusion: each
> file D is the state **after** D's games, in both the backfilled
> era (2014-15) and the recent era (2022-23).

Attempt 3's verdict stands unaltered: the attempt is a failed
execution record, not a screen result; no fitting was performed.

## 3. Verification of the convention (the D−1 side)

Declaring D−1 does not make it true. The convention was verified
before this amendment was drafted, by a scripted, re-runnable probe
suite — `probe_prior_snapshot_convention.py` in this directory,
results in `prior_snapshot_probe_results.json` — over 47 archive
files pulled from the pinned mirror commit, every input
pin-verified (hoopR substrate vs PR #2867's manifest; CBR leg via PR
#2871's pinned derivation; the 2023-03-12 archive pull's sha256
equals PR #2832's recorded sample `9524481d…`).

**Gates.** The *delta gate* (absolute): file D's record equals file
D−1's record plus exactly the team's result on D, and file D−1
contains no part of D's result. The *equality gate*: file D−1's
record equals the team's entering record over **all games** in the
pin-verified substrate through D−1 — an absolute basis, because
Torvik's `record` column is a school's full record. A deviation
fails the probe unless it matches one of two pre-declared
explanations exactly, with the games named: a **non-universe
opponent** (Torvik does not carry the school) or a **substrate
omission** (a fixture the CBR leg of the §2 gate supplies that the
hoopR substrate omits). First-date probes additionally require the
whole D−1 file to total **0 games** (preseason), and spot-check
every both-teams-resolved game in file D for the same-day
contamination the convention exists to exclude.

**Result: 19/19 probes PASS — `PRIOR_SNAPSHOT_VERIFIED`.**

| Probe | Season / date D | Result |
|---|---|---|
| W1 attempt-3 witnesses (Duke/Kentucky/Wisconsin; fingerprints at full float precision) | 2014-15, 2014-11-14 | PASS — file 11-13 totals 0 games; all three 0-0 in D−1, 1-0 in D; Wisconsin adj_d 90.405→89.118, Kentucky adj_o 117.724→117.434 reproduce |
| W2 attempt-3 witness (Purdue; Penn State) | 2022-23, 2023-03-12 | PASS — Purdue 28-5 in file 03-11, 29-5 in 03-12; Penn State (Torvik surface "Penn St.") 22-12 → 22-13 |
| F1 first playing date ×8 | 2015-11-13, 2016-11-11, 2017-11-10, 2018-11-06, 2019-11-05, 2020-11-25, 2021-11-09, 2022-11-07 | PASS — every D−1 file totals 0 games; 722 both-resolved games spot-checked in file D, exactly 1 violation, classified below |
| T1 championship date ×8 | 2015-04-06, 2016-04-04, 2017-04-03, 2018-04-02, 2019-04-08, 2021-04-05, 2022-04-04, 2023-04-03 | PASS — delta gate exact for all 16 finalists; equality exact for 13; 3 deviations, all explained below |
| L1 last playing date of the COVID-shortened season (2020-03-11, 34 games, 68 team-slots) | 2019-20 | PASS — 63/68 slots identified (92.6% coverage), all 63 pass both gates, 0 failures |

**The three explained deviations** (none involves a game played on
a probe date D; none is same-day contamination):

1. **Villanova, 2015-16 final** — file D−1 shows 34-5 vs the hoopR
   substrate's 33-5. `EXPLAINED_SUBSTRATE_OMISSION`: the substrate
   omits Villanova vs East Tennessee State, 2015-11-20 (Villanova
   won 86-51), a fixture the CBR leg supplies. Torvik's 34-5 is the
   true entering record; the substrate, not the archive, is short.
2. **North Carolina, 2016-17 final** — file D−1 shows 31-7 vs the
   substrate's 32-7. `EXPLAINED_NON_UNIVERSE_OPPONENT`: Torvik does
   not carry Chaminade (D2), whom UNC beat on 2016-11-21.
3. **Michigan, 2017-18 final** — file D−1 shows 32-7 vs the
   substrate's 33-7. Same cause: Chaminade, beaten 2017-11-21.

**The one dating edge** (F1 2016-17): Harvard 70 @ Stanford 80 was
played in Shanghai on the substrate's 2016-11-11; both teams stand
0-0 in file 11-11, and file **2016-11-12** shows Stanford 1-0 /
Harvard 0-1 — Torvik filed the game under the local (Shanghai)
date, one snapshot **late**. A late filing is the conservative
direction: under this convention the game can enter a fixture's
input one snapshot later than the US calendar suggests, never
earlier. No lookahead arises from it, and it does not touch the
D−1 cleanliness claim.

**Honesty note.** The probe suite's first execution failed 11 of 19
probes — every failure traced to the probe's own basis error (it
expected Torvik's full-record column to equal a resolver-resolvable
subset of the substrate), not to the convention. The executed
script's docstring records that failure and its classification;
the gates above are the corrected, declared basis, and the
committed results JSON is the corrected run's output.

## 4. What does NOT change

Byte-for-byte the same, per the design as drafted:

- the construction (§1 mechanics: opponent-adjusted efficiency
  margin over the design's declared formula);
- both baselines (naive league-mean; the §1 simple-ratings
  baseline);
- the screen criteria (design pass = paired season-block bootstrap
  CI upper bound < 0 vs **both** baselines on **both** legs);
- the seasons (2014-15 through 2022-23);
- the §2 three-way fixture gate — its structure, its CBR and hoopR
  legs, and its agreed-fixture rule are unchanged;
- the Illinois-college exclusion.

Only the input vintage convention is declared. No threshold is
lowered, no criterion is edited, no failed construction is touched.

## 5. Mechanical consequences (declared, not silent)

- **§2 Torvik leg, as amended, reads:** *the prior-snapshot file for
  the game date (D−1) exists on the admitted route and carries both
  teams.* The amended screen run must rebuild its fixture universe
  on file D−1 existence (attempt 3's universe was built on file D);
  the gate's three-way agreement structure is unchanged.
- **Drift-schema window shifts one day.** The design's handling of
  the 2022-11-07/08/09 header-drift files applies to the files
  actually read under the convention: fixtures on 2022-11-08…10
  read the drift-layout files; fixtures on 2022-11-07 become
  ratable from the 2022-11-06 file (which itself uses the drift
  layout: leading index column, `rk`, `rec`, no `adj_tempo`).
- Attempt 3's ten recorded design readings (§7 of its report) are
  inherited by the amended run unchanged, except where this
  amendment's convention supersedes a vintage assumption.

## 6. Scope

- This amendment governs the **design screen only**. A forward
  preregistration, if any is ever proposed for this construction,
  needs its own terms and its own review; nothing here pre-adopts
  the convention for it.
- This amendment does **not** rewrite PR #2832's admission.
  Admissions change by their own successor records. It records
  that #2832's rule 2 provider claim ("results of games played on
  D are first reflected in the archive for D+1 or later") is
  **disproven by the pinned bytes**, and that no other consumer
  may rely on rule 2's morning-of semantics without its own
  declared convention and review.
- Attempt 3 remains `NOT_EXECUTABLE` on the record. The next
  screen attempt runs under this convention as a new attempt, on
  its own record.

## 7. Live-route guard note (record only — follow-up, not an edit)

The live Torvik route (PR #2841: `barttorvik.com/{year}_team_results.csv`,
a living file) differs in kind from the archive: it has no dated
snapshots, so its morning-of property is created by **pull
discipline** — the daily job (`torvik-morning-pull-daily`, ~06:21
America/Chicago) pulls once each morning before first tip and
hash-pins the vintage; #2841 §2.2 already states that a pull taken
after any of D's games have started is not a morning-of snapshot
for D.

This amendment records the required guard for that job's next
revision, so the archive lesson is not re-learned live:

> **Each daily manifest's `games_played_total` must be checked to
> exclude same-day games. A pull whose total already includes any
> game played on D is a contaminated vintage for D and must be
> refused / NO_DATA for D — never pinned as D's snapshot.**

This PR does not edit the cron, the job, or the #2841 admission;
the guard is recorded here as a stated follow-up for the job's
next governed revision.

## 8. Re-running the verification

```
python3 research/nba_cbb_activation_20261028/probe_prior_snapshot_convention.py
```

Inputs resolve from the kept, pin-verified pulls of PRs #2867
(hoopR substrate), #2871 (CBR leg) and #2832/#2873 (archive route);
archive files are pulled from the pinned mirror commit on first
use and hash-logged in the results JSON. Exit 0 =
`PRIOR_SNAPSHOT_VERIFIED` (19/19); exit 1 = a probe failed;
exit 2 = an input pin failed (the evidence base itself is not what
the records say it is).
