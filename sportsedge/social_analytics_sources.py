from __future__ import annotations

"""Curated X/social analytics source registry for SportsEdge.

These accounts are research/context sources only. Their projections, rankings,
picks, model outputs, consensus and commentary never vote directly in Model_P,
never substitute for sportsbook prices, and never constitute Truth-Gate promotion
evidence. They are used to discover objective data, corroborate or challenge
SportsEdge projections, surface injuries/role changes/weather/model disagreement,
and prioritize deeper investigation.
"""

SOURCE_ROLE = "CONTEXT_ONLY"
MODEL_P_ELIGIBLE = False
TRUTH_GATE_ELIGIBLE = False

# Tier A: primary/high-signal analytics or official data accounts.
# Tier B: useful specialized/secondary analytics.
# Tier C: commentary/model-output awareness only; never directional confirmation.

SOURCES: dict[str, tuple[dict[str, object], ...]] = {
    "MLB": (
        {"handle": "@BallparkPal", "tier": "A", "role": "park_weather_sims_matchups"},
        {"handle": "@DerekCarty", "tier": "A", "role": "the_bat_x_projection_benchmark"},
        {"handle": "@EV_Analytics", "tier": "A", "role": "projection_and_prop_market_research"},
        {"handle": "@fangraphs", "tier": "A", "role": "advanced_stats_and_projections"},
        {"handle": "@darenw", "tier": "A", "role": "baseball_savant_statcast_tools"},
        {"handle": "@tangotiger", "tier": "A", "role": "statcast_methodology_and_research"},
        {"handle": "@MLBStats", "tier": "A", "role": "official_mlb_statistical_context"},
        {"handle": "@PitchingNinja", "tier": "B", "role": "pitch_shape_mechanics_visual_context"},
        {"handle": "@mike_petriello", "tier": "B", "role": "statcast_analysis_and_trends"},
        {"handle": "@DataLabsMLB", "tier": "B", "role": "daily_slate_park_and_projection_visuals"},
        {"handle": "@PropCaddie", "tier": "B", "role": "daily_hr_analytics_candidate_discovery"},
        {"handle": "@OptaSTATS", "tier": "B", "role": "cross_sport_official_data_context"},
    ),
    "NFL": (
        {"handle": "@NextGenStats", "tier": "A", "role": "official_tracking_data"},
        {"handle": "@SumerSports", "tier": "A", "role": "football_analytics_and_simulation"},
        {"handle": "@benbbaldwin", "tier": "A", "role": "epa_win_probability_fourth_down"},
        {"handle": "@KevinCole___", "tier": "A", "role": "bayesian_qb_and_team_strength_models"},
        {"handle": "@SharpFootball", "tier": "A", "role": "predictive_nfl_analytics_and_visuals"},
        {"handle": "@SharpFBAnalysis", "tier": "B", "role": "nfl_model_and_matchup_context"},
        {"handle": "@FantasyPts", "tier": "B", "role": "player_usage_and_projection_context"},
        {"handle": "@TeamRankings", "tier": "B", "role": "team_stats_and_model_crosscheck"},
        {"handle": "@OptaAnalystUS", "tier": "B", "role": "us_sports_data_storytelling"},
        {"handle": "@OptaSTATS", "tier": "B", "role": "official_data_context"},
    ),
    "CFB": (
        {"handle": "@CFB_Data", "tier": "A", "role": "collegefootball_data_epa_ppa_and_lines"},
        {"handle": "@statsowar", "tier": "A", "role": "cfb_simulations_efficiency_and_game_control"},
        {"handle": "@PFF_College", "tier": "A", "role": "player_grades_usage_and_matchup_context"},
        {"handle": "@cfb_professor", "tier": "B", "role": "cfb_power_ratings_and_projection_context"},
        {"handle": "@CFBAnalytical", "tier": "B", "role": "cfb_personnel_and_composite_analytics"},
        {"handle": "@TeamRankings", "tier": "B", "role": "ncaaf_team_stats_and_model_crosscheck"},
        {"handle": "@OptaAnalystUS", "tier": "B", "role": "us_sports_data_storytelling"},
    ),
    "NBA": (
        {"handle": "@nbastats", "tier": "A", "role": "official_nba_stats"},
        {"handle": "@The_BBall_Index", "tier": "A", "role": "player_impact_role_and_tracking_metrics"},
        {"handle": "@Shot_Quality", "tier": "A", "role": "shot_quality_and_game_model_context"},
        {"handle": "@EV_Analytics", "tier": "B", "role": "prop_projection_and_market_research"},
        {"handle": "@OptaAnalystUS", "tier": "B", "role": "nba_data_storytelling"},
        {"handle": "@OptaSTATS", "tier": "B", "role": "official_data_context"},
        {"handle": "@TeamRankings", "tier": "B", "role": "nba_team_stats_and_model_crosscheck"},
    ),
    "NCAAB": (
        {"handle": "@EvanMiya", "tier": "A", "role": "bayesian_player_team_lineup_and_game_models"},
        {"handle": "@TeamRankings", "tier": "B", "role": "ncaab_team_stats_and_model_crosscheck"},
        {"handle": "@OptaAnalystUS", "tier": "B", "role": "college_basketball_data_context"},
    ),
    "NHL": (
        {"handle": "@MoneyPuckdotcom", "tier": "A", "role": "xg_live_win_prob_power_rankings"},
        {"handle": "@EvolvingWild", "tier": "A", "role": "player_team_and_goalie_models"},
        {"handle": "@JFreshHockey", "tier": "A", "role": "projected_war_player_cards_and_context"},
        {"handle": "@TopDownHockey", "tier": "A", "role": "xg_and_player_impact_analytics"},
        {"handle": "@MeghanChayka", "tier": "B", "role": "hockey_analytics_and_tracking_context"},
        {"handle": "@OptaAnalystUS", "tier": "B", "role": "nhl_data_storytelling"},
    ),
    "PGA": (
        {"handle": "@DataGolf", "tier": "A", "role": "golf_projections_course_fit_and_live_modeling"},
        {"handle": "@JustinRayGolf", "tier": "A", "role": "golf_statistical_research"},
        {"handle": "@RickRunGood", "tier": "B", "role": "golf_model_and_course_research"},
        {"handle": "@BetspertsGolf", "tier": "B", "role": "shotlink_course_and_condition_model_tools"},
        {"handle": "@OptaAnalystUS", "tier": "B", "role": "golf_data_storytelling"},
    ),
    "UFC": (
        {"handle": "@Fightnomics", "tier": "A", "role": "quantitative_mma_matchup_analysis"},
        {"handle": "@NateLatshaw", "tier": "A", "role": "mma_expected_rounds_and_next_gen_metrics"},
        {"handle": "@FightMetric", "tier": "B", "role": "legacy_mma_statistical_reference"},
        {"handle": "@tapology", "tier": "B", "role": "fight_history_roster_and_consensus_context"},
        {"handle": "@Moneyball16", "tier": "B", "role": "ufc_projection_context"},
    ),
    "SOCCER": (
        {"handle": "@OptaAnalyst", "tier": "A", "role": "xg_predictions_and_data_storytelling"},
        {"handle": "@StatsBomb", "tier": "A", "role": "xg_event_and_tracking_analytics"},
        {"handle": "@OptaJoe", "tier": "B", "role": "official_opta_statistical_context"},
    ),
    "TENNIS": (
        {"handle": "@TennisViz", "tier": "A", "role": "tracking_based_tennis_analytics"},
        {"handle": "@UltmTennisStats", "tier": "B", "role": "historical_tennis_statistical_context"},
    ),
    "MULTI": (
        {"handle": "@OptaSTATS", "tier": "A", "role": "cross_sport_official_data"},
        {"handle": "@OptaAnalystUS", "tier": "A", "role": "us_cross_sport_data_storytelling"},
        {"handle": "@TeamRankings", "tier": "A", "role": "multi_sport_team_stats_and_models"},
        {"handle": "@UnabatedSports", "tier": "B", "role": "prop_projection_and_market_tool_context"},
        {"handle": "@EV_Analytics", "tier": "B", "role": "multi_sport_projection_and_prop_context"},
    ),
}

# Accounts supplied by the user that should be searched, but whose current
# activity/identity should be re-verified before relying on any post.
VERIFY_BEFORE_USE = {
    "@HomeRunPredict",
    "@darenw",  # verified historically/currently, retain re-verification guard
    "@CFBAnalytical",
}

PROHIBITED_USES = (
    "model_p_vote",
    "confidence_boost_from_agreement",
    "truth_gate_promotion_evidence",
    "sportsbook_price_substitution",
    "no_vig_input",
    "standalone_bet_recommendation",
)


def accounts_for_sport(sport: str, *, include_multi: bool = True) -> tuple[dict[str, object], ...]:
    key = str(sport).strip().upper()
    rows = list(SOURCES.get(key, ()))
    if include_multi and key != "MULTI":
        rows.extend(SOURCES["MULTI"])

    # Preserve first occurrence while removing duplicate handles.
    seen: set[str] = set()
    out: list[dict[str, object]] = []
    for row in rows:
        handle = str(row["handle"])
        if handle.lower() in seen:
            continue
        seen.add(handle.lower())
        out.append({
            **row,
            "source_role": SOURCE_ROLE,
            "model_p_eligible": MODEL_P_ELIGIBLE,
            "truth_gate_eligible": TRUTH_GATE_ELIGIBLE,
            "prohibited_uses": PROHIBITED_USES,
        })
    return tuple(out)
