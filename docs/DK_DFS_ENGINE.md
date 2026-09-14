# SportsEdge DraftKings DFS Engine

## Purpose

This module is a separate DFS decision lane inside SportsEdge. It builds **one DraftKings Classic single-entry tournament lineup** for MLB, NFL, or CFB from a point-in-time salary slate and a SportsEdge DFS projection snapshot. It does **not** inherit betting promotion authority from the sportsbook models and must never label a DFS projection as a validated betting `Model_P`.

## Command contract

The intended conversational command is: **"Send DK lineup for the 7:10 MLB slate"** (or NFL/CFB equivalent). The runtime resolves the closest DraftKings Classic draft group by lock time, downloads its draftables/salaries, joins a current SportsEdge projection snapshot, validates freshness/coverage, and optimizes one lineup.

CLI equivalent:

```bash
python scripts/run_dk_dfs.py \
  --sport MLB \
  --start 2026-09-18T19:10:00-04:00 \
  --projections artifacts/dfs/mlb/latest_projection_snapshot.json
```

`--allow-dk-fppg-baseline` exists only as an emergency diagnostic mode. DraftKings FPPG is not a SportsEdge projection model and should not be presented as such.

## DraftKings acquisition

The client discovers lobby contests/draft groups and then requests the draft group's `draftables` payload. The endpoint is public-facing but **unofficial and unsupported**, so acquisition is fail-closed. A future transport fallback may ingest an official user-exported `DKSalaries.csv` without changing the downstream model contract.

Every live run records:

- sport and requested slate lock time;
- resolved DraftKings draft-group ID;
- actual slate start in UTC;
- player count and projection coverage;
- projection source counts;
- salary used vs. salary cap;
- optimizer version/parameters in the surrounding run artifact.

## Roster rules

- MLB Classic: P, P, C, 1B, 2B, 3B, SS, OF, OF, OF; $50,000 cap; max five hitters from a team; no hitter against either selected pitcher.
- NFL Classic: QB, RB, RB, WR, WR, WR, TE, FLEX, DST; $50,000 cap. A tournament lineup must pair its QB with at least one same-team WR/TE. Opposing DST/offense combinations are blocked.
- CFB Classic: QB, RB, RB, WR, WR, WR, FLEX, SUPERFLEX; $50,000 cap. Every selected QB must have at least one same-team WR/TE in the lineup.

## Projection contract

A projection snapshot may provide either direct DFS distribution fields (`mean`, `ceiling`, `floor`, `stddev`, `ownership`) or expected stat components. SportsEdge converts expected MLB and football stats to DraftKings scoring before optimization.

Every non-baseline projection must be timestamped, must predate slate lock, and must satisfy the configured freshness window. Missing, stale, or post-lock evidence fails closed.

Recommended automatic input layers:

### MLB

Confirmed lineups/batting order, probable starters, pitcher workload, handedness/platoon, Statcast quality of contact, pitch-type matchup, park, roof/weather, umpire/catcher framing, bullpen quality/fatigue, stolen-base environment, Vegas/team run distribution, and SportsEdge hitter/pitcher prop distributions.

### NFL

Snap/route participation, pass/rush attempts, target and red-zone share, depth chart/inactives, OL/DL and coverage matchup, pace/pass rate, weather/roof, team scoring distribution, and SportsEdge player yardage/TD distributions.

### CFB

The NFL feature family plus CFB-specific depth-chart volatility, transfer/new-starter uncertainty, tempo, garbage-time/substitution risk, team strength, and game-state blowout distributions. NFL and CFB must remain separate validation lanes.

## Single-entry GPP objective

The optimizer starts with mean projection, adds a controlled ceiling/upside term, adds modest ownership leverage when ownership exists, and then adds sport-specific correlation value. Correlation is not allowed to create a high projection from a weak player; it only ranks otherwise viable combinations.

MLB rewards primary and secondary hitting stacks. NFL/CFB reward QB + WR/TE stacks and modest opponent bring-backs. The optimizer is deterministic for a fixed input snapshot.

## Public-repo research adopted as patterns

The implementation is original SportsEdge code. Research patterns were taken from public DFS projects, notably:

- `chanzer0/MLB-DFS-Tools`: contest/field simulation, stack ownership, and GPP-oriented evaluation patterns.
- `tburger101/dfs_simulator`: correlated football outcome simulation and ownership-vs-sim leverage concepts.
- `DimaKudosh/pydfs-lineup-optimizer`: salary/roster constraint architecture and optimizer ergonomics.
- `Biscuits4Lunch/DKNFLData`: NFL QB-stack workflow and prop-to-projection pipeline ideas.

No third-party source is treated as predictive truth. Any copied implementation in a future change must preserve its license and be added to `THIRD_PARTY_NOTICES.md`.

## Next validation layer

Before calling the system a production-quality DFS projection model, build chronological backtests by sport and slate type. Track projection MAE/RMSE, distribution calibration, top-1%/top-10% finish rate, contest ROI, duplication, ownership calibration, stack-pattern performance, and drawdown. Tune only on training windows and freeze out-of-sample evaluation windows.
