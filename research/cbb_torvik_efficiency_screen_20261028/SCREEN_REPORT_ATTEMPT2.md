# SCREEN REPORT — ATTEMPT 2 — CBB_TORVIK_EFFICIENCY_V1 design screen

# VERDICT: NOT_EXECUTABLE — the screen was NOT run (again)

**Family:** CBB sides/totals (spread, moneyline, game total).
**Construction:** `CBB_TORVIK_EFFICIENCY_V1` (design:
`research/nba_cbb_activation_20261028/CBB_SIDES_TOTALS_DESIGN_AND_PREREG_DRAFT.md`,
merged in PR #2843). **Screen:** the historical design screen of design §3 —
DESIGN EVIDENCE ONLY by the design's own terms; it can never validate the
family. Date of this report: 2026-10-28. Base main head:
`311f62c11` (merge of PR #2866). Attempt 1: PR #2866
(`SCREEN_REPORT.md`, this directory) — NOT_EXECUTABLE on precondition (b).

Attempt 1's blocker is cured. Attempt 2 stops on the next precondition in
the design's own list — (c), the three-way fixture agreement — because its
College Basketball Reference leg has no lawful bytes. No fixtures were
scored, no parameters were fitted, no criteria were relaxed, and no
substitute data was used. No circumvention of the upstream refusal was
attempted.

## 1. Precondition audit on current main (design §3: "Data pins before any run")

| Pin | State | Evidence |
|---|---|---|
| (a) Torvik archive files via the PR #2832 retrieval script at its pinned commit, one file per game date | **MET** | Carried from attempt 1 and re-verified this run: the attempt-1 reproduction script (`verify_preconditions.py`) was re-run on this main head — both admission samples reproduce byte-identically (2022-01-13: 58,716 B, sha256 `4de4761c…`; 2023-03-12: 60,010 B, sha256 `9524481d…`) and all 26 by-date season probes return valid morning-of files (26/26 OK). |
| (b) Historical schedule/results assets pinned by the full-tuple rule of PR #2835 under a successor manifest | **MET** | PR #2867 merged `research/cbb_hoopr_mbb_schedule_successor_20261028/successor_manifest.json`: 18 assets (CSV + parquet, seasons 2015–2023) pinned by tag + release ID (97399224) + asset ID + size + `updated_at` + SHA-256, pulled 2026-10-28T10:42:46Z. Independent check this run: the kept bytes at `~/workspace/cbb-successor-admission-20261028/pulls/` re-hash to the manifest for **18/18 assets (MATCH 18, MISMATCH 0, MISSING 0)**. |
| (c) The §2 three-way fixture agreement, applied before any fitting | **NOT MET** | The College Basketball Reference leg is `REFUSED_HTTP_403_NOT_PINNED` (successor manifest `cbr_leg`; attempt 2026-10-28T10:43:44Z: the 2015 season-schedule page returned HTTP 403; per Sports Reference bot policy the remaining eight seasons were not attempted; no circumvention). No CBR bytes exist to agree against, so no fixture can be admitted under §2. |

## 2. Adjudication of precondition (c) — from the design text

The question attempt 2 turns on: does the design treat College Basketball
Reference as a **required input** to the screen's fixtures, or as an
optional documented cross-check the screen may proceed without? The
design's own words settle it. Design §2 ("Third cross-check — College
Basketball Reference"):

> "In this design it is a third, independent cross-check on the two
> admitted substrates: **a fixture enters the §3 screen only on
> three-way agreement** — hoopR substrate (ESPN game ID, date, teams,
> final score), Torvik archive (a morning-of file exists for that date
> and carries both teams), and College Basketball Reference's season
> schedule (same fixture, same date, same final score). Any
> disagreement excludes the fixture and is logged as
> `SCHEDULE_DISCREPANCY`, never silently resolved."

And design §3 lists, under "**Data pins before any run**":

> "(c) the §2 three-way fixture agreement, applied before any fitting."

The same section's §2 "Role limits" sentence — "cross-check / reference
only. It is not a ratings input (no CBB-Reference metric enters the
construction), not a validation or market baseline (it publishes no
odds), and not an identity admission" — limits **what CBR data may be
used for**; it does not make the agreement optional. A cross-check that
a fixture "enters only on" is a gate, and a gate cannot be passed
against bytes that do not exist. The successor admission record reads
the design identically (PR #2867, ADMISSION_RECORD §6): "(c) Three-way
fixture agreement — PARTIALLY OUTSTANDING… a fixture enters the screen
only on three-way agreement, so fixtures cannot be three-way-verified
until the CBR leg is pinned by a successor record."

**Adjudication: CBR agreement is a required data input to the screen's
fixture set. With the CBR leg refused and unpinned, the screen remains
NOT_EXECUTABLE as designed.** Proceeding on two legs and claiming
"two-way agreement" would silently amend §2/§3 — a criterion edit,
which no runner is authorized to make. Attempt 1's §6 unblock list
states the same cure: "A College Basketball Reference leg with bytes
actually pulled and hash-pinned per season (or an admitted verification
method), so the §2 three-way agreement can be applied as written."

## 3. Criteria — all NOT RUN

| # | Design §3 criterion (design pass requires all four) | Result |
|---|---|---|
| 1 | Spread MAE: paired season-block bootstrap CI upper bound < 0 vs naive league-mean baseline | NOT RUN — precondition (c) unmet |
| 2 | Spread MAE: CI upper bound < 0 vs §1 simple ratings baseline | NOT RUN — precondition (c) unmet |
| 3 | Total MAE: CI upper bound < 0 vs naive league-mean baseline | NOT RUN — precondition (c) unmet |
| 4 | Total MAE: CI upper bound < 0 vs §1 simple ratings baseline | NOT RUN — precondition (c) unmet |

n per season: none. n pooled: none. No DESIGN_PASS and no DESIGN_FAIL
is recorded.

**Family state is unchanged:** CBB sides/totals remains DESIGN +
DESIGN-SCREEN SPEC + PREREG DRAFTED. The §5 forward prereg is unaffected
and remains blocked by its own data gates (identity crosswalk OPEN;
capture delivery), which this historical screen could not cure in any
case.

## 4. Hazard flagged for the reviewer — attempt-1 reproduction script

`verify_preconditions.py` (attempt 1, this directory) was re-run on
this main head. Its (a) and (b) sections are correct and are cited
above, but its verdict logic hard-codes (c) as "not applicable until
(b)" — true only in attempt 1's world — and therefore prints
`"screen_verdict": "EXECUTABLE"` on current main even though its own
(c) section reports `"met": false`. **That printed verdict is wrong
under the design text and must not be acted on.** The script is
attempt 1's record and is left unedited here; `verify_preconditions_attempt2.py`
(this PR) implements the design's gate faithfully — (c) is applicable
now that (b) is met, and it is unmet — and prints NOT_EXECUTABLE. A
future attempt must not reuse the attempt-1 script's verdict line.

## 5. What unblocks the screen (one line each)

1. A lawful College Basketball Reference pull (an egress Sports
   Reference does not refuse), hash-pinned per season in a successor
   record with its own review — completing precondition (c)'s third leg.
2. Or an owner/design amendment admitting a different verification
   method for the third leg — a design change, which only the owner
   can make; no runner may substitute it unilaterally.
3. Then the screen runs exactly as §3 specifies — walk-forward by
   season, morning-of ratings, Illinois over-exclusion first, audited
   name-join with the ambiguity list published — with no criterion edits.

## 6. Provenance and reproduction

- Repo / base: `isaacrome21-sys/SportsEdge` @ `311f62c11` (fresh clone;
  includes PR #2866 merge and PR #2867 merge `cf37de4f6`).
- Design: PR #2843 (merged). Torvik admission: PR #2832 (merged),
  mirror pinned commit `46d1036443ca452fdd1c6cf25cf5dff50de68337`.
  Schedule successor manifest: PR #2867 (merged). Attempt 1: PR #2866
  (merged).
- Machine-readable record: `screen_result_attempt2.json` (this directory).
- Reproduction: `python3 verify_preconditions_attempt2.py` (this PR,
  stdlib only) re-checks the (b) manifest pins' presence per season,
  re-hashes the kept schedule bytes when available, scans every repo
  manifest for a CBR pin, and prints NOT_EXECUTABLE with the (c) reason.
- PAPER / research only: 0u, no staking, no wager execution. Nothing
  was frozen; this PR is a draft for Rocky's clearance.
