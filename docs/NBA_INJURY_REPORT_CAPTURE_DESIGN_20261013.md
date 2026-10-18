# Design: forward-only, timestamped capture of official NBA injury-report PDFs

**Design only.** No code, no scheduler, no activation. **No backfill:** historical PDFs are never captured as as-of evidence. The capture begins on its first real run, and only reports fetched by it count. The parser it feeds is `sportsedge/sports/nba/injury_report_parser.py` (pre-registered and registered).

## Source
- `https://ak-static.cms.nba.com/referee/injury/Injury-Report_YYYY-MM-DD_HHAM|PM.pdf`, free and public.
- The filename slot is an ET hour label. The real report time is in the PDF header; seen fixtures had a header 30 minutes after the slot.
- **Cadence and naming for 2026-27 are unverified.** The planner must not assume them. Any change (e.g. minute-level names) is found by probing and recorded as a schema event.

## Two times, never merged
| field | meaning | source |
|---|---|---|
| `received_at_utc` | when *we* got the bytes | capture host clock (NTP-synced; clock source and offset recorded) |
| `effective_at_utc` | the time the report claims | PDF header, parsed by the registered parser |
| `http_last_modified` | server-asserted modification time | response header, kept as a cross-check only |

- An as-of consumer uses a report only if `received_at_utc < cutoff`. **Both** times are shown, and the effective time never stands in for the receipt time.
- If `received_at < effective`, or `|Last-Modified − effective| > 5 min`, the record is kept but flagged `TIME_INCONSISTENT` and is unusable.

## Expected slots, and missed or late reports
- **Planner:** for each game day (from the NBA schedule), list the expected slots from 3 hours before the first tip-off through the last tip-off, hourly per the observed naming. The planner re-runs if the schedule changes.
- **Probe:** each slot is probed starting at slot + 35 min, with retries up to slot + 90 min.
- **Status per slot** (one of):
  - `ON_TIME`: received by slot + 45 min.
  - `LATE`: received later, before the last tip-off of the day.
  - `MISSED`: never received (HTTP 403/404 or no run), with an explicit record of the reason (`NOT_PUBLISHED`, `HTTP_<code>`, `RUNNER_DOWN`, `NOT_ATTEMPTED`).
  - `AFTER_TIPOFF`: received after a game had already started, per game. It is not usable for that game.
- **No guarantees.** No slot is guaranteed: hosted schedulers can be delayed or dropped. A run gap shows up as `MISSED: RUNNER_DOWN`, never as silence.
- **Changed bytes.** A second fetch of the same slot with different bytes is a new record, `REVISED`, linked to the prior one. Earlier bytes are never overwritten.

## Append-only record and external anchor
- **Raw store:** PDF bytes are stored content-addressed by sha256, outside the repo.
- **Capture log:** an append-only JSONL. Each line holds slot, url, status, received_at_utc, http_status, http_last_modified, content_length, pdf_sha256, effective_at_utc (or a parse error), parser version, extractor version, and `prev_line_sha256` (hash chain).
- **External anchor:** after each run, the head of the chain is written to a separate anchor location the capture job cannot rewrite. Options:
  - a separate append-only repo or branch;
  - a GitHub issue comment;
  - an object-lock bucket.
- **Verification:** recompute the chain and compare it with the anchors. Any mismatch means the log is untrusted from that point onward.
- No edits and no deletes. Corrections are new lines.

## Downstream rules
- Parsed rows keep `participation=UNKNOWN`: listed AVAILABLE does not mean the player played.
- Player IDs come only from an as-of directory; unmapped players are UNKNOWN.
- Props stay WATCH/BLOCKED until a reviewed, frozen evaluation exists. That evaluation would use only forward-captured reports.
- Low request rate (≤ 1 request per slot plus retries). Terms for automated access are unverified and need an owner decision before any run.

## Open items (owner/reviewer)
- Where the anchor lives.
- Which host runs the capture, and how its clock is checked.
- Confirming the 2026-27 cadence and naming once the season starts.
- Terms of use.

## Approved offline build + infrastructure design (ChatGPT ruling)
**Offline module:** `sportsedge/sports/nba/injury_report_capture.py`, with tests in `tests/test_nba_injury_report_capture.py` using recorded fixtures only.
- **Trusted receipt clock.** `received_at` comes from a module clock read inside the module; only tests monkeypatch it. It is kept separate from the header effective time.
- **Slot status.** ON_TIME / LATE / AFTER_LAST_TIPOFF, plus explicit MISSED records.
- **Inconsistencies.** Parse failures and `TIME_INCONSISTENT` are kept but marked unusable.
- **Hash chain.** Records are hash-chained, and `verify_chain` requires an anchor head held outside the log. Tampering or truncation fails.
- **As-of lookup.** `usable_as_of` uses the receipt time only.
- **No network or scheduler.** The module has no network, scheduler, storage SDK or subprocess code, and a test enforces this.

**Infrastructure (design only; nothing provisioned):**
- **Runner:** a dedicated GitHub Actions runner/job identity used only for this capture. It has no repo write token beyond appending anchor heads, and no access to betting or pricing secrets.
- **Storage:** an object bucket with retention lock (WORM/compliance mode, fixed retention period).
  - **Write role:** `PutObject` only, no delete or overwrite, used by the capture job.
  - **Read role:** `GetObject`/`List` only, used by analysis.
  - The two roles are separate credentials. Neither can change retention settings.
- **External anchor:** the chain head after each run goes to a separate append-only location (a different bucket prefix with its own lock, or an issue comment) that the write role cannot modify.
- **Clock:** the runner records its NTP source and offset in each run header.
- **Not done:** no provisioning, no automated downloads, no scheduler or workflow file. Turning any of this on needs an explicit owner decision.

**Terms note:** the NBA's terms of use restrict use related to gambling, and **permission for this use is UNVERIFIED**. Every record carries `permission="UNVERIFIED_NBA_TERMS_RESTRICT_GAMBLING_USE"`. No capture may run until the owner confirms permission in writing (or rejects the source).

This build is not evaluative, so it has no pre-registration. Any later evaluation using captured reports must be pre-registered first.
