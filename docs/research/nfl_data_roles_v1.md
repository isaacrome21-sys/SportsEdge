# NFL data roles (model / context / settle)

Nothing moves from context into the model until it passes a held-out test.
Every pull is timestamped and kept.

| Item | Role now | Notes |
|---|---|---|
| Schedule, start, venue | model | ESPN public scoreboard / nflverse games.csv |
| Final scores | model + settle | Strictly prior for features; after the game for settlement |
| Team game logs (PF/PA) | model | Attempt 9 owner |
| Prior-season games in the history stream | model | Frozen Attempt 9 rule for early weeks |
| DraftKings prices | settle / card only | Phone issue; never a feature |
| Closing line after the game | settle | Not a live feature |
| Official injury report / inactives | context | Not in Attempt 9 |
| Depth chart, snaps, targets, routes | context | Not in Attempt 9 |
| QB change | context → forces rerun or block when modeled | Not yet a model input |
| Weather (wind/temp/precip) | context | Not in Attempt 9 |
| Rest / travel | context | Not in Attempt 9 |
| Play-by-play / EPA | context | M2 research only; M2 is unfrozen |

Late official changes (QB, inactives) block or rerun the card. They do not
invent a substitute mean.
