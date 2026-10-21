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
