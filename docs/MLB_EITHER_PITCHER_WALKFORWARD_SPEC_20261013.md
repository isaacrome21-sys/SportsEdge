# Either-Pitcher ladder walk-forward: specification (fixed before running)

Committed before any data was fetched or evaluated. This is a pre-registered specification. It is named `*_SPEC` so it does not add a second unmapped governance path while the mapping for the F5 dispersion doc is pending ChatGPT guidance on #2156. ChatGPT may re-home it once the mapping guidance lands. Research only. The market baseline is MISSING. Settlement is UNVERIFIED_DK_RULES.

## Data (free MLB Stats API, cached outside the repo)
- `schedule?sportId=1&gameType=R&hydrate=probablePitcher,linescore`, one call per month, 2024-2025.
- `people/{id}/stats?stats=gameLog&group=pitching&season=YYYY` for every listed probable pitcher.

## Events
- Regular-season FINAL games where **both** listed probable pitchers have a start (`gamesStarted=1`) in that game's gamePk.
- Games where a probable pitcher did not start are excluded. That is a void/action question for DK rules, which are unverified.
- Proposition: max(away starter stat, home starter stat) > line.

## Lines (fixed)
- HITS_ALLOWED: 5.5, 6.5, 7.5
- BB: 2.5, 3.5
- ER: 2.5, 3.5

## Point in time
- Cutoff = the slate's earliest first pitch.
- A start is usable only if its game is FINAL and available by the cutoff (start + 6h), with its start time known from the schedule cache.

## Candidate (no free parameters)
- Per-pitcher PMF from his last 15 usable starts, smoothed toward the as-of league start PMF with strength 10.
- Requires at least 5 usable starts per pitcher, and at least 50 league starts for the prior.
- Ladder = `either_pitcher_ladder` (independent pitchers).

## Baseline (naive, league-only)
The same ladder with both pitchers set to the as-of league PMF. It isolates pitcher-specific information.

## Metrics
- Brier and log-loss (clip 1e-6), per market and line, reported for 2024 and 2025 separately.
- The league prior resets at each season start (only that season's games train), matching the F5 work.

## Decision rule (fixed)
- **PASS_RESEARCH** for a market iff on **2025** the candidate's Brier < naive **and** log-loss < naive at every line of that market. Otherwise FAIL.
- No tuning after viewing results. No promotion, no eligibility change.
