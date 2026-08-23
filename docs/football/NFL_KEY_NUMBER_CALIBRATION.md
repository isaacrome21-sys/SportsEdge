# NFL key-number behavioral validation

Historical signed margin frequencies at +3/-3 and +7/-7 are **validation targets only**. They must never be injected into the simulator as exact probability mass.

The real-history audit publishes both `absolute_margin_pmf` and `signed_margin_pmf`. Signed frequencies are required because NFL spread behavior is directional: `P(margin=+3)` and `P(margin=-3)` are separate empirical targets. Do not copy `P(|margin|=3)` onto both signs.

The simulator must generate its margin distribution without receiving historical key-number frequencies as an input. After simulation, emergent signed frequencies are compared with held-out, hash-bound, multi-season historical targets under the contract `EMERGENT_VALIDATION_TARGET_V1`.

Acceptance means the emergent frequencies are within the frozen historical tolerance for the stated validation window. It does **not** mean the simulator is instructed to reproduce those frequencies. The historical-window choice remains a design decision because NFL scoring rules and kicking environments are not stationary across all eras.

Any artifact or API that supplies non-empty `empirical_key_mass` to the simulator is non-compliant and must fail closed.
