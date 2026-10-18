# NHL rate v1 — 2025–26 one-shot

Window spent. Do not retune.

Official `api-web.nhle.com/v1/score`, REG, 1,312 games, 10 skipped (<10 priors), **1,302 scored**.
Same stand-in features as the 2024–25 fit. 8k Poisson paths + one OT/SO goal if tied.

| Market | Pred | Obs | \|gap\| | Gate | Result |
|---|---:|---:|---:|---|---|
| Home win (final) | 56.4% | 52.2% | 4.27 pp | ≤ 5 pp | PASS |
| Over 5.5 | 56.1% | 57.5% | 1.31 pp | ≤ 6 pp | PASS |
| Over 6.5 | 45.3% | 46.9% | 1.67 pp | ≤ 6 pp | PASS |
| Home puck line −1.5 | 32.6% | 30.1% | 2.44 pp | ≤ 6 pp | PASS |

**PASS.** Home-win is the tight one. Totals are clean.

Promotion is a **separate PR**: freeze these coefficients, parity test vs this research copy, then flip the phone card from `NO_MODEL` to ML / puck line / totals only. Goals/points stay unsupported. Label stays `NOT Truth Gate / NOT OFFICIAL`.
