"""Pinned public SportsDataverse acquisition plan for frozen CFB history.

This module only constructs and validates source identities. Network I/O and RDS
parsing belong to the runner so tests remain deterministic.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict

BASE="https://github.com/sportsdataverse/sportsdataverse-data/releases/download"
SOURCE_REPO="sportsdataverse/sportsdataverse-data"
UPSTREAM_LOADER_REPO="sportsdataverse/cfbfastR"

_ASSETS={
 "cfb_schedules":("cfb_schedules","cfb_schedules_{season}.csv.gz"),
 "espn_cfb_adv_team":("espn_cfb_adv_team","adv_team_{season}.csv"),
 "espn_cfb_adv_drives":("espn_cfb_adv_drives","adv_drives_{season}.csv"),
 "espn_cfb_adv_situational":("espn_cfb_adv_situational","adv_situational_{season}.csv"),
}
PROHIBITED={"espn_cfb_betting"}

class SDVAcquisitionError(ValueError): pass

@dataclass(frozen=True)
class Asset:
    dataset:str
    season:int
    tag:str
    filename:str
    url:str
    def to_dict(self): return asdict(self)

def asset(dataset:str,season:int)->Asset:
    if dataset in PROHIBITED: raise SDVAcquisitionError("CFB_SDV_BETTING_DATASET_PROHIBITED")
    if dataset not in _ASSETS: raise SDVAcquisitionError(f"CFB_SDV_DATASET_NOT_ALLOWLISTED:{dataset}")
    if not 2015 <= int(season) <= 2025:
        raise SDVAcquisitionError("CFB_SDV_ACQUISITION_OUTSIDE_FROZEN_WINDOW")
    tag,pattern=_ASSETS[dataset]; filename=pattern.format(season=int(season))
    return Asset(dataset,int(season),tag,filename,f"{BASE}/{tag}/{filename}")

def acquisition_plan(start_season:int=2015,end_season:int=2025):
    if (start_season,end_season)!=(2015,2025):
        raise SDVAcquisitionError("CFB_SDV_FROZEN_WINDOW_REQUIRED")
    return [asset(ds,yr) for yr in range(start_season,end_season+1) for ds in _ASSETS]

__all__=["Asset","SDVAcquisitionError","PROHIBITED","asset","acquisition_plan"]
