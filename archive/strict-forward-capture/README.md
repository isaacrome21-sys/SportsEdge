# Strict forward-capture archive

Append-only evidence store for the strict paired MLB out-of-sample
evaluator (`sportsedge/backtest/strict_paired_oos.py`). Built October 12,
2026 (Phase 7, first slice) because the historical record cannot supply
what the evaluator certifies: frozen production predictions with
point-in-time receipts plus verified two-sided quote pairs captured
shortly before first pitch. Those artifacts only exist if they are
captured live. This directory is that capture mechanism.

## Layout

```
captures/<fixture_id>__<market>__<selection>.json   one file per capture, write-once
settlements.jsonl                                   one appended line per settlement
```

The layout is data-branch ready: commit this directory to the `data`
branch (or keep it here) without restructuring.

## Rules

- Capture files are **immutable**. `write_capture` refuses to overwrite.
  A bad capture is superseded by operator decision at evaluation time,
  never edited after the fact.
- Settlements are **appended**, never edited. The first settlement for a
  key stands unless a later line carries `"correction": true`.
- A capture record holds every evaluator-required field except
  `outcome`, a `prediction` section (market-blind Lane A candidate with
  push-aware P(win)/P(push)/P(loss); the market-anchored Lane B
  probability labeled `MARKET_ANCHORED` when emitted — never as the
  candidate), and a `capture_provenance` envelope (production row
  verbatim, model identities, receipt bases, input hash). Each market
  (ML / run line / total) is an independent observation with its own
  matched quote pair.
- A settlement line carries an explicit `outcome_state` of `WIN` /
  `LOSS` / `PUSH`. A PUSH blocks that observation at assembly (reported,
  never graded): the strict evaluator is binary-only.
- Timing contract (from the evaluator, verified in code): both quotes
  from the same book, captured before first pitch, **<=120s apart**, and
  the latest quote **<=1800s (30 min) before first pitch**. Captures
  outside the window are archived truthfully and flagged in
  `compliance_warnings`; the evaluator will reject them.

## Operating procedure

1. In the closing window (30 min before first pitch), capture both sides
   of the market from one book with real timestamps.
2. Immediately run:
   `python scripts/capture_strict_mlb_record.py --input <input.json> --archive-dir archive/strict-forward-capture`
   (input schema `SPORTSEDGE_STRICT_CAPTURE_INPUT_V1`; see the script
   docstring). The script runs the frozen production pricer live — the
   prediction is generated at capture time, never backfilled.
3. After the game is Final:
   `python scripts/settle_strict_mlb_captures.py --archive-dir archive/strict-forward-capture`
4. Periodically:
   `python scripts/evaluate_strict_forward_capture.py --archive-dir archive/strict-forward-capture --output <readout.json>`
   Expect `BLOCKED_EVIDENCE` / `INSUFFICIENT_OOS` until the archive
   holds >=300 games across >=20 series with zero rejected rows. That is
   the bar working, not a defect.

v1 scope: moneyline captures (the in-repo comparison model, the Elo
floor, is ML-only; spread/total captures fail closed in the CLI rather
than archive a comparison probability that does not exist).
