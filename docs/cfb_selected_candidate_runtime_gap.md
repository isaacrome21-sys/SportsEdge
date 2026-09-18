# CFB selected-candidate serving gap

The frozen CFB bakeoff contains four preregistered candidate families. The `GAMES_IN_SAMPLE_FEATURE` family appends two features beyond the canonical base joint-model vector. The existing production runtime currently loads and simulates `CFBJointScoreModel`, while the candidate fit surface is represented by `CFBCandidateScoreModel`.

Therefore the first candidate evaluation must not be consumed until the production artifact/runtime can serialize, load, hash-bind, and simulate the selected candidate family exactly. Otherwise the bakeoff could select a family that the serving runtime cannot faithfully execute.

This is a pre-attempt engineering blocker only. It creates no Model_P, Truth Gate, promotion, eligibility, staking, evidence-clock, backfill, or OFFICIAL authority.
