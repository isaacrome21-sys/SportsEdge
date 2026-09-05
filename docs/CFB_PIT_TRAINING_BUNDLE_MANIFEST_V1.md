# SportsEdge CFB PIT Training Bundle + Source Manifest V1

Status: **TIER-0 REQUIRED INPUT CONTRACT**

This is the front-door evidence contract for building `models/cfb_joint_v1.json`. A frozen CFB model may not be built from a training bundle that merely contains a claimed source-manifest hash. The exact source-manifest file must be supplied to the builder and its SHA-256 must match the hash embedded in the training bundle.

## 1. Required files

A candidate build requires both immutable JSON inputs:

1. `cfb_pit_training_bundle.json`
2. `cfb_pit_source_manifest.json`

The exact bytes of both files are hashed. Reformatting either JSON file changes its identity and therefore creates a different evidence object.

The builder invocation is:

```bash
python3 scripts/build_cfb_model_artifact.py \
  --training-bundle path/to/cfb_pit_training_bundle.json \
  --source-manifest path/to/cfb_pit_source_manifest.json \
  --fit-max-season 2025 \
  --ridge-alpha 10.0 \
  --output models/cfb_joint_v1.json \
  --provenance-output artifacts/cfb/cfb_model_training_provenance.json
```

Runtime AUTO never performs this fit.

## 2. Source manifest schema

Top-level contract:

```json
{
  "schema_version": "CFB_PIT_SOURCE_MANIFEST_V1",
  "generated_at_utc": "2026-09-05T18:00:00+00:00",
  "fit_max_season": 2025,
  "training_window": {"min_season": 2014, "max_season": 2025},
  "materializer_version": "CFB_JOINT_HISTORY_PIT_V1",
  "feature_contract": "CFB_JOINT_GAME_FEATURES_V1",
  "post_cutoff_information_excluded": true,
  "market_data_used_as_model_feature": false,
  "sources": []
}
```

Every source entry requires:

- `source_id` — stable unique id within the manifest
- `role` — one of `FEATURE_INPUT`, `LABEL`, `UNIVERSE`
- `provider` — source/provider identity
- `dataset` — dataset or endpoint identity
- `locator` — auditable storage locator; never a secret/token
- `retrieved_at_utc` — timezone-aware retrieval/materialization timestamp
- `content_sha256` — SHA-256 of the frozen source payload represented by the entry
- `availability_mode` — one of `PRE_EVENT_ARCHIVE`, `EVENT_TIMESTAMPED_REPLAY`, `POST_EVENT_LABEL`
- `availability_rule` — human-auditable rule stating exactly what information was eligible at each game cutoff
- `market_data` — must be `false`
- `post_cutoff_excluded` — must be `true`
- `seasons` — explicit seasons covered by that frozen source object

A source with `role=LABEL` must use `availability_mode=POST_EVENT_LABEL`. A non-label source may not use `POST_EVENT_LABEL`.

### Interpretation of availability modes

`PRE_EVENT_ARCHIVE` means the feature payload itself was captured before the target event.

`EVENT_TIMESTAMPED_REPLAY` means the underlying observations are timestamped and the deterministic replay/materializer enforces an as-of cutoff before target kickoff. This does **not** mean a present-day endpoint is automatically PIT-safe; the source and transform must make the historical availability rule auditable.

`POST_EVENT_LABEL` is reserved for realized training labels such as final scores. Label data may be known after an individual game ends, but the frozen training set may not contain labels from seasons after `fit_max_season`.

`EX_POST_RECONSTRUCTION` is intentionally not an accepted mode for frozen production training evidence.

## 3. Training bundle schema

The training bundle must contain:

```json
{
  "schema_version": "CFB_PIT_TRAINING_BUNDLE_V1",
  "materializer_version": "CFB_JOINT_HISTORY_PIT_V1",
  "generated_at_utc": "2026-09-05T18:00:00+00:00",
  "source_manifest_sha256": "<sha256 of exact cfb_pit_source_manifest.json bytes>",
  "rows": []
}
```

Each row is one completed FBS game and must satisfy the canonical `CFB_JOINT_GAME_FEATURES_V1` model contract. At minimum it carries:

- `game_id`
- `season`
- `week`
- `neutral_site`
- `home_metrics`
- `away_metrics`
- `weather`
- `home_score`
- `away_score`
- optional paired regulation scores for overtime reconstruction

`home_metrics` and `away_metrics` are the pregame team snapshots selected by the historical materializer. Week 2+ uses the exact current-season snapshot through `week - 1`; Week 1 uses the explicit immediately-prior-season fallback required by the materializer. Feature snapshot timestamps must be strictly before kickoff.

The model surface rejects market fields such as spread, total, line, price, implied probability, no-vig probability, book, sportsbook, moneyline, closing line, closing price, and odds.

## 4. Source checklist before the bundle is accepted

For every raw source used to construct the bundle, verify:

- exact provider/dataset identity is named
- immutable source bytes or a reproducible content-addressed snapshot exist
- SHA-256 is recorded
- seasons covered are explicit and do not exceed 2025 for the 2026 base candidate
- source role is explicit: feature, label, or universe
- pregame feature availability is demonstrable, not inferred from a current endpoint
- market/odds data are absent from feature sources
- final scores are label-only
- FBS membership is season-specific
- weather has an availability basis appropriate to the target kickoff; do not silently substitute realized postgame weather for a pregame forecast feature
- no injury, lineup, line movement, closing market, final score, or other observation from after the applicable feature cutoff is embedded in a feature snapshot

If any item is unknown, status is `DATA_GAP`; the source is not silently upgraded to PIT-safe.

## 5. Provenance emitted alongside the artifact

`artifacts/cfb/cfb_model_training_provenance.json` now records:

- model id
- feature contract
- artifact SHA-256
- model code-surface SHA-256
- training code-surface SHA-256
- training-bundle SHA-256
- exact upstream source-manifest SHA-256
- source-manifest schema
- source count and source ids
- game-id set SHA-256
- historical materializer version
- bundle generation timestamp
- `fit_max_season`
- observed training seasons
- training window
- row count
- ridge alpha
- training seed policy
- `promotion_changed=false`

The current base fit is deterministic ridge regression, so its training seed policy is explicitly `NONE_DETERMINISTIC_RIDGE_V1`; a fake random seed must not be recorded. Runtime Monte Carlo seeds are a separate execution concern.

## 6. Build acceptance sequence

The builder must fail before fitting if any of the following is false:

1. training bundle parses and has the expected schema/materializer version
2. source manifest parses and has the expected schema/materializer/feature contract
3. manifest cutoff equals the requested `fit_max_season`
4. exact source-manifest bytes hash to the value embedded in the bundle
5. feature and label source roles are both present
6. all sources explicitly exclude post-cutoff data
7. all training sources explicitly set `market_data=false`
8. no non-label source is post-event label data
9. the latest represented row season equals `fit_max_season`
10. no row season exceeds the cutoff

Only then may the joint model fit and artifact packaging occur.

## 7. What this contract does not prove

A syntactically valid manifest does not prove that a provider's historical endpoint was genuinely available at an earlier date. The evidence still has to support the declared `availability_rule`. The historical materializer itself explicitly does not make that provenance claim.

Likewise, successful artifact construction is not model validation and does not promote any CFB market. The frozen artifact still must pass the predeclared chronological OOS and untouched forward evidence gates in `CFB_BASE_ARTIFACT_AND_VALIDATION_GATE_V1.md` before any `SPORTSEDGE OFFICIAL` status is possible.
