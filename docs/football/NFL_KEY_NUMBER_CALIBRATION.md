# NFL key-number calibration

The simulator consumes **signed** margin masses at +3/-3 and +7/-7. The real-history audit must therefore publish both `absolute_margin_pmf` and `signed_margin_pmf`.

Do not copy `P(|margin|=3)` to both +3 and -3. That doubles the empirical mass and corrupts spread probabilities. The calibration fitter fails closed unless the evidence is real public history, hash-bound, multi-season, and contains signed PMF entries for every requested key.

The fitted masses remain exact point masses inside `KeyNumberMarginModel`; the remaining probability is allocated to non-key margins by the discretized-normal component.
