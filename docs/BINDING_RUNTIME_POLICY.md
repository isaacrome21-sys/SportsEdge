# Binding runtime policy

A malformed or incomplete priced offer must not abort the full slate. The row is emitted as `BLOCKED` with the concrete binding error; other rows continue independently.

Binding validation belongs at the normalized quote/orchestration boundary and executes before model engine invocation. Card assembly is too late because rows rejected earlier would disappear from binding coverage.

The model layer must not synthesize `event_id`, `game_number`, `book_key`, executable price, retrieval timestamp, or canonical quote entity identities. Those originate at acquisition/normalization. Missing origin identity is a data gap and remains blocked.
