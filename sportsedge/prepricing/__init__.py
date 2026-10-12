"""Pre-pricing factor-ingestion stage for the phone RUN IT runner.

Single orchestration point that pulls per-game factors BEFORE any market is
priced: verified injuries/QB-participation, weather, MLB probable pitchers,
and rest/travel. See factor_ingestion.py.
"""
from .factor_ingestion import stage_games  # noqa: F401
