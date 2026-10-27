# AMENDMENT 1 — NBA Team Totals Forward Test V1 (2026-10-22)

**Amends by reference** the FROZEN prereg
`PREREG_NBA_TEAM_TOTALS_FORWARD_V1_DRAFT.md`
(sha256 `0274e8cd248ed56a43c445c3d23e96e04eb218f4abcafb2ebe4041448ef55504`).
The frozen text is not edited (§11: amendments supersede by reference).

**Ruling:** Grok, under the owner's delegation (t234u), 2026-10-22.
**Effective:** before the first counted slate. Allowed because no slate has
counted and the evaluator is not yet pinned or reviewed. Nothing in this
amendment changes the engine, runner, pick rule, gates, metrics, k, seed,
resamples, or verdict logic. It only declares fail-closed codes for
malformed or ambiguous records that the frozen §8 list did not name
(§8 already requires "a malformed row is refused alone").

## Added engine/evaluator refusal codes (row never scored; counted, reported)

- `DUPLICATE_ROW` — more than one priced row for the same
  (game_id, team). Every copy is refused; none is chosen.
- `ENTRY_QUOTE_CONFLICT` — the entry capture holds conflicting quotes
  (different price) for the same capture, line and side.
- `ROW_MALFORMED` — a row timestamp (tipoff, priced_at) is unparseable or
  zoneless, or a required numeric field (engine mean, b1, b2) is non-finite.
  Only that row is refused.
- `QUOTE_TIMESTAMP_INVALID` — an entry quote for the row has an
  unparseable or zoneless captured_at.
- `CAPTURE_ID_MISSING` — an entry quote for the row has no capture_id.
- `PRICED_BEFORE_QUOTE` — priced_at is earlier than an entry quote's
  captured_at (pricing must follow the quote: 0 ≤ priced_at − quote ≤ 180 s;
  the upper bound remains `QUOTE_STALE_180S`).
- `SLATE_DATE_MISMATCH` — slate_date is not the tipoff's America/Chicago date.

## Added CLV-missing codes (row priced; excluded from CLV; inside the 20% limit)

- `CLOSE_QUOTE_CONFLICT` — conflicting close quotes for the same capture,
  line and side; that line's pair is invalid.
- `CLOSE_TIMESTAMP_INVALID` — a close quote for the row has an unparseable
  or zoneless captured_at.
- `CLOSE_CAPTURE_ID_MISSING` — a close quote for the row has no capture_id.
- `CLOSE_MAIN_FLAG_MISSING` — a close quote in the last capture lacks a
  boolean main-line flag. Only main-line close quotes are used.

## Clarifications (stricter readings, no new code)

- A capture containing any quote at or after tipoff is still a capture; if
  it is the last capture, the close is `CLOSE_NOT_PRETIP`.
- A non-finite entry line is `PRICE_INVALID`; a non-finite final is
  `RESULT_UNAVAILABLE`.
- `PUSH` counts are not reported before the review slate.
