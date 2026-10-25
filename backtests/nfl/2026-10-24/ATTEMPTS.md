# NFL attempt log

1. Input audit only, preserved in input_audit.json (7,548 source rows / 7,368 completed).
2. Frozen Attempt9 replay, executed Oct 25: run_frozen_diagnostic.py -> attempt2_frozen_diagnostic.json. Existing weights/calibration unchanged; sequential 2020–2026 season reports, with 2026 partial. Fixed historical fit is NOT an expanding-season refit or a newly sealed holdout. Data vintage is retrospective; no archived pregame feature availability asserted. Same-date outcomes are excluded by the reused feature routine.

Reproduce: `python backtests/nfl/2026-10-24/run_frozen_diagnostic.py --csv INPUT.csv --output OUTPUT.json`.

2025: 285 games; margin MAE 10.13795, total MAE 10.69427. Among 214 noninteger spread thresholds, 97.6636% of calibrated probabilities are within 45–55%; mean distance from 0.5 shrinks from raw 0.08477 to calibrated 0.01869. Total probabilities: 95.0877% in 45–55% on 285 thresholds. Spread probabilities are research diagnostics, not card eligibility or promotion.

CRITICAL SCOPE: #2384 concerns free_models.py's composite/base-22 side path, NOT Attempt9. These results do not reproduce or resolve that issue. Composite replay and required prior-season refit evaluation remain pending. Moneyline is unsupported by Attempt9's no-tie-mass contract; no proxy supplied.

Muse's #2606 reports a one-week September 2026 props export with consensus fair and best Over price, not a paired same-book multi-season close archive. This does not support season walk-forward props validation. Missing paired closing provenance and logged entry receipts keep all market verdicts INSUFFICIENT_DATA and CLV/ROI/EV selection counts null. No guessed -110 or fabricated timestamps.
