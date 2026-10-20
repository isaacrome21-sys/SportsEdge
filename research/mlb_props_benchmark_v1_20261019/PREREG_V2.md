# Benchmark v2 preregistration (Oct 19, 2026, before any real-sample scoring)

Same as v1 (`README.md`) except one rule: **DK entry = DK's last quote at or before start − 3 hours** (`ENTRY_HOURS = 3`). The sharp fair price at entry uses only sharp quotes at or before that DK quote. The sharp close is the last sharp two-way quote at or before start. Script `bench_mlb_props_v2.py` (blob cf6c259e).

**Primary test:** edge ≥ 2%, flat 1-unit ROI, date-clustered CI. Verdict BEATS_MARKET_CI_EXCLUDES_0 only if the CI lower bound is above 0 with ≥ 200 bets and ≥ 10 dates. The 0% and 5% rows and CLV are secondary.

**Data rule:** v2 is scored once, on the first uncapped download (max_rows=0) that reaches a records branch with its sha256. The 4-game Oct 18 file was used only for smoke runs (v2: 65 paired quotes, 2 games, INSUFFICIENT_DATA) and is excluded from scoring.

Nothing here is a play.
