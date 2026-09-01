# Stage 0 local execution note

Date: 2026-08-19 America/Chicago
PR: #96
Head at original local check: `a88dfcc484b33ab7f1a43ffc58aedbdb27ef3ec6`

GitHub-hosted CI was failing before any job steps executed, so the original CI attempts did not provide test evidence.

To avoid treating the stage as completely blocked, the exact PR-head source for `sportsedge/market_surface.py` and `tests/test_market_surface.py` was fetched through the connected GitHub repository interface and executed in a temporary local Python workspace with pytest.

Result:

```
....                                                                     [100%]
4 passed in 0.05s
```

This establishes only that T1-T4 execute and pass against the fetched PR-head market-surface implementation. It does **not** satisfy the merge gate, does not prove the full repository test suite passes, and does not replace the requirement for green GitHub CI on the eventual merge SHA.

Historical dataset note: the model runtime environment could not clone the private repository over the network, so the exact local git-history commands (`git lfs ls-files`, `git log --all --diff-filter=A ...`) could not be executed here. GitHub-side inspection found no `.gitattributes` file on `main`, no current code-search hits for `parquet`, and commit-history searches show odds/archive implementation commits but do not establish whether a historical dataset was ever added. Therefore the historical-dataset question remains unresolved until those exact commands are run in an authenticated clone.

## 2026-09-01 fresh CI recovery attempt

GitHub Actions access was reported restored. Re-running the old failed workflow attempts still produced the same zero-step/BlobNotFound signature, so those old attempts remain non-evidence. This commit exists to force a **fresh pull-request synchronization run on a new head SHA**. Only fresh runs that execute real job steps can satisfy Stage 0 CI evidence; old rerun metadata must not be treated as recovery.
