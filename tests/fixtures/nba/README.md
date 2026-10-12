# NBA recorded fixtures — provenance

All fixtures in this directory are **recorded live ESPN responses** captured
2026-10-11 (America/Chicago), trimmed to small structurally-faithful subsets.
Trimming removed only whole events/athletes; no field was edited or invented.

| file | source | recorded |
|---|---|---|
| `scoreboard_20241023.json` | `site.api.espn.com/.../basketball/nba/scoreboard?dates=20241023` — 3 of the 10 real 2024-25 opening-night games (IND@DET, BKN@ATL, ORL@MIA), kept whole | 2026-10-11 |
| `gamelog_1966_2025.json` | `site.web.api.espn.com/apis/common/v3/sports/basketball/nba/athletes/1966/gamelog?season=2025` — athlete 1966, full `names`/`labels`, 3 real 2024-25 regular-season games (eventIds 401704684, 401704677, 401704662) | 2026-10-11 |
| `roster_lal_2026.json` | `site.api.espn.com/.../basketball/nba/teams/13/roster` — team identity + 5 real athletes incl. Bronny James (4683774); LeBron James (1966) is **not** on the 2026-27 preseason roster | 2026-10-11 |
| `search_lebron_james.json` | `site.web.api.espn.com/apis/search/v2?query=LeBron James` — real hit; note the `subtitle` team label ("Philadelphia 76ers") was already stale, which is why roster verification is required | 2026-10-11 |
| `teams_registry.json` | `site.api.espn.com/.../basketball/nba/teams` — all 30 teams reduced to id/abbreviation/displayName | 2026-10-11 |
| `summary_401704629.json` | `site.api.espn.com/.../basketball/nba/summary?event=401704629` — trimmed to header quarter linescores (IND@DET: DET quarters 31/27/32/19, IND 25/24/33/33, reconciled to 109-115) + one player group sample | 2026-10-11 |

Unit tests inject these via a fake `getter` and never touch the network.
