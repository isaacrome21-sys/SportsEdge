# Grok builder playbook

Single writer: this Grok. Still one step per run. Still `grok/<area>/<topic>` only
for new pushes. Never merge, force-push, or delete.

## Rules (paste at end of every automation)

- Repo: isaacrome21-sys/SportsEdge. Only push to branches named grok/<area>/<topic>.
  Never push to other branches, never merge, never force-push, never delete branches,
  files on the data branch, or tests. Open PRs for the owner to review.
- First list open PRs/branches for this area. If a live branch already owns the next
  step, skip it and report (do not double-write).
- ONE step per run. Leave the branch in a working state.
- Research/audit code never edits production engine files. Promotion is its own PR:
  re-freezes the model surface on purpose, closes old evidence clocks and opens new
  ones (never mixed), and adds a research-vs-production parity test (~1 pt).
- Every tuning or validation window is written down in the repo BEFORE scoring and
  used once. A failed candidate needs a new window.
- Never loosen or delete a failing test; find the cause. Core CI (test,
  pytest-discovery, frozen-full-pipeline) must be green before asking for merge.
- Free data only. Time-stamp every pull. Label data model / context / grading.
  Context never enters the model without passing a held-out test.
- Cards: MySpariEdge-style, NOT Truth Gate / NOT OFFICIAL. Never make images or
  numbers that didn't come from engine output. Anything unpriceable = NO_MODEL.
- End every run with a report under 10 lines: what you did, PR link, numbers,
  what's next, anything blocked.

## Already open (do not fork these; owner reviews)

| PR | Branch | Area |
|---|---|---|
| #1253 | promote/nhl-rate-v1 | NHL promotion |
| #1249 | research/nhl-rate-v1 | NHL fit+validate PASS |
| #1247 | research/nfl-discrete-score-v1 | NFL discrete FAIL 2025 |
| #1250 | research/nfl-prop-usage-v1 | NFL props pre-lock |
| #1251 | phone/nba-cfb-failclosed | NBA/CFB phone doors |
| #1252 | research/five-sport-pull-inventory | inventory + finish line |
| #1242 | research/mlb-starter-vs-defense-heldout | MLB starter |
| #1243 | research/mlb-prop-heldout-calibration | MLB props |

New work goes on `grok/*` only.

## First unfinished step per builder (2026-09-29)

- MLB: starter v2 bootstrap already run; 95% CI straddled 0. Next is F5 card wiring on `grok/mlb/f5-card` after owner decides no-promote on starters.
- NFL: #1244 is on main. Discrete v1 failed 2025. Next spec uses 2026 weeks not yet played (W4+), not a second look at 2025.
- NHL: holdout passed; promotion is #1253. Next after merge: goalie required-input on `grok/nhl/goalie-gate`.
- NBA: phone door is #1251. Next: prove hoopR/ESPN pull from Actions on `grok/nba/source-probe`.
- CFB: still paused. Next: #1070 close-vs-snapshot proof only.
