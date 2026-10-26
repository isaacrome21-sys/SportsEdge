# MLB game lines G1 — construction and market-validation protocol

**2026-10-26 · DRAFT / RESEARCH ONLY / NOT FROZEN / NOT IMPLEMENTED / NOT VALIDATED.**
Owner commission: create the first *new* MLB game-lines construction after the retirement of Lane A and closure of V8. The existence of older V7, Lane A, card derivatives, or score-readout research **does not** make G1 an operational construction. This document only fixes the intended test design and stop conditions; it grants no prices, counted rows, production wiring, freeze, or PLAY authority.

## 1. One version, one coherent game path

Working candidate name: `mlb_game_lines_g1_joint_runs_v0_draft`. Its output must be a normalized joint distribution over final official away/home runs, with `P(final_away == final_home) == 0`. It must settle all four primary DK families from **the same simulated games**, not independently fitted binary pick models:

| Family | Derive from official final score | Notes |
| --- | --- | --- |
| MONEYLINE | away/home final-score winner | Includes postseason/regular-season extra innings, never ties |
| RUN_LINE | final run difference at the captured handicap | Respect price, push possibility for integer alternative lines |
| TOTAL | sum of final runs at captured line | Over, under, and push probabilities sum to one |
| TEAM_TOTALS | each team's final runs at its captured line | Report each side separately, retain correlated paths |

A full-inning representation should account for actual home-team batting truncation (no bottom ninth when unnecessary), extra-inning rules for the season/game type (including the regular-season automatic runner but **not** in postseason), and official end-of-game settlement. An independent-product final-score construction that strands tied final scores is expressly inadmissible. All path probability checks and settlement parity tests must pass before any market validation.

**Planned feature families**, pre-event and source-stamped: prior-only team offense by batting order/opponent handedness; opposing starter expected innings and ability with uncertainty; bullpen prior usage/availability and opponent prevention; park/roof/weather; verified home/away and lineup/starter identity. Any omitted item must be explicit. No book price, implied probability, future lineup, postgame event, or outcome enters candidate features.

**Planned estimation family:** shrinkage-centered hierarchical count intensity per half inning (team/opponent factors, pitcher role weights, park/environment), with a shared game-run-environment latent variable inducing dependence. The final mathematical formula, priors, feature transforms, sample cutoffs, seed, simulation count, and code SHA are **OPEN DESIGN ITEMS** that must be fixed in a second candidate-spec commit *before running the sealed comparison*. No grid search or alternate candidate may be retroactively described as G1. Until that specification and executable tests exist, status is `NO_CONSTRUCTION`, not `MODEL_READY`.

## 2. Source and as-of admissibility

Join official MLB StatsAPI `gamePk`, UTC scheduled/actual start, teams, venue, game type, starting pitchers, lineups, final run path, and MLB outcome to the exact captured DK event id, teams, market and selection. Save raw input bytes, source URL, fetched-at UTC, sha256, normalized fields, and versioned feature bytes. Reject duplicate/mismatched game identity, invalid/naive time, after-decision fetch, unknown starter/lineup where required, or uncertified final.

The quote ledger needs actual *quote* capture time, bookmaker/market/line/price/selection, paired sides and separately captured later close. Never substitute GitHub issue creation time, a screenshot posting time, an entry quote for its own close, or an after-start line. Apply the current cross-sport quote-age/pairing policy as independently enforced by the pipeline (owner's Oct 26 all-sports 30-minute age maximum applies to quote usability); log exact failure reason per excluded row. A close must be an independent, later, pre-event capture within the standing close window (at most 60 minutes before start). Missing historical timestamps mean `NO_VERIFIED_CLV`, never invented closing-line movement.

Game-time starter or lineup scratches trigger a newly timestamped rerun only if sources and prices remain valid. Never backfill a missed pre-event prediction or overwrite an immutable prior prediction. Keep one canonical scored decision per `event_id × family × selection × capture-window × model_version` (duplicate records are explicit exclusions); maintain source-to-row SHA links.

## 3. Chronological research design (not a result)

1. **Dataset audit first:** enumerate seasons, games, complete results, starter/lineup PIT coverage, exact-entry and exact-close quote availability, missingness/exclusions, and distinct model hashes. Separate MLB regular season from postseason/extra-inning regimes. Historical game scores without independently captured DK prices can support outcome accuracy only, never market EV or verified CLV.
2. **Design:** use 2023–2024 as the initially proposed development era; 2025 may be a *labeled research selection window* after a predeclared single comparison; 2026 historical rows are diagnostics only if already inspected. Reconcile vintage availability before sealing dates. No fitted parameter, normalization, or feature may see events after its own as-of cutoff. A single game and all its simultaneous market selections stay on one side of every split.
3. **Seal one candidate:** final algorithm + model/config/source hashes + chosen analysis windows + metrics + sample floors + missing-data rule + clock, committed before examining the independent evaluation outcome. If the prior 2025 window was already consulted while designing, label it contaminated and use only a genuinely unused prospective window for confirmation.
4. **Chronological backtest:** walk forward, refitting only on previously completed and available inputs (settlement must have been observable before each training decision), preserving original timestamps. Compare candidate to prior incumbent, simple prior-only/climatology baselines, and the contemporaneous no-vig DK market **on identical eligible games/selections**. No synthetic or untimestamped price receives a market-grade claim.
5. **Frozen forward leg:** owner approves a separate immutable prereg/version and names the first future slate. Only predictions *committed before each game's start and after freeze* count. No backfill. Score each family independently until the owner's ≥50 graded forward picks, positive mean verified CLV and positive actual-odds ROI floor is satisfied; retain all additional family-specific minimum games/slates and uncertainty requirements of the active evaluator.

## 4. One-shot scoring and negative outcomes

Pre-register every reported metric and denominator. On the same matched games: moneyline binary log loss/Brier and calibration; full-run joint distribution proper score and marginal run calibration; spread/total/team-total event probabilities at actual quoted lines, Brier/log loss, hit/push rates, market-relative probability error; flat one-unit settled ROI using **recorded actual odds** and explicit pushes; paired entry-vs-later-close verified CLV with sign/price convention recorded. Report grouped-by-game/date block-bootstrap confidence intervals and both weighted/unweighted views only if specified before the sealed run. Correctly account for multiple outcomes of one game as correlated; never inflate N by counting both sides as independent games.

Verdicts per family: `NO_CONSTRUCTION`, `NO_DATA`, `NO_MARKET_TEST`, `DOES_NOT_BEAT_MARKET`, `INSUFFICIENT_SAMPLE`, `INSUFFICIENT_CLOSE_DATA`, or `ELIGIBLE_FOR_OWNER_PROMOTION_REVIEW` only after **all** frozen forward gates. A failed screen retires the exact tested version; refinements are new challengers on a new clock. Do not optimize thresholds from losing bets, market-close hindsight, or hand-selected subgroups.

## 5. Acceptance tests required before freeze

- Source/game-identity conflicts, non-PIT starter/lineup, stale/missing odds and after-start captures fail closed with named reasons.
- Regular-season and postseason extra innings; walk-off and absent bottom ninth; no official tied final; run-line/total/team-total coherent settlement including push at integer lines.
- Probability mass finite, nonnegative, normalized; deterministic seed reproducibility; dependence retained across all market prices.
- Train/selection game-cohort leakage, differing timestamps for same game, unobserved training settlements, duplicate row ids, contaminated version mixes, zero prices/NaNs all refuse.
- A genuinely unseen fixture produces exactly one immutable pre-start prediction receipt, and a second independent later close receipt; a missing close stays `CLV_MISSING`.
- Replay parity from archived source bytes and pinned code, plus negative tests where one changed input byte or wrong model pin refuses evaluation.

## 6. Build sequence and owner hold

`source census → implementation+fixtures → final candidate prereg/pins → chronological sealed score vs DK close → independent review → owner freeze of a named future slate → forward accumulation → separate promotion decision`.

**Current result: zero G1 priced rows, zero G1 backtest decisions, zero G1 forward graded picks.** Old MLB game-line estimates remain disqualified from being advertised as a verified G1 model. All SportsEdge sports remain PAPER / 0u.


## 7. 2027 forward-clock and adjacent work reconciliation (Oct 26 follow-up)

A separate owner-side design has been reported under the name `MLB_GAME_DIST_V1`, while this draft uses the working name `mlb_game_lines_g1_joint_runs_v0_draft`. These **must not become two independent freeze clocks by accident**. A future owner-reviewed final candidate must select **one canonical name, implementation hash and prospective freeze record**; this G1 name is provisional. The proposed first *eligible* forward slate is **2027 MLB Opening Day**, contingent on a before-game freeze and actual receipt/source gates. Remaining 2026 World Series games are shakedown/research only, never counted retroactively.

Draft **PR #2775** is a complementary receipt-contract preflight, not a G1 model or historical-closing-line admission. It handles regular-season ML/run-line/total rows with independent entry/close stamps and future-season regime checks, refuses self-close and mismatched contracts, and explicitly labels receipts `MANIFEST_SHAPED_RESEARCH_ONLY` / `counted=false` / `verified_clv=false`. It excludes team totals pending a separately versioned preregistration; its same-threshold rule excludes changed lines (e.g. total 8.5→9.0). Those excluded decisions and their denominator must be reported verbatim; any cross-threshold CLV comparator needs separate preregistration.

**The actual source admission gap is upstream:** `sportsedge/direct_web_capture_source.py::acquire_board` has the exact DK raw response bytes to hash but returns only parsed payload plus the digest; `scripts/capture_mlb_direct_paired_ml.py` persists only moneyline-side observations, not replayable original HTTP bodies. The three-game-line DK normalizer does not itself provide team-total evidence. Before a G1 score may count, archive the original raw DK bytes under content-addressed SHA-256 with retrieval time/source/event id, reparse and compare the stored bytes to every normalized quote, and bind the DK event to an independently verified StatsAPI `gamePk`/actual first-play anchor. Do not infer that the *last archived pregame quote* is the true last sportsbook quote. Enforce ≤30-minute quote usability and ≤60-minute prestart close-window rules as **separate** conditions.

Historical StatsAPI results are useful design inputs; [issue #382](https://github.com/isaacrome21-sys/SportsEdge/issues/382) documents that independently admitted historical DK decision-and-later-close game-line pairs remain missing. Other archived quote adapters and manifest checks do not substitute for original bytes or timestamps. Thus **zero historically verified G1 CLV or ROI** can be asserted, and a future frozen prospective clock remains the honest market-verification path.
