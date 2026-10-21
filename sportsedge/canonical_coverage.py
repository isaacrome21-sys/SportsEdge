"""Canonical RUN IT coverage map: one resolution for every catalog market.

Source of truth for the market list: the Phase 1 coverage matrix
(89 markets: 38 MLB + 51 NFL).  This module is the runtime counterpart of
that matrix for the ONE canonical card path (``artifacts/run_it_full.py``):

* every matrix market resolves to exactly one state --
  ``PRICED_PATH`` (a real engine with verified inputs is reachable from the
  canonical entry point) or ``BLOCKED`` with a named blocker from the
  taxonomy ``NO_QUOTE / NO_ENGINE / NO_DATA / NO_SETTLEMENT /
  NO_PARTICIPATION / NO_VALIDATION``;
* validation status is carried separately and is NEVER implied by the
  resolution: a PRICED_PATH market is an unvalidated research price until
  the strict paired-OOS evaluator says otherwise, per market family;
* blocked rows produced through this map name the cause instead of the
  legacy generic ``NO_VERIFIED_MODEL_FOR_THIS_MARKET``.

Row-level fail-closed outcomes still belong to the engines themselves
(missing identity, unconfirmed lineup, insufficient history).  This map
only answers "does the canonical path have a priced route for this
market, and if not, why not".
"""
from __future__ import annotations

BLOCKER_TAXONOMY = frozenset({
    "NO_QUOTE", "NO_ENGINE", "NO_DATA",
    "NO_SETTLEMENT", "NO_PARTICIPATION", "NO_VALIDATION",
})

PRICED_PATH = "PRICED_PATH"
BLOCKED = "BLOCKED"

# (sport, matrix market) -> resolution dict.
# state: PRICED_PATH | BLOCKED; engine: canonical-path engine id or the
# wired-but-gated pricer; blocker: taxonomy code when BLOCKED;
# detail: the exact reason; validation_status: the Phase 1 matrix verdict,
# carried unchanged (coverage is not validation).
_R = {}


def _priced(sport, market, engine, detail, validation="NOT_RUN"):
    _R[(sport, market)] = {
        "sport": sport, "market": market, "state": PRICED_PATH,
        "engine": engine, "blocker": None, "detail": detail,
        "validation_status": validation,
    }


def _blocked(sport, market, blocker, detail, engine=None, validation="NOT_RUN"):
    assert blocker in BLOCKER_TAXONOMY, blocker
    _R[(sport, market)] = {
        "sport": sport, "market": market, "state": BLOCKED,
        "engine": engine, "blocker": blocker, "detail": detail,
        "validation_status": validation,
    }


_FREE_MODELS = "FREE_MODELS_GAME (artifacts/free_models.calculate; Lane A independent)"
_SNAPSHOT_ONLY = ("a pricer exists only behind the manual-snapshot intake "
                  "contract (run_canonical_manual_mlb: gamePk-bound paired "
                  "quotes + deployment card); that contract is not the "
                  "canonical card intake and no verified feature assembly "
                  "for it exists on this path")
_DISTRIBUTION_MISSING = ("the derivative pricer is wired into the canonical "
                         "path, but it prices only from an independent joint "
                         "score distribution (simulation paths); the canonical "
                         "game engine (free_models) is analytic and emits no "
                         "simulation paths, so the required input does not "
                         "exist on this path")

# ---------------------------------------------------------------- MLB (38)
for _m in ("MONEYLINE", "RUN_LINE", "TOTALS", "TEAM_TOTALS"):
    _priced("MLB", _m, _FREE_MODELS,
            "Game market priced by the canonical game stage after the "
            "prepricing factor gate (verified StatsAPI identity/history).")
for _m in ("F5_MONEYLINE", "F5_RUN_LINE", "F5_TOTALS", "F5_TEAM_TOTALS"):
    _blocked("MLB", _m, "NO_VALIDATION",
             "F5_DEPLOYMENT_NOT_ELIGIBLE (deployment eligible=false, stage "
             "F5_STATE_CANDIDATE; this gate stays until an owner ruling -- "
             "quotes are not the blocker). "
             "F5 quotes now bind on the canonical path through "
             "sportsedge.mlb_f5_quote_binding (sportsbook + book event ID "
             "+ verified gamePk fixture + explicit FIRST_5 period + "
             "selection/line/price + <=180s freshness + <=120s pairing), "
             "and F5 features assemble from strictly-prior StatsAPI "
             "linescores without the snapshot contract. The settlement "
             "basis is verified from code for all four F5 markets: "
             "F5_RUN_LINE/F5_TOTALS/F5_TEAM_TOTALS settle from the "
             "score through 5 completed innings with push on equality, "
             "and F5_MONEYLINE is VERIFIED_TWO_WAY (owner settlement "
             "ruling 2026-10-12; declared in "
             "sportsedge.moneyline_settlement from DraftKings' "
             "published rules -- its market rules define 2-Way "
             "Moneyline Markets as offering no Draw selection with "
             "ties settled as Push, "
             "https://sportsbook.draftkings.com/help/general-betting-rules/market-rules, "
             "and its baseball guide's first-five section offers only "
             "the two teams and states a tied team bet pushes with "
             "the stake refunded, "
             "https://sportsbook.draftkings.com/help/how-to-bet/baseball-betting-guide) "
             "-- a tied score after five now settles PUSH in code "
             "through the typed TWO_WAY model. Rows still resolve "
             "BLOCKED here at the one remaining gate: every F5 "
             "deployment remains stage F5_STATE_CANDIDATE "
             "(eligible=false) in config/deployments.json, so no F5 row "
             "may price on this path; row-level reasons name the exact "
             "gate (F5_DEPLOYMENT_NOT_ELIGIBLE).",
             engine="SHARED_F5_ENGINE (via MLB_F5_QUOTE_BINDING_V1, "
                    "deployment-gated)")
for _m in ("NRFI", "YRFI"):
    _priced("MLB", _m, "MLB_FIRST_INNING_BINARY (mlb_first_inning_model."
            "price_first_inning_binary via FIRST_INNING_RUNS at line 0.5; "
            "NRFI=UNDER, YRFI=OVER)",
            "First-inning binary priced from verified StatsAPI linescore "
            "pools + probable-starter indicators; fail-closed per row on "
            "fixture/history verification.",
            validation="UNVALIDATED")
_BATTER = ("MLB_BATTER_EMPIRICAL_GAMELOG (mlb_phone_batter_pricing -> "
           "research_three_sport_bridge; verified StatsAPI game logs, "
           "official-lineup gate per row)")
for _m in ("HITS", "TOTAL_BASES", "RBI", "RUNS",
           "BATTER_BB", "SINGLES", "DOUBLES",
           "HITS_RUNS_RBIS"):
    _priced("MLB", _m, _BATTER,
            "Batter market in the empirical gamelog engine's market set; "
            "rows fail closed per player when identity/history is "
            "unverified or the official starting lineup is unconfirmed "
            "(row-level NO_PARTICIPATION).")
for _m in ("HOME_RUNS", "BATTER_K"):
    _priced("MLB", _m, _BATTER,
            "Batter market in the empirical gamelog engine's market set. "
            "FIXTURE OBSERVATION (DK Oct 13 2026, not global): "
            "On the inspected fixture this family appeared as a single-sided "
            "milestone ladder (no native two-sided O/U observed there); ladder rows "
            "convert at intake through "
            "sportsedge.milestone_ladder_intake and reach this engine "
            "as one-sided rows. Rows fail closed per player when "
            "identity/history is unverified or the official starting "
            "lineup is unconfirmed (row-level NO_PARTICIPATION).")
for _m in ("TRIPLES", "EXTRA_BASE_HITS", "RUNS_RBIS"):
    _priced("MLB", _m, _BATTER,
            "Batter market in the empirical gamelog engine's market set "
            "(TRIPLES reads the measured per-game triples field; "
            "EXTRA_BASE_HITS is the exact per-game sum "
            "doubles+triples+home_runs; RUNS_RBIS the exact per-game sum "
            "runs+rbi; a game missing any component fails the market "
            "closed). FIXTURE OBSERVATION (DK Oct 13 2026, not global): "
            "On the inspected fixture this family appeared as a single-sided "
            "milestone ladder (no two-sided O/U observed there); ladder rows convert "
            "at intake through sportsedge.milestone_ladder_intake and "
            "reach this engine as one-sided rows. Rows fail closed per "
            "player when identity/history is unverified or the official "
            "starting lineup is unconfirmed (row-level "
            "NO_PARTICIPATION).")
_blocked("MLB", "STOLEN_BASES", "NO_QUOTE",
         "NOT_OBSERVED_ON_INSPECTED_FIXTURE (DK Oct 13 2026), not a "
         "global determination of market availability. The empirical "
         "gamelog engine can research this statistic, but no row may "
         "price without verified per-fixture offered quote evidence.",
         engine=_BATTER)
for _m in ("HITS_RUNS_STOLEN_BASES",
           "HITS_STOLEN_BASES", "HITS_WALKS_STOLEN_BASES"):
    _blocked("MLB", _m, "NO_ENGINE",
             "The empirical gamelog engine's market set excludes this "
             "market; " + _SNAPSHOT_ONLY + ".",
             engine="HITTER_JOINT_ENGINE (snapshot contract only)")
_PITCHER = ("MLB_PITCHER_JOINT_EMPIRICAL_BAYES (mlb_phone_pitcher_pricing "
            "-> research_three_sport_bridge; verified StatsAPI prior starts)")
for _m in ("PITCHER_K", "PITCHER_OUTS", "PITCHER_HITS_ALLOWED",
           "PITCHER_BB", "PITCHER_ER"):
    _priced("MLB", _m, _PITCHER,
            "Pitcher market priced from verified prior starts; rows fail "
            "closed per pitcher when identity/history is unverified.")
_blocked("MLB", "PITCHER_HITS_WALKS_ER", "NO_QUOTE",
         "NO VERIFIED OFFERED QUOTE on the inspected fixture. The current "
         "config/mlb_market_surface.json provider flags prevent acquisition "
         "until separately reconciled against per-fixture evidence; do not "
         "infer global market nonexistence. The pitcher probability engine "
         "is not the immediate blocker.", engine=_PITCHER)
# Truthful named gates (backtest matrix M32/M33; wiring-queue items
# 3-4). Both families used to share the generic NO_ENGINE text "No
# engine for this market is reachable" -- which was never the real
# reason for either: a probability construction EXISTS in research
# code for both. These are label refinements only -- pricing stays
# refused on every path, no intake path produces a price, and no
# registry/deployment/validation state changes.
_blocked("MLB", "PITCHER_RECORD_WIN", "NO_ENGINE",
         "PITCHER_RECORD_WIN_OFFERING_UNVERIFIED (pricing gate; "
         "also outstanding: PITCHER_RECORD_WIN_ENGINE_CANDIDATE_"
         "UNVALIDATED): a win-credit probability construction "
         "EXISTS in research code (pitcher_record_win_engine "
         "credit-state candidate: F5 joint lead state x starter "
         "workload x team score paths), so 'no engine' was never "
         "the real reason. The immediate gate is the OFFERING: no "
         "verified DraftKings offering rows for this market exist "
         "on the enumerated board in this lane's evidence, so no "
         "quote can bind (per-fixture absence is not proof of "
         "global nonexistence). Behind it, the engine itself "
         "remains a candidate -- historical PIT, holdout, "
         "calibration, sportsbook settlement, forward evidence "
         "and production parity are all unsatisfied, by the "
         "engine module's own statement. Pricing stays refused "
         "until a verified offering exists AND the candidate "
         "clears its own gates; intake plumbing is deliberately "
         "not built ahead of either.",
         engine="PITCHER_RECORD_WIN_ENGINE credit-state candidate "
                "v2 (research complex only; gated PITCHER_RECORD_"
                "WIN_OFFERING_UNVERIFIED)")
_blocked("MLB", "FIRST_HOME_RUN", "NO_ENGINE",
         "FIRST_HOME_RUN_ABSENT_ON_ENUMERATED_BOARD (pricing "
         "gate; also outstanding: FIRST_HOME_RUN_MULTI_OUTCOME_"
         "SELECTION_SET_UNBOUND): a batting-order probability "
         "construction EXISTS in research code (first_hr_order_"
         "engine lineup-order candidate), so 'no engine' was "
         "never the whole reason. The immediate gate is the "
         "BOARD: this market was absent on the sampled board in "
         "this lane's evidence (per-fixture absence is not proof "
         "of global nonexistence). Behind it, the market is "
         "MULTI-OUTCOME -- one selection per batter across both "
         "lineups, an N-way field -- and the canonical path binds "
         "binary, pair and verified-partition markets only; no "
         "N-way selection-set binding exists, and first-HR "
         "settlement needs full-game play-by-play first-home-run "
         "attribution. Pricing stays refused until a verified "
         "offering exists AND the multi-outcome binding is built.",
         engine="FIRST_HR_ORDER_ENGINE lineup-order candidate v1 "
                "(research complex only; gated FIRST_HOME_RUN_"
                "ABSENT_ON_ENUMERATED_BOARD)")
for _m in ("EITHER_PITCHER_HITS_ALLOWED", "EITHER_PITCHER_BB",
           "EITHER_PITCHER_ER"):
    # Truthful named gate (EITHER_PITCHER decision package, DESIGN.md
    # sections 3/5/7; owner-approved Oct 14 2026). An either-probability
    # construction EXISTS in the research joint engine (Cartesian-product
    # pools), so "no engine" was never the real reason: the construction
    # assumes the two starters' outcomes are independent, and that
    # dependence is unmeasured. This is a label refinement only --
    # pricing stays refused, no intake path produces a price, and
    # settlement stays fail-closed (EITHER_PITCHER_BOOK_SPECIFIC_
    # SEMANTICS_REQUIRED in either_pitcher_settlement).
    _blocked("MLB", _m, "NO_ENGINE",
             "EITHER_PITCHER_MARGINAL_TAIL_ERROR (pricing gate; "
             "also outstanding: EITHER_PITCHER_RUNG_LABEL_UNVERIFIED, "
             "EITHER_PITCHER_PAIR_BINDING_INCOMPLETE): the only "
             "either-probability construction (pitcher_joint_engine "
             "Cartesian-product pools) inherits the single-pitcher "
             "marginals' tail error and OVERSTATES the far X+ rungs "
             "DraftKings sells. Evidence: M31 paired-starter audit "
             "(spec 5e0eb543, research/mlb-market-legs-20261014) verdict "
             "DEPENDENCE_MEASURED, starter residual correlation ~0 "
             "(n=2,160 pairs; HA/BB/ER |rho|<=0.009), but independence "
             "either-probabilities materially wrong from the marginals "
             "(BB X+6 pred 0.059 vs obs 0.009). The previous "
             "independence/dependence blocker is superseded: repairing "
             "the combination rule fixes nothing; the marginals must be "
             "repaired first. Pricing stays refused. Rung labels: no "
             "capture on record pins them to the max/min reading (vs a "
             "combined-sum reading). Pair binding: no verified "
             "two-pitcher intake exists on the canonical path; the "
             "pair identity <away_pitcher_id>|<home_pitcher_id> is "
             "defined only in the settlement and PIT layers.",
             engine="PITCHER_JOINT_ENGINE either branch (research "
                    "complex only; gated EITHER_PITCHER_MARGINAL_"
                    "TAIL_ERROR)")

# ---------------------------------------------------------------- NFL (51)
for _m in ("moneyline", "spread"):
    _priced("NFL", _m, _FREE_MODELS,
            "Game market priced by the canonical game stage after the "
            "prepricing factor gate (verified ESPN/nflverse history).")
_priced("NFL", "total", _FREE_MODELS,
        "Game total priced by the canonical game stage; prior-only totals "
        "are suppressed to WATCH by the merged totals safeguard.",
        validation="UNVALIDATED")
_blocked("NFL", "team_total", "NO_ENGINE", _DISTRIBUTION_MISSING + ".",
         engine="NFL_TEAM_TOTAL_DERIVATIVE (sports/nfl/team_totals."
                "price_nfl_team_totals, wired)")
for _m in ("first_half_moneyline", "first_half_spread", "first_half_total",
           "second_half_moneyline", "second_half_spread",
           "second_half_total", "quarter_moneyline", "quarter_spread",
           "quarter_total"):
    _blocked("NFL", _m, "NO_ENGINE",
             _DISTRIBUTION_MISSING + " Period markets additionally require "
             "per-period score paths (and, for second half, an explicit "
             "overtime settlement rule).",
             engine="PERIOD_DERIVATIVE (core/simulate/markets."
                    "derive_period_markets, wired)")
for _m in ("alternate_spread", "alternate_total"):
    _blocked("NFL", _m, "NO_ENGINE", _DISTRIBUTION_MISSING + ".",
             engine="ALTERNATE_DERIVATIVE (core/simulate/markets."
                    "derive_alternate_markets, wired)")
for _m in ("race_to_n_points", "first_score", "largest_lead",
           "winning_margin_band", "both_teams_to_score_n",
           "total_touchdowns", "longest_fg_made",
           "defensive_special_teams_td", "safety"):
    _blocked("NFL", _m, "NO_ENGINE",
             "No pricing engine for this market exists anywhere in the "
             "repository; it is a catalog declaration only.")
_EMPIRICAL = ("NFL_PLAYER_EMPIRICAL (nfl_phone_player_pricing -> "
              "nfl_player_empirical; verified ESPN gamelogs; watch-only "
              "per row because participation is not verified from gamelog)")
for _m in ("passing_yards", "completions", "attempts", "passing_tds",
           "interceptions", "rush_yards", "pass_plus_rush_yards",
           "rushing_yards", "receiving_yards", "receptions",
           "rush_attempts", "rush_plus_rec_yards"):
    _blocked("NFL", _m, "NO_ENGINE",
             "GOVERNANCE_NO_ENGINE: config/football_prop_engine_surface.json "
             "and football_market_surface.engine_state_by_sport.NFL declare "
             "NO_ENGINE for all NFL player props; the empirical gamelog "
             "pricer is wired but not governance-admitted, so it may not "
             "price on the canonical path.", engine=_EMPIRICAL)
for _m in ("targets",):
    _blocked("NFL", _m, "NO_ENGINE",
             "The empirical gamelog engine's market set excludes this "
             "market and no other pricer exists for it.")
for _m in ("longest_completion", "longest_reception", "longest_rush"):
    _blocked("NFL", _m, "NO_ENGINE",
             "GOVERNANCE_NO_ENGINE: config/football_prop_engine_surface.json "
             "and football_market_surface.engine_state_by_sport.NFL declare "
             "NO_ENGINE for all NFL player props; the empirical longest-plays "
             "engine is wired but not governance-admitted, so it may not "
             "price on the canonical path.",
             engine="NFL_LONGEST_PLAYS_EMPIRICAL (nfl_longest_plays_empirical."
                    "estimate_longest_plays, wired, not admitted)")
_blocked("NFL", "anytime_td", "NO_ENGINE",
         "GOVERNANCE_NO_ENGINE: the prop-engine surface declares NO_ENGINE "
         "for NFL player props; the nflverse anytime-TD estimator is wired "
         "but not governance-admitted.",
         engine="NFL_ANYTIME_TD_NFLVERSE (nfl_anytime_td.estimate_anytime_td, "
                "wired, not admitted)")
_blocked("NFL", "first_td", "NO_DATA",
         "NO_VERIFIED_FIRST_SCORING_ATTRIBUTION: opening possession is a "
         "game-time coin toss recorded only post-game, and no free "
         "pre-kickoff source attributes first-score probability to a "
         "player verifiably (nfl_anytime_td.assess_first_td, wired).",
         engine="NFL_ANYTIME_TD (assessment only)")
_blocked("NFL", "two_plus_td", "NO_ENGINE",
         "The anytime-TD engine prices P(at least one TD) only; no "
         "P(two or more TDs) pricer exists and the >=2 case is not "
         "derived by extending the >=1 model.")
for _m in ("fg_made", "kicking_points", "xp_made"):
    _blocked("NFL", _m, "NO_ENGINE",
             "GOVERNANCE_NO_ENGINE: config/football_prop_engine_surface.json "
             "and football_market_surface.engine_state_by_sport.NFL declare "
             "NO_ENGINE for all NFL player props; the empirical kicking "
             "engine is wired but not governance-admitted, so it may not "
             "price on the canonical path.",
             engine="NFL_KICKING_EMPIRICAL (nfl_kicking_empirical."
                    "estimate_kicking, wired, not admitted)")
for _m in ("player_sacks", "tackles_assists", "player_interceptions",
           "team_sacks", "team_turnovers"):
    _blocked("NFL", _m, "NO_ENGINE",
             "Defensive derivative pricers exist only over attributed "
             "simulation paths (core/simulate); no such paths exist on "
             "the canonical path and the governance surface declares "
             "NO_ENGINE for NFL props.")

MARKET_RESOLUTIONS = dict(_R)

# Canonical-path dispatch sets (kept in this dependency-light module so
# artifacts/run_it_full.py can classify rows without importing the
# pandas/numpy-backed stage modules; the stages import these back).
NFL_DERIVATIVE_MARKETS = frozenset({
    "TEAM_TOTALS", "TEAM_TOTAL",
    "FIRST_HALF_MONEYLINE", "FIRST_HALF_SPREAD", "FIRST_HALF_TOTAL",
    "FIRST_HALF_TEAM_TOTAL",
    "SECOND_HALF_MONEYLINE", "SECOND_HALF_SPREAD", "SECOND_HALF_TOTAL",
    "QUARTER_MONEYLINE", "QUARTER_SPREAD", "QUARTER_TOTAL",
    "ALTERNATE_SPREAD", "ALTERNATE_TOTAL", "ALT_SPREAD", "ALT_TOTAL",
})
NFL_ANYTIME_TD_MARKETS = frozenset({"ANYTIME_TD", "ANYTIME_TOUCHDOWN"})
NFL_FIRST_TD_MARKETS = frozenset({"FIRST_TD", "FIRST_TOUCHDOWN"})

# Intake (canonical-path) market name -> matrix market name, per sport.
# Only aliases whose canonical dispatch exists are listed; the map exists
# so blocked intake rows can be annotated with their matrix resolution.
INTAKE_ALIASES = {
    "MLB": {
        "ML": "MONEYLINE", "MONEYLINE": "MONEYLINE",
        "SPREAD": "RUN_LINE", "RUN_LINE": "RUN_LINE",
        "TOTAL": "TOTALS", "TOTALS": "TOTALS",
        "TEAM_TOTALS": "TEAM_TOTALS",
        "F5_MONEYLINE": "F5_MONEYLINE", "F5_ML": "F5_MONEYLINE",
        "F5_RUN_LINE": "F5_RUN_LINE", "F5_SPREAD": "F5_RUN_LINE",
        "F5_TOTALS": "F5_TOTALS", "F5_TOTAL": "F5_TOTALS",
        "F5_TEAM_TOTALS": "F5_TEAM_TOTALS",
        "NRFI": "NRFI", "YRFI": "YRFI",
        "FIRST_INNING_RUNS": "NRFI",
        "BATTER_HITS": "HITS", "HITS": "HITS",
        "BATTER_TOTAL_BASES": "TOTAL_BASES", "TOTAL_BASES": "TOTAL_BASES",
        "BATTER_RBIS": "RBI", "RBI": "RBI", "RBIS": "RBI",
        "BATTER_RUNS": "RUNS", "RUNS": "RUNS",
        "BATTER_HRS": "HOME_RUNS", "BATTER_HOME_RUNS": "HOME_RUNS",
        "HOME_RUNS": "HOME_RUNS",
        "BATTER_STOLEN_BASES": "STOLEN_BASES",
        "STOLEN_BASES": "STOLEN_BASES",
        "BATTER_BB": "BATTER_BB", "BATTER_WALKS": "BATTER_BB",
        "BATTER_K": "BATTER_K", "BATTER_STRIKEOUTS": "BATTER_K",
        "BATTER_SINGLES": "SINGLES", "SINGLES": "SINGLES",
        "BATTER_DOUBLES": "DOUBLES", "DOUBLES": "DOUBLES",
        "HITS_RUNS_RBIS": "HITS_RUNS_RBIS", "H_R_RBI": "HITS_RUNS_RBIS",
        "EXTRA_BASE_HITS": "EXTRA_BASE_HITS",
        "BATTER_EXTRA_BASE_HITS": "EXTRA_BASE_HITS",
        "HITS_RUNS_STOLEN_BASES": "HITS_RUNS_STOLEN_BASES",
        "RUNS_RBIS": "RUNS_RBIS",
        "BATTER_RUNS_RBIS": "RUNS_RBIS",
        "HITS_STOLEN_BASES": "HITS_STOLEN_BASES",
        "HITS_WALKS_STOLEN_BASES": "HITS_WALKS_STOLEN_BASES",
        "BATTER_TRIPLES": "TRIPLES", "TRIPLES": "TRIPLES",
        "PITCHER_K": "PITCHER_K", "PITCHER_STRIKEOUTS": "PITCHER_K",
        "PITCHER_OUTS": "PITCHER_OUTS",
        "PITCHER_HITS_ALLOWED": "PITCHER_HITS_ALLOWED",
        "PITCHER_BB": "PITCHER_BB", "PITCHER_WALKS": "PITCHER_BB",
        "PITCHER_ER": "PITCHER_ER",
        "PITCHER_HITS_WALKS_ER": "PITCHER_HITS_WALKS_ER",
        "EITHER_PITCHER_HITS_ALLOWED": "EITHER_PITCHER_HITS_ALLOWED",
        "EITHER_PITCHER_BB": "EITHER_PITCHER_BB",
        "EITHER_PITCHER_WALKS": "EITHER_PITCHER_BB",
        "EITHER_PITCHER_ER": "EITHER_PITCHER_ER",
        "PITCHER_RECORD_WIN": "PITCHER_RECORD_WIN",
        "FIRST_HOME_RUN": "FIRST_HOME_RUN",
    },
    "NFL": {
        "ML": "moneyline", "MONEYLINE": "moneyline",
        "SPREAD": "spread", "TOTAL": "total", "TOTALS": "total",
        "TEAM_TOTALS": "team_total", "TEAM_TOTAL": "team_total",
        "FIRST_HALF_MONEYLINE": "first_half_moneyline",
        "FIRST_HALF_SPREAD": "first_half_spread",
        "FIRST_HALF_TOTAL": "first_half_total",
        "SECOND_HALF_MONEYLINE": "second_half_moneyline",
        "SECOND_HALF_SPREAD": "second_half_spread",
        "SECOND_HALF_TOTAL": "second_half_total",
        "QUARTER_MONEYLINE": "quarter_moneyline",
        "QUARTER_SPREAD": "quarter_spread",
        "QUARTER_TOTAL": "quarter_total",
        "ALTERNATE_SPREAD": "alternate_spread", "ALT_SPREAD": "alternate_spread",
        "ALTERNATE_TOTAL": "alternate_total", "ALT_TOTAL": "alternate_total",
        "RACE_TO_N_POINTS": "race_to_n_points",
        "FIRST_SCORE": "first_score", "LARGEST_LEAD": "largest_lead",
        "WINNING_MARGIN_BAND": "winning_margin_band",
        "BOTH_TEAMS_TO_SCORE_N": "both_teams_to_score_n",
        "TOTAL_TOUCHDOWNS": "total_touchdowns",
        "LONGEST_FG_MADE": "longest_fg_made",
        "DEFENSIVE_SPECIAL_TEAMS_TD": "defensive_special_teams_td",
        "SAFETY": "safety",
        "PLAYER_PASSING_YARDS": "passing_yards",
        "PLAYER_PASS_YARDS": "passing_yards",
        "PLAYER_COMPLETIONS": "completions",
        "PLAYER_PASS_ATTEMPTS": "attempts",
        "PLAYER_PASS_TDS": "passing_tds",
        "PLAYER_PASSING_TDS": "passing_tds",
        "PLAYER_INTERCEPTIONS": "interceptions",
        "PLAYER_RUSHING_YARDS": "rushing_yards",
        "PLAYER_RUSH_YARDS": "rushing_yards",
        "PLAYER_PASS_PLUS_RUSH_YARDS": "pass_plus_rush_yards",
        "PLAYER_RECEIVING_YARDS": "receiving_yards",
        "PLAYER_REC_YARDS": "receiving_yards",
        "PLAYER_RECEPTIONS": "receptions",
        "PLAYER_RUSH_ATTEMPTS": "rush_attempts",
        "PLAYER_RUSH_PLUS_REC_YARDS": "rush_plus_rec_yards",
        "LONGEST_COMPLETION": "longest_completion",
        "TARGETS": "targets",
        "LONGEST_RECEPTION": "longest_reception",
        "LONGEST_RUSH": "longest_rush",
        "ANYTIME_TD": "anytime_td", "ANYTIME_TOUCHDOWN": "anytime_td",
        "FIRST_TD": "first_td", "FIRST_TOUCHDOWN": "first_td",
        "TWO_PLUS_TD": "two_plus_td",
        "FG_MADE": "fg_made", "KICKING_POINTS": "kicking_points",
        "XP_MADE": "xp_made", "PLAYER_SACKS": "player_sacks",
        "TACKLES_ASSISTS": "tackles_assists",
        "DEFENSIVE_PLAYER_INTERCEPTIONS": "player_interceptions",
        "TEAM_SACKS": "team_sacks", "TEAM_TURNOVERS": "team_turnovers",
    },
}


def _with_nfl_registration(sport, resolution):
    """Layer the versioned NFL family registration (#2265) onto a matrix
    resolution.  Registration names the governed research-only state
    (NOT_VALIDATED, eligible=false, non-promotable) for NFL player-prop
    families; it never changes the state, blocker, or detail, and no
    other sport or market is affected."""
    if sport != "NFL" or resolution is None:
        return resolution
    from sportsedge.nfl_family_registry_v2 import coverage_registration_v2
    registration = coverage_registration_v2(sport, resolution["market"])
    if registration is None:
        return resolution
    merged = dict(resolution)
    merged.update(registration)
    return merged


REGISTERED_RESEARCH_ONLY = "REGISTERED_RESEARCH_ONLY"
FAILED_VALIDATION = "FAILED_VALIDATION"

# ---------------------------------------------------------------------
# Family-registry surfacing (truth-in-labeling).  The family branch of
# resolve_market used to hardcode state BLOCKED for every CFB/NBA/CBB
# market, so a surface consulting this authority refused outright even
# for families the family registry of record
# (sportsedge.family_market_registry) had already registered
# research-only, while the phone lane priced the same families as
# labeled research through sportsedge.registry_gate.  The helpers below
# surface each family's TRUE recorded state.  Nothing here grants
# pricing: research-pricing permission lives only in
# sportsedge.registry_gate (per-row pricing conditions), eligible and
# promotable stay False everywhere, and no validation state changes.

# NBA game lines carry a recorded FAILED_VALIDATION verdict -- an
# accuracy gap vs the close (NBA market readiness verdict 2026-10-18;
# tested-ideas ledger sections 9-10; research/
# forward_validation_program_20261020/PROGRAM.md).  The odds vintage
# was untimestamped, so it is an accuracy-gap verdict, not a
# beat-the-close verdict.  These families are not NOT_VALIDATED by
# omission and are not research-pricing-eligible as validated
# candidates; any successor is a NEW model version scored forward only.
_NBA_GAME_LINE_FAILURES = {
    "moneyline": ("moneyline Brier diff (model - market) +0.0117, "
                  "95% CI [0.0087, 0.0147], n=4,374 games"),
    "spread": "spread RMSE model 13.83 vs line 13.30",
    "total": "game-total RMSE model 21.46 vs line 20.72",
}
_NBA_RATINGS_ENGINE = ("NBA_RATINGS_RAW (sportsedge/sports/nba/"
                       "ratings_model.py, committed defaults; the "
                       "owner-decided test subject)")

# NBA team-total and period-total forms (the forms the #2422 engine
# builds).  PR #2422 built the engine and recorded NO registration or
# eligibility change: the families stay unregistered and BLOCKED, with
# calibration evidence only and no market test in existence.
_NBA_TEAM_PERIOD_ENGINE = ("NBA_TEAM_PERIOD_RATINGS_V1 (sportsedge."
                           "nba_team_period_engine; Oct 18 calibration "
                           "construction, no market leg)")
_QTR_CAL = ("quarter-total calibration BEATS_BASELINE vs climatology "
            "baselines only (MAE 4.6103 vs B1 4.7070 / B2 4.7099, "
            "n=62,024 team-quarters)")
_AGG_CAL = ("an exact mechanical sum of the scored team-quarter "
            "primitives (first-screen aggregation in the #2422 build, "
            "not separately scored by the Oct 18 sweep)")
_NBA_TEAM_PERIOD_FORMS = {
    "team_total": ("team_total",
                   "TEAM_TOTAL calibration BEATS_BASELINE vs "
                   "climatology baselines only (MAE 8.9975 vs "
                   "B1 9.5411 / B2 9.8275, n=15,506 team-games)"),
    "team_totals": ("team_total",
                    "TEAM_TOTAL calibration BEATS_BASELINE vs "
                    "climatology baselines only (MAE 8.9975 vs "
                    "B1 9.5411 / B2 9.8275, n=15,506 team-games)"),
    "team_quarter_total": ("team_quarter_total",
                           "TEAM_QUARTER_TOTAL " + _QTR_CAL),
    "game_quarter_total": ("game_quarter_total",
                           "GAME_QUARTER_TOTAL is " + _AGG_CAL),
    "quarter_total": ("quarter_total", "This form carries the " + _QTR_CAL),
    "first_quarter_total": ("first_quarter_total",
                            "This form carries the " + _QTR_CAL),
    "second_quarter_total": ("second_quarter_total",
                             "This form carries the " + _QTR_CAL),
    "third_quarter_total": ("third_quarter_total",
                            "This form carries the " + _QTR_CAL),
    "fourth_quarter_total": ("fourth_quarter_total",
                             "This form carries the " + _QTR_CAL),
    "team_half_total": ("team_half_total", "TEAM_HALF_TOTAL is " + _AGG_CAL),
    "game_half_total": ("game_half_total", "GAME_HALF_TOTAL is " + _AGG_CAL),
    "half_total": ("half_total", "This form is " + _AGG_CAL),
    "first_half_total": ("first_half_total", "This form is " + _AGG_CAL),
    "second_half_total": ("second_half_total", "This form is " + _AGG_CAL),
}


def _family_key(name):
    """Canonical family key (mirror of family_market_registry._canon_key,
    lower-cased): upper-case, hyphens/spaces/dots -> underscores."""
    out = str(name or "").strip().upper()
    for ch in "- .":
        out = out.replace(ch, "_")
    while "__" in out:
        out = out.replace("__", "_")
    return out.lower()


def _family_engine(sport, family):
    """The registered engine of record for a REGISTERED_RESEARCH_ONLY
    family decision, per the family registry's own statements."""
    if sport == "NBA":
        return ("NBA_PROP_EMPIRICAL_V1 (sportsedge.nba_prop_empirical; "
                "research pricing gated by sportsedge.registry_gate on "
                "the engine sufficiency stamp)")
    if sport == "CFB":
        return ("FREE_MODELS_GAME (artifacts/free_models.calculate; "
                "research pricing gated by sportsedge.registry_gate on "
                "satisfied Form 2 identity for both teams)")
    return None


def _family_resolution(sport, raw_market, family):
    """Resolution for a CFB/NBA/CBB family decision, surfacing the
    family's true recorded state (see the surfacing note above)."""
    market = family["market"]
    if sport == "NBA" and market in _NBA_GAME_LINE_FAILURES:
        return {
            "sport": sport, "market": market, "state": FAILED_VALIDATION,
            "engine": _NBA_RATINGS_ENGINE, "blocker": "NO_VALIDATION",
            "detail": ("FAILED_VALIDATION: accuracy gap vs the close "
                       "-- " + _NBA_GAME_LINE_FAILURES[market] + " "
                       "(NBA market readiness verdict 2026-10-18; "
                       "tested-ideas ledger sections 9-10). The family "
                       "was tested against the market and failed; it "
                       "is not research-pricing-eligible as a validated "
                       "candidate, and any successor is a new model "
                       "version scored forward only. (family-level "
                       "registry, sportsedge.family_market_registry; "
                       "research-only)"),
            "validation_status": FAILED_VALIDATION,
            "family_registry": True,
            "registration_state": "UNREGISTERED",
            "eligible": False, "promotable": False,
            "research_only": True, "official_authority": False,
            "model_p_authority": False, "staking_authority": False,
        }
    if family.get("state") == REGISTERED_RESEARCH_ONLY:
        return {
            "sport": sport, "market": market,
            "state": REGISTERED_RESEARCH_ONLY,
            "engine": _family_engine(sport, family),
            "blocker": family["blocker"],
            "detail": (family["reason"] + ": family registry state "
                       "REGISTERED_RESEARCH_ONLY / NOT_VALIDATED "
                       "(eligible=false, promotable=false); "
                       "registration is not validation -- rows may "
                       "price as research-only LEANs (\"unvalidated "
                       "estimate\") only through "
                       "sportsedge.registry_gate when the family's "
                       "pricing condition is met (" +
                       str(family.get("pricing_condition")) + "); this "
                       "coverage lookup grants no pricing by itself. "
                       "(family-level registry, "
                       "sportsedge.family_market_registry; "
                       "research-only)"),
            "validation_status": family["validation_status"],
            "family_registry": True,
            "registration_state": family["registration_state"],
            "pricing_condition": family.get("pricing_condition"),
            "evaluation_scope": family.get("evaluation_scope"),
            "eligible": False, "promotable": False,
            "research_only": True, "official_authority": False,
            "model_p_authority": False, "staking_authority": False,
        }
    if (sport == "NBA" and family.get("reason") == "FAMILY_MARKET_UNREGISTERED"
            and _family_key(raw_market) in _NBA_TEAM_PERIOD_FORMS):
        form, calibration = _NBA_TEAM_PERIOD_FORMS[_family_key(raw_market)]
        return {
            "sport": sport, "market": form, "state": BLOCKED,
            "engine": _NBA_TEAM_PERIOD_ENGINE, "blocker": "NO_VALIDATION",
            "detail": ("FAMILY_NOT_REGISTERED: an engine exists "
                       "(NBA_TEAM_PERIOD_RATINGS_V1), but PR #2422 "
                       "recorded NO registration or eligibility change "
                       "for this family and no market test exists for "
                       "it (readiness verdict NO_MARKET_TEST / NO-GO "
                       "for play, 2026-10-18; period outcomes are "
                       "NO_DATA on the maintained sportsdataverse path "
                       "and period lines are outside the DK capture "
                       "scope). " + calibration + ". The family stays "
                       "BLOCKED / NOT_VALIDATED (eligible=false, "
                       "promotable=false) until a registration ruling "
                       "and a forward test exist. (family-level "
                       "registry, sportsedge.family_market_registry; "
                       "research-only)"),
            "validation_status": "NOT_VALIDATED",
            "family_registry": True,
            "registration_state": "UNREGISTERED",
            "eligible": False, "promotable": False,
            "research_only": True, "official_authority": False,
            "model_p_authority": False, "staking_authority": False,
        }
    return {
        "sport": sport, "market": market, "state": BLOCKED,
        "engine": None, "blocker": family["blocker"],
        "detail": family["reason"] + " (family-level registry, "
                  "sportsedge.family_market_registry; research-only)",
        "validation_status": family["validation_status"],
        "family_registry": True,
    }


def resolve_market(sport, market):
    """Resolution for a matrix market name or a canonical intake alias."""
    sport = str(sport or "").upper()
    key = str(market or "").upper() if sport == "MLB" else str(market or "")
    direct = MARKET_RESOLUTIONS.get((sport, key))
    if direct is not None:
        return _with_nfl_registration(sport, dict(direct))
    alias = INTAKE_ALIASES.get(sport, {}).get(str(market or "").upper())
    if alias is not None:
        return _with_nfl_registration(
            sport, dict(MARKET_RESOLUTIONS[(sport, alias)]))
    # The versioned pitch-count extension names its failed validation
    # verdict without changing the frozen 89-market V1 census or granting
    # authority to the existing research pricing route.
    from sportsedge.mlb_family_registry_v2 import coverage_resolution_v2
    extension = coverage_resolution_v2(sport, market)
    if extension is not None:
        return extension
    # t134 (#2219): CFB/NBA/CBB resolve through the isolated family
    # registry so the canonical lookup can never return None (= pass
    # through) for them; not part of the 89-market matrix. The
    # resolution surfaces the family's true recorded state:
    # REGISTERED_RESEARCH_ONLY for families the registry has registered
    # (registration is not validation and grants no pricing here),
    # FAILED_VALIDATION for the NBA game lines (their recorded
    # accuracy-gap verdict), engined-but-unregistered for the NBA
    # team/period totals (#2422 recorded no registration change), and
    # BLOCKED with the registry's exact reason for everything else.
    from sportsedge.family_market_registry import family_market_decision
    family = family_market_decision(sport, market)
    if family is not None:
        return _family_resolution(sport, market, family)
    return None


def blocked_row_for(sport, market, row):
    """Standard fail-closed card row naming the taxonomy blocker.

    Returns None when the market has a priced path (its engine owns the
    row outcome) or when the market is outside the coverage matrix.
    """
    resolution = resolve_market(sport, market)
    if resolution is None or resolution["state"] != BLOCKED:
        return None
    if resolution.get("family_registry"):
        # Family rows are built by sportsedge.registry_gate.family_gate_row,
        # which applies the Illinois exclusion first; this matrix helper
        # must not shadow it (t134).
        return None
    return {
        "status": "NO_MODEL_OR_MARKET",
        "reason": (resolution["blocker"] + ": " + resolution["detail"])[:400],
        "blocker": resolution["blocker"],
        "blocker_detail": resolution["detail"],
        "coverage_market": resolution["market"],
        "sport": sport,
        "market": row.get("market"),
        "selection": row.get("side") or row.get("selection"),
        "player_name": row.get("player_name") or row.get("label"),
        "research_only": True, "official_authority": False,
        "model_p_authority": False, "staking_authority": False,
    }


def coverage_summary():
    """The 89-market coverage pass as a card/report section."""
    priced, blocked = [], {}
    for (sport, market), res in sorted(MARKET_RESOLUTIONS.items()):
        entry = {"sport": sport, "market": market,
                 "engine": res["engine"],
                 "validation_status": res["validation_status"]}
        if res["state"] == PRICED_PATH:
            priced.append(entry)
        else:
            entry["blocker"] = res["blocker"]
            entry["detail"] = res["detail"]
            blocked.setdefault(res["blocker"], []).append(entry)
    return {
        "schema": "SPORTSEDGE_CANONICAL_COVERAGE_V1",
        "source": "Phase 1 coverage matrix (89 markets) resolved against "
                  "the canonical RUN IT path",
        "coverage_is_not_validation": True,
        "markets_total": len(MARKET_RESOLUTIONS),
        "priced_path_count": len(priced),
        "blocked_count": sum(len(v) for v in blocked.values()),
        "priced_path": priced,
        "blocked_by_cause": {k: blocked[k] for k in sorted(blocked)},
        "blocked_counts_by_cause": {
            k: len(blocked[k]) for k in sorted(blocked)},
    }
