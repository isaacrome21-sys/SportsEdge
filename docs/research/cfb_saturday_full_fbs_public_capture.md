# Saturday, October 10: full FBS-involving slate capture

The public multi-page DraftKings Network splits table contains scheduled October
10 FBS matchups beyond the limited Friday-era 14-game board. The full-slate
collector preserves all 46 scheduled games in an audit inventory and attempts
to parse paired **exact same-game, same-line, opposite-side** spread and total
public quotes from all five NCAA-football result pages, with hashes and fetch
timestamps. It does not extrapolate unavailable prices.

Three games involving Illinois college teams are excluded from SportsEdge
candidate scoring. Sacramento State–Bowling Green and North Dakota State–UNLV
are retained in the inventory but not passed to the native FBS-only model
because their FCS opponents may lack complete production snapshots.
Up to 41 remaining games can be priced and scored, subject to valid public
paired quotes and pregame data. If fewer than 30 game pairs are found,
**fail** rather than claim complete live coverage.

The `cfb-saturday-full-fbs-board` workflow runs isolated test and public-source
capture on pull request, then tries native SportsDataverse capture and the
existing no-bet CFB scorer when merged onto main. Audits, entire public board,
and scored JSON are archived for review.

**Important:** displayed DK Network prices combine jurisdictions. Web capture
time is not independent bookmaker quote-time attestation and cannot prove
Illinois-account availability. Equal or weighted market consensus, bookmaker
split percentages, implied odds or model dislocations alone do not establish
real positive EV. Current SDV probability quality remains unvalidated and the
directional totals issue remains a separate risk. No automatic wager, model
promotion, gate relaxation, or quote/score backfill.
