# RED evidence — Total Hits conservation battery vs PR #2334 candidate

Candidate: branch `research/mlb-aligned-total-hits-20261015`, exact head
`04d2c3a1b9c729a571dd368a04ce6331e51024fb`, construction module
`sportsedge/research/mlb_joint_total_hits.py` UNMODIFIED.

Battery: `tests/test_research_mlb_joint_total_hits_conservation.py` (this PR).
Run executed locally against the exact head; junit counts read from the
on-disk junit XML produced by that run:

**16 tests — 11 failed, 5 passed, 0 errors, 0 skipped.**

Every failure below is the same assertion kind: the test required a named
`TOTAL_HITS_*` refusal and the candidate instead returned a priced readout,
which the failure message records verbatim. For every witness-only mutation
(items 1, 2 and the truncated/extended pitcher-sample cases) the returned
`readout_sha256` is `48cd83a64be529df8bc76f6d021106c96f22e502af265bab9b86e8e44fed52cd`
— byte-identical to the readout of the UNMUTATED snapshot — proving the
candidate never reads the pitcher witness values at all.

## Failing tests (RED — the defect)

### `test_opponent_team_hits_contradiction_must_refuse[HME-P-0-1]`

```
AssertionError: expected a named TOTAL_HITS_* refusal, but the candidate silently priced a distribution: research_p=0.7083333333333334, push_p=0.0, count_pmf={'10': 0.041666666666666664, '11': 0.041666666666666664, '12': 0.08333333333333333, '13': 0.08333333333333333, '16': 0.20833333333333334, '17': 0.08333333333333333, '18': 0.125, '19': 0.041666666666666664, '20': 0.08333333333333333, '22': 0.125, '23': 0.041666666666666664, '9': 0.041666666666666664}, readout_sha256=48cd83a64be529df8bc76f6d021106c96f22e502af265bab9b86e8e44fed52cd
```

### `test_opponent_team_hits_contradiction_must_refuse[AWY-P-7-2]`

```
AssertionError: expected a named TOTAL_HITS_* refusal, but the candidate silently priced a distribution: research_p=0.7083333333333334, push_p=0.0, count_pmf={'10': 0.041666666666666664, '11': 0.041666666666666664, '12': 0.08333333333333333, '13': 0.08333333333333333, '16': 0.20833333333333334, '17': 0.08333333333333333, '18': 0.125, '19': 0.041666666666666664, '20': 0.08333333333333333, '22': 0.125, '23': 0.041666666666666664, '9': 0.041666666666666664}, readout_sha256=48cd83a64be529df8bc76f6d021106c96f22e502af265bab9b86e8e44fed52cd
```

### `test_opponent_team_hits_contradiction_must_refuse[HME-P-23--1]`

```
AssertionError: expected a named TOTAL_HITS_* refusal, but the candidate silently priced a distribution: research_p=0.7083333333333334, push_p=0.0, count_pmf={'10': 0.041666666666666664, '11': 0.041666666666666664, '12': 0.08333333333333333, '13': 0.08333333333333333, '16': 0.20833333333333334, '17': 0.08333333333333333, '18': 0.125, '19': 0.041666666666666664, '20': 0.08333333333333333, '22': 0.125, '23': 0.041666666666666664, '9': 0.041666666666666664}, readout_sha256=48cd83a64be529df8bc76f6d021106c96f22e502af265bab9b86e8e44fed52cd
```

### `test_team_market_witness_contradiction_must_refuse`

```
AssertionError: expected a named TOTAL_HITS_* refusal, but the candidate silently priced a distribution: research_p=0.0, push_p=0.0, count_pmf={'10': 0.08333333333333333, '11': 0.041666666666666664, '12': 0.08333333333333333, '13': 0.08333333333333333, '14': 0.041666666666666664, '3': 0.041666666666666664, '4': 0.08333333333333333, '5': 0.08333333333333333, '6': 0.041666666666666664, '7': 0.20833333333333334, '8': 0.041666666666666664, '9': 0.16666666666666666}, readout_sha256=fa11028acc113a8097e6718dd5c93f04e0f6cca681ffb2290a9823bec3423709
```

### `test_hits_allowed_decomposition_contradiction_must_refuse`

```
AssertionError: expected a named TOTAL_HITS_* refusal, but the candidate silently priced a distribution: research_p=0.7083333333333334, push_p=0.0, count_pmf={'10': 0.041666666666666664, '11': 0.041666666666666664, '12': 0.08333333333333333, '13': 0.08333333333333333, '16': 0.20833333333333334, '17': 0.08333333333333333, '18': 0.125, '19': 0.041666666666666664, '20': 0.08333333333333333, '22': 0.125, '23': 0.041666666666666664, '9': 0.041666666666666664}, readout_sha256=48cd83a64be529df8bc76f6d021106c96f22e502af265bab9b86e8e44fed52cd
```

### `test_bullpen_decomposition_contradiction_must_refuse`

```
AssertionError: expected a named TOTAL_HITS_* refusal, but the candidate silently priced a distribution: research_p=0.7083333333333334, push_p=0.0, count_pmf={'10': 0.041666666666666664, '11': 0.041666666666666664, '12': 0.08333333333333333, '13': 0.08333333333333333, '16': 0.20833333333333334, '17': 0.08333333333333333, '18': 0.125, '19': 0.041666666666666664, '20': 0.08333333333333333, '22': 0.125, '23': 0.041666666666666664, '9': 0.041666666666666664}, readout_sha256=48cd83a64be529df8bc76f6d021106c96f22e502af265bab9b86e8e44fed52cd
```

### `test_batter_hit_added_without_witness_update_must_refuse`

```
AssertionError: expected a named TOTAL_HITS_* refusal, but the candidate silently priced a distribution: research_p=0.7083333333333334, push_p=0.0, count_pmf={'10': 0.041666666666666664, '11': 0.041666666666666664, '12': 0.08333333333333333, '13': 0.08333333333333333, '16': 0.16666666666666666, '17': 0.125, '18': 0.125, '19': 0.041666666666666664, '20': 0.08333333333333333, '22': 0.125, '23': 0.041666666666666664, '9': 0.041666666666666664}, readout_sha256=2cefb112fafec3d302733e0783086381405942c6a5b0d7e80ac6aab84384584a
```

### `test_batter_hit_removed_without_witness_update_must_refuse`

```
AssertionError: expected a named TOTAL_HITS_* refusal, but the candidate silently priced a distribution: research_p=0.7083333333333334, push_p=0.0, count_pmf={'10': 0.041666666666666664, '11': 0.041666666666666664, '12': 0.08333333333333333, '13': 0.08333333333333333, '16': 0.20833333333333334, '17': 0.125, '18': 0.08333333333333333, '19': 0.041666666666666664, '20': 0.08333333333333333, '22': 0.125, '23': 0.041666666666666664, '9': 0.041666666666666664}, readout_sha256=d27e6ca48ebd4d8cfe1b0a80fc0cd7ae5d08f7f35718d5073990b989cdb70539
```

### `test_swapped_path_indices_in_one_hitter_row_must_refuse`

```
AssertionError: expected a named TOTAL_HITS_* refusal, but the candidate silently priced a distribution: research_p=0.7083333333333334, push_p=0.0, count_pmf={'10': 0.08333333333333333, '11': 0.041666666666666664, '12': 0.08333333333333333, '13': 0.08333333333333333, '15': 0.041666666666666664, '16': 0.16666666666666666, '17': 0.08333333333333333, '18': 0.125, '19': 0.041666666666666664, '20': 0.08333333333333333, '22': 0.125, '23': 0.041666666666666664}, readout_sha256=799d9693eb2aba24bc58f699ac28088bfc441c3125c4c18169121f17e6de3879
```

### `test_pitcher_samples_truncated_must_refuse`

```
AssertionError: expected a named TOTAL_HITS_* refusal, but the candidate silently priced a distribution: research_p=0.7083333333333334, push_p=0.0, count_pmf={'10': 0.041666666666666664, '11': 0.041666666666666664, '12': 0.08333333333333333, '13': 0.08333333333333333, '16': 0.20833333333333334, '17': 0.08333333333333333, '18': 0.125, '19': 0.041666666666666664, '20': 0.08333333333333333, '22': 0.125, '23': 0.041666666666666664, '9': 0.041666666666666664}, readout_sha256=48cd83a64be529df8bc76f6d021106c96f22e502af265bab9b86e8e44fed52cd
```

### `test_pitcher_samples_extended_must_refuse`

```
AssertionError: expected a named TOTAL_HITS_* refusal, but the candidate silently priced a distribution: research_p=0.7083333333333334, push_p=0.0, count_pmf={'10': 0.041666666666666664, '11': 0.041666666666666664, '12': 0.08333333333333333, '13': 0.08333333333333333, '16': 0.20833333333333334, '17': 0.08333333333333333, '18': 0.125, '19': 0.041666666666666664, '20': 0.08333333333333333, '22': 0.125, '23': 0.041666666666666664, '9': 0.041666666666666664}, readout_sha256=48cd83a64be529df8bc76f6d021106c96f22e502af265bab9b86e8e44fed52cd
```

## Passing tests (GREEN — positive controls)

- `test_simulated_paths_conserve_hits_end_to_end`
- `test_unmutated_snapshot_is_accepted`
- `test_correlated_fixture_with_consistent_witnesses_is_accepted`
- `test_missing_pitcher_row_refuses_by_name`
- `test_duplicate_pitcher_row_refuses_by_name`

The controls establish: (a) the simulator's own paths conserve — on every
path, each starter's `opponent_team_hits` equals the opposing lineup's summed
batter hits and `hits_allowed + bullpen_hits_allowed` decomposes it exactly;
(b) the unmutated snapshot and a perfect-correlation fixture with consistent
witnesses are accepted, so the battery is green when evidence is consistent;
(c) the player-set refusals the candidate already performs (missing/duplicate
pitcher row -> `TOTAL_HITS_PLAYER_SET_INVALID`) still fire by name.

Neighbouring suites on the same head, same session: the candidate's own 24
tests and the production total-hits battery (22) all pass; combined run of
the three files: 62 tests, 11 failed (only the REDs above), 51 passed.

No assertion in this battery was weakened to reach this state; the RED state
is the deliverable. The implementation fix belongs to the construction
owner's branch (#2334); when the candidate learns to refuse, these tests
turn green without modification.
