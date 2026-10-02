#!/usr/bin/env python3
"""Materialize frozen SportsDataverse CFB candidate-selection rows from local assets.

Network acquisition is intentionally outside this script. The caller supplies the exact
44 frozen SportsDataverse assets and a normalized historical-weather JSON file. Raw
asset SHA-256 receipts are verified before parsing. No candidate evaluation or model
fit occurs here.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))

from sportsedge.sports.cfb.sportsdataverse_acquisition import acquisition_plan
from sportsedge.sports.cfb.sportsdataverse_csv import parse_csv
from sportsedge.sports.cfb.sportsdataverse_pipeline import (
    materialize_training_rows,
    training_manifest,
)
from sportsedge.sports.cfb.sportsdataverse_receipts import receipt,validate_receipts
from sportsedge.sports.cfb.sportsdataverse_manifest import canonical_sha256


def _read_weather(path:Path)->list[dict]:
    try:
        payload=json.loads(path.read_text(encoding="utf-8"))
    except (OSError,json.JSONDecodeError) as exc:
        raise SystemExit("CFB_SDV_WEATHER_INPUT_UNREADABLE") from exc
    if not isinstance(payload,list) or not all(isinstance(row,dict) for row in payload):
        raise SystemExit("CFB_SDV_WEATHER_INPUT_LIST_REQUIRED")
    return payload


def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--asset-root",type=Path,required=True)
    ap.add_argument("--weather-json",type=Path,required=True)
    ap.add_argument(
        "--rows-out",
        type=Path,
        default=Path("artifacts/cfb/sportsdataverse_training_rows.json"),
    )
    ap.add_argument(
        "--manifest-out",
        type=Path,
        default=Path("artifacts/cfb/sportsdataverse_training_rows_manifest.json"),
    )
    ap.add_argument(
        "--receipts-out",
        type=Path,
        default=Path("artifacts/cfb/sportsdataverse_source_receipts.json"),
    )
    args=ap.parse_args()

    plan=acquisition_plan()
    raw_receipts=[]
    parsed_receipts=[]
    rows_by_dataset={a.dataset:[] for a in plan}

    for asset in plan:
        path=args.asset_root / asset.filename
        try:
            raw=path.read_bytes()
        except OSError as exc:
            raise SystemExit(f"CFB_SDV_ASSET_MISSING:{asset.filename}") from exc
        rr=receipt(asset,raw)
        rows,pr=parse_csv(
            raw,
            dataset=asset.dataset,
            season=asset.season,
            source_url=asset.url,
            raw_csv_sha256=rr.sha256,
        )
        raw_receipts.append(rr)
        parsed_receipts.append(pr)
        rows_by_dataset[asset.dataset].extend(rows)

    validate_receipts(plan,raw_receipts)
    weather=_read_weather(args.weather_json)
    training=materialize_training_rows(
        schedules=rows_by_dataset["cfb_schedules"],
        adv_team_rows=rows_by_dataset["espn_cfb_adv_team"],
        adv_situational_rows=rows_by_dataset["espn_cfb_adv_situational"],
        adv_drive_rows=rows_by_dataset["espn_cfb_adv_drives"],
        weather_rows=weather,
    )
    manifest=training_manifest(training)

    receipts_core={
        "schema":"CFB_SPORTSDATAVERSE_SOURCE_RECEIPTS_V1",
        "raw_asset_count":len(raw_receipts),
        "parsed_asset_count":len(parsed_receipts),
        "raw_receipts":[x.to_dict() for x in raw_receipts],
        "parsed_receipts":[x.to_dict() for x in parsed_receipts],
        "governance":{
            "attempts_consumed":0,
            "evaluation_performed":False,
            "model_p_created":False,
            "promotion_authority":False,
            "official_authority":False,
        },
    }
    receipts_core["manifest_sha256"]=canonical_sha256(receipts_core)

    for path,payload in (
        (args.rows_out,training),
        (args.manifest_out,manifest),
        (args.receipts_out,receipts_core),
    ):
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(payload,indent=2,sort_keys=True)+"\n",encoding="utf-8")

    print(json.dumps({
        "status":"MATERIALIZED_ONLY",
        "row_count":len(training),
        "rows_sha256":manifest["rows_sha256"],
        "manifest_sha256":manifest["manifest_sha256"],
        "source_receipts_sha256":receipts_core["manifest_sha256"],
        "attempts_consumed":0,
        "evaluation_performed":False,
    },sort_keys=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
