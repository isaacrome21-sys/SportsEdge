# Capture, clock and grading audit — Oct 21, 2026

Implementation draft for independent review; no frozen rule changed.

## Findings from source

- NBA frozen prereg `research/nba_props_forward_20261020/PREREG_NBA_PROPS_FORWARD_V1.md`
  section 5 already requires PICKED and PASSED rows. The evaluator's
  `_runner_disposition` accepts both candidate and PRICED_RESEARCH statuses.
  Full-board pricing is an operations requirement, not a new sample-size rule.
- The plan's 50-row shorthand is incomplete: section 4 also requires 100 rows
  before a verdict, four full slates and 40 distinct games per market. The
  frozen prose says **exactly 40** while code uses **at least 40**. A documented
  clarification is needed; this draft changes neither document nor evaluator.
- A raw row count is not independent outcome count. Repeated captures and
  over/under quotes support the same outcome; preserve raw records but apply
  the frozen unit identity for scoring. Do not inflate progress with snapshots.
- Capture Spec V1 allows entry any time before start. Close must be the final
  committed pre-start capture within 60 minutes. No close means missing CLV,
  while outcome/calibration evidence can still be retained under the prereg.
- Phone pricing uses a separate 180-second current-card freshness check.
  `WATCH_QUOTE_NOT_CURRENT` is unclassified by the NBA evaluator. Do not reprice
  old captures with current state and call them forward predictions. Preserve
  the original pregame model version, probabilities, and PICKED/PASSED status;
  display-time staleness must not overwrite that original record.
- AM/PM schedules alone do not establish fixture-local close coverage. Capture
  planning must track each game's close window and report missed windows.

## Delivery check implemented here

`scripts/check_grading_landing.py REQUEST.json RECEIPT.json` exits 1 with a
named failure if the expected report did not land, is empty or altered, has
the wrong run/input/card set, or points outside the delivery directory.
Exit 0 means delivery integrity only, never correct grading or validation.
Repeated checks do not write or grade anything. Explicit no-card runs still
produce a report, so silence cannot be confused with a successful empty run.

Request (freeze and retain before launching the grader):

```json
{"schema_version":1,"run_id":"2026-10-21-nightly","input_sha256":"<64 lowercase hex characters>","card_ids":["<stable card ID>"],"no_cards":false}
```

The grader writes `GRADE_AND_REVIEW.md`, then a receipt with those same fields
plus `report_path` (relative path) and `report_sha256` (exact report bytes).
The report's first line binds it to the request:

```python
binding = {k: request[k] for k in ("run_id", "input_sha256", "card_ids", "no_cards")}
binding["card_ids"] = sorted(binding["card_ids"])
header = "<!-- grading-run " + json.dumps(binding, sort_keys=True) + " -->"
```

The scheduler must execute this check in its unconditional completion path,
including when the grader itself fails. A separate watchdog must check the
expected request after the deadline if the scheduler never starts. Publish
the failure visibly instead of swallowing its exit code.

## Integration still required — no claim of live repair

The reported Oct 20 23:21 job and `operative_run_20261020` directories live
in Rocky's runtime, not this checkout. GitHub main at inspection contains no
matching run output or scheduler. The connected ChatGPT task inventory has
no active nightly grading task. Missing output alone does not establish the
root cause. Rocky must provide the actual scheduler/run logs and wire the
check into that job; inspect exit status, working directory, write/upload
failure, and whether it ran at all. Do not invent a diagnosis or re-grade
Oct 20 without checking the authoritative ledger.

The guard detects duplicate card IDs in a delivery and is read-only/idempotent.
It does **not** implement cross-run exactly-once settlement. The authoritative
grader still needs stable position IDs, transactional/idempotent settlement,
correlated-position handling and preserved VOIDs. It also cannot authenticate
a dishonest producer: request and receipt must be kept in trusted records.

Future work: full-capture adapter with raw-to-priced reconciliation and
per-row blocked reasons; fixture-local close scheduling; source instruments
C/E/D; held PR fixes. No live counts, new source admission or PLAY granted.
