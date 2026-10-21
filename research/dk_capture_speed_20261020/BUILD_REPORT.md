# DK rendered-browser capture speed — offline diagnostic build report

**Starting main:** `d722da64cc984c4466bfb83457cc99d36f66c6e5`  
**Branch:** `feat/dk-browser-capture-speed-audit-20261020`  
**Status:** Research-only DRAFT / UNVERIFIED / **NO REAL CAPTURE MEASURED**.

## Purpose

Isolate why multi-market DraftKings rendered-browser capture can exceed SportsEdge's fixed freshness limits *without changing the capture rules or avoiding the site's access controls*. The utility consumes sanitized monotonic timing receipts, one or more fixtures, and reports only measured stage seconds, dominant cost, per-stage p90, full capture span against **150s** target, quote age at finish against **180s** hard bound, and quote-pair span against **150s** target. A final re-read must follow the quote observation. Missing capture boundaries, source receipt hash, quote-pair span and inconsistent stage boundaries refuse. Captcha and provider-throttle events are operator-required named flags; **no bypass or retries**. It does not open pages, load screenshots, store actual selections/lines, claim a verified quote, or change any policy.

## Exact changes

* `sportsedge/dk_browser_capture_speed_diag.py` — blob `2cbfe23fc691007fb6f3726adf55c9a79c9da709`.
* `tests/test_dk_browser_capture_speed.py` — blob `951f837671138734e71ec99304696ab934aee83e`.
* No workflow, runner, browser automation, source ingestion, evidence writer, pricing, gate, registry, main ledger, or frozen document changed.

## Input contract

One sanitized local JSON envelope:

```json
{
  "version": "DK_CAPTURE_SPEED_DIAG_V1",
  "events": [
    {"fixture_id":"NFL-example","event":"capture_started","timestamp_utc":"2026-10-21T18:00:00Z"},
    {"fixture_id":"NFL-example","event":"quote_pair_captured","timestamp_utc":"2026-10-21T18:01:00Z","pair_span_seconds":12,"quote_receipt_hash":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"},
    {"fixture_id":"NFL-example","event":"final_quote_re_read","timestamp_utc":"2026-10-21T18:01:10Z"},
    {"fixture_id":"NFL-example","event":"capture_finished","timestamp_utc":"2026-10-21T18:01:20Z"}
  ]
}
```

Optional stage begin/end events use named `navigate`, `render_wait`, `market_expand`, `quote_transcription`, `pairing`, `final_re_read`, `receipt_write`; throttle/captcha events are bare markers. Unlisted fields such as URL, API key, cookie, raw page, screenshot, auth and IP are REJECTED rather than retained. Fixture IDs are hashed in output. This is instrumentation input, **not** a substitute for the immutable quote receipt.

```bash
python -m sportsedge.dk_browser_capture_speed_diag \
  --timing-json sanitized_capture_timing.json \
  --output-json local_speed_report.json
```

## Verification state and owner handoff

9 pytest functions with parameterized sensitive-field checks authored; no independent green claim at authoring time. Synthetic tests cover duration boundary, stale, pair span, missing final reread, captcha, throttle, dominant stage, multi-fixture aggregation and sensitive-data exclusion.

The provider/browser runtime is not available to the builder, so **zero actual DK latency measurements** are claimed; no optimization speedup is asserted. Rocky owns Thursday's captures and may later feed pre-approved sanitized durations from the real browser. Measure and diagnose first, then owner approves any code/flow change via independent PR. Do not merge unless verifier confirms safe record shape, no secret leakage and baseline test failure-set equivalence. Existing freshness/receipt holds remain.

## Governed code-surface correction — 2026-10-20
Proactively moved the identical diagnostic source bytes from newly added `scripts/` path to `sportsedge/dk_browser_capture_speed_diag.py`, updated the synthetic test import and CLI syntax, and deleted the former unmapped script. Reason: #2436 demonstrated the freeze-inventory guard treats new standalone `scripts/` additions as governance-unmapped, while new modules under the existing `sportsedge/` package passed. This is NOT an exemption or a change to frozen rules. Fresh CI must verify this head; no green is assumed.
