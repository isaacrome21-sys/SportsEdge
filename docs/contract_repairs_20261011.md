# Priority-1 Contract Repairs — 2026-10-11

Branch: `feat/contract-repair-20261011` (from `origin/main` @ `5e161b9`).
Status labels used below: **[ON MAIN]** = in this branch against origin/main;
**[BRANCH ONLY]** = exists on another branch, not in this bundle;
**[PLANNED]** = not implemented anywhere yet.

Research-only. Fail closed with explicit reason codes. Nothing here is a
validated edge; validation belongs to the backtest harness.

## Findings verified against code (before fixing)

1. **Market-blindness hole — CONFIRMED.** `artifacts/free_models.py::calculate`
   computed an `independent` projection, then shrunk the score means 15%
   toward the posted market line/total (`MARKET_ANCHORED_UNVALIDATED`) and
   returned the *anchored* probability as the top-level `estimate_p` /
   `ev_per_dollar` / `RESEARCH_EDGE` status. The architecture doc's claim of
   absolute market-blindness was wrong.
2. **Silent manual overrides — CONFIRMED.** `calculate` applied
   `row.get("context")` (and top-level `row.get(<context_key>)`) over verified
   factors, bounded ±15, with no label distinguishing verified from
   user-supplied values — on the normal phone intake path (`run_it_full`
   → `engine.run`, whose own docstring says intake is UNTRUSTED).
   Audit of every other `*.get("context")` in the repo: all remaining uses
   read *already-priced* `result.get("context")` (audit/render paths), not
   untrusted intake. `free_models.calculate` was the only silent-override
   site on the pricing path.
3. **Freshness inconsistent — CONFIRMED.** `MAX_AGE_SECONDS=180` existed only
   in `sportsedge/research_three_sport_bridge.py` (prop path). The game
   ML/SPREAD/TOTAL path (`artifacts/free_models.py`) never checked
   `quote_captured_at` at all — a stale screenshot could yield a
   top-level positive-EV status.
4. **As-of leakage — CONFIRMED.** `PublicContext.injury_points` fetches the
   *current* ESPN injury report and `weather` fetches the *forward* Open-Meteo
   window. Repriced historically (as_of < today), these silently apply
   today's state to a past kickoff. `schedule()` margins were already
   time-appropriate (pre-kickoff filter); `weather` failed closed for old
   kickoffs (no forecast hour within 3600s) but could leak realized weather
   for very recent games.
5. **Edge/EV/validated-profit conflation — CONFIRMED.** The per-row status
   `RESEARCH_EDGE` named an *unvalidated* EV estimate with the word "edge"
   (a validated concept). Outputs carried `validated_vs_close: False` but no
   explicit `validated_profitability` field, and the harness `report.py`
   wording needed checking.
6. **Docs —** the architecture doc now carries the Oct-11 correction; this
   file marks implementation status everywhere (see labels above).

## Repairs

### Repair 1 — Untrusted context overrides: GATED (not removed)

Decision: **gate behind an explicit flag**, documented here. Rationale: the
`--no-fetch` manual mode is a legitimate explicit research mode where the
user supplies all context; removing overrides entirely would kill it. The
normal phone intake path keeps the default `allow_manual_context=False`.

- `calculate(..., allow_manual_context=False)`: any `context.{key}` or
  top-level `<context_key>` value in the intake row **fails closed** with
  `BLOCKED_MANUAL_CONTEXT_UNDECLARED` (+ `attempted_override_keys`,
  explicit reason). Nothing is silently dropped or silently applied.
- `allow_manual_context=True`: overrides apply (±15 bound kept,
  `CONTEXT_ADJUSTMENT_UNBOUNDED` on excess) and every overridden factor is
  labeled `USER_SUPPLIED_MANUAL` in `context_provenance` and as
  `OVERRIDE_USER_SUPPLIED:<key>` in `context_notes`. Verified factors keep
  `VERIFIED_PUBLIC`.
- Conflict rule: verified data always wins by default (unflagged overrides
  block the row); a flagged override is the user explicitly taking
  responsibility, and it is labeled, never silent.
- `run()` / `run_it_full.run_full()` / both CLIs accept
  `--allow-manual-context`. The factor audit gains a `manual_context` field
  (`VERIFIED_PUBLIC_ONLY` / `USER_SUPPLIED_MANUAL:<keys>` /
  `BLOCKED_UNDECLARED_OVERRIDE`).

### Repair 2 — Two pricing lanes

- `calculate()` always computes **both** lanes and labels **every**
  probability:
  - `pricing_lanes.lane_a_independent` (`LANE_A_INDEPENDENT`): score means
    from base priors + HFA + verified context only. The win probability
    **never sees a market price** (tested: varying odds leaves Lane A p
    bit-identical; varying the line leaves Lane A means identical).
  - `pricing_lanes.lane_b_anchored` (`LANE_B_ANCHORED`): Lane A shrunk
    `ANCHOR_WEIGHT = 0.15` toward the posted line/total, status
    `MARKET_ANCHORED_UNVALIDATED`, hypothesis
    `UNVALIDATED_OUT_OF_SAMPLE_REQUIRED`. ML without `opposite_odds`
    → `LANE_B_UNAVAILABLE` / `BLOCKED_UNPAIRED_ML` (Lane A still prices —
    it needs no market input).
- **Lane A is the default primary view everywhere** (`lane="A"`; top-level
  `estimate_p`/`ev_per_dollar`/`pricing_lane`). `lane="B"` explicitly
  requests the anchored primary view (CLI `--lane B`).
- The card carries `primary_lane`, `edges` (primary-lane positive-EV rows),
  `lane_b_edges` (anchored candidates, always computed), and the legacy
  `independent_candidates` / `independent_watchlist` (Lane A, unchanged
  semantics). The phone renderer labels both sections by lane.
- **Harness merge note [BRANCH ONLY — `feat/backtest-harness-20261011`]:**
  no harness-code change is needed. The price adapter should register two
  models and dispatch on the name:
  ```python
  def price_fn(model_name, fixture, as_of, train):
      card = free_models.run(
          {"lines": [fixture_row(fixture)]}, now=as_of, as_of=as_of,
          historical=True, getter=cached_getter)
      row = card["evaluated_rows"][0]
      lane = {"lane_a_independent": row["pricing_lanes"]["lane_a_independent"],
              "lane_b_anchored": row["pricing_lanes"]["lane_b_anchored"]}[model_name]
      return [{"market": ..., "selection": ...,
               "model_p": lane["estimate_p"]}]
  # models=["lane_a_independent", "lane_b_anchored"]
  ```
  The 15% weight is then tested as a hypothesis: it stays only if Lane B
  beats Lane A chronologically out-of-sample.

### Repair 3 — Freshness: one centralized check, 180s everywhere

- New `sportsedge/quote_freshness.py`: `MAX_QUOTE_AGE_SECONDS = 180`,
  `check_quote_freshness(captured_at, *, now)` → explicit codes
  `QUOTE_FRESH_UNDER_180S` / `QUOTE_STALE_OVER_180S` /
  `QUOTE_TIMESTAMP_IN_FUTURE` / `QUOTE_FRESHNESS_UNVERIFIED` /
  `QUOTE_TIMESTAMP_INVALID`.
- `free_models.calculate`: every priced row carries `quote_freshness`; only
  `QUOTE_FRESH_UNDER_180S` can reach a positive-EV status — anything else is
  `WATCH_QUOTE_NOT_CURRENT` (reason `QUOTE_NOT_FRESH:<code>`). `run()`
  additionally requires fresh quotes for `independent_candidates` and
  `lane_b_edges` (stale → watchlist).
- `research_three_sport_bridge` now derives its (unchanged) labels
  `RECENT_CAPTURED_QUOTE` / `STALE_QUOTE` / `UNVERIFIED_QUOTE_FRESHNESS`
  from the centralized check; `MAX_AGE_SECONDS` kept as a legacy alias.

### Repair 4 — As-of snapshots

- `run(..., as_of=None, historical=False)`: `now` = wall-clock execution
  time; `as_of` = the point-in-time clock pricing must respect (defaults to
  `now`). The provider uses `as_of` for every time comparison and stamps
  receipts with it.
- Every card carries `input_snapshot: {n_rows, rows_sha1, as_of_utc,
  wall_utc, historical_repriced}` for reproducibility.
- `PublicContext(..., historical=True)`: `injury_points` returns
  `AS_OF_HISTORICAL_INJURIES_UNAVAILABLE` and `weather` returns
  `AS_OF_HISTORICAL_WEATHER_UNAVAILABLE` instead of leaking today's
  current-state endpoints into a historical repricing.
- **Harness merge note [BRANCH ONLY]:** the price adapter MUST pass
  `now=as_of, as_of=as_of, historical=True`; otherwise fixture verification
  and injury/weather context leak the present.
- **What cannot be snapshotted yet [PLANNED]:** injury reports, probable
  pitcher / lineup declarations, weather *forecasts*, and quotes — free
  endpoints serve current state only. In historical mode these are excluded
  with explicit codes, never silently substituted. Time-appropriate today:
  schedule/margin histories (pre-kickoff filter), fixture verification via
  ESPN `?dates=` pages, final outcomes via the harness `outcomes.py`
  historical endpoints.

### Repair 5 — Three quantities, strictly distinct

- **Model edge (estimate)** = `edge_over_break_even_pp` (P_model vs quoted
  breakeven, one-sided) and, when an exact DK pair exists,
  `edge_vs_dk_no_vig_pp` (P_model − P_no-vig, two-sided). Unvalidated.
- **EV at available prices** = `ev_per_dollar`. Unvalidated.
- **Validated profitability** = `validated_profitability: False` on every
  lane view, every row, and the card `authority` block. Only the harness
  can ever change this verdict.
- The `RESEARCH_EDGE` status is renamed `RESEARCH_POSITIVE_EV_UNVALIDATED`
  — an unvalidated positive-EV *estimate*, never a validated edge.
- Harness `report.py` wording audited **[BRANCH ONLY]**: `CONDITIONAL_PASS`
  already states "this is NOT a full pass ... must not enter production
  pricing on this verdict alone." No superiority implied; no change needed.

### Repair 6 — Docs discipline

This file, all new docstrings, and all new output fields mark
**[ON MAIN]** / **[BRANCH ONLY]** / **[PLANNED]** status. Branch-only code
(`sportsedge/backtest/`, `sportsedge/team_half_pricing.py`) is never
described as live.

## Merge notes (Phase 8 conflict)

Phase 8's branch touches `artifacts/free_models.py` (`injury_rows`,
`declared_weather_total_adj`, `rest_diff_adj` — not present on origin/main).
My changes to that file are confined to:

- imports (+ `hashlib`, `sys`, `sportsedge.quote_freshness`)
- lane constants + `_lane_view()` (new, additive)
- `PublicContext.__init__` (+ keyword-only `historical=False`, additive)
- `PublicContext.injury_points` / `weather` (early-return guards, additive)
- `calculate()` signature (+ keyword-only `lane`, `allow_manual_context`)
  and body (override gate, two-lane computation, freshness gate, status
  rename `RESEARCH_EDGE` → `RESEARCH_POSITIVE_EV_UNVALIDATED`)
- `run()` signature (+ `as_of`, `historical`, `lane`,
  `allow_manual_context`) and card assembly (`input_snapshot`,
  `primary_lane`, `lane_b_edges`, freshness-gated candidates)
- `main()` (+ `--lane`, `--allow-manual-context`, `--as-of`, `--historical`)

Expected merge behavior: Phase 8's factor additions (new context keys /
adjustments) compose with the override gate — its new keys should be added
to `CONTEXT_KEYS` and will then be covered by the same gate automatically.
If Phase 8 renames the status strings, prefer
`RESEARCH_POSITIVE_EV_UNVALIDATED` and keep `BLOCKED_*` codes stable.

## Tests

- New `tests/test_contract_repairs_20261011.py` (20 tests): override gate
  (block / flag / label / unbounded), conflicting-override discipline,
  Lane A never touches a market price, per-lane labeling, explicit Lane B,
  centralized freshness codes, stale/missing-quote watch-only on both the
  game path and the bridge, historical-mode source refusal, input snapshot,
  as-of clock, three-quantity separation, no `RESEARCH_EDGE` anywhere.
- Updated: `test_free_models_context.py` (override gate + fresh quotes +
  lane-aware assertions), `test_free_independent_projection_card.py` (fresh
  quotes), `test_free_models_phone_issue.py` (status rename + lane_b_edges),
  `test_run_it_full_free_factors.py` (lane-aware audit + fresh quotes).
- Full suite: green except two pre-existing collection errors
  (`test_cfb_dk_public_full_slate.py`,
  `test_nfl_prop_v1_inactive_articles.py` — both `ModuleNotFoundError:
  bs4`, environmental, unrelated to this branch).

## Limitations / open items

- The 15% anchor weight is still unfitted; the Lane A vs Lane B backtest
  that decides its fate lives on **[BRANCH ONLY]**
  `feat/backtest-harness-20261011` and needs the merge + the adapter above.
- Historical injury/weather/lineup/forecast snapshots are
  **[PLANNED]** — currently excluded with explicit codes, not reconstructed.
- Player-prop phone paths inherit the centralized freshness check via the
  bridge (already gated); their model inputs were out of scope for the
  as-of work here.
- `independent_projection` is kept as a legacy alias of Lane A for the
  renderer and existing consumers.
