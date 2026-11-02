"""NFL player-prop RESEARCH admission on the canonical RUN IT path (#2).

Owner ruling (Isaac, Nov 1 2026, relay #2447; standing preference: "daily
bets whenever there's a +EV edge, for every model and market ... validation
runs in the background and never blocks showing them"):

The free ESPN-gamelog empirical pricer (sportsedge.nfl_phone_player_pricing
-> nfl_player_empirical) is already wired into artifacts/run_it_full.py but
governance-blocked (GOVERNANCE_NO_ENGINE). This module admits it as a
RESEARCH-ONLY lane, mirroring the NBA prop engine admission
(sportsedge.registry_gate.nba_engine_sufficiency_met):

* Only the markets the empirical pricer supports (NFL_PLAYER_MARKETS), and
  only when the canonical coverage gate's blocker is exactly NO_ENGINE.
  Anything else keeps its blocker.
* A priced row is admitted only with the engine's sufficiency stamp:
  identity resolved by ESPN against the two fixture teams, a pregame
  kickoff, and at least NFL_PROP_MIN_PRIOR_GAMES verified prior games.
  Otherwise the original fail-closed blocker row is restored (with the
  pricer's own reason attached), so a row never carries a probability it
  did not earn.
* Admitted rows stay research_only / eligible False / promotable False /
  no official, Model_P or staking authority. They are NOT COUNTED, PAPER
  0u. Nothing here grants PLAY or alters any validated market.
"""
from __future__ import annotations

from sportsedge.nfl_phone_player_pricing import NFL_PLAYER_MARKETS

NFL_PROP_ENGINE_ID = "NFL_PLAYER_EMPIRICAL_V1"
NFL_PROP_MIN_PRIOR_GAMES = 8
ADMISSION_DISPOSITION = "RESEARCH_PRICING_ALLOWED_NFL_PROP_ENGINE_SUFFICIENCY_MET"
RULING = "OWNER_RULING_2026_11_01_NFL_PROP_RESEARCH_ADMISSION"
PRICED_KEYS = ("model_probability", "ev_per_dollar", "dk_odds")


def admission_candidate(sport: object, market: object, gate: object) -> bool:
    """True when a coverage-gated row may be routed to the NFL empirical
    lane for research pricing (it is still re-judged after pricing)."""
    return (str(sport or "").upper() == "NFL"
            and str(market or "").upper() in NFL_PLAYER_MARKETS
            and isinstance(gate, dict)
            and gate.get("blocker") == "NO_ENGINE")


def sufficiency_met(result: object) -> bool:
    """Fail-closed sufficiency check on a pricer output row."""
    if not isinstance(result, dict):
        return False
    if result.get("status") == "NO_MODEL_OR_MARKET":
        return False
    if any(result.get(k) is None for k in PRICED_KEYS):
        return False
    n = result.get("prior_game_count")
    if isinstance(n, bool) or not isinstance(n, int) or n < NFL_PROP_MIN_PRIOR_GAMES:
        return False
    return result.get("source") == "FREE_ESPN_NFL_GAMELOG"


def admit(result: dict, gate: dict) -> dict:
    """Return the admitted research row, or the original blocker row."""
    if not sufficiency_met(result):
        blocked = dict(gate)
        why = (result or {}).get("reason") if isinstance(result, dict) else None
        n = (result or {}).get("prior_game_count") if isinstance(result, dict) else None
        if why:
            blocked["nfl_prop_engine_reason"] = str(why)[:180]
        elif n is not None:
            blocked["nfl_prop_engine_reason"] = (
                f"NFL_PROP_SUFFICIENCY_NOT_MET: {n} prior games < {NFL_PROP_MIN_PRIOR_GAMES}")
        else:
            blocked["nfl_prop_engine_reason"] = "NFL_PROP_SUFFICIENCY_NOT_MET"
        blocked["registry_enforced"] = True
        return blocked
    row = dict(result)
    row.update({
        "nfl_prop_engine": {
            "engine_id": NFL_PROP_ENGINE_ID,
            "sufficiency_met": True,
            "n_prior": result["prior_game_count"],
            "min_prior": NFL_PROP_MIN_PRIOR_GAMES,
            "ruling": RULING,
        },
        "coverage_market": gate.get("coverage_market"),
        "registration_state": "REGISTERED_RESEARCH_ONLY",
        "validation_status": "NOT_VALIDATED",
        "counted": False, "paper_units": 0,
        "eligible": False, "promotable": False,
        "research_only": True, "official_authority": False,
        "model_p_authority": False, "staking_authority": False,
        "registry_enforced": True,
        "registry_module": "sportsedge.nfl_prop_research_admission",
        "registry_disposition": ADMISSION_DISPOSITION,
    })
    return row
