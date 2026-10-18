# NFL sides Elo v1: result (RESEARCH_EVIDENCE)

Prereg `05b2ecec…9038` locked at `f34f67bd` before any scoring. Corpus `a484c6ae…b284` (nflverse consensus closing lines).
Scored 2018–2025. Determinism: two runs byte-identical. The independent hand check
(`handcheck.py`, no evaluator import) reproduces the moneyline log losses exactly.

| Market | n | Log loss: Elo / closing market / naive | ΔLL Elo − market, 95% CI | Verdict |
|---|---|---|---|---|
| Moneyline | 2,219 | 0.6363 / **0.6089** / 0.6907 | +0.0274 [+0.0188, +0.0356] | **DOES_NOT_BEAT_CLOSE** |
| Spread | 2,175 | 0.7103 / **0.6925** / 0.6931 | +0.0178 [+0.0092, +0.0259] | **DOES_NOT_BEAT_CLOSE** |

The closing market is significantly better than Elo on both markets.

**Descriptive.** Flat bets at the close wherever Elo disagreed with the market by more than 3 pp:
- **Moneyline:** ROI −7.5% [−13.6%, −1.2%]; 67% of those bets were underdogs.
- **Spread:** ROI −3.6% [−8.4%, +1.3%]; 72% of those bets were underdogs.

That is the #2384 failure signature again. Rating models that disagree with the close mostly
back underdogs, and they lose doing it.

**Consequence.** The #2384 hold stays. A public team-rating model does not beat NFL closing
sides. Any future side candidate has to bring information the closing market lacks
(e.g. injuries or QB status known before the close) and pass this same gate.
