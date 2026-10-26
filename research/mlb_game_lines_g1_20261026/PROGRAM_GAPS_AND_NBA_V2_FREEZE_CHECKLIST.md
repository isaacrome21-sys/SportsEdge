# Construction gaps and next owner gates — 2026-10-26

**Research coordination snapshot, NOT a live readiness verdict.**
Baseline inventory: `research/forward_validation_program_20261020/PROGRAM.md` (55 MLB families, 51 NFL, 49 CFB, 19 NBA readiness rows, 3 CBB main markets) and `research/cross_sport_accuracy_readiness_20261021.md`. Counts describe their October 20–21 audited *scopes*, not a newly re-executed 2026-10-26 registry census. NHL/UFC/PGA were parked at that baseline, and NHL is still **PAUSED** under the current owner ruling. Where a newer PR changes source/provenance or proposal state, note it without claiming a verified betting construction.

## 1. Exact named gaps by blocker class

| Sport / families | Construction state | Immediate blocker / owner of next proof |
| --- | --- | --- |
| **MLB main ML, run line, total, team totals (4)** | **NO CURRENT ADMISSIBLE CONSTRUCTION**; Lane A retired, V8 closed | New G1 joint-score proposal and independent DK-close comparison; this PR only drafts the protocol |
| MLB F5 ML/RL/total/TT (4) | Candidate engine exists, not admitted | `F5_STATE_CANDIDATE` eligibility ruling, then price evidence and prereg |
| MLB 1st-inning binary, 13 batter families, pitcher outs | Historic engine/draft present, **not verified** | Failed batter baseline screens remain disclosed; new tests need frozen source and genuine forward rows |
| MLB pitcher K / BB / ER / hits allowed | Pre-existing specific pitcher promotion instrument; new K ridge in flight | Keep its prereg/attempt clock separate; audit source and DK timestamped market captures |
| MLB 11 closed families (either-pitcher ×3, pitcher pitches, alt run lines/totals, 3-way ML, hit totals ×2, 1st-inning team runs/hits) | **CLOSED previous versions** | Only a new construction/prereg; do not thaw historic failures |
| MLB 9 greenfield groups: 3-way totals, F5 BTTS ladder, F5 exact score/margin, innings 1–3, innings 1–7, first-inning deep, innings 2–9, plate appearances, game exotics | **NO_ENGINE**, except a plate-appearance research construction not yet installed as a production engine | Build path-specific engines, identity/settlement evidence, prereg; PA also needs admitted PBP pool |
| MLB stolen bases, hits/runs/SB combos ×3, pitcher hits+walks+ER, pitcher win, first HR | Engine or candidate exists but not operational | Canonical binding, DK offering proof, PIT gates, or N-way first-HR attribution as specified in Oct 20 inventory |
| **NFL game ML, spread, prior-driven totals** | Previous candidate/market evidence failed or held | New independent challenger (shrinkage, capped model-vs-market disagreement); LEVEL v2 total is a separate frozen forward leg |
| NFL passing/rushing/receiving yards, receptions, attempts, completions | Frozen/forward or next version in flight, **not yet market-verified** | #2759 pricer fail-closed fix, B8 #2756 effective re-pin and clean live data dir; preserve each old version |
| NFL anytime TD and pass yards successor | Forward / successor design in flight | ATD v1.1 and passing-yards v2 prereg + prospective sample; no retroactive scoring |
| NFL TEAM_TOTAL, periods (halves/quarters), alternate side/total lines | Derivative shells without admitted joint-score probability input | Build and verify independent discrete scoring joint before admitting derivatives |
| NFL pass+rush, rush+rec, targets, 2+ TD, kicks ×3, defense ×3 | Engines/drafts exist, not verified | DK scope/listing and fixed source clocks; defensive/targets have absent DK listing evidence on sampled board |
| NFL first TD, longest completion/rush/rec | Data-source/attribution admission hold | Verified PBP first scorer and per-game max-play evidence before any honest outcome panel |
| NFL nine exotics (race, first score, largest lead, margin band, BTTS points, total TD, long FG, DST TD, safety) | **NO_ENGINE** | Joint-score/score-path construction and provenance |
| **CFB ML/spread/total** | Attempt-1 and 2023–2025 historical constructions FAILED versus closes | New successor; 2023–2025 design only, 2026 as-of diagnostic, unused chronological test, explicit shrinkage/disagreement cap; Form 2 and capture |
| CFB team total | Registration BLOCKED; no historically scored team-total construction | New pricing logic, independent market closes and owner registration |
| CFB 11 player families | Empirical research bridge exists, registration BLOCKED | Prospective PIT participation source, owner scope and prereg; failed C10 QB yard model is closed |
| CFB 34 unregistered groups (alternates, periods, TD/team TD, longest, kicking, defense, game exotics) | **NO_ENGINE + UNREGISTERED** | Build, data, owner registration, DK offering evidence |
| **NBA ML/spread/total** | V1 raw ratings failed historical market comparisons | New forward successor; do not relabel V1 as verified |
| NBA team totals | Construction with baseline screen, new frozen forward leg awaits mid-November sufficiency | Wait for original freeze/forward clock; no retrospective lift |
| NBA PTS/REB/AST/PRA | V1 frozen, V2 source amendment FINAL-CANDIDATE only | Owner V2 freeze gates below; #2757 cannot be merged/frozen solely because its tests pass |
| NBA periods, 2-stat combos, threes/STL/BLK/TOV, double-double | Some provisional construction, missing capture/result wiring | Source/outcome, canonical binding, individual prereg per family |
| NBA alt lines, correct score/margin, triple-double, first basket/race | **NO_ENGINE**; first basket additionally NO_DATA | Game paths and verified first-scoring attribution |
| **CBB ML/spread/total** | Three main-market families NO_ENGINE at Oct 20 audit | Season ingest, price identity, new CBB game-score model and unused validation |
| **NHL** | No approved live capture or validated bets | #2763 dual-source identity/provenance, then #2765 exact raw-byte archival; independently review and verify before capture re-enable. No retrospective admission. |
| UFC / PGA | Parked / outside current construction audit | Owner separate scope ruling and fresh market inventory |

**Completion discipline:** An Oct 20 group can contain several registry family keys; a group count is not a fully reconciled October 26 exact-key list. The next mechanical registry pass must emit `sport, canonical_family, offered_market, engine_version, prereg_sha, pinned_data_sha, test_state, forward_count, paired_close_count, blocker, source_commit` for *every* key, reconcile aliases and siblings once, and fail on duplicate ids or unstated classifications. Do not state that all families have constructions until that census and source inspection pass. Today the definite blocker is still that no family has met the owner's forward proof bar.

## 2. NBA props V2 — prepared freeze checklist, NOT an owner freeze

Current candidate PR #2757 head as observed on Oct 26: `15b96d30fe084df4413b726fccbd86adc07afe98`. Candidate prereg text hash: `9a20c19193095ebb9f93b12fae3877465b81f91682427ba2770e60ebe5b3b944`. These are **pre-freeze review identities**, not automatically the identities of a later freeze commit.

- [x] A FINAL-CANDIDATE V2 document and four V2 configs exist; V1 remains byte-untouched.
- [x] New head enforces `V2_FREEZE_NOT_AUTHORIZED` in the evaluator while status is NOT FROZEN; direct-counting regression exists. Re-review the latest *exact head* independently before any merge.
- [x] Oct 26 historical/research store remains permanently RESEARCH_ONLY.
- [ ] Owner names a single **specific, prospective NBA slate date and DK event set** as first eligible V2 slate; not inferred from an example date in the unit tests.
- [ ] Freeze record pins the final committed document/config/evaluator hashes and their exact source bytes, with effective UTC time prior to that slate.
- [ ] Freeze-time source asset has a raw-byte archive manifest with URL/fetched_at/size/sha256 and the required positions snapshot; no future positions may enter the slate.
- [ ] The **named first slate** independently passes the positions-as-of-slate / raw-manifest gate **before pricing**. If it fails, remain RESEARCH_ONLY and name a new prospective slate through a new owner record; never upgrade the old slate.
- [ ] Forward capture mode is explicitly enabled only for eligible games on/after the freeze; all counted ids separately versioned. No V1/V2 blends, no backfill.
- [ ] Wait for each prop family's genuine ≥50 graded forward picks with positive CLV and ROI (plus any stricter pinned family floors); promotion requires a separate owner ruling.

**Therefore at preparation time:** freeze `WITHHELD`; counted V2 rows `0`; V2 verdict `NONE`. No date is silently selected for the owner.

## 3. NHL evidence gate (still PAUSED)

1. #2763 must pass exact-head hosted CI and an independent review of official boxscore + landing identity, actual source hashes and timestamps. A comment from the connected owner account is evidence, not a distinct GitHub approver.
2. #2765 is stacked on #2763, must pass its own full hosted collector integration and independent review, archive BOTH exact raw HTTP bodies content-addressably before admitting normalized receipts, and refuse tampered/missing blobs. In particular, the Oct 26 snapshot has **no submitted review on #2765**; the five local helper tests exclude the two collector integration tests.
3. Complete independent evidence-admission verification on a truly new predeclared forward capture, then obtain an explicit owner re-enable ruling. Never reconstruct old missing raw bytes. Until then no capture activation, counted rows, or price promotion.

## 4. Merge separation

- #2754 fixes research calibration event leakage; after exact-head green CI and review it can land without changing production math.
- #2759 pricer repair must distinguish malformed *capture input* (per-row REFUSED) from evaluator/model/build failures (slate abort, zero committed artifacts) with both package regressions, and must be checked on its current-main refreshed head.
- #2756 B8 re-pin needs its *own* post-refresh CI and live active data-directory composition proof (`sp_2025_played_v2.csv.gz` present, old `sp_2025.csv.gz` absent), plus no B8 regression loss after integration. A staged test directory is **not** proof of live deployment composition.
- No merge implies an NBA V2 freeze, NHL restart, model promotion, or any sportsbook PLAY.

## 5. Executable next tasks

1. Complete/CI-review #2759 and #2756 sequentially under branch protections; independently verify the active NFL player-data directory before #2756.
2. Add G1 source census + canonical DK-price/close matching fixture, then build the first deterministic final-score-path candidate.
3. Run a registry-and-prereg census to replace this dated group map with an exact-key October 26 report; do not double-count aliases.
4. Obtain a named future NBA V2 slate, freeze only once its actual source/pin/gate criteria pass.
5. Keep NHL paused until #2763/#2765 review, merge, and raw-byte audit complete.

**Bankroll / authorization: six sports PAPER, 0u; verified bets 0.**
