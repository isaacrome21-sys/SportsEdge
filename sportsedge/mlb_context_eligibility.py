"""Governed eligibility rules for MLB pregame context features.

Eligibility is deterministic and conservative. This module decides whether a
public pregame lane is safe to expose to a fitted context model; it does not
invent effect sizes and never reads sportsbook prices.
"""
from __future__ import annotations
from typing import Any, Mapping

VERSION = "mlb_context_eligibility_v1"

def _m(v: Any) -> Mapping[str, Any]:
    return v if isinstance(v, Mapping) else {}

def context_eligibility(bundle: Mapping[str, Any]) -> dict[str, Any]:
    lineups=_m(bundle.get("lineups")); umpire=_m(bundle.get("umpire")); statcast=_m(bundle.get("statcast"))
    weather=_m(bundle.get("weather_roof")); park=_m(bundle.get("park_venue")); bullpen=_m(bundle.get("bullpen_workload"))
    starters=_m(bundle.get("starters")); complete=_m(lineups.get("complete_by_side"))
    probable=_m(starters.get("probable_pitchers"))
    roof=str(weather.get("roof_state") or park.get("roof_type") or "").strip().lower()
    roof_closed=roof in {"closed","retractable closed","dome","fixed"}
    ump_games=umpire.get("home_plate_games", umpire.get("sample_games", 0))
    try: ump_games=float(ump_games or 0)
    except (TypeError,ValueError): ump_games=0.0
    lanes={
      "starters": bool(_m(probable.get("away")).get("player_id") and _m(probable.get("home")).get("player_id")),
      "lineups": bool(complete.get("away") and complete.get("home")),
      "injuries_scratches": _m(bundle.get("injuries_scratches")).get("status") == "AVAILABLE",
      "umpire": umpire.get("status") == "AVAILABLE" and ump_games >= 20,
      "statcast": statcast.get("status") == "AVAILABLE",
      "park_venue": park.get("status") == "AVAILABLE",
      "weather": weather.get("status") == "AVAILABLE" and not roof_closed,
      "bullpen_full_game": bullpen.get("status") == "AVAILABLE",
      "bullpen_f5": False,
    }
    return {"version":VERSION,"roof_closed":roof_closed,"lanes":lanes}

