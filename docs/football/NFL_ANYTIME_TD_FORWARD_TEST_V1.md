**NFL Anytime-TD Forward Test, V1 (locked, owner-approved Oct 18, 2026)**

1. **Picked rows:** a row is YES if and only if the model's probability is greater than the raw implied probability of the Yes price at entry, with DraftKings' cut included. Otherwise it is PASS. No minimum edge.
2. **Unpriced rows:** rows the engine refuses, or whose names can't be matched, are recorded as UNPRICED with a reason. They count in neither the picked nor the passed group.
3. **Entry freeze:** selections are fixed at the entry capture. Later price moves don't change them.
4. **CLV:** the change in the Yes price's raw implied probability from pricing to close. Close is the last Yes-price capture before kickoff and no more than 60 minutes before kickoff. If no such capture exists, the row is CLV_MISSING with a named reason (NO_CLOSE_ROW or CLOSE_STALE). No de-vig, because every board is Yes-only. Known bias: DraftKings' cut drift counts as skill, most of all on longshots.
5. **BEATS_MARKET:** requires CLV above zero on picked rows, and picked rows must beat passed rows, plus a per-game check that DraftKings' cut didn't drift.
6. **Test length:** 4 full weeks, at least 150 picked rows and 40 games, game-clustered confidence intervals.
7. **Names:** captures must use full names or nflverse player_id.
8. **Settlement:** fumble and special-teams TDs settle as Yes, as DraftKings grades them.
9. **Edge (descriptive only):** edge = model_p / raw implied(Yes at entry) − 1. Picks are defined by rule 1, not by edge.

Notes:
- This supersedes the 2026-10-11 build note for forward-test purposes.
- Part 2 amendment still open.
- Locked prior to Thursday pricing.
