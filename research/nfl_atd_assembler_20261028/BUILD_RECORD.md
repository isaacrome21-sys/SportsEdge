# BUILD RECORD — NFL anytime-TD v1.1 capture→records assembler

Date: Oct 28, 2026 (CT) · Builder: Rocky (Muse) · Branch:
`rocky/nfl-atd-assembler-20261028` · Status: **DRAFT PR — NOT MERGED,
NOT COUNTED.** Nothing in this PR touches the frozen engine
(`grok/t227-nfl-atd-engine-fixes-20261022` @ c2fd86dc), the records
branch (`records/nfl-atd-v1-1`), or main's v1 ATD engine
(`sportsedge/nfl_anytime_td.py`). The assembler pushes nothing itself;
it writes record bodies into a local records-layout directory for the
operator to push under the records branch's single-commit discipline.

## Why this exists

Rocky's Oct 28 pre-flight (`~/workspace/atd-preflight-20261028/FINDINGS.md`,
gap 1, CRITICAL) found the frozen ATD v1.1 engine proven — pins exact,
257 family tests passing — but **no path from lane captures to the
board/close JSON records the engine consumes**, so Nov 1 could not
count. This build is that path.

## What was built (`research/nfl_atd_assembler_20261028/`)

- **`atd_assembler.py`** — the assembler module + CLI (`board` / `close`
  subcommands). Version stamp `NFL_ATD_ASSEMBLER_V1_20261028`, carried
  in every emitted record's `assembler_provenance` block together with
  the source capture kind/name, the source read timestamp, the DK event
  id, the nflverse game id, and the window classification.
- **`test_atd_assembler.py`** — 23 self-contained tests (synthetic
  pinned data, schedule, captures; no frozen code, no network).
- **`dry_run_fixture.py`** + **`dry_run_output_20261026.json.txt`** —
  the NON_COUNTED end-to-end proof on the real Oct 26 fixture (below).

### Contracts implemented (mirrored from the frozen tree at c2fd86dc)

- **Board record** → `nfl_atd_v1_1/boards/<season>-W<week>/<sha256>.json`,
  body `{season, week, game_id (DK event id), game_teams, captured_at,
  kickoff, slate_id, rows: [{player_name, player_id, yes_price}]}` —
  exactly what `price_nfl_atd_board_v11.price_core` consumes; sha256 is
  over the exact emitted bytes (`json.dumps(..., sort_keys=True)`).
- **Close record** → `nfl_atd_v1_1/closes/<season>-W<week>/<sha256>.json`,
  body `{game_id (nflverse), kickoff, captured_at, captures:
  [{player_id, yes_price, captured_at}]}` — exactly what
  `atd_provenance.load_closes` proves.
- **Identity** — the frozen family's own pinned data path: the eight
  pinned player-data files, sha256-verified against the freeze's
  SPEC_HASHES values (embedded verbatim; the frozen pricer re-verifies
  independently), plus the current-season stats file merged
  **point-in-time** (appearances count only from games completed before
  the capture: schedule result present AND kickoff + 4h ≤ captured_at —
  mirroring `atd_refresh.load_current_season`). Name normalization and
  resolution mirror `atd_engine.normalize_name` / `resolve_name`,
  including the `recent_team` → `team` column fallback the frozen
  reader uses. Game identity/kickoff resolution mirrors
  `atd_refresh.schedule_kickoff` (exactly one REG game, teams equal,
  schedule instant equal to the claimed kickoff, else
  `KICKOFF_SCHEDULE_MISMATCH`).
- **Unresolved players are named refusals, never guessed** — the
  assembly report lists each with its reason (`NO_MATCH`,
  `TEAM_MISMATCH`, `AMBIGUOUS`, `PRICE_INVALID`) and keeps the row out
  of the emitted record (an unresolvable board row would fail the whole
  slate closed at the pricer; the Oct 25 operating record treats such
  names as a declared systematic exclusion). D/ST rows and "No
  Touchdown Scorer" are excluded by name (`NOT_A_PLAYER_ROW`) — the
  engine is player-keyed.
- **Snapshot rules — the frozen family's own terms** (prereg
  Rules 4–6, ATD §6's Oct 22 rulings; Part 2/2B's LINE_MOVED bucket and
  sign test do **not** exist in this family and are not imported):
  board from the entry (T-1H-mark) capture — a capture inside the FINAL
  window (≤20 min before kickoff) is refused as a board source
  (`CAPTURE_IN_CLOSE_WINDOW`); a capture outside the nominal T-1H band
  (45–75 min) assembles only with a stamped
  `CAPTURE_OUTSIDE_T1H_BAND` warning (owner-ordered entries outside the
  band are on the record — Oct 26). Close from the **latest capture
  strictly before kickoff**, refused when that capture is more than 60
  minutes before kickoff (`CLOSE_STALE`, the frozen Rule 4 rule;
  exactly 60 minutes is accepted, matching the scorer's `>` test).

### Inputs

(a) a lane detailed capture file — either the **canonical capture JSON**
contract documented in the module docstring, or the **verbatim
detailed-read text** a single-game rendered DK capture returns (only
the TD Scorers **tab** snapshot the read itself designates is taken;
the Popular-tab drift snapshots are never blended, and a read that
does not designate its snapshot is refused,
`TEXT_SNAPSHOT_NOT_DESIGNATED`); (b) the same capture JSON written by a
fresh single-game capture. The assembler is capture-source-agnostic:
the live rendered read itself remains the lane's single-game dispatch
step (the Oct 26 DAL@PHI read was produced exactly that way). **The
GitHub issue-comment form is NOT a source** — comments are stripped by
the shared intake by design (proven: 0 anytime-TD rows extract from
issue bodies), carry no nflverse ids, and hold dual snapshots with no
authoritative designation. The assembler never opens an issue body.

## Proof

### Unit tests — 23 passed

Including: happy-path board with point-in-time merge (a player whose
pinned-snapshot team is stale resolves only after the merge moves his
latest team); named refusals for NO_MATCH / TEAM_MISMATCH / AMBIGUOUS;
rookie resolvable only with the merge; close-window capture refused as
a board source; capture at/after kickoff refused; **stale close
refused (61 min) and the exactly-60-minute boundary accepted**;
missing capture refused (`CAPTURE_MISSING`,
`CLOSE_NO_CAPTURE_BEFORE_KICKOFF`); pin mismatch refused; detailed-read
parsing incl. unicode minus and the drift-note designation; CLI
end-to-end writing a record into the records layout. Ruff gate
(E9,F821,F822,F823,F811) clean on all three files.

### Fixture dry run — NON_COUNTED, ACCEPTED (non-binding)

`dry_run_fixture.py` on the real Oct 26, 2026 DAL @ PHI capture
(DK event 34118071; the detailed read delivered in issue #2618's body —
the script unwraps the read as fixture prep; the assembler never sees
the issue wrapper), the real pinned player-data dir, a freshly
downloaded nflverse `stats_player_week_2026.csv.gz` and `games.csv`:

- **Rows extracted: 29** (the designated 4:59 PM TD Scorers tab
  snapshot — not the 4:57 PM Popular drift read).
- **Identities resolved: 23** with real nflverse player_ids (Williams
  00-0036997, Barkley 00-0034844, Lamb 00-0036358, …).
- **Named refusals: 3** — Eli Stowers (NO_MATCH), Camden Brown
  (NO_MATCH), Elijah Mitchell (TEAM_MISMATCH).
- **Exclusions: 3** — DAL Cowboys D/ST, PHI Eagles D/ST, No Touchdown
  Scorer (all NOT_A_PLAYER_ROW). Warning stamped:
  CAPTURE_OUTSIDE_T1H_BAND (the Oct 26 entry was owner-ordered at
  T-134 min).
- Board record: `nfl_atd_v1_1/boards/2026-W7/d72f736d….json`,
  slate `ASM-2026W07-DAL-PHI`.
- Close assembled from the latest pre-kickoff capture (the 19:09:08 CT
  record-only read, **5.9 min before kickoff**, selected over the
  17:01 CT entry read): 6 entries, `nfl_atd_v1_1/closes/2026-W7/e594809f….json`.
- **Frozen acceptance (in-memory FakeGitHub, nothing pushed):** the
  board was priced by the **real frozen pricer** (`pr.replay` — the
  review's own entry point): 23 rows, 11 YES / 11 PASS / 1 refusal
  (Grant Calcaterra, `PLAYER_TEAM_UNRESOLVED` by the pricer's own
  2026-stats team gate). The run record composed as `main()` composes
  it was accepted by the frozen scorer's loader:
  **`pv.load_slate` → COUNTS, zero reasons.** `pv.load_closes` proved
  all 6 close captures, 0 unproven records.
- **Frozen family suite re-run untouched: 257 passed, 44 subtests
  passed** (in the frozen tree at c2fd86dc).

## FINDING — a latent defect in the FROZEN family (not in this build)

The dry run surfaced a real defect in the frozen code, reproduced
**independently of this assembler** using only the frozen family's own
fixtures (`synthetic_world` + real pricer + publish + close):
`load_slate` returns COUNTS, but `score_nfl_atd_forward.score_slate_rows`
raises `KeyError: 'week'`, and the scorer CLI's `review()` dies the same
way (`score_nfl_atd_forward.py:271`, `_games`). Cause: the real
pricer's rows carry no `week` key, while the scorer requires
`row["week"]`. The frozen tests miss it because the scorer/closes tests
run on the fake pricer (whose rows are ledger rows that carry `week`)
and the replay tests never call `score_slate_rows`. The obvious
workaround — adding `week` to run-record rows — is foreclosed by
design: the loader's replay check requires run rows canonical-identical
to the pricer's output, so an edited row flips the slate to SCREEN
(`RUN_REPLAY_MISMATCH`).

**Consequence: even with perfect Nov 1 execution, no CLV can be scored
and no verdict produced for any real-priced ATD slate until this is
fixed — and fixing it means amending frozen code, i.e. a NEW VERSION
of the family scored forward (the freeze at c2fd86dc must not be
edited in place; its pins are exact). That is an owner decision, not
part of this build.** Board/close assembly, pricing, and loader
acceptance (COUNTS) all work today; scoring/verdicts do not.

## What remains for Nov 1 after this lands

The assembler closes pre-flight gap 1 only. **Gap 2 (CRITICAL) is
untouched by this PR: no execution is booked.** The two 09:30 CT
pre-check jobs detect; nothing acts. For Sunday Nov 1 (week 8; first
kickoffs 12:00 CT) an operator job must be booked to run the frozen
sequence:

1. Check out the frozen code at **c2fd86dc** and prove
   `local_shas()` == FREEZE.json on `records/nfl-atd-v1-1` before
   anything runs (gap 4: main carries the v1 engine — the wrong-code
   trap; never price from main's ATD code).
2. Refresh inputs per the standing rule (re-download the
   current-season stats file; never edit a pinned file), then push the
   records **before capture**: data + fetch records for stats and
   schedule and for the eight pinned player-data files (provenance
   rule C: fetch push < capture ≤ run push < first kickoff; rule G:
   one commit per push; records branch is single-commit, never
   edited/re-pushed, never force-pushed).
3. Per game in the T-1H window: single-game detailed capture →
   `atd_assembler board` → push the board record (one commit).
4. **Token-gated price run:** the frozen pricer's `main()` needs the
   GitHub token in its environment — per the Oct 24 record these steps
   run in the lane environment where the token lives (the fallback is
   that lane environment, not a token copy); the run record it emits
   must be pushed **before the 12:00 CT kickoffs** or the slate is
   SCREEN by construction.
5. Per game in the FINAL window: latest capture → `atd_assembler
   close` → push the close record **within kickoff + 15 minutes**
   (frozen grace) with the capture itself inside the 60-minute Rule 4
   window. Gap 5 stands: Oct 28's lane delivered 0/38 marks — close
   capture delivery is the fragile leg; the single-game dispatch
   pattern (the Oct 26 rescue flow, ~4–6 min dispatch→write) is the
   proven shape.
6. Settlements are pushed after games finish (nflverse results); the
   verdict review happens once, at the first slate close where the
   frozen gates are met (≥4 weeks, ≥150 picked, ≥40 distinct games —
   minimums per the Oct 22 clarification) — **and only once the
   `week` defect above is resolved by a new version**, since the
   scorer cannot grade real-priced rows today.

Also still open from the pre-flight: gap 3 (governing terms — the
Option B moved-line/sign-test machinery some records attribute to ATD
§6 does not exist in the frozen ATD prereg or code; it lives in
Part 2/2B. This assembler implements ATD's own frozen terms only. If
the owner wants that protection on ATD it needs his ruling + a new
version scored forward), and gap 6 (the issue-comment form is not a
stable capture contract — this build's answer is the canonical
capture JSON + detailed-read text contract above).
