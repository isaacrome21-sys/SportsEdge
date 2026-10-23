# DK market-family inventory — Grok lane, Oct 22 2026 (main 334cda5e)

Sources: config/dk_inspected_menu_census_v1.json (MLB/NFL/CFB only — NBA/CBB/NHL
have NO census in repo; rows below for those sports are from public knowledge of
DK menus, marked PK), sportsedge/canonical_coverage.py, family registries, Rocky
handoff Oct 22. Zero families validated. Engine: none / research / merged.

## MLB (census: 64 keys)
| Family | Engine | Registration | Prereg/freeze | Clock | Blocker |
|---|---|---|---|---|---|
| ML / RL / total / team total | merged (FREE_MODELS Lane A) | — | — | closed | Lane A RETIRED (Brier .2479 vs mkt .2363); no construction commissioned |
| F5 ML/RL/total/TT | merged (SHARED_F5) | — | — | none | F5 eligible=false |
| First 3 / First 7 | research (period binding) | none | none | none | no registration |
| NRFI/YRFI, inning-1 | merged | — | — | none | NO_VALIDATION |
| Innings 2–9, inning-1 props (K, pitches, HR, hits) | none | none | none | none | NO_ENGINE (PA engine pool is Rocky's lane) |
| Game/team total hits | merged research | — | — | none | Total Hits step 5 verification (Rocky) |
| Pitcher K | merged | protocol | frozen | running 4/150 graded | sample; WS intake Oct 23 |
| Pitcher outs/H/ER/BB | merged | research | benchmark v2 prereg | not started | MLB month-file owner ruling |
| Pitcher pitches | research | RESEARCH_ONLY | none | none | — |
| Either-pitcher K/outs/pitches | none | none | none | none | NO_ENGINE; others: marginal-tail error |
| Batter H/TB/R/RBI/HR/BB/K/1B/2B/3B/XBH/HRR | merged (empirical) | research | benchmark v2 | not started | owner ruling (month files) |
| Batter SB combos, first-PA | none | none | none | none | NO_ENGINE / NO_QUOTE |
| Exotics (race, BTTS, grand slam, extras, margin, correct score) | research gates | none | none | none | NO_VALIDATION |
| Statcast / factors / umpire | collection only | — | — | — | PENDING_VALIDATION, zero pricing impact |

## NFL (census: 65 keys)
| Family | Engine | Registration | Prereg/freeze | Clock | Blocker |
|---|---|---|---|---|---|
| Pass/rush/rec yds, receptions | Part 2 evaluator | registered research | frozen #2396 (v1.1 moved-line amendment pending) | running, slate 1 | 4 slates/40 games; yardage = Part 2 only |
| Rush att, pass att, completions (+pass TDs shadow) | Part 2B | registered | frozen #2415 | running | same |
| Anytime TD | research, UNMERGED cae825534 | registered | rules #2399 | not started | engine freeze/merge |
| 2+ TD, targets, FG/XP/kicking pts, sacks, tackles, def INT, pass+rush, rush+rec | merged research (NFL_PROP_ENGINES_V1) | registered research | none | none | 2+TD screen DOES_NOT_BEAT_BASELINE; no prereg |
| Longest completion/rush/reception | merged research (longest plays) | registered | none | none | GOVERNANCE_NO_ENGINE; no prereg |
| **Longest FG made** | **research — built tonight (grok branch)** | RESEARCH_UNSCREENED (grok proposal) | none | none | settlement of no-make case unverified; owner registration |
| 3+ TD, last TD, period TD, TD exacta, first TD | none | none | none | none | first TD NO_DATA; others NO_ENGINE |
| QB INT (offense) | Part 2B scope-out | — | — | — | owner ruled OUT |
| Q1/1H player splits, QB H2H, most rec yds | none | none | none | none | NO_ENGINE; yardage stays owner's (#2305) |
| Sides ML/spread | merged | — | — | CLOSED | Elo v1 + Challenger DOES_NOT_BEAT_CLOSE |
| Total | Totals LEVEL v2 | — | SCREEN_PASSED | forward to Jan 13 2027 | time |
| Halves/quarters/period TT | derivative wired | none | none | none | prices sim only; no calibrated period engine |
| Team TDs, total TDs, safety, BTTS, race, margin, largest lead, first score, HT/FT | none | none | none | none | NO_ENGINE |

## CFB (census: 7 tabs)
| ML/spread/total | merged | REGISTERED_RESEARCH_ONLY (#2416) | Attempt 1 unspent | HOLD | Path A/B ruling |
| Props, team totals, halves, quarters, exotics | partial / none | BLOCKED | — | — | owner-blocked; Illinois college excluded |

## NBA (no census; PK)
| PTS/REB/AST/PRA | merged | V1 | frozen #2424 | running, 0 countable rows | in-season history store (#2484 probe) |
| 3PM/STL/BLK/TOV/stocks/DD/TD/milestones | merged #2442 | RESEARCH_UNSCREENED | none | none | screen on accumulating captures |
| P+R, P+A, R+A combos (PK) | not separately confirmed | none | none | none | derivable from V1 engine; needs registration |
| Team totals, quarter/half totals | merged #2422 | UNREGISTERED | none | none | owner registration ruling |
| ML/spread/total | merged | FAILED_VALIDATION | — | diagnostics only | new construction = owner |
| First basket, quarter ML/spread, race, player H2H (PK) | none | none | none | none | NO_ENGINE; no admitted PBP-order source |

## CBB (no census; PK)
| ML/spread/total, team totals, halves, player props | none (Torvik candidate) | none | none | none | capture starts Nov 1; source admission; Illinois teams excluded |

## NHL (no census; PK)
| ML/puck line/total, SOG, points, goals, saves, periods | research modules merged (sports/nhl) | attempt-1 no-edge stands | none | none | MoneyPuck/HR admission ruling pending (attempt 2) |
