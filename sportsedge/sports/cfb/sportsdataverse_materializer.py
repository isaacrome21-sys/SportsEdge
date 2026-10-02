"""Outcome-blind materialization of SportsDataverse-native CFB candidate inputs."""
from __future__ import annotations
from dataclasses import asdict
from typing import Any, Mapping, Sequence
from .sportsdataverse_history import TeamSnapshot, SOURCE_CONTRACT
from .sportsdataverse_manifest import build_manifest

FEATURES=(
 "off_ppa_rush","off_ppa_dropback","def_ppa_rush_allowed","def_ppa_dropback_allowed",
 "off_success_rate","def_success_rate_allowed","standard_down_ppa",
 "passing_down_success_rate","explosive_rate","net_field_position",
)

class SDVMaterializationError(ValueError): pass

def materialize_native_candidate_inputs(*, games:Sequence[Mapping[str,Any]], snapshots:Sequence[TeamSnapshot]) -> list[dict[str,Any]]:
    """Attach only pre-game snapshots. Scores/outcomes are deliberately ignored."""
    idx={(s.team_id,s.season,s.through_week):s for s in snapshots}
    out=[]
    for raw in sorted(games,key=lambda r:(int(r["season"]),int(r["week"]),int(r["game_id"]))):
        season,week=int(raw["season"]),int(raw["week"])
        if season >= 2026: raise SDVMaterializationError("CFB_SDV_2026_OUTCOMES_PROHIBITED")
        if week <= 1: raise SDVMaterializationError("CFB_SDV_PRIOR_SEASON_SNAPSHOT_REQUIRED")
        try:
            home_id,away_id=int(raw["home_id"]),int(raw["away_id"])
        except (KeyError,TypeError,ValueError) as exc:
            raise SDVMaterializationError("CFB_SDV_GAME_IDENTITY_INVALID") from exc
        home=idx.get((home_id,season,week-1)); away=idx.get((away_id,season,week-1))
        if home is None or away is None:
            raise SDVMaterializationError(f"CFB_SDV_PREGAME_SNAPSHOT_MISSING:{raw.get('game_id')}")
        if home.source_contract != SOURCE_CONTRACT or away.source_contract != SOURCE_CONTRACT:
            raise SDVMaterializationError("CFB_SDV_SOURCE_CONTRACT_MISMATCH")
        out.append({
          "game_id":str(raw["game_id"]),"season":season,"week":week,
          "home_id":home_id,"away_id":away_id,
          "home_features":{k:getattr(home,k) for k in FEATURES},
          "away_features":{k:getattr(away,k) for k in FEATURES},
          "home_games_in_sample":home.games_in_sample,
          "away_games_in_sample":away.games_in_sample,
          "source_contract":SOURCE_CONTRACT,
          "provenance_class":"RECONSTRUCTED_HISTORICAL_NOT_PIT",
        })
    return out

def manifest_native_inputs(*, rows, source_datasets, season:int, target_week:int):
    return build_manifest(season=season,target_week=target_week,datasets=source_datasets,feature_names=FEATURES)
