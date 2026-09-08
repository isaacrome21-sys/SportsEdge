# Review order

1. Run focused binding attacks.
2. Run full repository suite.
3. Inspect compatibility failures; do not weaken mandatory identity to make old fixtures pass.
4. Update upstream fixtures/adapters only where they can provide genuine source identity.
5. Adversarially review diff.
6. Merge only after governance invariants remain unchanged.
