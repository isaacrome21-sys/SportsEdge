# NHL frozen-rate total line binding guard

The current frozen NHL rate-card simulation exposes only `over_5_5` and `over_6_5` events.

The phone renderer must therefore bind totals only when the pasted line is exactly 5.5 or 6.5. It may not:

- treat 6.0 as 5.5 (a whole-number total needs explicit push mass at 6);
- treat 5.0 as 5.5;
- treat 7.5 as 6.5; or
- select a nearest grid probability for any unsupported total.

Unsupported total lines fail closed as `NO_MODEL:TOTAL_LINE_UNSUPPORTED_PUSH_OR_GRID` until the frozen simulation emits the exact event/push mass required for correct pricing.

This guard changes no NHL coefficients, training/validation result, model probability for supported lines, Score, staking, Truth Gate, or OFFICIAL authority.
