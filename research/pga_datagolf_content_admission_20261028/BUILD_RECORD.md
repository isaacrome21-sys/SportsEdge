# BUILD RECORD — G-PGA-2 content-pin packet (Workstream A, 2026-10-28)

Branch: `rocky/pga-gpga2-content-pin-20261028` (DRAFT PR for Rocky
clearance; this record is builder-reported until independently
verified).

## What was built

- `extract_dg_content.py` — the extraction of record
  (`PGA_DG_CONTENT_EXTRACT_V1`): re-verifies every raw page pin from
  PR #2886's `dg_pages_manifest.json` before reading content, applies
  the identity-match universe rule, dedupes on `(event_id, date)`,
  emits canonical per-event content + `content_manifest.json`.
- `verify_content_pins.py` — pin verification + determinism proof
  (full and `--manifest-only` modes).
- `content_manifest.json` — the DRAFT content manifest: 157 events,
  19,630 rows, corpus sha256
  `cef59544a3f9f813db90154eed0715ccd2d4cd09acb486dbe12ae7585eec96d6`.
- `fixture_event_14_2025.json` — the extracted content of the 2025
  Masters (event 14, 2025-04-13; 95 rows), committed so the family
  tests can exercise the canonical form and the manifest pin without
  the workspace store.
- `ADMISSION_DRAFT.md` — the admission document this packet prepares.
- `tests/test_pga_datagolf_content_admission.py` — manifest tests.

## Execution evidence (2026-10-28, this build)

- Pull store located at `~/workspace/pga_screen_20261028/pulls/`
  (the PR #2886 workdir) and re-verified independently of the
  extractor: 780 manifest entries, 780 HTTP 200, **0 missing files,
  0 hash mismatches**.
- Extraction run: raw pages reverified 780/780; identity-matched 157;
  events 157; rows 19,630; owgr_rank valid 16,567 (84.4%) — the
  Amendment 1 §3.1 census reproduced exactly, confirming the universe
  definition.
- Determinism: `verify_content_pins.py` full mode — kept files match
  all 157 pins; re-extraction byte-identical (events + manifest).
- Spot checks (Amendment 1 §4 re-verification): exhaustive 2020
  owgr_rank ranges — Molinari {20, 21, 24, 85}, Kuchar 17–29, Day
  34–58; contemporaneous, not backfilled.

## State this packet leaves behind

The corpus is pinned as a DRAFT. Nothing is admitted; Amendment 1 is
not adopted; the Leg 1 screen remains NOT_EXECUTABLE. The extracted
corpus is kept at `~/workspace/pga_screen_20261028/extracted_content/`
(regenerable byte-identically from the pull store).
