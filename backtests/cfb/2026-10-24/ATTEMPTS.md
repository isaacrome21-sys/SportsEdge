# CFB attempt log

1. Original prior-seasons-only SDV diagnostic is preserved unchanged in sdv_initial_diagnostic.json.
2. Added descriptive bias/baseline audit, executed Oct 25 with the same constants, family and ridge alpha. No model tuning. Reproduce: `python backtests/cfb/2026-10-24/run_sdv_bias_audit.py --rows INPUT.json --output OUTPUT.json`.

2025 (706 rows): mean predicted 56.32045 versus actual 52.21955; 434 overpredictions / 272 underpredictions; prediction SD 4.73908 vs outcome SD 16.16062. These are prediction-versus-final counts, NOT OVER/UNDER bets versus a market line. SDV total MAE 13.20583 vs flat 56 comparator 13.43768. Flat 56 is only a constant baseline, not an executed opponent-adjusted forecast.

Source audit: data commit 53d9452f8140cf7769d4ef0a5e1a057e57a622cf, history/cfb/sportsdataverse-selection/training_manifest.json explicitly sets historical_pit=false and MATERIALIZED_ZERO_AUTHORITY. Raw receipts reference current downloadable SDV releases and hashes, not historical availability timestamps. All 6,620 rows contain historical weather; weather feature records lack forecast issuance/availability time. Season/week metadata checks pass, but these cannot prove PIT weather. Keep RECONSTRUCTED_HISTORICAL_NOT_PIT.

Opponent-adjusted replay remains pending: the SDV rows lack actual kickoff/spread, while canonical project() requires both. Do not insert synthetic spreads or kickoff timestamps. Muse #2603 supplies a 2022 SBR archive candidate (partial season; no 2023–25 confirmed complete archive); spread/total line values alone do not supply paired prices. Further schedule/archive matching is needed before replay. No paired-market verdict, CLV, ROI or EV>=2% count is available.
