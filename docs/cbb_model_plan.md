# CBB (men's college basketball) model foundation plan (research only)

Owner lane: Grok. Base: main `ac598d708`. DESIGN ONLY: no pricing, eligibility, promotion, staking or workflow changes.
Shared pricing/catalog/card/routing changes require ChatGPT integration review.

## 1. Inventory on main
- **No CBB modeling code exists.** Only a mention in `sportsedge/social_analytics_sources.py`. `artifacts/free_models.py` has no CBB sport key; CBB is not in the #2136 ledger (`SPORTS = {MLB, NFL, CFB}`).
- Reusable: NBA possession/pace/efficiency components (`sportsedge/sports/nba/pace_efficiency.py`, `possession_history.py`, `periods.py`), ESPN verified-source patterns, CFB school-identity matching (#2087) and `IL_COLLEGE_NAMES` exclusion list in `artifacts/free_models.py`.

## 2. DK market families observed
**All CBB DK families are UNKNOWN (not inspected).** No CBB DK capture exists in the repo ledgers. Nothing may be labeled offered or priced until a reviewed DK CBB board capture lands.

## 3. Free data sources (no paid historical odds)
- ESPN public mens-college-basketball scoreboard/summary/boxscore (scores, halves, player box, limited injuries).
- Public team schedule/results for tempo/efficiency estimation computed in-house (no paid ratings feeds).
- Historical market baseline: **none identified**. Market leg stays MISSING until a verified free close source exists; no promotion without it.

## 4. Team model
- PIT adjusted offensive/defensive efficiency per 100 possessions and tempo, opponent-adjusted via iterative ridge on games strictly before as-of; strong shrinkage early season and for low-sample teams (~360 D-I teams; non-D-I opponents flagged and down-weighted).
- Home court, neutral-site flag (verified from fixture), no rest/travel adjustment (**disabled, zero**, same ruling as NBA `rest_adj`).
- Identity: exact school matching with cross-school collision guards (Florida vs Florida Atlantic class of bugs).

## 5. Player model
- Initially out of scope for pricing: availability data is sparse and unverified for CBB. Player props stay BLOCKED (`NO_VERIFIED_CBB_AVAILABILITY_SOURCE`) until a PIT availability source is verified.
- Minutes/role model reuses the NBA design (40-minute constraint) once availability exists.

## 6. Joint score distribution
- One path model of per-half team points (CBB plays halves); full game, spread, ML, totals, team totals and 1H/2H from the same paths. OT 5-minute periods for regulation ties; integer push mass preserved. No full-game scaling to halves.

## 7. Validation plan
- Chronological walk-forward by date, leakage-safe PIT features; prior-season data only for priors.
- Metrics: log loss, Brier, calibration, margin/total CRPS vs naive and vs market close where verified; failed families NOT_WIRED_WITH_REASON.
- No sealed-holdout access, no attempt resets.

## 8. Playable exclusions
- **Illinois college teams are excluded from playable output** (reuse `IL_COLLEGE_NAMES`; extend for CBB-only programs, e.g. Chicago State, Loyola Chicago, DePaul, Bradley, SIU, SIUE, Eastern/Western Illinois, UIC, Illinois State, Northern Illinois). Must be enforced at intake with mascot-qualified names, and regression-tested.
- Price cap -165 for straight bets applies as elsewhere.

## 9. Build order
1. CBB sport key + ESPN fixture/identity binding with Illinois exclusion (needs ChatGPT review: shared routing).
2. PIT tempo/efficiency ratings + harness on game ML/spread/total.
3. Half-level joint paths; team totals and 1H.
4. Player props only after an availability source is verified.

## Decisions / missing sources
- DK CBB catalog capture needed.
- No free historical CBB closing-line source identified (market baseline MISSING).
- OWNER: confirm full Illinois exclusion list for CBB.
- Reuse note: no Muse CBB probe artifacts were found under /workspace at time of writing; credit them here if handed off.
