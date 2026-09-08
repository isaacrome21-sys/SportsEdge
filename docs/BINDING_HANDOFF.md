# Binding handoff

Implementation branch: `chatgpt/binding-value-scanner-v1`.

Review focus: verify existing engines/readouts can supply explicit period, probability threshold, and probability team identity without copying them from sportsbook quotes; then wire real acquisition adapters to canonical event/team/player identity. Any temptation to fill missing binding fields from the quote inside the model/readout must be rejected.
