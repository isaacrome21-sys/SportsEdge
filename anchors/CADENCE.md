# Anchor cadence registration

Cadence: **daily roll-up** -- each active system's current head
is anchored once per capture day, and additionally at any cohort
boundary (activation day, freeze change). The rewrite window an
anchor leaves open equals the cadence interval; daily bounds it
to at most 24 hours of captures.

Writer: the records-branch publisher
(`sportsedge/mlb_receipt_anchor_publisher.py`) through the
established push-driver path; each publication surfaces the
driver's runtime approval card.

Missed-window rule: if a day's anchor is late or skipped, the
gap is visible in the series' dates and is recovered by
publishing at the next window with its true (later) receipt
time. **Never backfill a fabricated earlier receipt.** Records
in the gap are bounded only by the next anchor.

Host downtime defers publication; preparation is local and
queues. Captures never wait on publication: a failed or skipped
anchor degrades the evidence bound, never the capture.
