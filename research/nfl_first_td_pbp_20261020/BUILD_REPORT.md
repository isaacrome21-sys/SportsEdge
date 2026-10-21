# NFL first-TD and longest-play evidence handoff

**Branch base main:** `d722da64cc984c4466bfb83457cc99d36f66c6e5`  
**Branch:** `feat/nfl-first-td-pbp-attribution-packet-20261020`  
**Status:** RESEARCH-ONLY DRAFT / UNVERIFIED / NO PREGAME MODEL / NO ODDS.

## Overlap audit

The previously merged **#2341** already added `sportsedge/nfl_longest_plays_empirical.py` with longest-play research distributions and merged **#2343** supplied strict source identity and measured-yardage evidence repairs. **Do not duplicate this existing engine** or replace its quarantined participation/missing-route gates. The separately open #1010 team-TD candidate code is held; no dependency or code change to #1010.

## Actual build

The missing first-TD settlement evidence layer, `sportsedge/nfl_first_td_pbp_evidence.py`, accepts a fully ordered after-game play-by-play record and returns the **explicit credited player and team on the first touchdown event**, or no TD if and only if a complete final PBP packet is asserted. It never guesses an NFL scorer from a pass's quarterback, longest play, team touchdown count, or final football score. All categories include defensive/return scores. Missing scorer identity, cross-game plays, out-of-order/missing sequence, incomplete event count, timestamp inconsistencies, uncertain event type and mismatched team source are named refusals.

**No prospectively admissible first-TD prediction yet.** A postgame settlement packet only defines the label. It does not create future player opportunity, participation, first-event ordering, source completeness certification, team-score path or player-specific calibrated probability. Those require a frozen PIT player/event history and market-paired screen; the builder may not imply those exist. Operator PBP-completeness flags and source SHA values are not independently verified until the source/archive admission gate runs.

## File identity (Git blob SHA-1)

* `sportsedge/nfl_first_td_pbp_evidence.py`: `4ac628b78813489bba518dfe3a69b23d4b586060`
* `tests/test_nfl_first_td_pbp_evidence.py`: `78f7af2a14e4c5816be01709ba956975014a2004`

Synthetic offline suite authored, not independent execution claimed; 5 pytest test functions including parameterized 11 hostile cases, receiver-vs-QB attribution and defensive-return case. No backend engine, odds intake, runner, gate, label, eligibility or frozen document modified. No historical test, EV/ROI/CLV, nor market-baseline verdict.

## What remains to finish the NFL packet

(1) Fetch and hash a complete PBP feed with official scoring-player attribution and observed-at time for every event; resolve official NFL stat corrections. (2) Join scorer identity to participation-active verified player IDs and ensure true-play ordering. (3) Predeclare and run chronological scorer-first baseline screen, independent of market lines; score *all outcomes*, including NO TD, defense/team scorers and candidates missing participation. (4) Admit paired first-TD odds or leave `NO_MARKET_TEST`. (5) Existing longest-play engine needs evidence-source audit and chronological screen; source completeness cannot be inferred from maximum play length alone. Same-game correlated exotics never graded as independent positions.

## Rocky verifier handoff

Review exact head, recompute first receiver vs passer and defensive-return scorer, inject missing official scorer, cross-game event, discontinuous PBP and postgame observed-before-final bad time. Confirm no pricing capability, no claim of verified settlement, and no changes to merged longest-play engine or its gates. Run neighboring tests and full-suite failure set comparison. Do not merge without independent green CI.
