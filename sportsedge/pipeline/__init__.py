"""One pipeline for every sport and market.

lines issue -> ``intake.parse_issue`` -> model price (sport engine, unchanged)
-> ``picks.PickRecord`` -> snapshot (``snapshot_hook``) -> ``grading.grade``
-> ``grading.no_vig_clv`` -> ``ladder`` status.

Only the probability engine differs per sport. Adapters in ``adapters`` map
market names and team names; they contain no parsing or pricing logic.
"""
