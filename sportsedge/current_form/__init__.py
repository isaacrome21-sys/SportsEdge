"""Current-form analytics layer (research context only).

Free, public, keyless analytics wired as LABELED CONTEXT for the
SportsEdge card/research pipeline: NFL Next Gen Stats + usage/EPA via
nflverse, ESPN public JSON form, Baseball Savant leaderboards, and
BartTorvik player advanced stats. Documented-only sources (KenPom,
StatMuse, Basketball Monster, ESPN BPI) are recorded -- not scraped --
in research/analytics_current_form_20261027/.

Nothing here changes a model, price, threshold, verified status, or
PLAY eligibility. See CURRENT_FORM_FACTORING_SPEC_20261027.md.
"""
from .context import LABEL, build_context_block, capped_adjustment
from .espn_public import fetch_scoreboard, fetch_standings, team_form_from_scoreboards
from .nflverse_ngs import current_form_ngs, fetch_ngs
from .nflverse_usage_epa import snap_share_form, target_share_form, team_epa_form
from .savant_leaderboards import expected_statistics
from .sports_reference import bbr_per_game, pfr_team_stats
from .torvik_current import player_advanced_stats

__all__ = [
    "LABEL",
    "build_context_block",
    "capped_adjustment",
    "current_form_ngs",
    "expected_statistics",
    "fetch_ngs",
    "fetch_scoreboard",
    "fetch_standings",
    "bbr_per_game",
    "pfr_team_stats",
    "player_advanced_stats",
    "snap_share_form",
    "target_share_form",
    "team_epa_form",
    "team_form_from_scoreboards",
]
