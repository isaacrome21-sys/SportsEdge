# MLB PIT watcher current-main transplant

This branch restores the previously verified Actions-independent PIT watcher onto the current `main` without changing model pricing, settlement, promotion thresholds, or evidence semantics.

The code is a content transplant of the previously targeted-tested watcher/CLI contract. Integration scope is isolated to four runtime/test files plus this note. The watcher only captures and publishes immutable PIT evidence to the `data` branch.
