# PGA H2H MATCHUPS — LEG 1 DESIGN SCREEN, ATTEMPT 2026-10-28: **NOT_EXECUTABLE**

Family: `PGA / TOURNAMENT_MATCHUPS_72H` (flagship for PGA).
Design of record: `research/new_sports_designs_20261027/PGA_H2H_MATCHUPS_DESIGN_PREREG_DRAFT.md`
(PR #2844, merged — DESIGN + DRAFT PREREGISTRATION, NOT FROZEN, NOT IN FORCE).
This attempt changes no family state: **NO_CONSTRUCTION → DESIGN ONLY**, exactly as the
design draft stands. No fitting, no simulation, no substitute data, no criterion edited,
no PASS or FAIL recorded for any criterion.

## 1. The screen as designed (verbatim spec, design §6, Leg 1)

> **Leg 1 — historical calibration screen (executable on free data).**
> Chronological: fit ≤2022 → test 2023; refit ≤2023 → test 2024; refit ≤2024
> → test 2025. All 72-hole matchups between two priced players, outcomes from
> the free results archive. References: (a) a market proxy — pairwise
> probabilities implied by the DataGolf past-results **outright Close odds**
> (field-normalized); (b) an OWGR-points-implied reference rating.
> **Leg 1 PASS requires ALL of:** pooled H2H log loss strictly better than
> both references; calibration error (mean |predicted − realized| in
> probability deciles) ≤ 0.05; ≥ 1,500 test matchups per season.

The construction (§4) is a strokes-gained distribution simulation: trailing
24-month, 6-month-half-life recency-decayed, shrinkage-weighted SG skill
(minimum 40 measured rounds else UNPRICED); a hard-shrunk same-course history
adjustment; per-player residual round-score SD floored/capped at the field's
10th/90th percentiles; 100,000 simulated events with a simulated cut;
matchup probability = P(A finishes ahead of B) with the priced comparison
conditional on a non-tied finish. Features use only rounds completed before
the event's first tee time, under composite `(event_id, year)` keys (§5).

## 2. Verdict per criterion

| # | Criterion | Result |
|---|---|---|
| 1 | Pooled H2H log loss strictly better than reference (a) (outright-Close proxy) | **NOT RUN** — reference (b) precondition failed (§3) |
| 2 | Pooled H2H log loss strictly better than reference (b) (OWGR-points-implied) | **NOT RUN** — reference (b) cannot be constructed (G-PGA-1) |
| 3 | Calibration error ≤ 0.05 | **NOT RUN** |
| 4 | ≥ 1,500 test matchups per season | **NOT RUN** — volume material present (see §3a) |

n per season: none scored. n pooled: none.

## 3. Input evidence

### 3a. DataGolf free past-results pages — PULLED, PINNED, SUFFICIENT (not the blocker)

The design's primary input was verified empirically, not assumed. Each free
event page embeds its full record as JSON (`reload_data`): per-player round
scores (R1–R4), per-round SG totals (R1_sg–R4_sg), finish, and outright
Open/Close odds. Worked examples pulled before the sweep:

- 2025 Masters (`/past-results/pga-tour/14/2025`, sha256 `b94d4db9…`): 95 rows,
  outright Open **and** Close present on 95/95 rows (e.g. McIlroy open 7.625 /
  close 7.625), per-round SG on all cut-makers.
- 2017 Northern Trust (sha256 `e95f0e0f…`): full scores/SG, but Open/Close are
  the `-9999.0` missing sentinel on all rows — the free odds record does not
  reach back to 2017. Outside the test scope; noted for the archive's limits.

Full sweep (script `pull_dg_pages.py`, manifest `dg_pages_manifest.json`):
event ids 1..130 × calendar years 2020..2025 = **780/780 pages HTTP 200**,
every body sha256-pinned; all 780 parse. Deduped on the composite
`(event_id, date)` key (§5), the archive yields per season:

| Season | Unique events | Player-rows | Rows with outright Close |
|---|---|---|---|
| 2020 | 23 | 2,960 | 99.5% |
| 2021 | 28 | 3,663 | 98.7% |
| 2022 | 29 | 3,795 | 99.6% |
| 2023 (test) | 30 | 3,912 | 95.6% |
| 2024 (test) | 30 | 3,561 | 94.9% |
| 2025 (test) | 29 | 3,442 | 94.7% |

Per-page detail is in `dg_pages_coverage.json`. Transport note: the first
sweep client (urllib) suffered systematic `IncompleteRead` truncations from
this network (205 requests); the identical URLs succeed via curl, which the
committed pull script uses. No page was accepted from a truncated body —
every manifest entry re-hashes.

**Coverage limit, recorded honestly:** the free archive carries DataGolf's
~30 modeled events per season, not the full ~45-event PGA Tour calendar
(opposite-field events are absent). This is *not* a blocker as designed:
~3.4–3.9k player-rows per test season make the ≥1,500-matchup floor
satisfiable from the covered subset, and the design does not require the
full calendar.

### 3b. OWGR weekly points — NOT OBTAINABLE (the decisive gap, G-PGA-1)

Reference (b) needs OWGR **points** per player for each test event's week.
Probes (full record: `owgr_probe.json`, 2026-10-28):

1. **owgr.com live:** the archive PDF paths (e.g.
   `https://www.owgr.com/archive/PastRankings/2025/Rankings/owgr14f2025.pdf`)
   return HTTP 200 with `Content-Type: text/html` — a 147,450-byte Next.js
   application shell beginning `<!DOCTYPE html>`, byte-count identical across
   different years/weeks (2025 w14 sha256 `cebfc8ab…`; 2020 w37 sha256
   `61a7f957…`). The PDF payload is no longer served at these paths.
2. **Wayback Machine:** CDX shows captures of the weekly PDF URLs, but every
   one is the http→https **301 redirect stub** (344–616 bytes, identical
   content digest `3I42H3S6NNFQ2MSVX7XZKYAYSCX5QBYJ`); the payload was never
   archived under these URLs, and snapshot downloads from this environment
   are additionally rate-blocked (HTTP 429).

Not attempted, by law: OWGR's undocumented internal site API (and it serves
current rankings, not the 2023–2025 weekly archive), and the paid DataGolf
API (Scratch Plus — closed NO under the owner's free-only law; the design
itself forbids depending on it).

The per-event `owgr_rank` embedded in the DataGolf pages is a *rank*, not
points; the design says points. Substituting rank for points would be a
silent criterion edit, so it was not done.

### 3c. The design's own admission precondition (G-PGA-2)

Design §7 declares: *"Admission gap (blocker for Leg 1): the DataGolf free
archive and PGA Tour stats need pin/hash admissions before any screen runs
on them."* No such admission exists on main. This attempt's manifest +
coverage files are the admission raw material; granting the admission is a
separate governed act that this screen does not perform for itself.

## 4. Unblock paths (none applied by this attempt)

1. **Owner design amendment** replacing reference (b) with a constructable
   reference. Two candidates are point-in-time and pinnable today from the
   same admitted DataGolf pages: (i) an OWGR-**rank**-implied Bradley–Terry
   reference from the per-event `owgr_rank`; (ii) a DataGolf-points-implied
   Bradley–Terry reference from the per-event `dg_pts`. Either changes a
   preregistered criterion, so either is the owner's act.
2. **OWGR restoring direct PDF service** at its archive paths — external;
   would be re-probed and hash-pinned before any use.
3. **A governed pin/hash admission** of the DataGolf free archive
   (G-PGA-2), so a future amended screen runs on admitted inputs.

## 5. Files in this record

- `SCREEN_REPORT.md` — this report.
- `screen_result.json` — machine-readable verdict, criteria, gaps, input states.
- `verify_preconditions.py` — stdlib re-verification of the pins, coverage,
  and probe record; derives the verdict from the gap list (never hard-coded).
- `pull_dg_pages.py` / `parse_dg_pages.py` — the exact pull and parse code.
- `dg_pages_manifest.json` — 780 URL → sha256/bytes pins (raw HTML stays in
  the workspace pull store, per the repo's hashes-only pattern).
- `dg_pages_coverage.json` — per-page parse/coverage detail.
- `owgr_probe.json` — the OWGR probe evidence.
- `fixture_masters_2025.json` — a 3-row extracted fixture (with source hash)
  for the family tests.
- `tests/test_pga_h2h_screen_preconditions.py` — parser, manifest, and
  verdict tests.

*Evidence state: DataGolf coverage and OWGR unavailability were each
established by direct pulls/probes in this run (2026-10-28), hash-pinned
above. Nothing in this record is a screen result.*
