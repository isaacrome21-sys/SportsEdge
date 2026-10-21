# Check E — coverage instrument

Authority: issue #2447 comments 6308060982 (governing bars) and 6315337229
(explicit build GO). >=90% **in each sampled window**, per sport/market/book;
unsampled cells remain explicitly NO_DATA. No threshold override.

API: `evaluate_check_e(payload)` in `sportsedge/oddspapi_check_e.py`.
Input schema and examples are in `tests/test_oddspapi_check_e.py`. Caller
supplies a complete frozen cell universe and expected unit IDs for every
sampled window, separately from observed IDs. Expected and observed IDs must
use identical fixture/selection granularity. Missing units remain in the
denominator; extra units and duplicate IDs/cells/windows refuse. Windows
are never pooled to rescue poor coverage. An empty denominator is NO_DATA.

Synthetic verification: `python -m unittest discover -s tests -p
'test_oddspapi_check_e.py' -v`: 8 tests passed. No real provider data read.

The manifest hash is shape-checked, not independently authenticated. A caller
can omit a cell from the supplied universe; source acquisition and the admission
runner must compare the entire universe to its independently frozen manifest.
This calculator cannot prove completeness from hash strings. No global source
admission verdict is emitted. Every result remains NOT_ADMITTED, eligible
false and play_authority false. Independent exact-head verification required.
