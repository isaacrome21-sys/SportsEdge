# Grok ruling: screen_only guard residual (2026-10-23)

Status: SCREEN / NOT_VALIDATED. Governs `sportsedge/screen_only_guard.py` (t256).

## Ruling D: ACCEPTED_RESIDUAL

An in-process Python guard cannot stop a determined caller. Closure reflection
(`require_screen_only.__closure__`), writing a module's `__dict__` directly,
frame/`ctypes` tricks, or editing the source files all defeat any guard that
runs in the same interpreter. The guard exists to prevent MISTAKES (production
code accidentally reaching an unrestricted / NAIVE_FAIL pricer), not determined
bypasses.

Cheap detection is still in place and tested
(`tests/test_screen_only_bypasses_v2_20261023.py`):
- `checked_require()` compares the guard function to a pinned reference, so a
  replaced or closure-rebuilt function refuses with `GUARD_TAMPERED`;
- every read of `NAIVE_FAIL_FAMILIES` is checked against a pinned sha256 of the
  sorted family list (`NAIVE_FAIL_FAMILIES_TAMPERED`);
- guard and pricer modules refuse attribute rebinding (`LOCKED_ATTRIBUTE`).

## Rulings 5, A, B, C (fixed, not residual)
- 5: entry refused if any repo frame above it is outside research/ or tests/;
  at pricing time every repo frame between entry and pricer must be research/,
  tests/, guard, or registered pricer internals. Static test: no
  sportsedge/ or scripts/ file imports `research.*`.
- A: the entering file must exist, its module `__file__` must match, and the
  real source line (linecache) must call screen_only.
- B: pricers call `checked_require` (identity-checked against the pin); module
  attributes are locked.
- C: `NAIVE_FAIL_FAMILIES` is a frozenset, attribute-locked, and sha256-pinned.

Not a validation result. play_allowed=false. Owner review required before merge.
