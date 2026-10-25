# Overnight NFL evaluation intake, interim

The source audit finds real schedule rows and paired price fields in a saved nflverse schedule snapshot. Counts and hashes are in input_audit.json. This is not a completed NFL backtest, and no NFL forecast performance is claimed.

Remaining work: verify source closing-price provenance, run current sides/totals and props models with strictly pre-kickoff features and season walk-forward, audit the even-probability compression, and report requested metrics against actual paired closes. Do not use a historical model artifact trained on a target season as an out-of-sample prediction. No logged entry snapshots are present in the schedule CSV, so mean CLV/entry-price ROI must remain unavailable unless real entry evidence is found. Props need their own closing quote archive.

Results are due on #2447 by Oct 25, 9 AM CT. Missing evidence means INSUFFICIENT_DATA. No inferred -110 prices, fabricated model probabilities, model/threshold/promotion changes, or merges.
