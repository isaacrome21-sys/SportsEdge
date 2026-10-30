# Challenger OT and independent-seed protocol — 2026-09-20

Research-only mechanics amendment, recorded before the new distribution outputs.
Prior same-seed results remain in NFL_CHALLENGER_IMPLEMENTATION_CHECKS_20260920.md.
No historical game data or holdout is read; zero holdout attempts consumed.

## Independent fixtures

All comparisons retain the frozen 200,000 paths and tolerances. Reference/vector
seeds are distinct; the only retry is one shared 1,000,000-path run for failing
exact-3/7 mass metrics, using reference seed +10000 and vector seed +20000.
No other failed metric is retried. Original metrics and retry metrics are retained
in JSON when SPORTSEDGE_EQ_REPORT_DIR is set, and printed in every run.

| Fixture | Season rule only | Reference seed | Vector seed |
| --- | --- | --- | --- |
| Near-even/high-OT/safety | 2026 | 4101 | 5101 |
| Lopsided home | 2026 | 4201 | 5201 |
| Lopsided away | 2026 | 4301 | 5301 |
| Near-even/high-OT/safety | 2016 | 4401 | 5401 |
| Near-even/high-OT/safety | 2024 | 4501 | 5501 |

A season parameter selects rules only. These fixtures contain no games, labels,
empirical holdout moments, fitted parameters, or prospective evidence.

## Regular-season overtime

The isolated challenger selects 2016 (900 seconds, opening TD wins), 2017–2024
(600 seconds, opening TD wins), or 2025–2026 (600 seconds, both opportunities
subject to expiry). Unsupported years fail closed. No postseason support is claimed.

The 2017 clock reduction is corroborated by the NFL's May 23, 2017 search-index
summary, titled “NFL owners approve shortening overtime to 10 minutes”; its old
article URL currently fails to resolve. Historical full-rulebook source-byte
freezing remains incomplete, so this mapping does not satisfy the historical
source-hash gate by itself.

Current rules: [NFL 2026 Rulebook, Rule 16](https://static.www.nfl.com/image/upload/fl_attachment/league/tqivdkzt9mu6wdgsh1ku.pdf).
The [NFL 2025 rule-change summary](https://operations.nfl.com/rules-officiating/featured-rules)
confirms the new possession provision. The source URLs are references, not an
assertion of a completed immutable historical source archive.

Both implementations now consume OT drive clock time, allow expiry to end a tie
or leave a leader, permit an answering possession where required, end on a safety,
and omit a try after a TD already wins. The former arbitrary twelve-drive cap is
removed. Scripted oracle tests cover each represented regime and score/clock edge
case independently of stochastic distribution comparisons.

## Scope limits

Drive duration is a coarse model: a drive whose sampled duration exceeds remaining
time is censored with no score. A drive finishing exactly at zero may score.
This does not model a play snapped before zero and ending afterward, timeout policy,
penalty extensions, kickoff outcomes, defensive/return TDs, or field position.
Regulation expiry behavior remains as previously implemented. Final-regulation
scoring edge cases and full historical kickoff/OT rule-source binding still block
a full structural-readiness claim. The production 2026 model is unchanged.
