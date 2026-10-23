# Forward-validation framework (v1)

The universal forward-test evaluator for SportsEdge market families. It
generalizes the **frozen** NFL props Part 2 forward test
(`research/nfl_props_part2_20261018/PREREG_NFL_PROPS_PART2_FORWARD_V1.md`)
and the Capture Spec V1 close rule (`docs/football/CAPTURE_SPEC_V1.md`)
into one config-driven evaluator every family can be declared into.

**Standing law this implements.** A family validates ONLY through a
preregistered forward test scored against our own timestamped DraftKings
captures. CLV vs the final pre-event capture is the primary verdict metric;
calibration and win/loss are secondary. Confidence intervals are clustered
by game/event. A market under its row/event minimums is
`INSUFFICIENT_SAMPLE`, never a verdict. Every model version is scored AS
IT STOOD when it priced the games. Historical screens never validate. The
frozen tests already in force (NFL props Part 2, Part 2B, anytime-TD,
NFL totals LEVEL v2 forward leg) are separate instruments and are not
reimplemented or altered here.

## Declaring a family

One JSON config per family in `configs/`:

| Field | Meaning |
|---|---|
| `sport`, `family`, `markets` | Identity; verdicts issue per market key. |
| `engine_id`, `model_version` | The engine and the EXACT version string priced rows must carry. At freeze time this string is pinned; rows priced by any other version refuse the run (`MODEL_VERSION_MISMATCH`). |
| `market_form` | `TWO_SIDED` (paired two-sided quotes, multiplicative de-vig) or `YES_ONLY` (one-sided board, raw-implied CLV — the locked anytime-TD form). |
| `sides`, `over_side` | The two side labels; `over_side` is the side that wins iff the realized value exceeds `line`. |
| `min_rows`, `min_events`, `min_slates` | Insufficiency gates. Defaults mirror Part 2 §4 (100 rows / 40 games; slates gate only where the family's prereg declares one). |
| `max_clv_missing_share` | Above this share of CLV_MISSING rows the market's verdict is `INSUFFICIENT_CLOSE_DATA` (frozen value: 0.20). |
| `clv_beats_threshold` | `BEATS_MARKET` iff the clustered 95% CI for mean CLV lies entirely above this (frozen value: 0.0). |
| `close_max_age_minutes` | A close captured earlier than this before event start is `CLOSE_STALE` (Capture Spec: 60; exactly 60:00 is readable). |
| `status` | `DRAFT — NOT FROZEN` until the owner freezes the family's preregistration. A verdict record stamps the config status and sha256, so a draft-config readout can never present as a frozen verdict. |
| `capture_scope`, `capture_note`, `prereg_draft` | Where the family's lines are captured today and the path to its draft preregistration. |
| `prereg`, `prereg_sha256` | For an already-frozen family: the frozen preregistration's path and sha256. Stamped on every verdict record, so a readout names the exact frozen text it was scored under. |
| `picked_beats_passed_required` | Frozen picked/passed verdict mode (NBA props §9; TWO_SIDED only). The verdict sample is the market's classified engine rows — PICKED (runner-surfaced research candidates) and PASSED (engine-priced, not picked) — the CLV leg is the picked rows, and `BEATS_MARKET` additionally requires picked mean CLV > passed mean CLV. Rows with no runner disposition are reported unclassified and enter no denominator. |

## Record contracts

**Priced entry record** (one per priced row, written before event start):

```json
{"row_id": "…", "sport": "NFL", "family": "TARGETS", "market": "TARGETS",
 "event_id": "2026-W08-NE-CHI", "event_start": "2026-10-22T19:15:00-05:00",
 "subject_id": "<player id or null for game markets>", "subject_name": "…",
 "line": 6.5, "model_version": "<config model_version>",
 "model_p": {"OVER": 0.58, "UNDER": 0.42},
 "entry_prices": {"OVER": -110, "UNDER": -110},
 "entry_captured_at": "<ISO-8601 with offset>",
 "recorded_at": "<ISO-8601 with offset>",
 "label": "PROSPECTIVE",
 "crps_candidate": null, "crps_baseline": null}
```

- `line` is always on the realized-value scale for the `over_side`: the
  over_side wins iff `value > line`, the other side iff `value < line`,
  push iff equal. (A home spread of −4.5 is stored as line 4.5 on the
  home-margin scale with `over_side: "HOME"`; a total of 45.5 is line
  45.5 with `over_side: "OVER"`.) Family adapters own this conversion.
- `crps_candidate` / `crps_baseline` are optional and engine-supplied
  (the framework averages them when present; it never invents
  distribution math of its own).
- YES_ONLY rows carry `model_p: {"YES": p}` and `entry_prices: {"YES": price}`.
- Entry probabilities, entry odds, matching close odds, and entry/close lines
  must be finite numeric values (numeric strings remain supported; booleans
  are refused). Invalid lines use `LINE_INVALID`; invalid probabilities and
  odds use `MODEL_PROBABILITY_INVALID` and `PRICE_INVALID`. Odds must produce
  a finite decimal payout greater than one. Numerically equal line spellings
  share one prospective-row identity and cannot inflate the sample count.
- A record written after its event started must carry `label:
  "HISTORICAL"`; historical records are counted and excluded from all
  verdict math. An unlabeled post-start record refuses the run.

**Close capture record** (Capture Spec shape):

```json
{"event_id": "…", "subject_id": "…", "market": "TARGETS", "line": 6.5,
 "prices": {"OVER": -115, "UNDER": -105}, "captured_at": "<ISO-8601>"}
```

Closes match entries on (event, subject, market, line). A close at a
different line is `LINE_MOVED`, never repriced.

Supply one selected final close record per (event, subject, market, line).
Repeated identities refuse the run with `CLOSE_DUPLICATE`, including exact
copies. The adapter must explicitly select the final close under its capture
contract before evaluation; file order cannot select a quote or overwrite
evidence. This evaluator does not resolve raw capture histories.

All entry and close timestamps require an explicit UTC offset (`Z` is
accepted). Date-only values and naive local times are refused; the evaluator
never guesses a timezone. Invalid entry clocks use `RECORD_MISSING_TIMESTAMP`,
and invalid close clocks use `CLOSE_RECORD_MISSING_TIMESTAMP`. Every supplied
close is checked before indexing, including unmatched or duplicate rows.

**Outcome record**: `{"event_id", "subject_id", "market", "value"}` —
the realized value on the line scale, from the family's declared
results source.

## Refusals (fail-closed, named)

The evaluator raises `ForwardValidationRefusal` and scores nothing when
any prospective row violates: `MODEL_VERSION_MISMATCH`,
`POST_START_RECORD`, `RECORD_MISSING_TIMESTAMP`,
`CLOSE_RECORD_MISSING_TIMESTAMP`, `DUPLICATE_PROSPECTIVE_ROW`,
`MODEL_PROBABILITY_INVALID`, `PRICE_INVALID`, `CONFIG_INVALID`.

Per-row dispositions that are not refusals (frozen Part 2 mechanics): an
entry captured at/after event start is excluded (`ENTRY_NOT_PRE_EVENT`);
a close violating the close rule yields `CLV_MISSING` with exactly one of
`NO_CLOSE_ROW` / `LINE_MOVED` / `CLOSE_SINGLE_SIDED` /
`CLOSE_NOT_PREKICKOFF` / `CLOSE_STALE`; a graded row with no matching
outcome is reported unscored, never invented.

## Verdict rule (per market)

1. Graded verdict-sample rows < `min_rows`, or distinct events <
   `min_events`, or (where declared) slates < `min_slates` →
   `INSUFFICIENT_SAMPLE`, with the gate table in the record.
2. CLV_MISSING share > `max_clv_missing_share` →
   `INSUFFICIENT_CLOSE_DATA`.
3. Game-clustered 95% CI for mean CLV entirely above
   `clv_beats_threshold` → `BEATS_MARKET`; otherwise
   `DOES_NOT_BEAT_MARKET`. The burden of proof is on the model.

For YES_ONLY markets the verdict sample is the PICKED rows (model beats
the entry raw implied probability — the anytime-TD selection rule), and
the passed rows' CLV is reported alongside for the picked-vs-passed read.

**No verdict creates a PLAY.** A `BEATS_MARKET` verdict is evidence for
an owner ruling, exactly as in the frozen tests.

## Frozen family: NBA player props (PTS / REB / AST / PRA)

The four NBA prop families are declared in `configs/nba_player_*.json`
under the **frozen** preregistration
`research/nba_props_forward_20261020/PREREG_NBA_PROPS_FORWARD_V1.md`
(sha256 `54363908…f86657bc79`, frozen 2026-10-20 by owner ruling) —
§12 of that document names this package as its evaluator, and the
configs pin it by path + sha256. Score them only through
`sportsedge.forward_validation.nba_props.evaluate_nba_props` (with
`load_nba_config`, which verifies the pin), never through the generic
entry point: the wrapper applies the prereg's §2 scope refusal
(`MARKET_OUT_OF_SCOPE`) and §5 engine-provenance screen (engine
stamp, `sufficiency_met`, `n_prior` ≥ 10, pool source, store
provenance, declared participation limitation) before the framework's
admission, and the configs declare the §9 picked/passed mode above.
Prospective counting begins with the Wednesday Oct 21, 2026 slate;
everything on or before the freeze date is historical record.
