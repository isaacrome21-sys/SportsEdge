# NFL Anytime-TD Engine v1.2 — Amendment DRAFT

**DRAFT — NOT FROZEN — NOT ADOPTED**
**Counted rows under this draft: 0. Research only, PAPER / 0u.**
**Nothing in this document authorizes counting, a freeze, or a records-branch write.**

Basis: frozen v1.1 at branch `grok/t227-nfl-atd-engine-fixes-20261022`,
commit `c2fd86dcc995e34af2b315319d3a184f8b5178cf` (FREEZE.json on
`records/nfl-atd-v1-1`, commit `5ba400ef2`). The v1.1 freeze is
byte-untouched by this draft and is not edited in place.
Owner ruling (Isaac, Oct 29, 2026): draft the v1.2 scorer fix; Nov 1,
2026 runs as a NON_COUNTED rehearsal; no retroactive counting; v1.2 must
pass independent review and freeze requirements before counting begins.

Package: `research/nfl_atd_engine_v1_2_20261029/` — a full copy of the
frozen v1.1 family directory in which exactly one code file differs
(§1) and two files are new (this amendment; the regression test,
`test_nfl_atd_v12_regression_real_pricer.py`). Every other file,
including the v1.1 preregistration incorporated by reference in §2, is
byte-identical to the frozen commit (verifiable with `diff -r` against
the v1.1 directory at `c2fd86dc`).

## 1. The single change vs v1.1

**The defect (verified).** The frozen v1.1 scorer cannot score any
real-priced slate. `atd_engine.price_board_row` — the real pricer's row
constructor — emits rows with keys: family/labels, `game_id`,
`player_name`, `player_id`, `yes_price`, `captured_at`, `kickoff`, and
the pricing fields. There is no `week` key. But the v1.1 scorer indexes
`row["week"]` on every priced row (`score_nfl_atd_forward.py`, `_games()`
at line 271; also `score_row()`), so `score_slate_rows` and the scorer
CLI's `review()` raise `KeyError: 'week'` on any slate priced by the
real pricer. Assembly, pricing, and loader acceptance (COUNTS) all work
under v1.1; CLV scoring and verdicts are impossible. The frozen tests
miss the defect because the scorer/closes tests run on the fake pricer,
whose ledger rows carry `week`, and the replay tests never call
`score_slate_rows`. (Discovery record: assembler BUILD_RECORD, PR
#2920; pre-flight: `~/workspace/atd-preflight-20261028/FINDINGS.md`.)

**Why the week cannot be added to the rows.** The loader's replay check
(`atd_provenance._replay_check`) re-runs the pricer on the slate's
proven inputs and requires the run record's rows to be
canonical-JSON-identical to the pricer's output. A row edited to carry
`week` flips the slate to SCREEN (`RUN_REPLAY_MISMATCH`). The fix must
therefore source the week outside the rows.

**The fix (the only code change).** In the v1.2 scorer, the week of a
scored row is taken from the slate's own metadata — the run record's
top-level `week` (`record["week"]`) — in the two places the scorer
builds its working rows:

- `_rows(st)` annotates each priced row copy with
  `week=int(st["record"]["week"])`, in-memory only, alongside the
  schedule-recomputed kickoff it has always substituted the same way;
  the stored record is never modified.
- `_games(loaded)` builds the per-game map with
  `week=int(st["record"]["week"])` instead of `r["week"]`.

`score_row()`'s contract is unchanged (it reads `row["week"]`); every
production path reaches it through `_rows()`. The run record's `week`
is authoritative for the slate: it is the board's week, it is bound by
the replay check to the proven board record filed under
`boards/<season>-W<week>/`, and the loader already cross-checks any
row-carried week against the schedule's week for the game
(`ROW_KICKOFF_SCHEDULE_MISMATCH`). `load_closes` / `load_settlements`
validate close/settlement filing against the same (season, week) pair,
so a wrong slate week fails closed rather than scoring.

No other code differs. `atd_engine.py`, `atd_refresh.py`,
`atd_provenance.py`, `price_nfl_atd_board_v11.py`,
`price_nfl_atd_board.py`, and `fake_github_api.py` are byte-identical
to the frozen commit; the pricer composite pin and the provenance pin
are therefore unchanged (§5).

**Regression proof.** `test_nfl_atd_v12_regression_real_pricer.py`
scores slates priced by the REAL pricer end-to-end: (A) the family's
`synthetic_world` priced via `pricer.replay`, published, closed,
settled, scored, and reviewed; (B) the real Oct 26, 2026 DAL @ PHI
capture assembled through the merged assembler
(`research/nfl_atd_assembler_20261028/`), priced by the real pricer,
loaded (COUNTS), scored (22 priced rows; the 6 close-covered players
CLV-scored, the rest `CLV_MISSING / NO_CLOSE_ROW`), reviewed, and run
through the scorer CLI in its `ATD_TEST_FAKE_STATE` non-binding mode —
the exact call that died with `KeyError` under v1.1. Both parts assert
the defect precondition (real pricer rows carry no `week`) and that
every scored row's week equals the slate-metadata week. Part B's
settlement values are placeholders that exercise the settlement path
only; they assert nothing about the real game's outcomes.

## 2. Everything else carries over unchanged

The v1.1 preregistration,
`PREREG_NFL_ATD_ENGINE_V1_1_DRAFT.md` (sha256 `778441d4…`, byte-identical
copy in this package), is incorporated by reference in full: §§1–4 and
§2b (server-side provenance rules A–G), the row-level fail-closed
rules, and the declared UNPRICED code list are unchanged. The §5/§6
forward-scorer terms carry over **exactly as frozen in v1.1**,
including:

- **Rule 4 (close / CLV).** CLV = raw implied(close Yes) − raw
  implied(entry Yes), no de-vig. Close = the LATEST capture strictly
  before kickoff; more than 60 minutes before kickoff ⇒
  `CLV_MISSING / CLOSE_STALE`; invalid close price ⇒
  `CLOSE_LATEST_INVALID` (no fallback); none ⇒ `NO_CLOSE_ROW`; any
  untimed capture ⇒ `CLOSE_TIMESTAMP_INVALID`. CLV_MISSING rows keep
  their win/loss.
- **Rule 5 (cut drift).** Per game, drift = mean CLV over all
  CLV-scored rows (picked + passed); `clv_adj = clv − drift`; games
  with |drift| > 0.02 flagged.
- **INSUFFICIENT_CLOSE_DATA.** If more than 20% of graded picked rows
  are CLV_MISSING (**all reasons together**), the verdict is
  INSUFFICIENT_CLOSE_DATA. Exactly 20% does not trip.
- **BEATS_MARKET.** Iff not INSUFFICIENT_CLOSE_DATA AND picked mean CLV
  game-clustered 95% CI lower bound > 0 AND picked mean clv_adj > 0
  AND picked mean CLV > passed mean CLV.
- **Rule 6 (gates).** `MIN_WEEKS, MIN_PICKED, MIN_GAMES = 4, 150, 40`,
  applied with `>=` — minimums, per the Oct 22, 2026 clarification
  memo. **One review**, at the first slate close where all gates are
  met; that accumulated sample is the sample of record. No review is
  rerun unless a new version preregisters it.
- **Multiple testing** remains a program-level PLAY rule, not applied
  inside this family's scorer. Output remains RESEARCH_ONLY; nothing
  here can open PLAY.

## 3. OWNER DECISION POINT — §5 CLV treatment (NOT resolved by this draft)

One question is named for the owner's ruling before any v1.2 freeze.
This draft does not resolve it; the default carried into the draft is
Option 1.

- **Option 1 (default, carried into this draft):** v1.2 keeps v1.1's
  §5 CLV treatment exactly as frozen (§2 above), including the >20%
  trip counting **all** CLV_MISSING reasons together.
- **Option 2:** v1.2 adopts the Part 2-style moved-line bucket with
  direction recording, a moved-bucket sign test at α = 0.05, the 20%
  trip counting only true capture failures, and moved share > 50% ⇒
  LOW_COVERAGE.

Record of fact (Rocky, Oct 28, 2026, verified against the frozen tree):
**that machinery does not exist in ATD's frozen prereg or code.** Grep
over the frozen tree and the records branch returns zero hits for
`LINE_MOVED`, `LOW_COVERAGE`, or any sign test; two of its trip codes
(`CLOSE_SINGLE_SIDED`, `CLOSE_NOT_PREKICKOFF`) do not exist in ATD at
all. The machinery lives in the NFL props Part 2 / Part 2B families,
whose markets are line-based. ATD is a price-only market (a Yes price;
there is no line that can move), so Option 2 is not a restatement of an
existing ATD term: adopting it would require the owner to also settle
what "moved" means for a Yes price, as new terms scored forward from
the v1.2 freeze. If the owner rules Option 2, this amendment must be
revised to specify those terms before freeze; the scorer change in §1
is unaffected either way.

## 4. Nov 1, 2026 — NON_COUNTED rehearsal terms

Per the owner's Oct 29, 2026 ruling, the Sun Nov 1, 2026 slates run as
a **NON_COUNTED full rehearsal** under this draft: PAPER / 0u; the
v1.2 draft scorer may be exercised in its non-binding modes (including
the `ATD_TEST_FAKE_STATE` test switch) to prove the pipeline end to
end; **no Nov 1 row counts**, no verdict from the rehearsal is binding,
and no slate priced before a v1.2 freeze can ever be counted
retroactively under v1.2. The Oct 25, 2026 slate exclusion
(`PERMANENTLY_EXCLUDED_NO_BACKFILL`) is unchanged. The v1.1 clock state
is likewise unchanged by the rehearsal: counted rows under v1.1 remain
0, and v1.1 remains incapable of producing a verdict (§1).

## 5. Freeze requirements — before any counting under v1.2

Counting under v1.2 begins only when ALL of the following hold:

1. **Independent review closed on the exact head** of the v1.2 freeze
   candidate (the review covers the §1 diff, this amendment, and the
   regression evidence).
2. **Owner freeze act, prospective only**, recorded before the first
   counted slate, naming the first counted slate **by rule** (the
   first NFL slate priced by the frozen v1.2 construction after the
   freeze act lands) — no past slate named, no retroactive counting.
3. **v1.2 FREEZE pins struck on the exact head.** Candidate pins at
   this draft (computed by the v1.2 package's own `local_shas()`):
   - `pricer_sha256`: `c054c372a6984b65697aad859111fab941faaf51948045f47ee6674ecc4f8a89` — unchanged from v1.1.
   - `provenance_sha256`: `48f0c18aba1c8ea540e0665d385aa7e0da20b8598d87e2c2500f950569e814e0` — unchanged from v1.1.
   - `prereg_sha256`: `778441d449f3d3c16d8888e6120d3c90cb856d1c91444fb8769d967b669b7e0d` — the incorporated v1.1 preregistration; the freeze act states whether this amendment joins the pinned instrument set (its own sha256 is then struck in the FREEZE record, not inside it).
   - `scorer_sha256`: `1dfa4098a1925fda70eb966175c9efd370ccc5039e7a196ccb1f6b3cff9e0f6a` — **the only pin that changes vs v1.1** (v1.1: `000e8f86…`).
4. **§3 decided.** The owner's Option 1 / Option 2 ruling is recorded;
   if Option 2, the revised amendment specifying the new terms is the
   instrument reviewed under (1).
5. **Records-location decision.** This draft deliberately leaves
   `atd_provenance.py` byte-identical, so the draft code still points
   at `records/nfl-atd-v1-1` / root `nfl_atd_v1_1` and the §2b verdict
   path `nfl_atd_v1_1/VERDICT.json`. The freeze act must either (a)
   adopt that location for v1.2 — recording that the family's single
   verdict path then serves the v1.2 clock (v1.1 produced no verdict
   and, per §1, never can) — or (b) amend the provenance module in the
   same act to a v1.2 records location, which changes the provenance
   pin and requires the amended head to be the reviewed head under
   (1). Not decided by this draft.
6. **Suites green on the exact head**: the frozen v1.1 family suite
   passing untouched at the frozen commit `c2fd86dc`, and the v1.2
   package suite (the carried-over tests plus
   `test_nfl_atd_v12_regression_real_pricer.py`) passing on the freeze
   candidate head.

Until all six hold, v1.2 is a draft: it prices nothing that counts,
scores nothing that counts, and its only authorized live use is the
§4 rehearsal.
