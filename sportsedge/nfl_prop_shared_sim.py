RATE_KEYS = frozenset({"completion_rate", "pass_td_rate", "interception_rate", "catch_rate"})
# Yardage efficiency can legitimately be signed in tiny samples (for example a
# receiver with one catch for negative yardage). The live-role source already
# permits signed passing/rushing/receiving yardage, so the stabilized-role
# contract must not reject the derived efficiency before the coherent team
# allocator can pool it with the rest of the offense.
SIGNED_EFFICIENCY_KEYS = frozenset({
    "pass_yards_per_completion",
    "rush_yards_per_attempt",
    "receiving_yards_per_reception",
})
RARE_RATE_KEYS = frozenset({"pass_td_rate", "interception_rate"})