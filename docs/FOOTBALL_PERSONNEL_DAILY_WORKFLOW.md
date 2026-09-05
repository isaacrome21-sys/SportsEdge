# SportsEdge Football Personnel Daily Workflow

Applies to CFB and NFL RUN IT.

## Daily sequence
1. **QB status** — official team report first; then PFF/SIS/SIC/NGS context where available.
2. **OL/DL depth** — official two-deep plus PFF, CFBDepth and TWO·DEEP; capture starters, backups, continuity, portal losses/additions and trench replacement quality.
3. **Snap / usage movement** — week-over-week snap share, route participation, target/carry share, red-zone/two-minute usage and alignment; flag material changes rather than raw counts.
4. **Secondary availability** — CB/S depth, coverage role, snap share, injury/eligibility and replacement quality.
5. **Unit mismatches** — quantify trench, coverage and skill-position mismatches using unit grades/metrics; separate quantitative mismatch evidence from editorial opinions.
6. **Freshness check** — every material item gets source timestamp/observation time; stale or conflicting data becomes DATA_GAP.
7. **Decision integration** — context may reopen or downgrade a frozen card only under an allowed material trigger. It may not create Model_P or promote a bet by agreement count.

## Preferred source hierarchy
### QB
- Official team/injury/availability report
- PFF
- Sports Info Solutions
- SIC Score
- Next Gen Stats / CBS returning-snap data as supporting context

### OL / DL
- Official depth charts
- PFF
- CFBDepth
- TWO·DEEP
- SIS / ESPN Analytics as supporting trench metrics

### Snap / usage
- PFF
- SIS
- RotoWire / Lineups.com for NFL supporting tables
- CBS returning-snap percentages for early-season CFB continuity

### Secondary
- Official depth chart / availability
- PFF
- CFBDepth
- TWO·DEEP
- SIS / SIC / Next Gen Stats coverage context

### Unit mismatch
- PFF unit grades/rankings
- SIS advanced unit metrics
- CFBDepth unit grades
- TWO·DEEP formation/matchup views
- Custom SportsEdge EPA/explosive/trench transforms when validated

## Materiality flags
- `QB_CHANGE`
- `QB_LIMITATION`
- `OL_STARTER_OUT`
- `OL_CONTINUITY_BREAK`
- `DL_PASS_RUSH_LOSS`
- `SECONDARY_STARTER_OUT`
- `USAGE_SPIKE`
- `USAGE_DROP`
- `PORTAL_DEPTH_CHANGE`
- `TRENCH_MISMATCH`
- `COVERAGE_MISMATCH`
- `DATA_CONFLICT`
- `DATA_STALE`
- `DATA_GAP`

## Suggested thresholds for review, not automatic betting decisions
These only trigger review; they never create an edge by themselves.
- QB starter change or expected snap limitation: always review.
- 2+ OL starter changes from expected unit: review.
- 2+ projected secondary starters unavailable: review.
- Skill-position snap share move >= 15 percentage points week over week: review.
- Route participation / target-share move >= 10 percentage points: review.
- Trench or coverage unit disagreement >= one full tier between source sets: review for source conflict.

## Output contract
For every serious candidate, surface only material items in compact form:
`TIME | GAME | FLAG | PLAYER/UNIT | CHANGE | SOURCE | FRESHNESS | MODEL_P=false`

Editorial/capper mismatch posts are commentary only and never a vote, confidence boost, or promotion input.
