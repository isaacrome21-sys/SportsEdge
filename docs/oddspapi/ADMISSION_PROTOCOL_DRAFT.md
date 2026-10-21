# OddsPapi historical source admission protocol - A-E thresholds (DRAFT TRANSCRIPTION)

Origin: Rocky/Muse, October 20, 2026, SportsEdge issue #2447, comment 6308060982.
Source-integrity warning: the exact original Rocky workspace ADMISSION_PROTOCOL_DRAFT.md file and original SHA-256 were not accessible to this lane. This is an in-repository transcription of the stated bars, NOT a certified byte-identical copy of the original workspace document.

## Governing decision
Admission is automatic upon proof under the pre-set bars, separately by sport x market x bookmaker. Passing an offline or synthetic instrument does not admit historical quotes.

## Check A - our DraftKings captures
- Matched quote within +/-30 minutes of our own DraftKings capture.
- Line exactly equal; American price difference <=10.
- At least 95% of sampled pairs pass these line and price conditions.
- 100% of matched quotes must be time-locatable within the allowed window.
- Zero post-start quotes may be reported as pregame.

## Check B - SBR NBA archive
- Stratified >=200 games across >=4 seasons, plus a final-week set of the most recent completed season.
- Moneyline American price difference <=10 for >=97% of the sample.
- Spread/total exact line agreement >=95%.
- Spread/total absolute line difference <=0.5 on >=99% of the sample.
- ZERO games with spread/total absolute line difference >1.0.
- Book identity explicit; unidentifiable bookmaker counts as failure, never a skip.
- Missing closing quotes count as failures in the denominators.

## Check C - MLB reproducibility and archive
- Exactly reproduce ALCS Game 6: Tampa Bay moneyline -158, Cleveland moneyline +130, Tampa Bay run line -1.5, with timestamp confirmed before actual first pitch.
- A separate stratified SBR MLB sample of >=200 games must meet Check B bars.

## Check D - timestamp semantics
- 100% of closes strictly before actual start.
- >=95% of closes in [actual start - 6 hours, actual start).
- A single consistent timezone offset across the 10 tightest Check A pairs.
- No impossible quotes.

## Check E - coverage
- Matrix per sport x market x bookmaker cell.
- >=90% coverage for each sampled window.
- Unsampled cells explicitly NO_DATA.

## Scope and evidence status
This is a documentation-only transcription from https://github.com/isaacrome21-sys/SportsEdge/issues/2447#issuecomment-6308060982. No threshold has been deliberately changed. No historical-source ADMITTED outcome, automatic ingestion, new model eligibility, or PLAY authority is claimed. The hash associated with this file describes this transcription only; original-workspace exact-file verification remains outstanding.
