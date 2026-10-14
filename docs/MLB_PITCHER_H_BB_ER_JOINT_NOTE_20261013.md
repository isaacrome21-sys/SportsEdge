# MLB pitcher H+BB+ER — joint-vs-marginal check (2026-10-13)

Question: does `PITCHER_HITS_WALKS_ER` sum independent marginals?

Answer: **No.** Every pricing path sums the three counts *within the same start*,
so the within-start dependence (hits and walks drive earned runs) is preserved:
* `pitcher_joint_engine._value`: `hits_allowed + walks_allowed + earned_runs` per
  history row (empirical-Bayes over joint start rows; long-window prior pool is
  also joint rows). No fallback for this market (`_FALLBACK_STAT` excludes it).
* `mlb_joint_card_research._pitcher_value` and
  `research/mlb_joint_market_readout` sum fields per simulated path.
No convolution of separate H, BB, ER distributions was found.

Therefore it is **not** flagged BLOCKED for independence. Existing restrictions stay:
postseason blocked (`MLB_POSTSEASON_PITCHER_HITS_WALKS_ER_BIASED`, #1973, +0.034
over-bias); the market is not validated against genuine DK odds; and the catalog
audit (#2090) found it marked priced while surfacing as unavailable — that is a
registry/coverage defect for the integration lane, not a model-independence one.

Remaining modeling gap (prereg proposal, not evaluated): the empirical pool is a
5–10 start sample of a sum with wide support, so the posterior is coarse; a
structured joint model (BB ~ NB(exposure), H ~ NB(exposure), ER | H,BB ~ NB with
mean linear in H+BB, sharing a start-level exposure/outs latent) is pre-registered
as a 2027 challenger in `docs/MLB_JOINT_TEAM_RUNS_2027_PREREG.md` §B.
