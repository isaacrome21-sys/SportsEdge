# ADMISSION (DRAFT) — DataGolf free past-results archive, CONTENT-LEVEL pin for the PGA H2H Leg 1 screen (G-PGA-2)

**Status: ADMISSION DRAFT — FOR THE GOVERNED ADMISSION ACT. THIS PACKET
GRANTS NOTHING.** The DataGolf free archive is **not admitted** by the
landing of this document. Admission is a separate governed act, exactly
as design §7 requires ("the DataGolf free archive and PGA Tour stats
need pin/hash admissions before any screen runs on them"). This packet
prepares that act: it performs the extraction, pins the extracted
content, proves the extraction deterministic, and states the scope the
act would grant.

**A Leg 1 re-run remains blocked after this packet lands.** Two
independent blockers stand, neither cured here:

1. **Amendment 1 adoption (the owner's act).** Reference (b′) exists
   only in `PGA_H2H_MATCHUPS_DESIGN_AMENDMENT_1_DRAFT.md` (PR #2896,
   landed as a draft record). Until the owner adopts it, criterion 2 of
   the Leg 1 screen has no lawful reference and the screen stays
   **NOT_EXECUTABLE**.
2. **This admission itself.** The pins below are a DRAFT manifest until
   the governed act admits them.

Family: `PGA / TOURNAMENT_MATCHUPS_72H`. Design of record:
`research/new_sports_designs_20261027/PGA_H2H_MATCHUPS_DESIGN_PREREG_DRAFT.md`
(design + draft preregistration, NOT FROZEN). Prior record: PR #2886
(Leg 1 attempt, NOT_EXECUTABLE; packet
`research/pga_h2h_screen_20261028/`).

## 1. Scope the act would grant

Admission of the corpus pinned in §3, for **PGA H2H design-screen use
only**: the Leg 1 historical calibration screen of the design of record
(and its Amendment 1 reference (b′) if adopted). No other family, no
forward/Leg 2 use, no clock credit, no PLAY eligibility. The corpus is
a historical archive (seasons 2020–2025 as published on the pulled
pages); it is design/screen data, and any screen run on it remains
subject to the design's own chronology and the program's no-backfill
law for verdicts.

## 2. Why the pin is content-level (the G-PGA-2 finding)

Amendment 1 §6 measured the decisive fact: **page bytes drift between
pulls** — a fresh 36-page stratified re-pull on 2026-10-28 matched 0/36
of the #2886 raw byte pins (the 2025 Masters page grew by 24 bytes),
while the extracted `reload_data` content was identical (95 rows; the
#2886 packet's 3-row fixture reproduced field-for-field). Pinning raw
bytes would therefore pin an artifact no future pull can reproduce.
This packet pins the **extracted content per event**, produced by the
extraction of record (`extract_dg_content.py`, version
`PGA_DG_CONTENT_EXTRACT_V1` in this directory) from the surviving
#2886 pull store, whose raw pins still verify 780/780 (§3). The store
survives at `~/workspace/pga_screen_20261028/pulls/` (workspace, per the
repo's hashes-only pattern for raw pages); the extracted corpus is kept
beside it at `~/workspace/pga_screen_20261028/extracted_content/` and is
regenerable byte-identically from the store by the pinned extractor
(§4).

## 3. The pinned corpus

Universe rule (the definition Amendment 1's census measured): a pulled
page enters the corpus only if its embedded identity — `info.event_id`
and `info.calendar_year` — equals the request key it was pulled under
(**identity-matched**); events are deduped on the composite
`(event_id, date)` key per design §5. Of 780 pulled pages, 157 are
identity-matched; the other 623 serve a different edition than requested
(DataGolf's URL scheme resolves some event/year pairs to a default
edition) and are excluded, not silently re-keyed.

| | |
|---|---|
| Raw pages in the #2886 store | 780 (all HTTP 200, all sha256-pinned) |
| Raw pins re-verified by this packet | **780/780** |
| Identity-matched pages → events | **157** |
| Player-rows extracted | **19,630** |
| `owgr_rank` valid (integer ≥ 1) | 16,567 rows (**84.4%**) — reproduces Amendment 1 §3.1 exactly |
| Events per season | 2020: 20 · 2021: 25 · 2022: 26 · 2023: 27 · 2024: 30 · 2025: 29 |
| **Corpus sha256** | `cef59544a3f9f813db90154eed0715ccd2d4cd09acb486dbe12ae7585eec96d6` |

The corpus hash is sha256 over the per-event content pins
(`event_id|date|content_sha256` lines, events sorted by (date,
event_id)); every per-event pin is in `content_manifest.json` beside
this document, over the canonical form stated there (JSON, keys
sorted, compact separators, ASCII-escaped, one trailing newline).

**Extracted fields** (per player-row; source values preserved as
published, sentinels included — validity rules belong to consumers):

- *Consumed by the design:* `dg_id`, `player_name`; per-round
  `score` / `par` / `sg` for each round present (a round is present
  iff the page carries a score or an SG value for it); `fin`;
  `total`; outright `open` / `close` (reference (a)); `owgr_rank`
  (reference (b′)).
- *Carried under `excluded`, never consumed:* `dg_pts` —
  **DISQUALIFIED** by Amendment 1 §3.1 (it is points earned *from* the
  event, an outcome; as a pre-event input it would be lookahead) — and
  `dg_rank` (DataGolf's proprietary ordering; not the official ranking
  reference (b) exists to represent). Both are pinned inside the
  content so the exclusion is auditable in the admitted bytes, and the
  executor's tests assert no consumed path reads them.

## 4. Determinism proof

`verify_content_pins.py` (this directory), run 2026-10-28:

- kept extracted files match all 157 content pins;
- raw pins re-verified during a full re-extraction: 780/780;
- **re-extraction from the raw store is byte-identical** — all 157
  event files and the regenerated content manifest equal the kept
  copies exactly. The extractor emits no timestamps and no
  host-dependent values.

Re-run at any time: `verify_content_pins.py` (full mode) or
`--manifest-only` for the committed manifest's internal consistency.

## 5. Point-in-time spot check (the re-verification Amendment 1 §4 asked the admission act to perform)

Amendment 1 §4 established empirically that the pages' `owgr_rank`
values are as-of-event, and asked the admission act to re-verify one
spot check when it pins the corpus. Done exhaustively over the pinned
corpus (all 2020-season events in the corpus, not a sample):

- Molinari, Francesco — 2020 ranks {20, 21, 24, 85} (his 2020 standing;
  he stands far lower today);
- Kuchar, Matt — 2020 ranks 17–29 across the season (one -9999
  sentinel);
- Day, Jason — 2020 ranks 34–58 across the season.

All three track their contemporaneous 2020 standings and decline; a
backfilled snapshot would show one later rank on every page. The
amendment's sampled ranges (Molinari 20; Kuchar 17–23; Day 34–51) sit
inside these exhaustive ranges. DataGolf publishes no methodology note
for these fields; the as-of reading remains empirical, as the amendment
states.

## 6. What the admission act must still decide

1. Adopt these content pins as the admitted corpus (or require a
   re-extraction under observation and admit its output instead —
   determinism makes the two identical).
2. Confirm the scope in §1 (design-screen use for this family only).
3. Note the standing caveat from PR #2886: the free archive carries
   DataGolf's ~30 modeled events per season, not the full PGA Tour
   calendar. The design's volume floor is satisfiable from the covered
   subset; the limitation is recorded, not cured.

*Prepared 2026-10-28. Evidence state: raw-pin re-verification,
extraction counts, determinism, and spot checks were each executed in
this build over the surviving pull store and are reproducible from the
scripts in this directory. Nothing here is a screen result; no fitting
or simulation was performed.*
