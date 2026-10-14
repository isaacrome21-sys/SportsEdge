# NHL rate v1 — 2024–25 fit only

**Not validated. Do not price a card from this artifact.**
2025–26 REG is reserved and has not been scored.

Source: official `api-web.nhle.com/v1/score`, gameType=2, completed games with score + SOG.

| | |
|---|---:|
| Completed REG games | 1310 |
| Skipped (<10 prior games) | 169 |
| Training rows (home+away) | 2282 |

Log-goals ridge (ridge=1.0) coefficients:

| Slot | Stand-in | Coef |
|---|---|---:|
| intercept | | 0.756 |
| offense_xg | prior GF/60 | 0.077 |
| opponent_xga | opp prior GA/60 | 0.146 |
| shot_share | prior SF / (SF+opp SA) | −0.905 |
| special_teams | 0 | 0 |
| goalie_gsax | 0 | 0 |
| rest | days since last game | 0.020 |
| travel | 0 | 0 |
| lineup | 0 | 0 |
| home_ice | 1/0 | 0.132 |

`shot_share` is large and negative because it is collinear with the goal rates. That is a fit-window diagnostic, not a reason to drop the slot after seeing coefficients. Leave the spec as locked; 2025–26 decides whether the whole vector is usable.

Next allowed action: score 2025–26 **once** against the gates in `nhl_rate_v1_prelock.md`. No retune.
