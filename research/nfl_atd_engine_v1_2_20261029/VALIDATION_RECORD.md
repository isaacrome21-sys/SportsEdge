# VALIDATION RECORD — NFL anytime-TD engine v1

**Family:** `anytime_td` (N37) · **Labels:** RESEARCH_ONLY / NOT_VALIDATED ·
eligible: false · promotable: false (unchanged) · **No PLAY follows from this record.**
Plan: `PREREG_NFL_ATD_ENGINE_V1.md`, sha256
`c3907b08041ccd36827aedc7cb3de57c172d41269dde76fbd28a82cd8565e099`, committed
**before** any engine code existed (local commit 40b4201b5; on the remote
branch the plan file lands in the first commit, ahead of every code file). The scorer and the board pricer both refuse to run if
the plan file's hash differs from the pin.

## Data (hash-verified before every run)

All eight files of the Part 1/Part 2 pinned nflverse snapshot, re-verified
against `research/nfl_props_part2_20261018/SPEC_HASHES.txt`:
ps_2018 `15730d75…`, ps_2019 `d143b91c…`, ps_2020 `e23a81d6…`, ps_2021
`a2fb2665…`, ps_2022 `2b7dca68…`, ps_2023 `b7590543…`, ps_2024 `629b77e0…`,
sp_2025 `c7401e32…` — all matched. Snap counts are not in this snapshot; the
engine gates on games played, as declared in the plan §0.

*Interpretation note (recorded, not a plan change):* pool keys use the data's
`position_group` field (QB/RB/WR/TE); fullbacks carry position_group RB in
nflverse's own taxonomy and pool as RB. One loader accommodation: the 2025
file names the team column `team` where earlier files use `recent_team`; the
loader accepts either.

## Calibration leg (frozen plan §3) — SCORED

Population: 2020–2025 regular-season player-games passing the §1 gate:
**n = 29,114 scored**; gated out 8,570 (UNPRICED_INSUFFICIENT_GAMES) and 7,642
(UNPRICED_POSITION_GROUP_NOT_POOLED — mostly defensive/special-teams
appearances); 29,114 + 8,570 + 7,642 = 45,326, the full REG player-game count.
Realized base rate 0.2126; mean model_p 0.2122.

| Arm | Log loss | Brier |
|---|---|---|
| **Engine v1** | **0.4881** | **0.1571** |
| POOL baseline (position pool only) | 0.5129 | 0.1659 |
| RAW baseline (unshrunk player rate) | 0.6551 | 0.1626 |

Paired bootstrap, 2,000 resamples clustered by game, seed 20261018:

| Comparison | Δ log loss [95% CI] | Δ Brier [95% CI] | Verdict |
|---|---|---|---|
| Engine − POOL | **−0.0248 [−0.0270, −0.0227]** | −0.0088 [−0.0096, −0.0080] | **BEATS_BASELINE** |
| Engine − RAW | **−0.1670 [−0.1839, −0.1497]** | −0.0055 [−0.0064, −0.0046] | **BEATS_BASELINE** |

Reading, honestly: the RAW baseline's log loss is heavily inflated by
unshrunk 0/1 rates on thin histories, so the POOL comparison is the
informative gate — individualization adds a real, if modest, −0.0248 log loss
over the position pool alone. Both frozen gates passed. Decile calibration is
monotone and close (predicted vs realized: 0.093/0.091, 0.125/0.117,
0.147/0.134, 0.166/0.151, 0.187/0.181, 0.209/0.194, 0.233/0.226, 0.263/0.264,
0.305/0.328, 0.393/0.438) — the top two deciles *under*-predict: the engine
is mildly conservative on the likeliest scorers. ST-only TD rows inside the
scored population: 54 (the declared settlement class the engine does not
price).

**This is a calibration verdict only.** It says the probabilities track
outcomes better than both baselines. It says nothing about beating
DraftKings prices — see the market leg.

## Prior diagnostic — preserved

The earlier estimator (`sportsedge/nfl_anytime_td.py`, opportunity
decomposition on unpinned live inputs incl. snap counts and play-by-play)
keeps its verdict: **FAILED_VALIDATION (diagnostic)** — 2023 walk-forward,
n = 4,760, Brier Δ vs naive +0.0002, 95% CI [−0.0012, +0.0018]
(Oct 14 program, carried Oct 17). This engine is a new version scored under
the version-scoring rule; the old verdict is neither overwritten nor
relabelled. Paired re-score against that diagnostic on identical games:
**NOT_EVALUABLE_FROM_RECORD** — its per-row outputs are not in the repo (the
harness depends on external worktrees; the Oct 11 report stores aggregates
only). Not reconstructed, per the freeze discipline.

## Market leg — NOT_EVALUABLE_HISTORICAL → PENDING_FORWARD_TEST

No historical DraftKings anytime-TD prices exist in free data; no market
baseline is fabricated. The market verdict path is the **locked forward
test** (`docs/football/NFL_ANYTIME_TD_FORWARD_TEST_V1.md`, unmodified),
starting **Thu Oct 22, 2026**, on boards captured under CAPTURE_SPEC_V1 and
priced by this engine: **PENDING_FORWARD_TEST**.

## Demonstration (HISTORICAL_DEMONSTRATION — not prospective evidence)

`demo_dal_gb_20261018.json`: the DAL@GB board captured Sun Oct 18, 2026
3:13 PM CT (records branch `records/dk-full-board-20261018`), 30 rows →
**18 PRICED** (8 YES / 10 PASS under locked Rules 1 + 9) and **12 UNPRICED**:
1 × UNPRICED_INSUFFICIENT_GAMES (MarShawn Lloyd — the game's listed lead
back; the snapshot shows < 4 prior appearances, so the engine refuses rather
than guesses, the exact role-blindness failure mode the gate exists for),
8 × UNPRICED_NAME_UNRESOLVED (players whose latest snapshot team is neither
DAL nor GB, incl. both non-game rookies), 3 × UNPRICED_NOT_A_PLAYER_ROW
(the two D/ST rows and "No Touchdown Scorer").
**Evidence caveat:** the pinned snapshot ends with the 2025 season, so these
prices use 2025-form evidence only; 2026 Weeks 1–6 form is not in them. The
wide gaps vs the board on favorites (e.g. Javonte Williams model 0.415 vs
0.697 raw implied) therefore measure evidence staleness as much as engine
output — the demonstration proves the pricing path and the fail-closed
behavior, not a prospective price. Prospective pricing starts Thursday, on
data current at pricing time.

## Verification

- Unit tests: 9/9 pass (`test_nfl_atd_engine.py`) — shrinkage, recency
  weights, implied-probability conversion, the Rule 1 strict-> boundary
  (a tie is PASS), Rule 9 edge, the games gate, the evidence-window season
  restriction, name normalization.
- Hand check: 12 scored player-games recomputed from the raw CSVs by
  `handcheck_nfl_atd.py` (imports nothing from the engine) — **ALL MATCH**
  (model_p, pool_p, raw_p, outcome, tolerance 1e-9).
- Determinism: scorer reruns (three separate processes) are byte-identical
  to the committed results file (sha256
  `8d45de850bf357607f7d90f5b687d506b8709c3261e7304a76402d018445b46b`).
- The registry entry is untouched: registration is not an engine, this
  branch admits nothing, and governance state (eligible/promotable/
  validation_status) is exactly as registered.
