# Five-sport pull / context / model inventory

Locked from the user spec. Nothing moves CONTEXT → MODEL without a pre-registered
holdout, one look per window.

DK prices stay manual (screenshot or paste). No paid odds API.

Labels:
- **PULL** = fetch on every `run it` when the source answers
- **CONTEXT** = printed on the card, does not change model_p
- **MODEL** = already in a frozen engine, or next candidate with a named window
- **BLOCKED** = source missing, ToS/cloud-block, or holdout failed

Checked 2026-09-29 from this environment:
StatsAPI, Savant, NWS, NHL official, MoneyPuck index, nflverse games = reachable.
`stats.nba.com` timed out (known cloud block).

## MLB

| Item | Source | Now |
|---|---|---|
| Probable starters, saved before first pitch | StatsAPI + PIT archive from Sep 13 | PULL / MODEL identity; v2 residual not promoted |
| Confirmed lineup + order | StatsAPI / lineup archive | PULL; MODEL for props only after #1243 |
| Team + player logs | StatsAPI box / Savant | PULL / MODEL team means |
| Pitch-level Statcast | Savant | PULL / CONTEXT (HR tags later) |
| Bullpen last 1–3 days | recent boxscores | PULL / CONTEXT |
| HP umpire | StatsAPI officials (often empty the night before) | PULL / CONTEXT |
| Park, roof | venue + schedule | PULL; park in engine, roof CONTEXT |
| Weather / wind | NWS + StatsAPI weather | PULL / CONTEXT |
| Injuries / roster moves | StatsAPI (injuries endpoint 404 tonight) | PULL when it exists; scratch forces rerun |
| Team runs offense vs opponent prevention | V7 | MODEL live |
| Starter K/BB/HR residual | starter v2 | MODEL pending promotion (bootstrap straddled 0) |
| PA by lineup spot, pitcher K vs lineup, leash, platoon | engines exist | MODEL after #1243 holdout |

## NFL

| Item | Source | Now |
|---|---|---|
| PBP, snaps, usage, rosters | nflverse | PULL |
| Official injury + inactives | nflverse / NFL.com | PULL / CONTEXT; missing player → that prop NO_MODEL |
| QB change | roster + you saying scratch | rerun |
| Weather / wind / rest / travel | NWS + schedule | PULL / CONTEXT |
| EPA / success, pass-rush split | nflverse PBP | next MODEL candidate, new window |
| Pace / PROE / QB adj | nflverse | next MODEL candidate |
| Score distribution 3/7/10/14 | Attempt 9 means + discrete v1 | **BLOCKED** — v1 failed 2025 push gate |
| Props: snap/route/target/air/rush/RZ share | nflverse | #1250 pre-lock only |

## CFB

| Item | Source | Now |
|---|---|---|
| PBP / efficiency / talent / returning / transfers | CFBD (free key, monthly cap), cfbfastR | PULL when key is present |
| Depth / QB status | CFBD / ESPN | PULL / CONTEXT |
| Weather, altitude, neutral, FBS vs FCS | NWS + schedule | PULL / CONTEXT; altitude notes already in-repo |
| Opponent-adjusted PPA/EPA, havoc | CFBD | MODEL frozen only after a new unused window — current freeze is UNFROZEN |
| Phone card | `[CFB LINES]` | NO_MODEL:CFB_UNFROZEN (#1251) |

## NHL

| Item | Source | Now |
|---|---|---|
| Schedule, rosters, PBP, shots | api-web.nhle.com | PULL |
| Starting goalie | NHL box / roster; Daily Faceoff is a public page, not a locked API | PULL official first; Faceoff is CONTEXT only |
| Lines / PP units | official + public pages | CONTEXT until a holdout |
| xG team/player | MoneyPuck free files (index reachable) | CONTEXT; rate v1 used GF/GA/SOG stand-in and **passed** 2025–26 |
| TOI, B2B, travel | schedule + box | PULL / CONTEXT (rest is already a small rate feature) |
| Injuries | official roster | PULL / CONTEXT |
| Goals model + OT/SO | shared NHL sim | MODEL ready after promotion of #1249 |
| Shot/goal/point props | TOI × SOG/60, xG share | NO_MODEL |

## NBA

| Item | Source | Now |
|---|---|---|
| Official injury + late scratch | NBA.com / ESPN | PULL ESPN/hoopR; stats.nba.com often blocks CI |
| Starters / minutes / rotations | hoopR / sportsdataverse | PULL |
| Pace, usage, B2B, travel | same | PULL |
| Pace + opponent-adjusted ratings | in-tree NBA engine | MODEL after freeze + one holdout |
| Lineup net ratings | lineup data | CONTEXT until holdout |
| Props: minutes × rates, usage redistrib on sit | | NO_MODEL until usage freeze |
| Phone card | `[NBA LINES]` | NO_MODEL:FROZEN_OWNER_MISSING (#1251) |

## Public-repo ideas worth stealing (method, not numbers)

- nflverse + cfbfastR + hoopR: PIT-safe season dumps, not live scrape spaghetti
- MoneyPuck: published xG CSVs instead of inventing shot quality
- Savant: pitch/batted-ball grain already used by the HR outline
- Do **not** copy another site's Model% / Edge% / grades

## Promotion rule (unchanged)

One agent, one branch. Research PRs do not edit live engine files.
Promotion owns the re-freeze, dual clock, and a tight parity test.
