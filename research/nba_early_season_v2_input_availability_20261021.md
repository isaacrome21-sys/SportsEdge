# NBA early-season V2 input availability audit — 2026-10-21

Status: **BLOCKED_INPUT_CONTRACT** (research only; no market validation or
PLAY authority).

The repository's real NBA Results Pull workflow runs
`scripts/pull_nba_results.py`. Its artifact contains player ID/name, team
abbreviation, game ID, minutes, PTS/REB/AST, season and season-type ID. The
script explicitly says the upstream asset does not provide `GAME_DATE`.

The distinct #2464 V2 screen also requires a Chicago-local game date, actual
tipoff, a result-availability receipt after tipoff and before each later
decision, row source reference, and player position. Those fields are absent
from the current artifact contract. They must be joined from separately
pinned and verified sources; they must not be inferred from a game ID, file
name, workflow run time, or the fact that a static download exists today.

`python -m sportsedge.research.nba_early_season_input_audit_v1 --csv FILE`
now records that blocker as machine-readable output. Exit code 2 means the
input contract is incomplete. Exit code 0 means only that the required column
names exist; it does not authenticate their values, admit a source, validate a
model against a market, modify frozen NBA_PROP_EMPIRICAL_V1, or authorize a
wager.
