# DRIVER LANDING CHECK — NFL team totals (NON_COUNTED)

**Status: NON_COUNTED landing check. Nothing in this record counts
toward the forward test.** The slate used (2026-10-25) was priced
here only to prove the driver machinery end-to-end; the family
evaluator is PENDING (pinned later by amendment, per the
FREEZE_RECORD), no §6 metric is computed anywhere in this check, and
the run carries `counted: false` throughout.

## What was built

`sportsedge/nfl_team_total_driver.py` (`NFL_TEAM_TOTAL_DRIVER_V1`) —
the operational shell around the FROZEN, library-only runner
(`NFL_TEAM_TOTAL_RUNNER_V1`). The driver is not part of the freeze
pin set; it modifies no pinned artifact. It:

- reads a RUN-IT handoff capture file (`captures_all.json` shape),
  extracts per-team main team-total rows (line, both prices, capture
  timestamp) and the game-total row used to elicit Lane A;
- joins every game to the nflverse schedules record — game_id,
  season, week, gameday, and team codes come from the schedules
  record, never from the capture's own labels (in this very check,
  the capture claimed `2026_08_SF_ATL` / week 8 while the schedules
  record says `2026_07_SF_ATL` / week 7; the driver priced under the
  schedules identity and noted the disagreement in the run report);
- builds the runner's history snapshot point-in-time (final
  regular-season games with gameday strictly before the slate's
  earliest gameday — same-day finals and the slate game itself never
  enter);
- passes raw capture values through to the pinned runner, so
  malformed rows earn the runner's own named refusals; driver-level
  failures (no unique schedules match, unresolvable team or
  team-total key, malformed capture) refuse per game with `DRIVER_*`
  codes and never price under a guessed identity;
- writes create-only entry records + a run report (counts and
  refusal codes only — the §4 operational-monitoring allowance), and
  settles written records via the runner's `evaluate_close` against
  finals joined on game_id from the schedules record (§3).

## The check run (2026-10-25, SF @ ATL)

Inputs:

- Capture: `landing_check_driver_capture_20261025.json` (this
  package) — the event-34118095 entry copied **verbatim** from
  `operative_run_20261025_runit_nfl/captures_all.json` (source file
  sha256 `05d47af0cab58d9a69a8908ed745e9ec7ab89e33d4c0c7e3869325d4682323c9`).
  It is the one game on that slate whose operative capture carries
  team-total rows: SF 26.5 (−115/−110), ATL 23.5 (−130/+100),
  captured 2026-10-25T10:53:25-05:00, kickoff 12:00 CT.
- Schedules/history/finals: the in-repo pinned nflverse games file
  `research/nfl_cfb_design_baselines_20261027/nflverse_games.csv.gz`,
  sha256 `82b05d7096b3f59acd127da8762b1e2260f4af70b49e5548ce4cd3ade92a49a5`
  (the PR #2831 pin). Final: ATL 29, SF 20.
- Pricing moment `--now 2026-10-25T10:54:25-05:00` (60 s after the
  entry capture, inside the pinned 180 s freshness bound); Lane A in
  its offline manual mode (the runner tests' mode) for determinism.

Results (`landing_check_driver_result.json`,
`landing_check_driver_out/`):

- **2 rows priced, 0 refusals.** SF: μ 27.424 vs line 26.5 →
  PASSED (gap +0.92). ATL: μ 21.189 vs line 23.5 → PICKED_UNDER
  (gap −2.31). §5 classifications recomputed independently in the
  check script from each record's own μ and entry line.
- **Pins recorded and re-verified against the FREEZE_RECORD:**
  engine `50c5d9ff…`, runner `076da740…`, config `4c5d7afb…`,
  preregistration `83f25f0e…` — all equal on every record; history
  snapshot 7,061 games, sha256
  `e263e4e0c82e779e6e5b2205c07e94964080e697968f3186ec306f30bd3a31de`.
- **Lane A (§6b) means recorded:** SF 21.25, ATL 22.75.
- **Settlement:** both rows carry exactly one §7 disposition —
  `CLOSE_STALE` — and settlement `GRADED` with the real finals
  (ATL 29, SF 20). The disposition is the honest one: the capture
  file's only paired team-total capture is the 10:53:25 pair,
  66m35s before kickoff, outside §7's 60:00 close window. No close
  quote was fabricated to force a READABLE; READABLE / LINE_MOVED /
  NO_CLOSE_ROW paths are covered by the driver's family tests with
  fixture captures.
- **Nothing counted:** result `counted: false`, `label:
  NON_COUNTED`, `metrics_computed: false`; the check script asserts
  no §6 metric key exists in any record or settlement.

Re-run: `python3 landing_check_driver.py` from this directory
(delete `landing_check_driver_out/` and
`landing_check_driver_result.json` first — create-only discipline).

## Tomorrow's counted-slate invocation (TNF, 2026-10-29)

Run at the moment the slate's ENTRY capture is staged (the pinned
runner refuses rows priced more than 180 s after the earliest entry
side quote), from a clone of current main:

```
python3 -m sportsedge.nfl_team_total_driver price \
  --captures <operative captures_all.json for the slate> \
  --games <nflverse games.csv.gz pull> \
  --slate-date 2026-10-29 \
  --out-dir research/nfl_team_totals_forward_20261028/runs
```

Lane A defaults to its live public-context mode (production). The
entry records land create-only at
`runs/entry_2026-10-29.jsonl` with the run report beside them;
settlement follows the same shape with the `settle` subcommand once
the final capture and the finals exist.
